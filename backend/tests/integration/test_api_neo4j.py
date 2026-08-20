import uuid

import pytest

from app.config import get_settings
from app.db.neo4j import Neo4jDB
from app.pipeline.merger import MergedGraph, PersonAgg, RelAgg
from app.schemas.llm import RelationshipType

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db():
    settings = get_settings()
    database = Neo4jDB(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        database.ping()
    except Exception:
        pytest.skip("Neo4j 不可达：请先 `docker compose up -d neo4j` 并配置 .env")
    database.ensure_constraints()
    yield database
    database.close()


def build_merged():
    return MergedGraph(
        persons={
            "贾宝玉": PersonAgg(name="贾宝玉", mention_count=3, chapters={1, 2}),
            "林黛玉": PersonAgg(name="林黛玉", mention_count=2, chapters={1}),
            "王熙凤": PersonAgg(name="王熙凤", mention_count=1, chapters={2}),
        },
        relationships={
            ("贾宝玉", "林黛玉", RelationshipType.love): RelAgg(
                source="贾宝玉", target="林黛玉", type=RelationshipType.love,
                chunk_ids={1, 7, 12}, confidences=[0.95, 0.9, 0.7],
                evidence=[{"chunk_id": 1, "chapter_id": 1, "text": "贾宝玉和林黛玉交谈。"}],
            ),
            ("王熙凤", "贾宝玉", RelationshipType.enmity): RelAgg(
                source="王熙凤", target="贾宝玉", type=RelationshipType.enmity,
                chunk_ids={2}, confidences=[0.8], evidence=[],
            ),
        },
    )


@pytest.fixture()
def novel_id(db):
    nid = f"test-{uuid.uuid4()}"
    yield nid
    db.delete_novel(nid)


def test_ensure_constraints_idempotent(db):
    db.ensure_constraints()
    db.ensure_constraints()  # 幂等，不抛错


def test_upsert_and_subgraph(db, novel_id):
    db.upsert_novel(novel_id, "测试小说", [{"id": 1, "title": "第1章"}, {"id": 2, "title": "第2章"}])
    db.upsert_graph(novel_id, build_merged())

    novel = db.get_novel(novel_id)
    assert novel["title"] == "测试小说"
    assert [c["id"] for c in novel["chapters"]] == [1, 2]

    cands = db.search_characters(novel_id, "贾")
    assert any(c["name"] == "贾宝玉" for c in cands)

    center = db.get_character(novel_id, cands[0]["id"])
    assert center["name"] == "贾宝玉"

    graph = db.get_subgraph(novel_id, center["id"])
    assert {n["name"] for n in graph["nodes"]} == {"贾宝玉", "林黛玉", "王熙凤"}
    center_node = next(n for n in graph["nodes"] if n["is_center"])
    assert center_node["name"] == "贾宝玉"

    love_edge = next(e for e in graph["edges"] if e["type"] == "love")
    assert love_edge["weight"] == 3
    assert love_edge["confidence"] == pytest.approx(0.85)
    assert love_edge["evidence"][0]["chapter_title"] == "第1章"
    assert love_edge["source_id"] == center["id"]

    stats = db.count_stats(novel_id)
    assert stats == {"persons": 3, "relationships": 2}


def test_subgraph_unknown_character_returns_none(db, novel_id):
    db.upsert_novel(novel_id, "测试小说", [])
    assert db.get_subgraph(novel_id, "no-such-id") is None
