from dataclasses import dataclass, field

from app.pipeline.chunker import Chunk
from app.schemas.llm import ExtractionResult, RelationshipType

EVIDENCE_CAP = 5


@dataclass
class PersonAgg:
    name: str
    mention_count: int = 0
    chapters: set[int] = field(default_factory=set)
    aliases: list[str] = field(default_factory=list)
    chunk_ids: set[int] = field(default_factory=set)   # V0.2.3-b2：distinct chunk 集合


@dataclass
class RelAgg:
    source: str
    target: str
    type: RelationshipType
    chunk_ids: set[int] = field(default_factory=set)
    confidences: list[float] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)

    @property
    def weight(self) -> int:
        return len(self.chunk_ids)

    @property
    def confidence(self) -> float:
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0.0


@dataclass
class MergedGraph:
    persons: dict[str, PersonAgg] = field(default_factory=dict)
    relationships: dict[tuple[str, str, RelationshipType], RelAgg] = field(default_factory=dict)


def merge_extractions(extractions: list[tuple[Chunk, ExtractionResult]]) -> MergedGraph:
    """按 chunk 聚合。

    - 唯一输入单位 chunk_id：同 (source, target, type) 在一个 chunk 内只计一次；
    - weight = 确认该关系的不同 chunk 数（distinct chunk_id）；
    - confidence = 各确认 chunk confidence 的算术平均（块内重复取首次值）；
    - evidence 按首次发现顺序保留前 EVIDENCE_CAP 条，之后不再追加；
    - mention_count = 该人物出现在 characters 字段中的不同 chunk 数（关系端点不计入）；
    - self-loop 防御性丢弃；
    - 输入先按 chunk_id 排序，保证首次发现顺序确定（多次运行结果稳定）。
    """
    graph = MergedGraph()
    for chunk, result in sorted(extractions, key=lambda e: e[0].chunk_id):
        seen_names: set[str] = set()
        for c in result.characters:
            seen_names.add(c.name)
        for r in result.relationships:
            if r.source == r.target:
                continue  # 防御：self-loop 直接丢弃
            rel = graph.relationships.setdefault(
                (r.source, r.target, r.type),
                RelAgg(source=r.source, target=r.target, type=r.type),
            )
            if chunk.chunk_id not in rel.chunk_ids:
                rel.chunk_ids.add(chunk.chunk_id)
                rel.confidences.append(r.confidence)
                if len(rel.evidence) < EVIDENCE_CAP:
                    rel.evidence.append({
                        "chunk_id": chunk.chunk_id,
                        "chapter_id": chunk.chapter_id,
                        "text": chunk.text,
                    })
        for name in seen_names:
            person = graph.persons.setdefault(name, PersonAgg(name=name))
            person.chunk_ids.add(chunk.chunk_id)   # V0.2.3-b2：收集 distinct chunk
            person.chapters.add(chunk.chapter_id)
    # V0.2.3-b2：mention_count = len(chunk_ids)（distinct chunk 语义）
    for person in graph.persons.values():
        person.mention_count = len(person.chunk_ids)
    return graph


def apply_aliases(graph: MergedGraph, canonical_aliases: dict[str, list[str]]) -> None:
    """把 resolver 的别名映射写回 PersonAgg（排除 canonical 自身、去重、保序）。"""
    for name, person in graph.persons.items():
        seen: set[str] = set()
        aliases: list[str] = []
        for a in canonical_aliases.get(name, []):
            if a == name or a in seen:
                continue
            seen.add(a)
            aliases.append(a)
        person.aliases = aliases


def apply_merges(graph: MergedGraph, merge_map: dict[str, str]) -> None:
    """把 b1 的 merge_map（C_drop -> C_keep）应用到内存 MergedGraph（V0.2.3-b2）。

    - 输入：aliases 已由 apply_aliases 完成的 MergedGraph + merge_map（唯一额外输入）；
      不接收 resolver.canonical_aliases，不在此重建 aliases；
    - C_keep 保留（canonical 不变）；C_drop 从 persons 移除；
    - aliases 合并顺序：C_keep 原 aliases → C_drop aliases → C_drop canonical name；
      canonical 不进入 aliases；去重；保持首次确认顺序；
    - chunk_ids/chapters 并集；mention_count = len(union)；
    - RELATES_TO：source/target == C_drop 重定向到 C_keep；重定向后同 key 合并
      （chunk_ids 并集、confidences 拼接、evidence 保序 cap EVIDENCE_CAP）；self-loop 删除；
    - 防御：merge_map 引用不存在的 canonical 安全跳过。
    """
    # 0) 校验并收集有效 merge（C_keep / C_drop 都必须存在）
    valid: dict[str, str] = {}
    for drop, keep in merge_map.items():
        if drop in graph.persons and keep in graph.persons and drop != keep:
            valid[drop] = keep

    if not valid:
        return

    # 1) PersonAgg 合并（先收集，再统一写回，避免迭代中修改 persons）
    merged_persons: dict[str, PersonAgg] = dict(graph.persons)
    for drop, keep in valid.items():
        target = merged_persons[keep]
        source = merged_persons[drop]
        target.chunk_ids |= source.chunk_ids
        target.chapters |= source.chapters
        target.mention_count = len(target.chunk_ids)
        # aliases：C_keep 原序 → C_drop aliases → C_drop name（去重、canonical 不进）
        seen = set(target.aliases)
        for a in source.aliases:
            if a == keep or a in seen:
                continue
            seen.add(a)
            target.aliases.append(a)
        if drop != keep and drop not in seen:
            target.aliases.append(drop)
        del merged_persons[drop]
    graph.persons = merged_persons

    # 2) RELATES_TO 重定向 + 同 key 聚合 + self-loop 删除
    new_rels: dict[tuple[str, str, RelationshipType], RelAgg] = {}
    for (src, tgt, rtype), rel in graph.relationships.items():
        nsrc = valid.get(src, src)   # src == drop → keep
        ntgt = valid.get(tgt, tgt)
        if nsrc == ntgt:
            continue  # self-loop 删除
        key = (nsrc, ntgt, rtype)
        existing = new_rels.get(key)
        if existing is None:
            new_rels[key] = RelAgg(
                source=nsrc, target=ntgt, type=rtype,
                chunk_ids=set(rel.chunk_ids),
                confidences=list(rel.confidences),
                evidence=list(rel.evidence),
            )
        else:
            existing.chunk_ids |= rel.chunk_ids
            existing.confidences.extend(rel.confidences)
            for item in rel.evidence:
                if len(existing.evidence) >= EVIDENCE_CAP:
                    break
                existing.evidence.append(item)
    graph.relationships = new_rels
