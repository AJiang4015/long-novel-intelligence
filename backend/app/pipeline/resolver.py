from dataclasses import dataclass, field
from typing import Callable

from app.pipeline.chunker import Chunk
from app.pipeline.sections import SectionType
from app.schemas.llm import (AliasCandidate, AliasJudgeResult, ExtractionResult,
                             MentionCategory, PendingMention)

RECALL_TOP_K = 5


def _chars(s: str) -> set[str]:
    return set(s)


def _overlap(a: str, b: str) -> int:
    return len(_chars(a) & _chars(b))


class EntityResolver:
    """一次 Novel ingest 一个实例；known / canonical_aliases / mention index 整本持续。"""

    def __init__(self, judge: Callable[[str, list[PendingMention]], AliasJudgeResult]):
        self._judge = judge
        self.known: dict[str, str] = {}               # 名字 → canonical（含 canonical 自身与别名）
        self.canonical_aliases: dict[str, list[str]] = {}  # canonical → [别名]，保序
        self._index: dict[str, set[str]] = {}         # canonical → matched_names（去重）

        # ---- V0.2.3-b1：canonical metadata + merge decision（纯 decision，不改上述状态）----
        self.merge_evidence: list[dict] = []          # 桥接 mention 旁路证据
        self.merge_map: dict[str, str] = {}           # C_drop -> C_keep（b1 产出，不用于改写 known）
        self._first_seen: dict[str, int] = {}         # canonical -> 首次确立 canonical 的 chunk_id
        self._canonical_chunks: dict[str, set[int]] = {}    # canonical -> 出现过的 chunk_id 集合
        self._canonical_chapters: dict[str, set[int]] = {}  # canonical -> 出现过的 chapter_id 集合
        self._current_chunk_id: int = 0
        self._current_chapter_id: int = 0
        # V0.2.5-a：section 上下文（chunk 级；BODY 默认）
        self._current_section_type: SectionType = SectionType.BODY
        self._provisional: set[str] = set()      # 非正文注册、未获正文确认的 provisional canonical
        self._chunk_dropped: set[str] = set()    # 本 chunk 内被丢弃（输出剔除）的 mention
        # V0.2.5-b：chunk 级 deferred / unresolved（canonical 创建推迟到 chunk 末决策边界）
        self._deferred: list[str] = []           # BODY DESCRIPTIVE/COMPOSITE 无候选（待重召回）
        self._unresolved: set[str] = set()       # 无法确认 → 不注册（输出剔除、不入 merge_evidence）
        # V0.2.4：mention hygiene 统计（job stats 输出）
        self.hygiene_stats: dict[str, int] = {
            "collective_filtered": 0, "generic_filtered": 0,
            "descriptive_resolved": 0, "composite_resolved": 0, "invalid_filtered": 0,
            # V0.2.5-a：非正文 section 统计
            "nonbody_person_provisional": 0, "nonbody_descriptive_dropped": 0,
            "nonbody_provisional_dropped": 0,
            # V0.2.5-b：BODY DESCRIPTIVE/COMPOSITE 无法确认统计
            "descriptive_unresolved": 0, "composite_unresolved": 0,
        }

    # ---- 公开 ----
    def resolve(self, chunk: Chunk, result: ExtractionResult) -> tuple[ExtractionResult, bool]:
        self._current_chunk_id = chunk.chunk_id
        self._current_chapter_id = chunk.chapter_id
        self._current_section_type = chunk.section_type   # V0.2.5-a
        self._chunk_dropped = set()                       # V0.2.5-a：本 chunk 丢弃集合重置
        self._deferred = []                               # V0.2.5-b：本 chunk deferred 重置
        self._unresolved = set()                          # V0.2.5-b：本 chunk unresolved 重置
        # V0.2.4：本 chunk 提取的 category 映射（LLM 提供时；缺省 None）
        self._current_categories: dict[str, MentionCategory] = {
            c.name: c.category for c in result.characters if c.category is not None}
        pending: list[PendingMention] = []
        resolved_chars: list = []
        resolved_rels: list = []
        # V0.2.4：硬过滤 COLLECTIVE/INVALID（不进候选源；relation endpoint 涉及则跳过该关系）
        from app.pipeline.hygiene import is_hard_filtered
        def _keep(name: str) -> bool:
            return not is_hard_filtered(name)
        # 预扫描：本 chunk 全部名字（characters + 关系端点）中已在 known 的 → 预置为共现源。
        # 消除同 chunk 共现召回的顺序敏感性：未知 mention 无论出现在已知名前/后，都能召回它。
        chunk_names = (
            {c.name for c in result.characters if _keep(c.name)}
            | {r.source for r in result.relationships if _keep(r.source)}
            | {r.target for r in result.relationships if _keep(r.target)}
        )
        confirmed: set[str] = {self.known[n] for n in chunk_names if n in self.known}
        # 排除硬过滤 canonical（防历史污染节点进入候选源）
        confirmed = {c for c in confirmed if not is_hard_filtered(c)}
        # V0.2.5-a：provisional（非正文注册、未获正文确认）不得进入候选源（T-a14 锁死）
        confirmed = {c for c in confirmed if c not in self._provisional}
        # 文本层共现源（V0.2.2）：chunk 原文中出现的已知 canonical/alias → canonical。
        # 仅作候选信号，绝不直接认定同一人（仍须经 judge）。
        text_confirmed: set[str] = self._text_mentions(chunk.text)
        text_confirmed = {c for c in text_confirmed if not is_hard_filtered(c)}

        def do_name(name: str) -> str | None:
            canonical, needs_judge = self._resolve_name(name, confirmed, text_confirmed)
            if needs_judge:
                pending.append(self._pending_for(name, confirmed, text_confirmed))
                return name  # 判定后再替换
            if canonical == name and name not in self.known:
                if name in self._deferred:
                    return name  # V0.2.5-b：deferred（BODY DESCRIPTIVE/COMPOSITE 无候选）→ 待 chunk 末决定
                return None  # V0.2.5-a：丢弃（GENERIC 无候选 / 非正文 DESCRIPTIVE/COMPOSITE 无候选）
            return canonical

        from app.pipeline.hygiene import classify_mention, is_hard_filtered
        # V0.2.4-a RC2：硬过滤 mention 在 characters 主处理入口剔除并计数一次；
        # 不进 resolved.characters；同一 mention 在 relationship endpoint 命中不再重复计数。
        for c in result.characters:
            if is_hard_filtered(c.name):
                if classify_mention(c.name) == MentionCategory.COLLECTIVE:
                    self.hygiene_stats["collective_filtered"] += 1
                else:
                    self.hygiene_stats["invalid_filtered"] += 1
                continue
            # V0.2.4-b RC3：relational generic 词表命中 → 强制 GENERIC。
            # GENERIC 无候选丢弃（不进 resolved.characters）；有候选走 judge。
            if classify_mention(c.name) == MentionCategory.GENERIC:
                resolved_name, needs_judge = self._resolve_name(c.name, confirmed, text_confirmed)
                if needs_judge:
                    pending.append(self._pending_for(c.name, confirmed, text_confirmed))
                # GENERIC 无候选丢弃：_resolve_name 返回 (name, False) 且未注册 → 跳过
                elif resolved_name == c.name and c.name not in self.known:
                    continue
                resolved_chars.append({"name": resolved_name})
                continue
            resolved_name = do_name(c.name)
            if resolved_name is not None:
                resolved_chars.append({"name": resolved_name})
        for r in result.relationships:
            # V0.2.4-a RC2：任一 endpoint 为硬过滤 mention → 丢弃整条关系（不计数）
            if is_hard_filtered(r.source) or is_hard_filtered(r.target):
                continue
            # V0.2.4-b RC3：relational generic endpoint → 走 GENERIC 语义；
            # 无候选丢弃整条关系（不计数）；有候选走 judge。
            if classify_mention(r.source) == MentionCategory.GENERIC:
                rsrc, r_needs = self._resolve_name(r.source, confirmed, text_confirmed)
                if r_needs:
                    pending.append(self._pending_for(r.source, confirmed, text_confirmed))
                    rsrc = r.source
                elif rsrc == r.source and r.source not in self.known:
                    continue   # GENERIC 无候选丢弃 → 整条关系丢弃
            else:
                rsrc = do_name(r.source)
                if rsrc is None:
                    continue   # V0.2.5-a：丢弃端点 → 整条关系丢弃
            if classify_mention(r.target) == MentionCategory.GENERIC:
                rtgt, t_needs = self._resolve_name(r.target, confirmed, text_confirmed)
                if t_needs:
                    pending.append(self._pending_for(r.target, confirmed, text_confirmed))
                    rtgt = r.target
                elif rtgt == r.target and r.target not in self.known:
                    continue   # GENERIC 无候选丢弃 → 整条关系丢弃
            else:
                rtgt = do_name(r.target)
                if rtgt is None:
                    continue   # V0.2.5-a：丢弃端点 → 整条关系丢弃
            resolved_rels.append({
                "source": rsrc, "target": rtgt, "type": r.type.value,
                "confidence": r.confidence,
            })

        # ---- V0.2.5-b：chunk 末 deferred 重召回（canonical 创建决策边界）----
        # confirmed / text_confirmed 语义（评审锁定 2026-08-26）：
        # ① 必须是完成当前 chunk 全部正常 character 处理后的候选集合（含本 chunk 新增正式
        #    canonical：confirmed 用实时值、text_confirmed 重算以纳入新入 _index 的 canonical）；
        # ② 绝不能包含 provisional（-a：provisional 不入 _index、且已从 confirmed 过滤）。
        # 重召回产生的 candidate pairs 与原 pending 合并 → 最终只调用一次 _judge（零额外请求）。
        if self._deferred:
            text_confirmed_recall = self._text_mentions(chunk.text)
            text_confirmed_recall = {c for c in text_confirmed_recall if not is_hard_filtered(c)}
            for m in list(dict.fromkeys(self._deferred)):   # 去重：同名多次出现只重召回一次
                cands = self._recall(m, confirmed, text_confirmed_recall)
                if cands:
                    pending.append(PendingMention(mention=m, candidates=cands))
                else:
                    self._register_or_unresolved(m)   # BODY DESCRIPTIVE/COMPOSITE → unresolved

        # ---- V0.2.3-b1：桥接 mention 旁路收集（纯观察，不改任何状态）----
        established = {c for c in self.known if self.known[c] == c}
        for p in pending:
            hits = [c.canonical for c in p.candidates if c.canonical in established]
            if len(hits) >= 2:
                for i in range(len(hits)):
                    for j in range(i + 1, len(hits)):
                        self.merge_evidence.append({
                            "mention": p.mention,
                            "candidates": list(hits),
                            "pair": [hits[i], hits[j]],
                            "chunk_id": chunk.chunk_id,
                            "chapter_id": chunk.chapter_id,
                            "text": chunk.text,
                        })

        failed = False
        if pending:
            try:
                judge_result = self._judge(chunk.text, pending)
                self._apply_judge(judge_result, pending)
            except Exception:
                # validation/网络等任何失败：待判定 mention 按 category 分派（V0.2.5-b D4）——
                # PERSON/None → 既有 fail-safe 注册；GENERIC → 丢弃（与 RC3「GENERIC 永不
                # canonical」对齐，修复既有 exception 路径洞）；DESCRIPTIVE/COMPOSITE →
                # unresolved（永不 canonicalize，避免 fail-safe 与 unresolved 决策冲突）
                for p in pending:
                    if classify_mention(p.mention) == MentionCategory.GENERIC:
                        continue
                    self._register_or_unresolved(p.mention)
                failed = True

        # 被丢弃 / unresolved mention 从输出剔除（unconditional：deferred 全部 unresolved 时
        # pending 为空，也必须剔除；V0.2.4-b RC3 / V0.2.5-a / V0.2.5-b 共用）
        from app.pipeline.hygiene import classify_mention
        dropped = {p.mention for p in pending
                   if p.mention not in self.known
                   and classify_mention(p.mention) == MentionCategory.GENERIC}
        dropped |= self._chunk_dropped   # V0.2.5-a：非正文 DESCRIPTIVE/COMPOSITE 丢弃
        dropped |= self._unresolved      # V0.2.5-b：无法确认 → 不注册
        if dropped:
            resolved_chars = [c for c in resolved_chars if c["name"] not in dropped]
            resolved_rels = [r for r in resolved_rels
                             if r["source"] not in dropped and r["target"] not in dropped]
        # 判定后二次替换（pending 中的 mention → canonical）
        if pending:
            name_map = {p.mention: self.known[p.mention]
                        for p in pending if p.mention in self.known}
            resolved_chars = [{"name": name_map.get(c["name"], c["name"])} for c in resolved_chars]
            for rel in resolved_rels:
                rel["source"] = name_map.get(rel["source"], rel["source"])
                rel["target"] = name_map.get(rel["target"], rel["target"])

        # V0.2.5-b：unresolved / 被丢弃 mention 的桥接证据清除（不进入 merge_evidence）
        if self._unresolved or self._chunk_dropped:
            self.merge_evidence = [
                ev for ev in self.merge_evidence
                if ev["mention"] not in self._unresolved and ev["mention"] not in self._chunk_dropped]

        # V0.2.3-b1：canonical 出现统计（轻量 metadata，供 merge judge 输入）
        # V0.2.5-a：非正文 chunk 不参与 mc/chapters 统计（晋升实体只计 BODY 证据）
        if self._current_section_type == SectionType.BODY:
            for c in resolved_chars:
                canon = c["name"]
                self._canonical_chunks.setdefault(canon, set()).add(chunk.chunk_id)
                self._canonical_chapters.setdefault(canon, set()).add(chunk.chapter_id)

        resolved = ExtractionResult.model_validate({
            "characters": resolved_chars,
            "relationships": resolved_rels,
        })
        return resolved, failed

    # ---- 内部 ----
    def _text_mentions(self, chunk_text: str) -> set[str]:
        """chunk 原文中出现的已知 canonical/alias → 对应 canonical 集合。

        子串匹配（如「天保」命中「天保大老」）作为候选信号可接受——它只是多提供一个候选，
        最终是否同一人仍由 judge 判定；绝不在此直接建立 alias。
        只扫描当前 chunk 原文，不跨 chunk / 不跨 chapter。
        """
        found: set[str] = set()
        for canonical, names in self._index.items():
            for n in names:
                if n in chunk_text:
                    found.add(canonical)
                    break
        return found

    def _resolve_name(self, name: str, confirmed: set[str], text_confirmed: set[str]) -> tuple[str, bool]:
        from app.pipeline.hygiene import classify_mention, is_hard_filtered
        if name in self.known:
            canonical = self.known[name]
            # V0.2.5-a：provisional 在 BODY 同名字出现 → 晋升为正式 canonical（D3）
            if canonical in self._provisional and self._current_section_type == SectionType.BODY:
                self._promote(canonical)
            if canonical not in self._provisional:
                confirmed.add(canonical)  # 已确认 → 成为后续同名 chunk 内共现候选源
            return canonical, False
        # V0.2.4：硬过滤 mention 永不注册（防御：即使漏过 resolve 开头过滤）
        if is_hard_filtered(name):
            if classify_mention(name) == MentionCategory.COLLECTIVE:
                self.hygiene_stats["collective_filtered"] += 1
            else:
                self.hygiene_stats["invalid_filtered"] += 1
            return name, False   # 不注册、不进 pending——原样返回（characters/关系保留原名，无害）
        candidates = self._recall(name, confirmed, text_confirmed)
        # V0.2.4-b RC3：category precedence（评审锁定）——
        # 1. COLLECTIVE / INVALID hard rules（已在上方 is_hard_filtered 分支处理）
        # 2. relational-generic exact-match → 强制 GENERIC（无论 LLM category 是 PERSON/None/其他，
        #    都不得注册为 canonical；有候选可 alias，无候选丢弃）
        # 3. 其余才使用 LLM category
        # 4. 无 category 才走 legacy PERSON fallback
        from app.pipeline.hygiene import classify_mention
        hy_cat = classify_mention(name)
        if hy_cat == MentionCategory.GENERIC:
            cat = MentionCategory.GENERIC   # 强制覆盖 LLM category（含 LLM 误标 PERSON）
        else:
            cat = self._category_of(name)   # LLM category（可能 None → legacy PERSON）
        if not candidates:
            if cat == MentionCategory.GENERIC:
                self.hygiene_stats["generic_filtered"] += 1
                return name, False   # 丢弃，不注册 canonical
            # V0.2.5-a：非正文 DESCRIPTIVE/COMPOSITE 无候选 → 永不注册，丢弃计数
            if (self._current_section_type != SectionType.BODY
                    and cat in (MentionCategory.DESCRIPTIVE, MentionCategory.COMPOSITE)):
                self.hygiene_stats["nonbody_descriptive_dropped"] += 1
                self._chunk_dropped.add(name)
                return name, False
            # V0.2.5-b：BODY DESCRIPTIVE/COMPOSITE 无候选 → deferred（不立即注册；
            # canonical 创建推迟到 chunk 末决策边界：重召回 + 单次 judge 后再定）
            if cat in (MentionCategory.DESCRIPTIVE, MentionCategory.COMPOSITE):
                self._deferred.append(name)
                return name, False
            # PERSON / DESCRIPTIVE / COMPOSITE / None → 注册 canonical（兜底不静默丢人物）
            # V0.2.5-a：非正文 → provisional（不参与候选源；BODY 确认后晋升）
            provisional = self._current_section_type != SectionType.BODY
            self._register(name, provisional=provisional)
            if not provisional:
                confirmed.add(name)
            return name, False
        return name, True  # 进 pending（GENERIC/DESCRIPTIVE/COMPOSITE/PERSON 均可 judge）

    def _category_of(self, name: str) -> MentionCategory | None:
        """返回本 chunk 提取的 category（若有）；跨 chunk 不保留。"""
        return self._current_categories.get(name)

    def _recall(self, mention: str, confirmed: set[str], text_confirmed: set[str]) -> list[AliasCandidate]:
        """候选召回（V0.2.3-a strong/weak 两段式）：

        - strong（全部保留，不受 RECALL_TOP_K 限制）：
          ① extraction 共现（confirmed，本 chunk 提取输出中已确认的 canonical）
          ② 文本层共现（text_confirmed，chunk 原文出现的已知 canonical/alias）
          strong 按 canonical 去重，extraction 在前、text 在后。
        - weak（只补足到 RECALL_TOP_K）：字符重合/子串，确定性 tie-break。
        - RECALL_TOP_K 语义 = weak 补位目标容量，不再是最终候选数硬上限。
        """
        out: list[AliasCandidate] = []
        seen: set[str] = set()
        # V0.2.4：硬过滤 canonical 不得进入任何一层候选（防历史污染节点）
        from app.pipeline.hygiene import is_hard_filtered
        def _candidate_ok(canonical: str) -> bool:
            return not is_hard_filtered(canonical)

        # 1) strong：extraction 共现候选（强，优先）
        for canonical in confirmed:
            if canonical == mention or canonical not in self._index or canonical in seen:
                continue
            if not _candidate_ok(canonical):
                continue
            seen.add(canonical)
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))

        # 2) strong：文本层共现候选（强，顺序在 extraction 之后）
        for canonical in text_confirmed:
            if canonical == mention or canonical not in self._index or canonical in seen:
                continue
            if not _candidate_ok(canonical):
                continue
            seen.add(canonical)
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))

        # 3) weak：字符重合 + 子串候选，只补足剩余容量；确定性 tie-break（不依赖 set/dict 顺序）
        scored: list[tuple[int, int, str]] = []
        for canonical, names in self._index.items():
            if canonical in seen or not _candidate_ok(canonical):
                continue
            hit = None
            for n in names:
                if mention in n or n in mention:      # 子串包含优先
                    hit = n
                    break
            overlap = max(_overlap(mention, n) for n in names) if names else 0
            scored.append((1 if hit else 0, overlap, canonical))
        # 排序键：-prio（子串命中优先）、-overlap（共享字符多优先）、canonical 升序（确定性 tie-break）
        scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
        for _prio, _ov, canonical in scored[: max(0, RECALL_TOP_K - len(out))]:
            seen.add(canonical)
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))
        return out

    def _pending_for(self, mention: str, confirmed: set[str], text_confirmed: set[str]) -> PendingMention:
        return PendingMention(mention=mention, candidates=self._recall(mention, confirmed, text_confirmed))

    def _apply_judge(self, judge_result: AliasJudgeResult, pending: list[PendingMention]):
        valid_canonicals = {c.canonical for p in pending for c in p.candidates}
        valid_mentions = {p.mention for p in pending}
        from app.pipeline.hygiene import classify_mention, is_hard_filtered
        for r in judge_result.resolutions:
            if r.mention not in valid_mentions:
                continue  # 约束：mention 必须来自输入
            if r.resolves_to is not None and r.resolves_to not in valid_canonicals:
                continue  # 约束：resolves_to 必须来自候选
            if r.resolves_to is not None and is_hard_filtered(r.resolves_to):
                continue  # V0.2.4 防御：不吸收硬过滤 canonical
            if is_hard_filtered(r.mention):
                continue  # V0.2.4 防御：被硬过滤 mention 的判定结果不写 known
            # V0.2.4-b RC3：relational generic（词表判定 GENERIC）判 null → 丢弃，不注册 canonical
            if r.resolves_to is None and classify_mention(r.mention) == MentionCategory.GENERIC:
                continue
            if r.resolves_to is None:
                # V0.2.5-b：DESCRIPTIVE/COMPOSITE null → unresolved（不写 known）；
                # PERSON/None → 既有 fail-safe（非正文 → -a provisional 语义）
                self._register_or_unresolved(r.mention)
                continue
            # 有效 resolves_to → 既有 alias/resolution 语义（含 deferred 重召回后并入 pending 者）
            self.known[r.mention] = r.resolves_to
            self._add_alias(r.resolves_to, r.mention)
            # V0.2.4：DESCRIPTIVE/COMPOSITE 消歧成功计数
            cat = self._category_of(r.mention)
            if cat == MentionCategory.DESCRIPTIVE:
                self.hygiene_stats["descriptive_resolved"] += 1
            elif cat == MentionCategory.COMPOSITE:
                self.hygiene_stats["composite_resolved"] += 1
        # 未出现在判定结果中的 pending mention → 独立 canonical（防御）
        judged = {r.mention for r in judge_result.resolutions}
        for p in pending:
            if p.mention not in judged:
                # V0.2.4 防御：被硬过滤 mention 不得因防御路径注册
                if is_hard_filtered(p.mention):
                    continue
                # V0.2.4-b RC3 防御：relational generic 不得因防御路径注册
                if classify_mention(p.mention) == MentionCategory.GENERIC:
                    continue
                # V0.2.5-b：DESCRIPTIVE/COMPOSITE 缺席 → unresolved；其余走 -a 语义
                self._register_or_unresolved(p.mention)

    def _register(self, name: str, provisional: bool = False):
        """name 成为新的 canonical（首次出现）。

        V0.2.5-a：provisional=True（非正文注册）→ 不进入 _index（对候选源不可见，
        T-a14），BODY 同名字出现时经 _promote 晋升为正式 canonical。
        """
        self.known[name] = name
        self.canonical_aliases.setdefault(name, [])
        if provisional:
            self._provisional.add(name)
            self.hygiene_stats["nonbody_person_provisional"] += 1
        else:
            self._index.setdefault(name, set()).add(name)
            # V0.2.3-b1：首次确立 canonical 的 chunk_id（非原文首次出现位置）
            self._first_seen.setdefault(name, self._current_chunk_id)

    def _promote(self, name: str):
        """V0.2.5-a：provisional → 正式 canonical（BODY 同名字出现时，D3）。"""
        if name not in self._provisional:
            return
        self._provisional.discard(name)
        self._index.setdefault(name, set()).add(name)
        # 首次 BODY 证据为准（非正文 chunk 不参与 mc/chapters 统计）
        self._first_seen.setdefault(name, self._current_chunk_id)

    def _register_mention(self, name: str) -> None:
        """V0.2.5-a：null/缺席/异常 路径的统一注册入口（按 section+category 分派）。

        - 非正文 DESCRIPTIVE/COMPOSITE：永不注册（丢弃计数 + 本 chunk 输出剔除）；
        - 非正文 PERSON / category=None：provisional 注册；
        - BODY：既有语义（正常注册）。
        """
        cat = self._category_of(name)
        if (self._current_section_type != SectionType.BODY
                and cat in (MentionCategory.DESCRIPTIVE, MentionCategory.COMPOSITE)):
            self.hygiene_stats["nonbody_descriptive_dropped"] += 1
            self._chunk_dropped.add(name)
            return
        self._register(name, provisional=(self._current_section_type != SectionType.BODY))

    def _register_or_unresolved(self, name: str) -> None:
        """V0.2.5-b：judge null/缺失/异常 路径的统一分派（不写 known）。

        - BODY DESCRIPTIVE/COMPOSITE → unresolved（永不 canonicalize，计数 + 输出剔除）
        - 其余（PERSON/None，或非正文 DESCRIPTIVE/COMPOSITE）→ 沿用 _register_mention（-a 语义）
        """
        cat = self._category_of(name)
        if (self._current_section_type == SectionType.BODY
                and cat in (MentionCategory.DESCRIPTIVE, MentionCategory.COMPOSITE)):
            self._unresolved.add(name)
            self._count_unresolved(name)
            return
        self._register_mention(name)

    def _count_unresolved(self, name: str) -> None:
        """V0.2.5-b：descriptive/composite_unresolved 计数。"""
        cat = self._category_of(name)
        if cat == MentionCategory.DESCRIPTIVE:
            self.hygiene_stats["descriptive_unresolved"] += 1
        elif cat == MentionCategory.COMPOSITE:
            self.hygiene_stats["composite_unresolved"] += 1

    def finalize(self) -> set[str]:
        """V0.2.5-a：flush 未获正文确认的 provisional canonical（不入图）。

        返回被排除的名字集合（novels.py 据此从 MergedGraph 移除对应 Person 与端点关系）。
        只清理 resolver 状态；不改 MergedGraph。provisional 从未进入 _index，
        故无需 _index 清理；也从未被吸收为 alias。
        """
        dropped: set[str] = set()
        for name in list(self._provisional):
            if self.known.get(name) == name:
                dropped.add(name)
                del self.known[name]
                self.canonical_aliases.pop(name, None)
            self._provisional.discard(name)
        self.hygiene_stats["nonbody_provisional_dropped"] = len(dropped)
        return dropped

    def _add_alias(self, canonical: str, alias: str):
        if alias == canonical:
            return  # canonical 不进 aliases
        if canonical not in self.known or self.known[canonical] != canonical:
            return  # 防御：canonical 必须已知且为主名
        self.known[alias] = canonical
        self._index.setdefault(canonical, set()).add(canonical)
        self._index[canonical].add(alias)
        if alias not in self.canonical_aliases[canonical]:
            self.canonical_aliases[canonical].append(alias)  # 首次确认顺序

    # ---- V0.2.3-b1：canonical merge decision（纯 decision，基于 snapshot，不修改 known/_index/canonical_aliases）----

    def decide_merges(self, merge_judge, confidence_threshold: float = 0.5) -> dict:
        """基于 resolve 完成后的 canonical metadata 快照构建 merge_map。

        - 纯 decision：不修改 known/_index/canonical_aliases；不提前应用 merge_map；
        - 所有 pair 基于同一份快照独立判定，不做传递合并；
        - judge failure / confidence 低于阈值 → 不 merge（计入统计）。
        返回 {"merge_map", "stats", "merge_failures"}。
        """
        from app.schemas.llm import BridgeEvidence, MergePair, MergePairSide

        # 1) pair 去重：frozenset(pair) -> evidence 列表（同 pair 只判一次）
        pair_evidences: dict[frozenset, list[dict]] = {}
        for ev in self.merge_evidence:
            key = frozenset(ev["pair"])
            pair_evidences.setdefault(key, []).append(ev)

        # 2) 从 canonical snapshot 构造 judge 输入（不因其他 pair 的判定变化）
        pairs_input: list[MergePair] = []
        for key, evs in pair_evidences.items():
            c1, c2 = tuple(key)
            if c1 not in self.known or c2 not in self.known:
                continue
            sides = []
            for c in (c1, c2):
                sides.append(MergePairSide(
                    canonical=c,
                    aliases=list(self.canonical_aliases.get(c, [])),
                    first_seen_chunk=self._first_seen.get(c, 0),
                    mention_count=len(self._canonical_chunks.get(c, set())),
                    chapters=sorted(self._canonical_chapters.get(c, set())),
                ))
            pairs_input.append(MergePair(
                a=sides[0], b=sides[1],
                bridge_evidence=[BridgeEvidence(
                    chunk_id=e["chunk_id"], chapter_id=e["chapter_id"],
                    mention=e["mention"], text=e["text"],
                ) for e in evs],
            ))

        stats = {"merge_candidate_pairs": len(pairs_input),
                 "merged_pairs": 0, "rejected_pairs": 0,
                 "low_confidence_pairs": 0, "failed_pairs": 0}
        merge_failures: list[dict] = []

        if not pairs_input:
            return {"merge_map": dict(self.merge_map),
                    "stats": {"entity_resolution": stats}, "merge_failures": merge_failures}

        # 3) batch merge judge
        try:
            result = merge_judge(pairs_input)
        except Exception as exc:
            stats["failed_pairs"] = len(pairs_input)
            merge_failures.append({"error": f"{type(exc).__name__}:{exc}"})
            return {"merge_map": dict(self.merge_map),
                    "stats": {"entity_resolution": stats}, "merge_failures": merge_failures}

        # 4) 过滤 + 构建 merge_map（C_keep = first_seen 更小；相同按 canonical 字符串升序）
        valid_keys = {frozenset((p.a.canonical, p.b.canonical)) for p in pairs_input}
        for d in result.merges:
            key = frozenset((d.a, d.b))
            if key not in valid_keys:
                continue  # 约束：a/b 必须来自输入 pairs
            if not d.merge:
                stats["rejected_pairs"] += 1
                continue
            if d.confidence < confidence_threshold:
                stats["low_confidence_pairs"] += 1
                continue
            c1, c2 = tuple(key)
            # 确定性 keep：first_seen 更小者；相同 → canonical 字符串升序较小者
            if (self._first_seen.get(c1, 0), c1) <= (self._first_seen.get(c2, 0), c2):
                keep, drop = c1, c2
            else:
                keep, drop = c2, c1
            self.merge_map[drop] = keep
            stats["merged_pairs"] += 1

        return {"merge_map": dict(self.merge_map),
                "stats": {"entity_resolution": stats}, "merge_failures": merge_failures}

    def resolve_merge_root(self, name: str) -> str:
        """沿 merge_map 解析最终 keep（仅查询，不创建新合并）。"""
        seen: set[str] = set()
        while name in self.merge_map and name not in seen:
            seen.add(name)
            name = self.merge_map[name]
        return name
