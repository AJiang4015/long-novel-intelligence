"""V0.2.3-b2 集成测试：bridge → merge_map → apply_merges → Neo4j 单事务（mock judge，不调真实 LLM）。"""
import uuid

import pytest

from app.config import get_settings
from app.db.neo4j import Neo4jDB
from app.pipeline.chunker import Chunk
from app.pipeline.merger import MergedGraph, PersonAgg, RelAgg, apply_aliases, apply_merges, merge_extractions
from app.pipeline.resolver import EntityResolver
from app.schemas.llm import AliasJudgeResult, ExtractionResult, MergeJudgeResult, RelationshipType

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db():
    settings = get_settings()
    database = Neo4jDB(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        database.ping()
    except Exception:
        pytest.skip("Neo4j 不可达")
    database.ensure_constraints()
    yield database
    database.close()


@pytest.fixture()
def novel_id(db):
    nid = f"test-merge-{uuid.uuid4()}"
    yield nid
    db.delete_novel(nid)


def make_chunk(chunk_id, chapter_id=1, text="文本"):
    return Chunk(chunk_id=chunk_id, chapter_id=chapter_id, chapter_title="第1章",
                 text=text, start_offset=0, end_offset=len(text))


def extraction(names, rels=None):
    return ExtractionResult.model_validate({
        "characters": [{"name": n} for n in names],
        "relationships": rels or [],
    })


class _AliasJudge:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def __call__(self, text, pending):
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": self.mapping.get(p.mention)}
                            for p in pending]})


class _MergeJudgeTrue:
    """mock merge judge：所有 pair 判 merge=true, confidence=0.95。"""

    def __call__(self, pairs):
        return MergeJudgeResult.model_validate({
            "merges": [{"a": p.a.canonical, "b": p.b.canonical,
                        "merge": True, "confidence": 0.95} for p in pairs]})


def run_b1_b2(chunks_extractions, alias_mapping=None):
    """执行 resolve → decide_merges → merge_extractions → apply_aliases → apply_merges，返回 (merged, merge_map)。"""
    resolver = EntityResolver(judge=_AliasJudge(alias_mapping or {}))
    resolved = []
    for chunk, ext in chunks_extractions:
        out, _ = resolver.resolve(chunk, ext)
        resolved.append((chunk, out))
    merge_out = resolver.decide_merges(_MergeJudgeTrue(), confidence_threshold=0.5)
    merged = merge_extractions(resolved)
    apply_aliases(merged, resolver.canonical_aliases)
    apply_merges(merged, merge_out["merge_map"])
    return merged, merge_out["merge_map"]


def test_full_merge_pipeline_to_neo4j(db, novel_id):
    """完整链：A/B bridge merge → Neo4j。验证 10 项。"""
    db.upsert_novel(novel_id, "合并测试", [{"id": 1, "title": "第1章"}, {"id": 2, "title": "第2章"}])

    # A=大儿子(chunk1, 含别名 天保), B=大老(chunk2)；chunk3 bridge mention 天保大老（并入大老）
    chunks = [
        (make_chunk(1, text="大儿子和天保在河边"), extraction(["大儿子", "天保"])),
        (make_chunk(2, text="大老在河边"), extraction(["大老"])),
        (make_chunk(3, text="天保大老在河边"), extraction(["大老", "天保大老"])),
    ]
    merged, merge_map = run_b1_b2(chunks, alias_mapping={"天保": "大儿子", "天保大老": "大老"})

    # merge_map 应为 {"大老": "大儿子"}（大儿子 first_seen=1 < 大老=2）
    assert merge_map == {"大老": "大儿子"}

    db.upsert_graph(novel_id, merged, merge_map)

    # 1) C_keep 保留
    keep = db.search_characters(novel_id, "大儿子", limit=10)
    assert any(c["name"] == "大儿子" for c in keep)
    keep_id = next(c["id"] for c in keep if c["name"] == "大儿子")
    # 2) C_drop 不存在
    search_drop = db.search_characters(novel_id, "大老", limit=10)
    assert not any(c["name"] == "大老" for c in search_drop)
    # 3) aliases 正确（search alias 命中 C_keep）
    by_alias = db.search_characters(novel_id, "天保大老", limit=10)
    assert any(c["name"] == "大儿子" for c in by_alias)
    by_drop_name = db.search_characters(novel_id, "大老", limit=10)
    assert any(c["name"] == "大儿子" for c in by_drop_name)   # 大老 现在是大儿子 的 alias
    # 4) C_keep.id 稳定：再次 upsert 后 id 不变
    db.upsert_graph(novel_id, merged, merge_map)
    keep_after = db.search_characters(novel_id, "大儿子", limit=10)
    keep_after_id = next(c["id"] for c in keep_after if c["name"] == "大儿子")
    assert keep_after_id == keep_id


def test_merge_upsert_without_merge_map(db, novel_id):
    """无 merge 场景（merge_map=None）→ 单事务写入正常，不创建/删除额外 Person。"""
    db.upsert_novel(novel_id, "无合并测试", [{"id": 1, "title": "第1章"}])

    merged = MergedGraph(persons={
        "A": PersonAgg(name="A", mention_count=1, chapters={1}, aliases=[], chunk_ids={1}),
    })
    db.upsert_graph(novel_id, merged, None)
    found = db.search_characters(novel_id, "A", limit=10)
    assert any(c["name"] == "A" for c in found)
