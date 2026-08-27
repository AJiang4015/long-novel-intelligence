"""CheckpointStore 单元测试（P19 Step 1）。

覆盖（Spec §13.1 / CHECKPOINT_LAYER.md §9）：
- round-trip（manifest / chunks / extraction / judge / merge_judge）
- 原子写（无 .tmp 残留）、损坏降级、novel 隔离、delete_novel 清理
- 复合索引：多配置并存（AC-11）、index 丢失重建、并发更新无 lost update、扫描兜底
- 路径防护（非 UUID / 非法 chunk_id / 非法 fingerprint / 穿越 key）
- 写失败降级（mock os.replace 失败 → False，不抛异常）
- manifest 两态 + mark_complete；completed_extraction_ids 指纹过滤；load_extraction_results 组装
"""

import json
import os
import shutil
import threading
import uuid
from pathlib import Path

import pytest

from app.checkpoint.store import CheckpointError, CheckpointStore

# P12 沙箱限制：pytest tmp_path（mode=0o700）目录会被沙箱锁定 → 自建工作区 .tmp 目录
# （默认 mode 可写；.tmp/ 已 gitignore，与 test_lineage.py 同约定）。
_REPO_TMP = Path(__file__).resolve().parents[2] / ".tmp" / "checkpoint-tests"


@pytest.fixture
def ws_tmp():
    d = _REPO_TMP / uuid.uuid4().hex[:12]
    os.makedirs(d, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _manifest(novel_id: str, content_hash: str, config_fp: str, status: str = "IN_PROGRESS") -> dict:
    return {
        "schema_version": 1,
        "novel_id": novel_id,
        "title": "t",
        "content_hash": content_hash,
        "config_fingerprint": config_fp,
        "chunking_version": "1",
        "extractor_version": "1",
        "extraction_prompt_hash": "a" * 64,
        "judge_prompt_hash": "b" * 64,
        "merge_prompt_hash": "c" * 64,
        "model": "m",
        "chunk_size": 4000,
        "chunk_overlap": 400,
        "structure_hash": "d" * 64,
        "chunk_count": 3,
        "status": status,
        "created_at": "2026-08-28T00:00:00+00:00",
        "updated_at": "2026-08-28T00:00:00+00:00",
        "final_stats": {},
    }


def _extraction(chunk_id: int, config_fp: str, status: str = "COMPLETED") -> dict:
    return {
        "schema_version": 1,
        "chunk_id": chunk_id,
        "status": status,
        "attempts": 1,
        "error": None if status == "COMPLETED" else "http_429",
        "config_fingerprint": config_fp,
        "result": {"characters": [{"name": f"c{chunk_id}"}], "relationships": []},
    }


# ---------------------------------------------------------------- round-trip

def test_manifest_roundtrip(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    m = _manifest(novel, "a" * 64, "b" * 64)
    assert store.save_manifest(novel, m) is True
    assert store.load_manifest(novel) == m
    assert store.load_manifest(str(uuid.uuid4())) is None


def test_chunks_roundtrip_and_corrupt(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    chunks = [
        {"chunk_id": 1, "chapter_id": 1, "text": "a"},
        {"chunk_id": 2, "chapter_id": 2, "text": "b"},
    ]
    assert store.save_chunks(novel, chunks) is True
    assert store.load_chunks(novel) == chunks
    # 损坏行 → 整体视为缺失（安全降级）
    (Path(ws_tmp) / novel / "chunks.jsonl").write_text('{"bad"\n', encoding="utf-8")
    assert store.load_chunks(novel) is None


def test_extraction_judge_mergejudge_roundtrip(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    cf = "b" * 64
    assert store.save_extraction(novel, 1, _extraction(1, cf)) is True
    assert store.load_extraction(novel, 1) == _extraction(1, cf)
    assert store.load_extraction(novel, 2) is None

    fp = "e" * 64
    judge_payload = {"schema_version": 1, "chunk_id": 1, "input_fingerprint": fp,
                     "result": {"resolutions": [{"mention": "x", "resolves_to": "y"}]}}
    assert store.save_judge(novel, 1, fp, judge_payload) is True
    assert store.load_judge(novel, 1, fp) == judge_payload
    assert store.load_judge(novel, 1, "f" * 64) is None

    mfp = "c" * 64
    merge_payload = {"schema_version": 1, "input_fingerprint": mfp, "result": {"merges": []}}
    assert store.save_merge_judge(novel, mfp, merge_payload) is True
    assert store.load_merge_judge(novel, mfp) == merge_payload


def test_atomic_write_no_tmp_leftover(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    store.save_extraction(novel, 1, _extraction(1, "b" * 64))
    leftovers = list((Path(ws_tmp) / novel).rglob("*.tmp"))
    assert leftovers == []


def test_corrupt_file_treated_as_missing(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    p = Path(ws_tmp) / novel / "extraction" / "1.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not json", encoding="utf-8")
    assert store.load_extraction(novel, 1) is None
    # 非 dict JSON 也视为缺失
    (Path(ws_tmp) / novel / "manifest.json").write_text('"just a string"', encoding="utf-8")
    assert store.load_manifest(novel) is None


# ---------------------------------------------------------------- 隔离 / 清理

def test_novel_isolation(ws_tmp):
    store = CheckpointStore(ws_tmp)
    n1, n2 = str(uuid.uuid4()), str(uuid.uuid4())
    store.save_extraction(n1, 1, _extraction(1, "b" * 64))
    assert store.load_extraction(n2, 1) is None
    assert store.list_keys(n2) == []


def test_delete_novel_cleans_dir_and_index(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    ch, cf = "a" * 64, "b" * 64
    store.save_manifest(novel, _manifest(novel, ch, cf))
    store.save_extraction(novel, 1, _extraction(1, cf))
    assert store.delete_novel(novel) is True
    assert not (Path(ws_tmp) / novel).exists()
    assert store.find_manifest(ch, cf) is None
    index = json.loads((Path(ws_tmp) / "index.json").read_text(encoding="utf-8"))
    assert f"{ch}:{cf}" not in index


# ---------------------------------------------------------------- 索引（复合键 / 多配置 / 重建 / 并发）

def test_multi_config_coexist(ws_tmp):
    """AC-11：同一 EPUB 不同 config_fingerprint → 两个 novel_id 并存、各自可发现、互不覆盖。"""
    store = CheckpointStore(ws_tmp)
    ch = "a" * 64
    cf1, cf2 = "1" * 64, "2" * 64
    n1, n2 = str(uuid.uuid4()), str(uuid.uuid4())
    store.save_manifest(n1, _manifest(n1, ch, cf1))
    store.save_manifest(n2, _manifest(n2, ch, cf2))
    assert store.find_manifest(ch, cf1)["novel_id"] == n1
    assert store.find_manifest(ch, cf2)["novel_id"] == n2
    index = json.loads((Path(ws_tmp) / "index.json").read_text(encoding="utf-8"))
    assert index[f"{ch}:{cf1}"] == n1
    assert index[f"{ch}:{cf2}"] == n2


def test_find_manifest_fallback_scan_and_rebuild(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    ch, cf = "a" * 64, "b" * 64
    store.save_manifest(novel, _manifest(novel, ch, cf))
    # index 丢失 → 扫描兜底
    (Path(ws_tmp) / "index.json").unlink()
    assert store.find_manifest(ch, cf)["novel_id"] == novel
    # 重建 → 索引恢复
    assert store.rebuild_index() == 1
    assert store.find_manifest(ch, cf)["novel_id"] == novel


def test_index_concurrent_updates_no_lost_update(ws_tmp):
    store = CheckpointStore(ws_tmp)
    items = [(str(uuid.uuid4()), f"{i:064x}", f"{i + 100:064x}") for i in range(1, 9)]
    errors: list[Exception] = []

    def w(item):
        try:
            store.save_manifest(item[0], _manifest(item[0], item[1], item[2]))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=w, args=(it,)) for it in items]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    index = json.loads((Path(ws_tmp) / "index.json").read_text(encoding="utf-8"))
    for nid, ch, cf in items:
        assert index[f"{ch}:{cf}"] == nid
        assert store.find_manifest(ch, cf)["novel_id"] == nid


def test_find_manifest_multi_hit_takes_latest(ws_tmp):
    store = CheckpointStore(ws_tmp)
    ch, cf = "a" * 64, "b" * 64
    old, new = str(uuid.uuid4()), str(uuid.uuid4())
    m_old = _manifest(old, ch, cf)
    m_old["updated_at"] = "2026-08-28T00:00:00+00:00"
    m_new = _manifest(new, ch, cf)
    m_new["updated_at"] = "2026-08-28T01:00:00+00:00"
    store.save_manifest(old, m_old)
    store.save_manifest(new, m_new)
    assert store.find_manifest(ch, cf)["novel_id"] == new


# ---------------------------------------------------------------- 路径防护

def test_path_protection(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    with pytest.raises(CheckpointError):
        store.load_manifest("../../etc/passwd")
    with pytest.raises(CheckpointError):
        store.load_manifest("not-a-uuid")
    with pytest.raises(CheckpointError):
        store.save_extraction(novel, -1, _extraction(-1, "b" * 64))
    with pytest.raises(CheckpointError):
        store.save_extraction(novel, 0, _extraction(0, "b" * 64))
    with pytest.raises(CheckpointError):
        store.save_extraction(novel, True, _extraction(1, "b" * 64))
    with pytest.raises(CheckpointError):
        store.save_judge(novel, 1, "not-hex", {})
    with pytest.raises(CheckpointError):
        store.put(novel, "extraction/1/../../x", {})
    with pytest.raises(CheckpointError):
        store.put(novel, "unknown/1", {})


# ---------------------------------------------------------------- 写失败降级 / manifest 校验

def test_write_failure_degrades(monkeypatch, ws_tmp):
    """AC-10：写失败 → 返回 False、不抛异常、文件不存在（该结果未 checkpoint）。"""
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())

    def boom(src, dst):  # noqa: ARG001
        raise OSError("disk full")

    monkeypatch.setattr("app.checkpoint.store.os.replace", boom)
    assert store.save_extraction(novel, 1, _extraction(1, "b" * 64)) is False
    assert store.load_extraction(novel, 1) is None


def test_save_manifest_validation(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    with pytest.raises(CheckpointError):
        store.save_manifest(novel, _manifest(novel, "not-hex", "b" * 64))
    bad = _manifest(novel, "a" * 64, "b" * 64)
    bad["novel_id"] = str(uuid.uuid4())
    with pytest.raises(CheckpointError):
        store.save_manifest(novel, bad)
    bad2 = _manifest(novel, "a" * 64, "b" * 64)
    bad2["status"] = "FAILED"
    with pytest.raises(CheckpointError):
        store.save_manifest(novel, bad2)


# ---------------------------------------------------------------- 状态与组装

def test_mark_complete_two_states(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    ch, cf = "a" * 64, "b" * 64
    store.save_manifest(novel, _manifest(novel, ch, cf, status="IN_PROGRESS"))
    assert store.load_manifest(novel)["status"] == "IN_PROGRESS"
    assert store.mark_complete(novel, {"persons": 3}) is True
    m = store.load_manifest(novel)
    assert m["status"] == "COMPLETED"
    assert m["final_stats"] == {"persons": 3}
    # 不存在的 novel → False
    assert store.mark_complete(str(uuid.uuid4()), {}) is False


def test_completed_extraction_ids_filters_status_and_fingerprint(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    cf = "b" * 64
    store.save_extraction(novel, 1, _extraction(1, cf))
    store.save_extraction(novel, 2, _extraction(2, cf, status="FAILED"))
    store.save_extraction(novel, 3, _extraction(3, "9" * 64))  # 指纹不匹配
    assert store.completed_extraction_ids(novel, cf) == {1}
    failed = store.load_failed_chunks(novel)
    assert [f["chunk_id"] for f in failed] == [2]
    assert failed[0]["attempts"] == 1


def test_load_extraction_results_assembled_sorted(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    cf = "b" * 64
    chunks = [
        {"chunk_id": 2, "chapter_id": 1, "text": "b"},
        {"chunk_id": 1, "chapter_id": 1, "text": "a"},
        {"chunk_id": 3, "chapter_id": 2, "text": "c"},
    ]
    store.save_extraction(novel, 1, _extraction(1, cf))
    store.save_extraction(novel, 2, _extraction(2, cf))
    store.save_extraction(novel, 3, _extraction(3, cf, status="FAILED"))
    results = store.load_extraction_results(novel, chunks, cf)
    assert [c["chunk_id"] for c, _ in results] == [1, 2]
    assert results[0][1]["characters"] == [{"name": "c1"}]


def test_list_keys(ws_tmp):
    store = CheckpointStore(ws_tmp)
    novel = str(uuid.uuid4())
    cf = "b" * 64
    store.save_extraction(novel, 1, _extraction(1, cf))
    store.save_judge(novel, 1, "e" * 64, {"result": {}})
    keys = store.list_keys(novel)
    assert "extraction/1" in keys
    assert "judge/1/" + "e" * 64 in keys  # 64 位 hex
    assert store.list_keys(novel, prefix="extraction") == ["extraction/1"]
