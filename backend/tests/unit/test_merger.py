import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.merger import MergedGraph, PersonAgg, apply_aliases, merge_extractions
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
