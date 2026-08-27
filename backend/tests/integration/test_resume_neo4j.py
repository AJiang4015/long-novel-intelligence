"""P19 resume 集成测试（真实 Neo4j + mock LLM；独立 novel_id 自建自清）。

覆盖（Spec §13.2）：
- 中断（chunk3 失败）→ 重传续跑 → 最终图与全量 run 一致（Neo4j 查询按稳定键排序比较，不使用 uuid id）
- resume 阶段已完成 chunk 的 extraction 零重复调用；judge 仅 chunk3 自身新增（其余重放）
- AC-9b：有缺口 → manifest IN_PROGRESS；补齐后 → COMPLETED
- AC-3：完整完成重传 → 同一 novel_id + 新 terminal job + 零 LLM 调用
- 清理：db.delete_novel + CheckpointStore.delete_novel（自建自清）
"""

import shutil
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.checkpoint.store import CheckpointStore
from app.main import create_app
from app.pipeline.llm_client import LLMRetryableError
from app.schemas.llm import AliasJudgeResult, ExtractionResult, MergeJudgeResult

pytestmark = pytest.mark.integration

N = 7
_REPO_TMP = Path(__file__).resolve().parents[2] / ".tmp" / "resume-integration"


@pytest.fixture(scope="module")
def db():
    from app.config import get_settings
    from app.db.neo4j import Neo4jDB

    settings = get_settings()
    database = Neo4jDB(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        database.ping()
    except Exception:
        pytest.skip("Neo4j 不可达：请先 `docker compose up -d neo4j` 并配置 .env")
    database.ensure_constraints()
    yield database
    database.close()


class CountingLLM:
    """逐 chunk 计数的 mock LLM；judge 全部 null；chunk3=[张三]（非空，恢复后图真正补全）。"""

    def __init__(self):
        self.extract_by_chunk: dict[int, int] = {}
        self.judge_by_chunk: dict[int, int] = {}
        self.merge_calls = 0
        self.fail: set[int] = set()
        self._names = {1: ["阿黑", "阿甲"], 2: ["阿白", "阿乙", "阿丙"], 3: ["张三"],
                       4: ["阿丁"], 5: ["阿大"], 6: ["阿二"], 7: ["阿戊"]}

    @staticmethod
    def _cid_of(text: str) -> int:
        for i in range(1, N + 1):
            if f"text-of-chunk-{i}" in text:
                return i
        raise KeyError(text)

    def extract_chunk(self, text):
        cid = self._cid_of(text)
        self.extract_by_chunk[cid] = self.extract_by_chunk.get(cid, 0) + 1
        if cid in self.fail:
            raise LLMRetryableError("http_429")
        return ExtractionResult.model_validate({
            "characters": [{"name": n} for n in self._names[cid]], "relationships": []})

    def judge_aliases(self, chunk_text, pending):
        cid = self._cid_of(chunk_text)
        self.judge_by_chunk[cid] = self.judge_by_chunk.get(cid, 0) + 1
        return AliasJudgeResult.model_validate(
            {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})

    def judge_merges(self, pairs):
        self.merge_calls += 1
        return MergeJudgeResult.model_validate({"merges": []})

    def snapshot(self):
        return {"extract": dict(self.extract_by_chunk), "judge": dict(self.judge_by_chunk),
                "merge": self.merge_calls}


@pytest.fixture(scope="module")
def ckpt_dir():
    shutil.rmtree(_REPO_TMP, ignore_errors=True)
    _REPO_TMP.mkdir(parents=True, exist_ok=True)
    yield _REPO_TMP
    shutil.rmtree(_REPO_TMP, ignore_errors=True)


@pytest.fixture(scope="module")
def client(ckpt_dir, db):
    app = create_app()
    with TestClient(app) as client:
        app.state.llm_client = CountingLLM()
        app.state.settings = app.state.settings.model_copy(update={"er_checkpoint_dir": str(ckpt_dir)})
        yield client


def upload(client, epub_bytes, filename="flow.epub"):
    resp = client.post("/api/novels", files={"file": (filename, epub_bytes, "application/epub+zip")})
    assert resp.status_code == 200
    return resp.json()


def wait_job(client, job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "completed_with_errors", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job 超时未结束")


def graph_snapshot(db, novel_id):
    """Neo4j 查询 → 稳定键排序的 canonical 快照（不使用 uuid id；AC-2 Neo4j 侧）。"""
    with db._driver.session() as session:
        persons = sorted(
            [{"name": r["name"], "aliases": sorted(r["aliases"] or []),
              "mention_count": r["mention_count"]}
             for r in session.run(
                 "MATCH (p:Person) WHERE p.novel_id=$n RETURN p.name AS name, "
                 "p.aliases AS aliases, p.mention_count AS mention_count", n=novel_id)],
            key=lambda d: d["name"])
        rels = sorted(
            [{"source": r["source"], "target": r["target"], "type": r["type"],
              "weight": r["weight"], "confidence": round(r["confidence"], 6)}
             for r in session.run(
                 "MATCH (:Person)-[r:RELATES_TO]->(:Person) WHERE r.novel_id=$n "
                 "RETURN r.source AS source, r.target AS target, r.type AS type, "
                 "r.weight AS weight, r.confidence AS confidence", n=novel_id)],
            key=lambda d: (d["source"], d["target"], d["type"]))
    return {"persons": persons, "relationships": rels}


def build_epub_bytes():
    from tests.epub_factory import build_epub
    return build_epub([f"text-of-chunk-{i}" for i in range(1, N + 1)])


def test_resume_full_flow(db, client, ckpt_dir):
    llm: CountingLLM = client.app.state.llm_client
    epub_bytes = build_epub_bytes()
    cleanup: list[str] = []
    try:
        # ---- 全量基准图：不同 config（model 名不同 → 独立 novel_id；mock LLM 输出与 model 无关 → 图可比）----
        client.app.state.settings = client.app.state.settings.model_copy(
            update={"bailian_model": "baseline-model"})
        llm.fail = set()
        data0 = upload(client, epub_bytes, filename="base.epub")
        cleanup.append(data0["novel_id"])
        job0 = wait_job(client, data0["job_id"])
        assert job0["status"] == "completed"

        # ---- run1：chunk3 失败 → 部分图（缺 张三）----
        client.app.state.settings = client.app.state.settings.model_copy(
            update={"bailian_model": "run-model"})
        llm.fail = {3}
        data1 = upload(client, epub_bytes, filename="flow.epub")
        cleanup.append(data1["novel_id"])
        job1 = wait_job(client, data1["job_id"])
        assert job1["status"] == "completed_with_errors"
        assert [b["chunk_id"] for b in job1["failed_blocks"]] == [3]
        cp = CheckpointStore(str(ckpt_dir))
        assert cp.load_manifest(data1["novel_id"])["status"] == "IN_PROGRESS"   # AC-9b
        assert len(graph_snapshot(db, data1["novel_id"])["persons"]) \
            == len(graph_snapshot(db, data0["novel_id"])["persons"]) - 1        # 缺 张三

        # ---- resume：重传同文件 → 复用 novel_id，新 job ----
        llm.fail = set()
        before = llm.snapshot()
        data2 = upload(client, epub_bytes, filename="flow.epub")
        assert data2["novel_id"] == data1["novel_id"]       # 复用 novel_id
        assert data2["job_id"] != data1["job_id"]
        job2 = wait_job(client, data2["job_id"])
        assert job2["status"] == "completed"
        assert cp.load_manifest(data1["novel_id"])["status"] == "COMPLETED"     # AC-9b 补齐
        after = llm.snapshot()
        # AC-1（extraction）：已完成 chunk 零重复抽取，只补 chunk3（1 次）
        extract_delta = {k: d for k, d in
                         {k: v - before["extract"].get(k, 0) for k, v in after["extract"].items()}.items() if d}
        assert extract_delta == {3: 1}
        # judge：仅 chunk3 自身新增（张三 不进 阿* 候选空间 → chunk1/2/4/5/6/7 重放）
        judge_delta = {k: d for k, d in
                       {k: v - before["judge"].get(k, 0) for k, v in after["judge"].items()}.items() if d}
        assert judge_delta == {3: 1}
        # merge：chunk3 成功新增 bridge evidence → 输入变化 → 重新判定（指纹保护，正确行为）
        assert after["merge"] == before["merge"] + 1

        # AC-2：resume 最终图 == 全量基准图（Neo4j 稳定键快照逐字节一致）
        assert graph_snapshot(db, data1["novel_id"]) == graph_snapshot(db, data0["novel_id"])

        # AC-3 幂等：第三次重传 → 同 novel_id + 新 terminal job + 零 LLM
        before3 = llm.snapshot()
        data3 = upload(client, epub_bytes, filename="flow.epub")
        assert data3["novel_id"] == data1["novel_id"]
        assert data3["job_id"] != data2["job_id"]
        job3 = wait_job(client, data3["job_id"])
        assert job3["status"] == "completed"
        assert job3["progress"]["done_chunks"] == job3["progress"]["total_chunks"] == N
        assert llm.snapshot() == before3
    finally:
        for nid in cleanup:
            db.delete_novel(nid)
            CheckpointStore(str(ckpt_dir)).delete_novel(nid)
