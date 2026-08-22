import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.merger import MergedGraph, PersonAgg, RelAgg, apply_aliases, apply_merges, merge_extractions
from app.schemas.llm import ExtractionResult, Relationship, RelationshipType


def make_chunk(chunk_id, chapter_id=1, text="abc"):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text))


def extraction(relationships, characters=None):
    return ExtractionResult.model_validate({
        "characters": characters or [],
        "relationships": relationships,
    })


def test_same_chunk_duplicate_counts_once():
    """weight 语义锁死：同一 chunk 重复输出同一关系只计一次。"""
    chunk = make_chunk(1)
    result = extraction([
        {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.95},
        {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.90},
    ])
    graph = merge_extractions([(chunk, result)])
    rel = graph.relationships[("贾宝玉", "林黛玉", RelationshipType.love)]
    assert rel.weight == 1
    assert rel.chunk_ids == {1}
    assert rel.confidence == pytest.approx(0.95)  # 块内取首次置信度


def test_weight_counts_distinct_chunks():
    chunks = [make_chunk(1), make_chunk(7), make_chunk(12)]
    results = [
        extraction([{"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": c}])
        for c in (0.95, 0.90, 0.70)
    ]
    graph = merge_extractions(list(zip(chunks, results)))
    rel = graph.relationships[("贾宝玉", "林黛玉", RelationshipType.love)]
    assert rel.weight == 3
    assert rel.chunk_ids == {1, 7, 12}
    assert rel.confidence == pytest.approx(0.85)  # (0.95+0.90+0.70)/3


def test_evidence_first_five_by_discovery_order():
    chunks = [make_chunk(i) for i in range(1, 9)]
    results = [
        extraction([{"source": "A", "target": "B", "type": "other", "confidence": 0.8}])
        for _ in chunks
    ]
    graph = merge_extractions(list(zip(chunks, results)))
    rel = graph.relationships[("A", "B", RelationshipType.other)]
    assert rel.weight == 8
    assert [e["chunk_id"] for e in rel.evidence] == [1, 2, 3, 4, 5]
    assert len(rel.evidence) == 5


def test_mention_count_is_distinct_chunks():
    chunk1 = make_chunk(1)
    chunk2 = make_chunk(2, chapter_id=2)
    r1 = extraction(
        [{"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.9}],
        characters=[{"name": "贾宝玉"}],
    )
    r2 = extraction([], characters=[{"name": "贾宝玉"}, {"name": "林黛玉"}])
    graph = merge_extractions([(chunk1, r1), (chunk2, r2)])
    assert graph.persons["贾宝玉"].mention_count == 2
    assert graph.persons["贾宝玉"].chapters == {1, 2}
    assert graph.persons["林黛玉"].mention_count == 1


def test_merger_defensively_skips_self_loop():
    chunk = make_chunk(1)
    result = ExtractionResult.model_construct(characters=[], relationships=[
        Relationship(source="A", target="A", type=RelationshipType.other, confidence=0.5),
    ])
    graph = merge_extractions([(chunk, result)])
    assert graph.relationships == {}


def test_merge_is_deterministic_regardless_of_input_order():
    chunks = [make_chunk(2), make_chunk(1)]
    results = [
        extraction([{"source": "A", "target": "B", "type": "other", "confidence": 0.8}])
        for _ in chunks
    ]
    graph = merge_extractions(list(zip(chunks, results)))
    rel = graph.relationships[("A", "B", RelationshipType.other)]
    assert [e["chunk_id"] for e in rel.evidence] == [1, 2]  # 按 chunk_id 排序后首现顺序


def test_apply_aliases_filters_canonical_and_dedupes():
    graph = MergedGraph(
        persons={"傩送": PersonAgg(name="傩送", mention_count=2, chapters={1})},
        relationships={},
    )
    apply_aliases(graph, {"傩送": ["二老", "傩送", "二老", "二老爷"]})
    assert graph.persons["傩送"].aliases == ["二老", "二老爷"]


# ---------- Task 1: chunk_ids 收集 ----------

def test_merge_extractions_collects_chunk_ids():
    """merge_extractions 聚合时收集 chunk_ids；同 chunk 内重复 canonical 只计一次。"""
    graph = merge_extractions([
        (make_chunk(1), extraction([], characters=[{"name": "大儿子"}, {"name": "大儿子"}])),  # 同 chunk 重复
        (make_chunk(2), extraction([], characters=[{"name": "大儿子"}])),
    ])
    p = graph.persons["大儿子"]
    assert p.chunk_ids == {1, 2}
    assert p.mention_count == 2   # len(chunk_ids)，非 3


def test_chunk_ids_distinct_across_chunks():
    """不同 chunk 各自计数；mention_count = distinct chunk 数。"""
    graph = merge_extractions([
        (make_chunk(1), extraction([], characters=[{"name": "A"}])),
        (make_chunk(2), extraction([], characters=[{"name": "A"}])),
        (make_chunk(3), extraction([], characters=[{"name": "A"}, {"name": "A"}, {"name": "A"}])),
    ])
    assert graph.persons["A"].chunk_ids == {1, 2, 3}
    assert graph.persons["A"].mention_count == 3


# ---------- Task 2: apply_merges ----------

def build_graph_for_merge():
    """A(keep, first chunk1) + B(drop, first chunk2)；A/B 各有关系与 alias。"""
    graph = MergedGraph(persons={
        "A": PersonAgg(name="A", chapters={1}, aliases=["别名A"], chunk_ids={1}),
        "B": PersonAgg(name="B", chapters={2}, aliases=["别名B"], chunk_ids={2}),
        "X": PersonAgg(name="X", chapters={1, 2}, aliases=[], chunk_ids={1, 2}),
    })
    graph.relationships = {
        ("A", "X", RelationshipType.friendship): RelAgg(
            source="A", target="X", type=RelationshipType.friendship,
            chunk_ids={1}, confidences=[0.8], evidence=[{"chunk_id": 1, "chapter_id": 1, "text": "e1"}]),
        ("B", "X", RelationshipType.friendship): RelAgg(
            source="B", target="X", type=RelationshipType.friendship,
            chunk_ids={2}, confidences=[0.7], evidence=[{"chunk_id": 2, "chapter_id": 2, "text": "e2"}]),
        ("B", "A", RelationshipType.family): RelAgg(   # B↔A 合并后成 self-loop → 删除
            source="B", target="A", type=RelationshipType.family,
            chunk_ids={2}, confidences=[0.6], evidence=[]),
    }
    return graph


def test_apply_merges_aliases_merge_order():
    """aliases = C_keep 原 aliases → C_drop aliases → C_drop canonical name。"""
    g = build_graph_for_merge()
    apply_merges(g, {"B": "A"})
    assert g.persons["A"].aliases == ["别名A", "别名B", "B"]


def test_apply_merges_aliases_dedup_and_no_canonical():
    """canonical 不进 aliases；重复 alias 去重。"""
    g = MergedGraph(persons={
        "A": PersonAgg(name="A", aliases=["X", "共享"], chunk_ids={1}),
        "B": PersonAgg(name="B", aliases=["X", "共享"], chunk_ids={2}),   # X/共享 均与 A 重复
    })
    apply_merges(g, {"B": "A"})
    assert g.persons["A"].aliases == ["X", "共享", "B"]


def test_apply_merges_chunk_ids_union():
    """chunk_ids union；mention_count = len(union)。"""
    g = MergedGraph(persons={
        "A": PersonAgg(name="A", chunk_ids={1, 2}),
        "B": PersonAgg(name="B", chunk_ids={2, 3}),   # 与 A 重叠 chunk 2
    })
    apply_merges(g, {"B": "A"})
    p = g.persons["A"]
    assert p.chunk_ids == {1, 2, 3}
    assert p.mention_count == 3          # union 长度，非 2+2=4


def test_apply_merges_chapters_union():
    g = MergedGraph(persons={
        "A": PersonAgg(name="A", chapters={1, 3}),
        "B": PersonAgg(name="B", chapters={2, 3}),
    })
    apply_merges(g, {"B": "A"})
    assert g.persons["A"].chapters == {1, 2, 3}


def test_apply_merges_c_drop_removed_from_persons():
    g = build_graph_for_merge()
    apply_merges(g, {"B": "A"})
    assert "B" not in g.persons


def test_apply_merges_relationship_redirect():
    """source/target == C_drop 的边重定向到 C_keep。"""
    g = build_graph_for_merge()
    apply_merges(g, {"B": "A"})
    assert ("B", "X", RelationshipType.friendship) not in g.relationships
    merged_rel = g.relationships[("A", "X", RelationshipType.friendship)]
    assert merged_rel.chunk_ids == {1, 2}          # A→X 与 B→X 合并


def test_apply_merges_relationship_confidence_reaggregated():
    """重定向后同 key 关系 confidence 重新聚合（算术平均）。"""
    g = build_graph_for_merge()
    apply_merges(g, {"B": "A"})
    rel = g.relationships[("A", "X", RelationshipType.friendship)]
    assert rel.confidences == [0.8, 0.7]
    assert rel.confidence == pytest.approx(0.75)


def test_apply_merges_evidence_cap():
    """evidence 保持 EVIDENCE_CAP=5，首次发现顺序。"""
    g = MergedGraph(persons={
        "A": PersonAgg(name="A", chunk_ids={1}),
        "B": PersonAgg(name="B", chunk_ids={2}),
        "X": PersonAgg(name="X", chunk_ids={1, 2}),
    })
    ev_a = [{"chunk_id": 1, "chapter_id": 1, "text": f"a{i}"} for i in range(5)]
    ev_b = [{"chunk_id": 2, "chapter_id": 2, "text": f"b{i}"} for i in range(5)]
    g.relationships = {
        ("A", "X", RelationshipType.friendship): RelAgg(
            source="A", target="X", type=RelationshipType.friendship,
            chunk_ids={1}, confidences=[0.8], evidence=ev_a),
        ("B", "X", RelationshipType.friendship): RelAgg(
            source="B", target="X", type=RelationshipType.friendship,
            chunk_ids={2}, confidences=[0.7], evidence=ev_b),
    }
    apply_merges(g, {"B": "A"})
    rel = g.relationships[("A", "X", RelationshipType.friendship)]
    assert len(rel.evidence) == 5      # cap
    assert rel.evidence[:5] == ev_a[:5]  # A 的 evidence 在前


def test_apply_merges_self_loop_deleted():
    """C_keep ↔ C_drop 合并后 self-loop 删除。"""
    g = build_graph_for_merge()
    apply_merges(g, {"B": "A"})
    assert ("A", "A", RelationshipType.family) not in g.relationships


def test_apply_merges_reverse_direction_redirect():
    """target == C_drop 的边（X→B）也重定向。"""
    g = MergedGraph(persons={
        "A": PersonAgg(name="A", chunk_ids={1}),
        "B": PersonAgg(name="B", chunk_ids={2}),
        "X": PersonAgg(name="X", chunk_ids={1, 2}),
    })
    g.relationships = {
        ("X", "B", RelationshipType.enmity): RelAgg(
            source="X", target="B", type=RelationshipType.enmity,
            chunk_ids={2}, confidences=[0.5], evidence=[]),
    }
    apply_merges(g, {"B": "A"})
    assert ("X", "B", RelationshipType.enmity) not in g.relationships
    assert ("X", "A", RelationshipType.enmity) in g.relationships


def test_apply_merges_multiple_drops_chain_independent():
    """merge_map 多项（B→A、C→A）各自独立应用；不做传递合并。"""
    g = MergedGraph(persons={
        "A": PersonAgg(name="A", chunk_ids={1}),
        "B": PersonAgg(name="B", chunk_ids={2}),
        "C": PersonAgg(name="C", chunk_ids={3}),
    })
    g.relationships = {}
    apply_merges(g, {"B": "A", "C": "A"})
    assert set(g.persons) == {"A"}
    assert g.persons["A"].chunk_ids == {1, 2, 3}
    assert g.persons["A"].aliases == ["B", "C"]


def test_apply_merges_unknown_keep_noop():
    """merge_map 引用不存在的 canonical → 安全跳过（防御）。"""
    g = MergedGraph(persons={
        "A": PersonAgg(name="A", chunk_ids={1}),
    })
    apply_merges(g, {"不存在": "A"})
    assert set(g.persons) == {"A"}
