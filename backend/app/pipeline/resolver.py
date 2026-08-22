from dataclasses import dataclass, field
from typing import Callable

from app.pipeline.chunker import Chunk
from app.schemas.llm import AliasCandidate, AliasJudgeResult, ExtractionResult, PendingMention

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

    # ---- 公开 ----
    def resolve(self, chunk: Chunk, result: ExtractionResult) -> tuple[ExtractionResult, bool]:
        self._current_chunk_id = chunk.chunk_id
        self._current_chapter_id = chunk.chapter_id
        pending: list[PendingMention] = []
        resolved_chars: list = []
        resolved_rels: list = []
        # 预扫描：本 chunk 全部名字（characters + 关系端点）中已在 known 的 → 预置为共现源。
        # 消除同 chunk 共现召回的顺序敏感性：未知 mention 无论出现在已知名前/后，都能召回它。
        chunk_names = (
            {c.name for c in result.characters}
            | {r.source for r in result.relationships}
            | {r.target for r in result.relationships}
        )
        confirmed: set[str] = {self.known[n] for n in chunk_names if n in self.known}
        # 文本层共现源（V0.2.2）：chunk 原文中出现的已知 canonical/alias → canonical。
        # 仅作候选信号，绝不直接认定同一人（仍须经 judge）。
        text_confirmed: set[str] = self._text_mentions(chunk.text)

        def do_name(name: str) -> str:
            canonical, needs_judge = self._resolve_name(name, confirmed, text_confirmed)
            if needs_judge:
                pending.append(self._pending_for(name, confirmed, text_confirmed))
                return name  # 判定后再替换
            return canonical

        for c in result.characters:
            resolved_chars.append({"name": do_name(c.name)})
        for r in result.relationships:
            src = do_name(r.source)
            tgt = do_name(r.target)
            resolved_rels.append({
                "source": src, "target": tgt, "type": r.type.value,
                "confidence": r.confidence,
            })

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
                # validation/网络等任何失败：本 chunk 待判定 mention 独立为 canonical（预期行为）
                for p in pending:
                    self._register(p.mention)
                failed = True

        # 判定后二次替换（pending 中的 mention → canonical）
        if pending:
            name_map = {p.mention: self.known[p.mention] for p in pending}
            resolved_chars = [{"name": name_map.get(c["name"], c["name"])} for c in resolved_chars]
            for rel in resolved_rels:
                rel["source"] = name_map.get(rel["source"], rel["source"])
                rel["target"] = name_map.get(rel["target"], rel["target"])

        # V0.2.3-b1：canonical 出现统计（轻量 metadata，供 merge judge 输入）
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
        if name in self.known:
            canonical = self.known[name]
            confirmed.add(canonical)  # 已确认 → 成为后续同名 chunk 内共现候选源
            return canonical, False
        candidates = self._recall(name, confirmed, text_confirmed)
        if not candidates:
            self._register(name)
            confirmed.add(name)
            return name, False
        return name, True  # 进 pending，本 chunk 末统一判定

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

        # 1) strong：extraction 共现候选（强，优先）
        for canonical in confirmed:
            if canonical == mention or canonical not in self._index or canonical in seen:
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
            seen.add(canonical)
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))

        # 3) weak：字符重合 + 子串候选，只补足剩余容量；确定性 tie-break（不依赖 set/dict 顺序）
        scored: list[tuple[int, int, str]] = []
        for canonical, names in self._index.items():
            if canonical in seen:
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
        for r in judge_result.resolutions:
            if r.mention not in valid_mentions:
                continue  # 约束：mention 必须来自输入
            if r.resolves_to is not None and r.resolves_to not in valid_canonicals:
                continue  # 约束：resolves_to 必须来自候选
            self.known[r.mention] = r.resolves_to if r.resolves_to is not None else r.mention
            if r.resolves_to is not None:
                self._add_alias(r.resolves_to, r.mention)
            else:
                self._register(r.mention)
        # 未出现在判定结果中的 pending mention → 独立 canonical（防御）
        judged = {r.mention for r in judge_result.resolutions}
        for p in pending:
            if p.mention not in judged:
                self._register(p.mention)

    def _register(self, name: str):
        """name 成为新的 canonical（首次出现）。"""
        self.known[name] = name
        self.canonical_aliases.setdefault(name, [])
        self._index.setdefault(name, set()).add(name)
        # V0.2.3-b1：首次确立 canonical 的 chunk_id（非原文首次出现位置）
        self._first_seen.setdefault(name, self._current_chunk_id)

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
