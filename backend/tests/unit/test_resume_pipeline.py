"""P19 resume 管线单元测试（mock LLM + mock db；无网络、无 Neo4j）。

覆盖（Spec §12/§13.1 验收）：
- AC-1：resume 时 fingerprint 一致且 COMPLETED 的 extraction/judge checkpoint 零 LLM 调用
- AC-2：全量 run vs resume run 最终 MergedGraph canonical serialization 逐字节一致
- AC-3：完整完成重传 → 同一 novel_id + 新 terminal job + 零 LLM（经 API）
- AC-4：config 指纹变化 → 全新分析（不复用 checkpoint）
- AC-5：同一 chunk 多个 judge 输入 → 独立 checkpoint，各自重放
- AC-6：er_checkpoint_enabled=False → 现状行为（无 checkpoint、重传新 novel_id）
- AC-9b：completed_with_errors + 缺口 → manifest 保持 IN_PROGRESS → resume 后重试缺口并转 COMPLETED
- AC-10：checkpoint 写失败降级（job 仍完成，warnings 计数）
"""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.novels as novels_mod
from app.checkpoint.store import CheckpointStore
from app.config import Settings
from app.main import create_app
from app.models.job import JobStore, JobStatus
from app.pipeline.epub_reader import Chapter
from app.pipeline.llm_client import LLMRetryableError
from app.schemas.llm import (AliasCandidate, AliasJudgeResult, ExtractionResult,
                             MergeJudgeResult, PendingMention)

# P12 沙箱限制：pytest tmp_path 目录会被沙箱锁定 → 自建工作区 .tmp 目录（与 test_lineage 同约定）。
_REPO_TMP = Path(__file__).resolve().parents[2] / ".tmp" / "resume-tests"

N = 7  # chunk 数


@pytest.fixture
def ws_tmp():
    import os
    import shutil
    d = _REPO_TMP / uuid.uuid4().hex[:12]
    os.makedirs(d, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_settings(ckpt_dir, model="m1"):
    return Settings(_env_file=None, bailian_api_key="k", bailian_url="https://x",
                    neo4j_password="p", bailian_model=model,
                    er_checkpoint_dir=str(ckpt_dir), er_checkpoint_enabled=True,
                    llm_concurrency=2)


def make_settings_disabled(ckpt_dir):
    return Settings(_env_file=None, bailian_api_key="k", bailian_url="https://x",
                    neo4j_password="p", er_checkpoint_dir=str(ckpt_dir),
                    er_checkpoint_enabled=False, llm_concurrency=2)


def fake_read_epub(_bytes) -> list[Chapter]:
    return [Chapter(chapter_id=i + 1, chapter_title=f"ch{i + 1}", text=f"text-of-chunk-{i + 1}")
            for i in range(N)]


class FakeLLM:
    """mock LLM：text → chunk_id 映射；按 chunk 失败注入；judge 全部 resolves_to null。

    人名设计（保证 judge 触发、merge pair 产生、且失败 chunk 不影响后续 judge 输入）：
    - chunk1: [阿黑, 阿甲]；chunk2: [阿白, 阿乙, 阿丙]  → chunk3 前已有 5 个「阿」系 canonical，
      weak recall top-5 饱和 → 零重合的 张三 不会成为 阿* 的候选；
    - chunk3: []（**空抽取**——失败与否都不产生任何 mention / judge / bridge evidence，
      因此 resume 补跑后全链路输入与 run1 逐字节一致 → judge 与 merge 均可干净重放）；
    - chunk4-7: [阿丁, 阿大, 阿二, 阿戊] → 每 chunk 都有候选 → judge；chunk5 阿大 有 ≥5 个
      established 候选 → bridge evidence → merge pair。
    """

    def __init__(self, fail_chunk_ids=()):
        self.fail = set(fail_chunk_ids)
        self.extract_calls: list[int] = []
        self.judge_calls: list[int] = []
        self.merge_calls = 0
        self._text_to_chunk = {f"text-of-chunk-{i + 1}": i + 1 for i in range(N)}
        self._names = {1: ["阿黑", "阿甲"], 2: ["阿白", "阿乙", "阿丙"], 3: [],
                       4: ["阿丁"], 5: ["阿大"], 6: ["阿二"], 7: ["阿戊"]}

    def extract_chunk(self, text: str) -> ExtractionResult:
        cid = self._text_to_chunk[text]
        self.extract_calls.append(cid)
        if cid in self.fail:
            raise LLMRetryableError("http_429")
        return ExtractionResult.model_validate({
            "characters": [{"name": n} for n in self._names[cid]],
            "relationships": [],
        })

    def judge_aliases(self, chunk_text: str, pending: list[PendingMention]) -> AliasJudgeResult:
        self.judge_calls.append(self._text_to_chunk[chunk_text])
        return AliasJudgeResult.model_validate({
            "resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})

    def judge_merges(self, pairs) -> MergeJudgeResult:
        self.merge_calls += 1
        return MergeJudgeResult.model_validate({"merges": []})


class FakeDB:
    """mock db：捕获 upsert_graph 的 MergedGraph（用于 AC-2 canonical 比较）。"""

    def __init__(self):
        self.graphs: list = []

    def ping(self):
        pass

    def upsert_novel(self, novel_id, title, chapters):
        pass

    def upsert_graph(self, novel_id, merged, merge_map):
        self.graphs.append(merged)

    def count_stats(self, novel_id):
        return {"persons": 0, "relationships": 0}


def canonical_graph_json(graph) -> str:
    """AC-2：Spec §12 定义的 canonical serialization（稳定键排序；不用 uuid id）。"""
    return json.dumps({
        "persons": sorted(
            [{"name": p.name, "aliases": p.aliases, "mention_count": p.mention_count,
              "chapters": sorted(p.chapters), "chunk_ids": sorted(p.chunk_ids)}
             for p in graph.persons.values()],
            key=lambda d: d["name"]),
        "relationships": sorted(
            [{"source": r.source, "target": r.target, "type": r.type.value,
              "chunk_ids": sorted(r.chunk_ids), "confidences": r.confidences,
              "evidence": sorted(r.evidence, key=lambda e: (e["chunk_id"], e["chapter_id"], e["text"]))}
             for r in graph.relationships.values()],
            key=lambda d: (d["source"], d["target"], d["type"])),
    }, sort_keys=True, ensure_ascii=False)


def run_ingest(settings, llm, db=None, fail_chunk_ids=()):
    """直接调用 _run_ingest（不经 HTTP），返回 (novel_id, job_id, job_store, llm, db)。"""
    novel = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    job_store = JobStore()
    job_store.create(job_id, novel)
    db = db or FakeDB()
    novels_mod._run_ingest(novel, job_id, "t", b"EPUBDATA", settings, db, job_store, llm)
    return novel, job_id, job_store, llm, db


def manifest_of(settings, novel_id):
    return CheckpointStore(settings.er_checkpoint_dir).load_manifest(novel_id)


# ======================================================================
# AC-1 / AC-2 / AC-9b：中断 → resume → 零重放 + 结果一致
# ======================================================================

def test_resume_after_mid_failure_zero_replay_and_identical_graph(ws_tmp, monkeypatch):
    monkeypatch.setattr(novels_mod, "read_epub", fake_read_epub)
    settings = make_settings(ws_tmp)

    # ---- 全量 run（基准图）----
    llm_full = FakeLLM()
    _, _, _, _, db_full = run_ingest(settings, llm_full)
    assert len(db_full.graphs) == 1
    full_graph = db_full.graphs[0]

    # ---- run1：chunk3 失败（transient 429；extract_one 重试 1 次 → 2 次调用）----
    llm1 = FakeLLM(fail_chunk_ids={3})
    novel, job1, store1, _, db1 = run_ingest(settings, llm1)
    assert store1.get(job1).status == JobStatus.completed_with_errors
    assert [f["chunk_id"] for f in store1.get(job1).failed_blocks] == [3]
    # AC-9b：有缺口 → manifest 保持 IN_PROGRESS
    assert manifest_of(settings, novel)["status"] == "IN_PROGRESS"
    assert sorted(llm1.extract_calls) == sorted([1, 2, 3, 3, 4, 5, 6, 7])  # chunk3 重试一次
    assert sorted(llm1.judge_calls) == [1, 2, 4, 5, 6, 7]   # chunk1 阿甲（同 chunk 内 阿黑 先注册 → 候选）；chunk3 失败未进 resolver
    assert llm1.merge_calls == 1                                           # chunk5 bridge → merge pair

    # ---- resume：同 novel_id，新 job，LLM 不再失败 ----
    llm2 = FakeLLM()
    job2 = str(uuid.uuid4())
    store2 = JobStore()
    store2.create(job2, novel)
    db2 = FakeDB()
    novels_mod._run_ingest(novel, job2, "t", b"EPUBDATA", settings, db2, store2, llm2)

    # AC-1：已完成 chunk 零重复调用——只补 chunk3；chunk3 空抽取 → 无 judge；merge 重放
    assert llm2.extract_calls == [3]
    assert llm2.judge_calls == []        # chunk1/2/4/5/6/7 judge 全部重放；chunk3 空抽取无 judge
    assert llm2.merge_calls == 0         # merge judge 重放（chunk3 空 → bridge evidence 与 run1 逐字节一致）

    # AC-9b 收尾：无缺口 → manifest COMPLETED；job completed
    assert store2.get(job2).status == JobStatus.completed
    assert manifest_of(settings, novel)["status"] == "COMPLETED"

    # AC-2：resume 图与全量 run 图 canonical serialization 逐字节一致
    assert len(db2.graphs) == 1
    assert canonical_graph_json(db2.graphs[0]) == canonical_graph_json(full_graph)


def test_resume_after_last_chunk_failure_replays_judges(ws_tmp, monkeypatch):
    """失败在末 chunk：resume 只补末 chunk，前面 judge 全部重放。"""
    monkeypatch.setattr(novels_mod, "read_epub", fake_read_epub)
    settings = make_settings(ws_tmp)
    llm1 = FakeLLM(fail_chunk_ids={7})
    novel, job1, store1, _, _ = run_ingest(settings, llm1)
    assert store1.get(job1).status == JobStatus.completed_with_errors
    assert sorted(llm1.judge_calls) == [1, 2, 4, 5, 6]   # chunk7 失败未进 resolver

    llm2 = FakeLLM()
    job2 = str(uuid.uuid4())
    store2 = JobStore()
    store2.create(job2, novel)
    db2 = FakeDB()
    novels_mod._run_ingest(novel, job2, "t", b"EPUBDATA", settings, db2, store2, llm2)

    assert llm2.extract_calls == [7]
    assert sorted(llm2.judge_calls) == [7]         # chunk1/2/4/5/6 重放；chunk7 重新 judge（无 checkpoint）
    assert llm2.merge_calls == 1                   # chunk7 成功新增 bridge evidence → 输入变化 → merge 重新判定（指纹保护，正确行为）
    assert store2.get(job2).status == JobStatus.completed
    assert manifest_of(settings, novel)["status"] == "COMPLETED"


# ======================================================================
# AC-3 / AC-4 / AC-6：经 API 的幂等 / 指纹失效 / 关闭开关
# ======================================================================

def _api_client(settings, monkeypatch):
    app = create_app()
    app.state.settings = settings
    app.state.job_store = JobStore()
    app.state.db = FakeDB()
    llm = FakeLLM()
    app.state.llm_client = llm
    monkeypatch.setattr(novels_mod, "read_epub", fake_read_epub)
    return TestClient(app), app, llm


def test_idempotent_reupload_via_api(ws_tmp, monkeypatch):
    """AC-3：完整完成重传 → 同一 novel_id + 新 terminal job + 零 LLM。"""
    settings = make_settings(ws_tmp)
    client, app, llm = _api_client(settings, monkeypatch)
    files = {"file": ("t.epub", b"EPUBDATA", "application/epub+zip")}

    r1 = client.post("/api/novels", files=files)
    assert r1.status_code == 200
    n1, j1 = r1.json()["novel_id"], r1.json()["job_id"]
    assert app.state.job_store.get(j1).status == JobStatus.completed
    assert manifest_of(settings, n1)["status"] == "COMPLETED"
    calls_before = len(llm.extract_calls)

    r2 = client.post("/api/novels", files=files)
    assert r2.status_code == 200
    n2, j2 = r2.json()["novel_id"], r2.json()["job_id"]
    assert n2 == n1                       # 同一 novel_id（幂等）
    assert j2 != j1                       # 新 terminal job（不复活历史 job）
    assert app.state.job_store.get(j2).status == JobStatus.completed
    st = app.state.job_store.get(j2)
    assert st.done_chunks == st.total_chunks == N
    assert len(llm.extract_calls) == calls_before   # 零 LLM 调用


def test_fingerprint_change_forces_fresh_analysis(ws_tmp, monkeypatch):
    """AC-4：model（config_fingerprint 之一）变化 → 不复用旧 checkpoint → 全新 novel_id 全量重跑。"""
    settings1 = make_settings(ws_tmp, model="model-a")
    client, app, llm = _api_client(settings1, monkeypatch)
    files = {"file": ("t.epub", b"EPUBDATA", "application/epub+zip")}

    r1 = client.post("/api/novels", files=files)
    n1 = r1.json()["novel_id"]
    calls_after_first = len(llm.extract_calls)
    assert calls_after_first == N

    settings2 = make_settings(ws_tmp, model="model-b")
    app.state.settings = settings2
    r2 = client.post("/api/novels", files=files)
    assert r2.status_code == 200
    n2 = r2.json()["novel_id"]
    assert n2 != n1                       # 指纹变化 → 全新分析
    assert len(llm.extract_calls) == calls_after_first + N   # 全量重跑
    assert manifest_of(settings1, n1)["status"] == "COMPLETED"   # 旧 checkpoint 保留、互不干扰（AC-11）


def test_disabled_checkpoint_is_legacy_behavior(ws_tmp, monkeypatch):
    """AC-6：er_checkpoint_enabled=False → 无 checkpoint 写入；重传 = 新 novel_id 全量重跑。"""
    settings = make_settings_disabled(ws_tmp)
    client, app, llm = _api_client(settings, monkeypatch)
    files = {"file": ("t.epub", b"EPUBDATA", "application/epub+zip")}

    r1 = client.post("/api/novels", files=files)
    n1 = r1.json()["novel_id"]
    assert len(llm.extract_calls) == N
    assert CheckpointStore(settings.er_checkpoint_dir).load_manifest(n1) is None  # 未写 checkpoint

    calls_before = len(llm.extract_calls)
    r2 = client.post("/api/novels", files=files)
    assert r2.json()["novel_id"] != n1
    assert len(llm.extract_calls) == calls_before + N


# ======================================================================
# AC-5：judge 多输入（同一 chunk 多个 input_fingerprint）
# ======================================================================

def test_judge_multiple_inputs_same_chunk(ws_tmp):
    """同一 chunk 两次不同 pending → 两个独立 checkpoint 文件，各自重放，互不污染。"""
    cp = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    judge_version = {"judge_prompt_hash": "a" * 64, "model": "m", "config_fingerprint": "b" * 64}
    llm = FakeLLM()
    rj = novels_mod.ReplayJudge(cp, llm, novel, judge_version)
    rj.set_chunk(1)
    p1 = [PendingMention(mention="阿大", candidates=[AliasCandidate(canonical="阿黑", matched_names=["阿黑"])])]
    p2 = [PendingMention(mention="阿二", candidates=[AliasCandidate(canonical="阿黑", matched_names=["阿黑"])])]

    r1 = rj.judge_aliases("text-of-chunk-1", p1)
    r2 = rj.judge_aliases("text-of-chunk-1", p2)
    assert len(llm.judge_calls) == 2          # 两个不同输入 → 两次 LLM
    assert len(cp.list_keys(novel, prefix="judge/1/")) == 2   # 两个独立 checkpoint 文件

    r1b = rj.judge_aliases("text-of-chunk-1", p1)
    r2b = rj.judge_aliases("text-of-chunk-1", p2)
    assert len(llm.judge_calls) == 2          # 各自重放，零新调用
    assert r1b == r1 and r2b == r2

    # judge 版本不匹配 → 重新调用（绝不盲目复用旧 judge）
    rj2 = novels_mod.ReplayJudge(cp, llm, novel,
                                 {"judge_prompt_hash": "x" * 64, "model": "m",
                                  "config_fingerprint": "b" * 64})
    rj2.set_chunk(1)
    rj2.judge_aliases("text-of-chunk-1", p1)
    assert len(llm.judge_calls) == 3


# ======================================================================
# AC-10：checkpoint 写失败降级
# ======================================================================

def test_checkpoint_write_failure_does_not_fail_job(ws_tmp, monkeypatch):
    """checkpoint 写失败 → 记日志降级 + job 正常完成（不浪费 LLM 工作）。"""
    monkeypatch.setattr(novels_mod, "read_epub", fake_read_epub)
    settings = make_settings(ws_tmp)

    def boom(src, dst):  # noqa: ARG001
        raise OSError("disk full")

    monkeypatch.setattr("app.checkpoint.store.os.replace", boom)
    novel, job_id, job_store, llm, _db = run_ingest(settings, FakeLLM())
    assert job_store.get(job_id).status == JobStatus.completed
    assert job_store.get(job_id).stats.get("checkpoint", {}).get("warnings", 0) > 0
    assert manifest_of(settings, novel) is None   # manifest 写失败 → 未落盘（下次 resume 会重跑，降级语义）
