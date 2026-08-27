"""P19 真实评估：EPUB 中断 → 重传自动 resume（TESTING.md §3/§6/§9）。

设计：
- 真实 LLM（qwen3.8-27b）+ 真实 Neo4j + 真实 FastAPI app；业务代码零改动；
- 中断以 wrapper 在指定 chunk 的 extract_chunk 上抛 LLMRetryableError（模拟 quota/网络），
  真实调用前抛（不浪费 token）；真实失败（限流等）也会被如实记录；
- Run A（完整基准）：checkpoint disabled 的完整 ingest → 基准图 + 调用计数；
- Run B（中断 + resume）：checkpoint enabled，chunk N 失败 → completed_with_errors →
  移除故障重传 → 复用 novel_id 自动 resume → completed；
- 输出：backend/.tmp/eval-p19-resume/result.json + stdout 摘要；
- 评估结果默认不删除（novel 保留；TESTING.md §7）。

用法（backend 目录，无缓冲 + 后台）：
    python -u tools/eval_p19_resume.py
"""

import json
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline.chunker import chunk_chapters
from app.pipeline.epub_reader import read_epub
from app.pipeline.llm_client import LLMClient, LLMRetryableError

OUT_DIR = Path(__file__).resolve().parents[1] / ".tmp" / "eval-p19-resume"
EPUB_PATH = Path(__file__).resolve().parents[2] / "books" / "边城_(沈从文)_(z-library.sk,_1lib.sk,_z-lib.sk).epub"
FAIL_CHUNK = 20  # 注入失败点（约 3/4 处；已完成大部分后中断）

MAX_JOB_WAIT = 30 * 60  # 单 job 最长等待（真实 LLM 串行，27 chunk 可能 10+ 分钟）


class CountingLLM:
    """真实 LLMClient 包装：逐 chunk 计数 + 指定 chunk 注入中断（模拟 quota/网络）。"""

    def __init__(self, inner: LLMClient, text_to_chunk: dict[str, int], fail_extract: set[int] | None = None):
        self.inner = inner
        self.text_to_chunk = text_to_chunk
        self.fail_extract: set[int] = set(fail_extract or ())
        self.extract_calls: list[dict] = []
        self.judge_calls: list[dict] = []
        self.merge_calls = 0

    def extract_chunk(self, text: str):
        cid = self.text_to_chunk.get(text)
        if cid in self.fail_extract:
            self.extract_calls.append({"chunk_id": cid, "ok": False, "error": "injected_http_429"})
            raise LLMRetryableError("http_429")
        try:
            result = self.inner.extract_chunk(text)
        except Exception as exc:
            self.extract_calls.append({"chunk_id": cid, "ok": False,
                                       "error": f"{type(exc).__name__}:{exc}"})
            raise
        self.extract_calls.append({"chunk_id": cid, "ok": True, "error": None})
        return result

    def judge_aliases(self, chunk_text: str, pending):
        cid = self.text_to_chunk.get(chunk_text)
        try:
            result = self.inner.judge_aliases(chunk_text, pending)
        except Exception as exc:
            self.judge_calls.append({"chunk_id": cid, "ok": False, "mentions": len(pending),
                                     "error": f"{type(exc).__name__}:{exc}"})
            raise
        self.judge_calls.append({"chunk_id": cid, "ok": True, "mentions": len(pending), "error": None})
        return result

    def judge_merges(self, pairs):
        self.merge_calls += 1
        return self.inner.judge_merges(pairs)


def llm_snapshot(llm: CountingLLM) -> dict:
    def by_chunk(calls):
        out: dict[int, int] = {}
        for c in calls:
            if c.get("chunk_id") is not None:
                out[c["chunk_id"]] = out.get(c["chunk_id"], 0) + 1
        return out

    return {
        "extract_total": len(llm.extract_calls),
        "extract_by_chunk": by_chunk(llm.extract_calls),
        "extract_failed": [c for c in llm.extract_calls if not c["ok"]],
        "judge_total": len(llm.judge_calls),
        "judge_by_chunk": by_chunk(llm.judge_calls),
        "judge_failed": [c for c in llm.judge_calls if not c["ok"]],
        "merge_total": llm.merge_calls,
    }


def upload(client, epub_bytes: bytes, filename: str) -> dict:
    resp = client.post("/api/novels", files={"file": (filename, epub_bytes, "application/epub+zip")})
    if resp.status_code != 200:
        raise RuntimeError(f"upload failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def wait_job(client, job_id: str) -> dict:
    deadline = time.time() + MAX_JOB_WAIT
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "completed_with_errors", "failed"):
            return job
        time.sleep(5)
    raise TimeoutError(f"job {job_id} 超时")


def graph_snapshot(db, novel_id: str) -> dict:
    """Neo4j 查询 → 稳定键排序的 canonical 快照（不使用 uuid id）。"""
    with db._driver.session() as session:
        persons = sorted(
            [{"name": r["name"], "aliases": sorted(r["aliases"] or []),
              "mention_count": r["mention_count"], "chapters": sorted(r["chapters"] or [])}
             for r in session.run(
                 "MATCH (p:Person) WHERE p.novel_id=$n RETURN p.name AS name, p.aliases AS aliases, "
                 "p.mention_count AS mention_count, p.chapters AS chapters", n=novel_id)],
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


def main() -> None:
    from app.config import Settings

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    epub_bytes = EPUB_PATH.read_bytes()
    settings0 = Settings()  # 读 backend/.env
    # 评估加速（用户确认，2026-08-28）：并发 1→4（.env 现状为 1）。
    # 不改 .env；Environment Baseline 记录 concurrency=4。P05 经验：并发非 429 主因。
    settings0 = settings0.model_copy(update={"llm_concurrency": 4})
    chapters = read_epub(epub_bytes)
    chunks = chunk_chapters(chapters, settings0.chunk_size, settings0.chunk_overlap)
    text_to_chunk = {c.text: c.chunk_id for c in chunks}
    total = len(chunks)
    print(f"[eval] chunks={total} FAIL_CHUNK={FAIL_CHUNK} model={settings0.bailian_model} "
          f"concurrency={settings0.llm_concurrency}", flush=True)

    app = create_app()
    with TestClient(app) as client:
        # 评估环境修正：默认 httpx timeout=60 对 qwen3.7-flash 长文本生成过紧（实测 720 字响应 ~15s，
        # 4000 字符 chunk + 长 prompt 生成可 >60s → 静默 ReadTimeout 重试污染结果）。
        # 注入 300s 超时（仅评估脚本实例化，不改业务代码）。
        inner = LLMClient(base_url=settings0.bailian_url, api_key=settings0.bailian_api_key,
                          model=settings0.bailian_model,
                          http_client=httpx.Client(timeout=300))
        llm = CountingLLM(inner, text_to_chunk, fail_extract=set())   # Run A 必须无注入（完整基准）
        app.state.llm_client = llm
        db = client.app.state.db

        # Neo4j 版本（Environment Baseline）
        with db._driver.session() as session:
            neo4j_ver = session.run(
                "CALL dbms.components() YIELD name, versions RETURN name, versions").data()
        print(f"[eval] neo4j components: {neo4j_ver}", flush=True)

        # ---- Run A：完整基准（checkpoint disabled；独立 novel）----
        app.state.settings = settings0.model_copy(update={"er_checkpoint_enabled": False})
        print("[eval] Run A（完整基准，checkpoint disabled）开始…", flush=True)
        data_a = upload(client, epub_bytes, "full.epub")
        job_a = wait_job(client, data_a["job_id"])
        snap_a = graph_snapshot(db, data_a["novel_id"])
        calls_a = llm_snapshot(llm)
        print(f"[eval] Run A done: status={job_a['status']} persons={len(snap_a['persons'])} "
              f"rels={len(snap_a['relationships'])} extract={calls_a['extract_total']} "
              f"judge={calls_a['judge_total']} merge={calls_a['merge_total']}", flush=True)

        # ---- Run B：中断（chunk FAIL_CHUNK 注入失败）----
        app.state.settings = settings0.model_copy(update={"er_checkpoint_enabled": True})
        llm.fail_extract = {FAIL_CHUNK}
        print(f"[eval] Run B run1（chunk {FAIL_CHUNK} 注入失败）开始…", flush=True)
        data_b = upload(client, epub_bytes, "flow.epub")
        job_b1 = wait_job(client, data_b["job_id"])
        calls_b1 = llm_snapshot(llm)
        print(f"[eval] Run B run1 done: status={job_b1['status']} failed={job_b1['failed_blocks']}", flush=True)

        # ---- Run B resume：移除故障 → 重传同文件 → 自动 resume ----
        llm.fail_extract = set()
        before = llm_snapshot(llm)
        print("[eval] Run B resume（重传同文件）开始…", flush=True)
        data_b2 = upload(client, epub_bytes, "flow.epub")
        job_b2 = wait_job(client, data_b2["job_id"])
        after = llm_snapshot(llm)
        snap_b = graph_snapshot(db, data_b["novel_id"])

        resume_delta = {
            "extract_total_delta": after["extract_total"] - before["extract_total"],
            "extract_by_chunk_delta": {k: after["extract_by_chunk"].get(k, 0) - before["extract_by_chunk"].get(k, 0)
                                       for k in sorted(set(after["extract_by_chunk"]) | set(before["extract_by_chunk"]))},
            "judge_total_delta": after["judge_total"] - before["judge_total"],
            "judge_by_chunk_delta": {k: after["judge_by_chunk"].get(k, 0) - before["judge_by_chunk"].get(k, 0)
                                     for k in sorted(set(after["judge_by_chunk"]) | set(before["judge_by_chunk"]))},
            "merge_total_delta": after["merge_total"] - before["merge_total"],
            "resume_extract_failed": after["extract_failed"][len(before["extract_failed"]):],
            "resume_judge_failed": after["judge_failed"][len(before["judge_failed"]):],
        }
        print(f"[eval] Run B resume done: status={job_b2['status']} novel_reused="
              f"{data_b2['novel_id'] == data_b['novel_id']} new_job={data_b2['job_id'] != data_b['job_id']}",
              flush=True)
        print(f"[eval] resume delta: {json.dumps(resume_delta, ensure_ascii=False)}", flush=True)

        # 图结构级对比（允许真实 LLM 方差；列出差异）
        persons_a = {p["name"]: p for p in snap_a["persons"]}
        persons_b = {p["name"]: p for p in snap_b["persons"]}
        diff = {
            "only_in_full_run": sorted(set(persons_a) - set(persons_b)),
            "only_in_resume_run": sorted(set(persons_b) - set(persons_a)),
            "alias_diff": {n: {"full": persons_a[n]["aliases"], "resume": persons_b[n]["aliases"]}
                           for n in sorted(set(persons_a) & set(persons_b))
                           if persons_a[n]["aliases"] != persons_b[n]["aliases"]},
            "mention_count_diff": {n: {"full": persons_a[n]["mention_count"], "resume": persons_b[n]["mention_count"]}
                                   for n in sorted(set(persons_a) & set(persons_b))
                                   if persons_a[n]["mention_count"] != persons_b[n]["mention_count"]},
        }
        print(f"[eval] graph diff (full vs resume): {json.dumps(diff, ensure_ascii=False)}", flush=True)

        result = {
            "meta": {
                "commit": __import__("subprocess").check_output(
                    ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"]).decode().strip(),
                "model": settings0.bailian_model,
                "chunk_size": settings0.chunk_size,
                "chunk_overlap": settings0.chunk_overlap,
                "concurrency": settings0.llm_concurrency,
                "fail_chunk": FAIL_CHUNK,
                "total_chunks": total,
                "neo4j": neo4j_ver,
                "er_checkpoint_enabled": settings0.er_checkpoint_enabled,
                "er_checkpoint_dir": settings0.er_checkpoint_dir,
            },
            "run_a": {"novel_id": data_a["novel_id"], "job_id": data_a["job_id"], "job": job_a,
                      "calls": calls_a, "graph": snap_a},
            "run_b": {
                "novel_id": data_b["novel_id"],
                "run1": {"job_id": data_b["job_id"], "job": job_b1, "calls": calls_b1},
                "resume": {"job_id": data_b2["job_id"], "job": job_b2, "calls_after": after,
                           "delta": resume_delta},
                "graph": snap_b,
            },
            "graph_diff_full_vs_resume": diff,
        }
        (OUT_DIR / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        print(f"[eval] result saved: {OUT_DIR / 'result.json'}", flush=True)
        print(f"[eval] DONE. Run A novel={data_a['novel_id']}  Run B novel={data_b['novel_id']}", flush=True)


if __name__ == "__main__":
    main()
