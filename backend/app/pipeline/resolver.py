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

    # ---- 公开 ----
    def resolve(self, chunk: Chunk, result: ExtractionResult) -> tuple[ExtractionResult, bool]:
        pending: list[PendingMention] = []
        resolved_chars: list = []
        resolved_rels: list = []

        def do_name(name: str) -> str:
            canonical, needs_judge = self._resolve_name(name)
            if needs_judge:
                pending.append(self._pending_for(name))
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

        resolved = ExtractionResult.model_validate({
            "characters": resolved_chars,
            "relationships": resolved_rels,
        })
        return resolved, failed

    # ---- 内部 ----
    def _resolve_name(self, name: str) -> tuple[str, bool]:
        if name in self.known:
            return self.known[name], False
        candidates = self._recall(name)
        if not candidates:
            self._register(name)
            return name, False
        return name, True  # 进 pending，本 chunk 末统一判定

    def _recall(self, mention: str) -> list[AliasCandidate]:
        scored: list[tuple[int, str, set[str]]] = []
        for canonical, names in self._index.items():
            hit = None
            for n in names:
                if mention in n or n in mention:      # 子串包含优先
                    hit = n
                    break
            overlap = max(_overlap(mention, n) for n in names) if names else 0
            scored.append((1 if hit else 0, overlap, canonical))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        out = []
        for _prio, _ov, canonical in scored[:RECALL_TOP_K]:
            out.append(AliasCandidate(
                canonical=canonical,
                matched_names=sorted(self._index[canonical]),
            ))
        return out

    def _pending_for(self, mention: str) -> PendingMention:
        return PendingMention(mention=mention, candidates=self._recall(mention))

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
