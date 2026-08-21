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


# ---------------------------------------------------------------- Task 10: API 层端到端

import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.llm import ExtractionResult


class FakeLLMClient:
    """固定返回两组关系（两个 chunk 都确认 love/enmity），验证 weight=2 贯穿全链路。"""

    def extract_chunk(self, text: str) -> ExtractionResult:
        return ExtractionResult.model_validate({
            "characters": [{"name": "贾宝玉"}, {"name": "林黛玉"}, {"name": "王熙凤"}],
            "relationships": [
                {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.9},
                {"source": "王熙凤", "target": "贾宝玉", "type": "enmity", "confidence": 0.8},
            ],
        })


@pytest.fixture(scope="module")
def client(db):
    app = create_app()
    with TestClient(app) as client:
        app.state.llm_client = FakeLLMClient()  # 替换真实 LLM，其余（db/job_store）走 lifespan
        yield client


@pytest.fixture()
def uploaded(client):
    from tests.epub_factory import build_epub

    epub_bytes = build_epub(["贾宝玉和林黛玉在大观园交谈。", "王熙凤对贾宝玉发怒。"])
    resp = client.post("/api/novels", files={"file": ("flow.epub", epub_bytes, "application/epub+zip")})
    assert resp.status_code == 200
    data = resp.json()
    yield data  # {"novel_id", "job_id"}
    client.app.state.db.delete_novel(data["novel_id"])


def _wait_job(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "completed_with_errors", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job 超时未结束")


def test_upload_to_graph_full_flow(client, uploaded):
    novel_id, job_id = uploaded["novel_id"], uploaded["job_id"]

    job = _wait_job(client, job_id)
    assert job["status"] == "completed"
    assert job["stats"]["persons"] == 3
    assert job["stats"]["relationships"] == 2

    novel = client.get(f"/api/novels/{novel_id}").json()
    assert [c["id"] for c in novel["chapters"]] == [1, 2]

    cands = client.get(f"/api/novels/{novel_id}/characters", params={"q": "贾"}).json()
    jia = next(c for c in cands if c["name"] == "贾宝玉")

    graph = client.get(f"/api/characters/{jia['id']}/graph").json()
    assert {n["name"] for n in graph["nodes"]} == {"贾宝玉", "林黛玉", "王熙凤"}
    love_edge = next(e for e in graph["edges"] if e["type"] == "love")
    assert love_edge["weight"] == 2            # 两个 chunk 都确认 → weight 语义贯穿全链路
    assert love_edge["confidence"] == pytest.approx(0.9)
    assert love_edge["evidence"][0]["chapter_title"] == "第1章"


def test_upload_rejects_non_epub(client):
    resp = client.post("/api/novels", files={"file": ("a.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_unknown_character_404(client, uploaded):
    resp = client.get("/api/characters/no-such-id/graph")
    assert resp.status_code == 404


def test_unknown_job_404(client):
    assert client.get("/api/jobs/no-such-job").status_code == 404


def test_health_ok(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_list_novels_empty(client):
    """清空小说后 GET /api/novels 返回空数组。"""
    db = client.app.state.db
    with db._driver.session() as session:
        session.run("MATCH (n:Novel) DELETE n").consume()
    assert client.get("/api/novels").json() == []


def test_list_novels_returns_sorted(client):
    """多本小说时 GET /api/novels 返回全部并按 title 升序（不依赖 internal id）。"""
    db = client.app.state.db
    nids = []
    try:
        for i, title in enumerate(["Novel-B", "Novel-A", "Novel-C"], start=1):
            nid = f"list-{uuid.uuid4()}"
            db.upsert_novel(nid, title, [{"id": i, "title": f"第{i}章"}])
            nids.append(nid)
        novels = client.get("/api/novels").json()
        ours = [n for n in novels if n["id"] in nids]
        assert len(ours) == 3
        assert [n["title"] for n in ours] == sorted(["Novel-B", "Novel-A", "Novel-C"])
        assert all("id" in n and "title" in n for n in ours)
    finally:
        for nid in nids:
            db.delete_novel(nid)
