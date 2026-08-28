"""P20 runner —— 事实采集与编排（Spec §6.1/§10.1；Step 2）。

职责边界（用户拍板，Step 2 约束）：
- runner 只负责**事实采集**：env / corpus / job / Neo4j 快照 / stats / evidence 原材料；
- **不承担任何 check 判定**：判定唯一入口 = `checks.evaluate_checkset`（本模块只调用，不实现判定逻辑）；
- 不修改 backend/app/*、P19 checkpoint 语义、P16/P17/P18 语义；
- eval 强制 `er_checkpoint_enabled=False`（fresh novel；checkpoint 零接触，G5 守卫）；
- 输出 `result.json`（run 原材料）；markdown 报告由 report.py（Step 3）生成。

CLI（backend 目录，无缓冲 + 后台，PROCESS.md 运行纪律）：
    python -u tools/eval_framework/run.py --runs N [--tag T] [--smoke] [--dry-run] [--out-dir DIR]

- `--runs N`    连续运行 N 次（每次全新 novel_id；默认 1）
- `--smoke`     mock LLM（FakeLLMClient 注入）+ 真实 Neo4j：自检骨架，不调真实 LLM
- `--dry-run`   只做前置校验（checkset / corpus hash / config 断言 / env 可采集项），不创建 app
- `--out-dir`   输出目录（默认 backend/.tmp/eval-framework；.tmp 已 gitignore）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# 脚本方式运行引导：runner.py 位于 backend/tools/eval_framework/，backend 根 = parents[2]。
# `python -u tools/eval_framework/runner.py` 时 sys.path[0]=脚本目录，需手动注入 backend 根以 import app.*。
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
# 仓库根（checkset.corpus.path 以 repo 根为基准；books/ 在 repo 根，同 eval_p19_resume）
_REPO_ROOT = Path(__file__).resolve().parents[3]

# P19 真实评估环境发现（docs/evaluation/2026-08-28-biancheng-p19-resume-eval.md §7）：
# llm_client 默认 httpx timeout=60 对 qwen3.x-flash 长文本生成过紧 → 静默 ReadTimeout 重试污染结果；
# eval 注入 300s（仅评估实例化，不改业务代码；同 eval_p19_resume.py）。
REAL_HTTP_TIMEOUT = 300

OUT_DEFAULT = Path(".tmp") / "eval-framework"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _prompt_hash(*prompts: str) -> str:
    """与 novels._prompt_hash 语义一致（compare_identity 与 manifest config_fingerprint 对齐）。"""
    return _sha256_hex("\n".join(prompts).encode("utf-8"))


def _git_state() -> tuple[str, bool]:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                                    text=True).stdout.strip())
        return head, dirty
    except Exception as exc:  # pragma: no cover - 环境故障
        raise RuntimeError(f"git 信息采集失败（TESTING.md §6 必填）: {exc}") from exc


# ---------------------------------------------------------------------------
# 事实采集（env / compare_identity / Neo4j / stats）
# ---------------------------------------------------------------------------


def compute_compare_identity(settings, corpus_hash: str) -> dict:
    """compare_identity（Spec §5.2/§7.1）：compare 兼容性唯一判定依据。

    语义身份：corpus_hash + checkset_version + model + chunk_size + chunk_overlap +
    chunker_version + extractor_version + prompt_hashes×3。
    **git_commit / git_dirty 不在此列**（仅 provenance；回归比较的正常场景 = 不同 commit vs 历史基线）。
    """
    from app.pipeline.chunker import CHUNKER_VERSION
    from app.pipeline.extractor import EXTRACTOR_VERSION
    from app.pipeline.llm_client import (
        ALIAS_JUDGE_SYSTEM_PROMPT, ALIAS_JUDGE_USER_PROMPT,
        EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT,
        MERGE_JUDGE_SYSTEM_PROMPT, MERGE_JUDGE_USER_PROMPT,
    )
    from tools.eval_framework.checks import CHECKSET_V1

    return {
        "corpus_hash": corpus_hash,
        "checkset_version": CHECKSET_V1.checkset_version,
        "model": settings.bailian_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "chunker_version": CHUNKER_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "prompt_hashes": {
            "extraction": _prompt_hash(EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT),
            "judge": _prompt_hash(ALIAS_JUDGE_SYSTEM_PROMPT, ALIAS_JUDGE_USER_PROMPT),
            "merge": _prompt_hash(MERGE_JUDGE_SYSTEM_PROMPT, MERGE_JUDGE_USER_PROMPT),
        },
    }


def _collect_env(settings, db, novel_id: str) -> dict:
    """TESTING.md §6 Environment Baseline 全字段（真实 run 必填；缺失会在上游 refuse）。"""
    head, dirty = _git_state()
    return {
        "git_commit": head,
        "git_dirty": dirty,
        "model": settings.bailian_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "concurrency": settings.llm_concurrency,
        "neo4j_version": _neo4j_version(db),
        "novel_id": novel_id,
        "checkpoint_enabled": settings.er_checkpoint_enabled,
        "llm_http_timeout": REAL_HTTP_TIMEOUT,
    }


def _neo4j_version(db) -> str:
    with db._driver.session() as session:  # 工具层访问（同 eval_p19_resume；无公开 components 方法）
        rows = session.run("CALL dbms.components() YIELD name, versions RETURN name, versions").data()
    for row in rows:
        if row.get("name") == "Neo4j Kernel":
            return " ".join(row.get("versions") or [])
    return str(rows)


def _graph_snapshot(db, novel_id: str) -> dict:
    """Neo4j 稳定键快照 + labels / novel_ids 采样（G1/G3 原材料；不使用 uuid id，P19 AC-2 同思路）。"""
    with db._driver.session() as session:
        persons = sorted(
            [{"name": r["name"], "aliases": sorted(r["aliases"] or []),
              "mention_count": r["mention_count"], "chapters": sorted(r["chapters"] or [])}
             for r in session.run(
                 "MATCH (p:Person) WHERE p.novel_id=$n RETURN p.name AS name, p.aliases AS aliases, "
                 "p.mention_count AS mention_count, p.chapters AS chapters", n=novel_id)],
            key=lambda d: d["name"])
        rels = sorted(
            [{"source": r["source"], "target": r["target"], "type": r["type"]}
             for r in session.run(
                 "MATCH (:Person)-[r:RELATES_TO]->(:Person) WHERE r.novel_id=$n "
                 "RETURN r.source AS source, r.target AS target, r.type AS type", n=novel_id)],
            key=lambda d: (d["source"], d["target"], d["type"]))
        labels = sorted({lb for row in session.run(
            "MATCH (p:Person) WHERE p.novel_id=$n RETURN labels(p) AS labels", n=novel_id)
            for lb in (row["labels"] or [])}
            | {lb for row in session.run(
                "MATCH (n:Novel) WHERE n.id=$n RETURN labels(n) AS labels", n=novel_id)
                for lb in (row["labels"] or [])})
        # G3 原材料：采样本 novel 相关节点的 novel_id（全部应 == 本 run novel_id；
        # 若 runner 查询未来失去 scope 会在此暴露跨 novel 污染）
        seen = sorted({novel_id} | {r["novel_id"] for r in session.run(
            "MATCH (p:Person) WHERE p.novel_id=$n RETURN p.novel_id AS novel_id", n=novel_id)})
    return {"novel_id": novel_id, "persons": persons, "relationships": rels,
            "labels_used": labels, "novel_ids_seen": seen}


def _nonbody_canonical_count(epub_bytes: bytes, persons: list[dict]) -> int:
    """B1 原材料：非正文 canonical 计数（仅出现在非正文章节 METADATA/EPIGRAPH/TRAILER 的 Person 数）。

    确定性：read_epub 内 sections 分类（D-16 项目级启发式）+ 最终图 persons.chapters。
    """
    from app.pipeline.epub_reader import read_epub
    from app.pipeline.sections import SectionType

    chapters = read_epub(epub_bytes)
    body = {ch.chapter_id for ch in chapters if ch.section_type == SectionType.BODY}
    return sum(1 for p in persons if p["chapters"] and not (set(p["chapters"]) & body))


def _alias_search(client, novel_id: str, queries: tuple[str, ...]) -> dict:
    """A6 原材料：characters 搜索接口结果 → {"q": {"hits": [{"name"}]}}。"""
    out: dict = {}
    for q in queries:
        resp = client.get(f"/api/novels/{novel_id}/characters", params={"q": q})
        if resp.status_code != 200:
            out[q] = {"hits": [], "error": f"http {resp.status_code}"}
            continue
        out[q] = {"hits": [{"name": h["name"]} for h in resp.json()]}
    return out


def _normalize_stats(job: dict) -> dict:
    """job 响应 → checks 的 STATS 契约（checks.py 模块 docstring）。"""
    raw = job.get("stats") or {}
    return {
        "job_status": job.get("status"),
        "failed_blocks": job.get("failed_blocks") or [],
        "counts": {"persons": raw.get("persons", 0), "relationships": raw.get("relationships", 0)},
        "hygiene": raw.get("mention_hygiene") or {},
        "merge": raw.get("entity_resolution") or {},
    }


# ---------------------------------------------------------------------------
# 运行编排
# ---------------------------------------------------------------------------


def _upload(client, epub_bytes: bytes, filename: str) -> dict:
    resp = client.post("/api/novels", files={"file": (filename, epub_bytes, "application/epub+zip")})
    if resp.status_code != 200:
        raise RuntimeError(f"upload failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def _wait_job(client, job_id: str, timeout: int = 120 * 60) -> dict:
    # 默认 2h/run：qwen3.8-max 大模型 + .env concurrency=1 时单 run（27 chunk extract 串行 + judge 串行）
    # 可能远超 30 分钟（P19 实测 flash 并发 4 时约 8 分钟）；超时仅保护「挂死」，不限制正常慢运行。
    deadline = datetime.now().timestamp() + timeout
    while datetime.now().timestamp() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "completed_with_errors", "failed"):
            return job
        time.sleep(5)
    raise TimeoutError(f"job {job_id} 超时（{timeout}s）")


def _run_single(settings, client, db, epub_bytes: bytes, corpus_hash: str,
                out_dir: Path, tag: str) -> dict:
    """单次真实 ingest：上传 → 轮询 → 快照 → stats → evaluate_checkset → evidence → result.json。

    判定唯一入口 = checks.evaluate_checkset（本函数只采集事实并调用）。
    """
    from tools.eval_framework.checks import CHECKSET_V1, evaluate_checkset
    from tools.eval_framework.evidence import collect_alias_contexts

    data = _upload(client, epub_bytes, "eval.epub")
    novel_id, job_id = data["novel_id"], data["job_id"]
    job = _wait_job(client, job_id)

    snap = _graph_snapshot(db, novel_id)
    snap["counts"] = {"nonbody_canonical_count": _nonbody_canonical_count(epub_bytes, snap["persons"])}
    snap["alias_search"] = _alias_search(client, novel_id, ("二老",))
    snap["checkpoint_dir_exists"] = (Path(settings.er_checkpoint_dir) / novel_id).is_dir()

    st = _normalize_stats(job)
    outcomes = evaluate_checkset(CHECKSET_V1, snap, st)
    checks = [{"check_id": o.check_id, "outcome": o.outcome,
               "reason": o.reason, "actual": o.actual} for o in outcomes]

    result = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "timestamp": _now_iso(),
        "tag": tag,
        "env": _collect_env(settings, db, novel_id),
        "corpus": {"name": CHECKSET_V1.corpus["name"], "content_hash": corpus_hash},
        "compare_identity": compute_compare_identity(settings, corpus_hash),
        "novel_id": novel_id,
        "job": {"job_id": job_id, "status": job["status"],
                "failed_blocks": job.get("failed_blocks") or []},
        "stats": st,
        "graph_snapshot": snap,
        "checks": checks,
        "evidence_dump": collect_alias_contexts(
            epub_bytes, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
            persons=snap["persons"]),
        "warnings": ([f"job 非 completed: {job['status']}"] if job["status"] != "completed" else []),
    }
    _write_result(out_dir, result)
    return result


def _write_result(out_dir: Path, result: dict) -> Path:
    run_dir = out_dir / "runs" / result["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "result.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _summarize(result: dict) -> str:
    counts: dict[str, int] = {}
    for c in result["checks"]:
        counts[c["outcome"]] = counts.get(c["outcome"], 0) + 1
    return (f"novel={result['novel_id']} job={result['job']['status']} "
            f"persons={result['stats']['counts']['persons']} "
            f"rels={result['stats']['counts']['relationships']} checks={counts}")


class FakeLLMClient:
    """smoke 模式 mock（test_api_neo4j 同款，确定性）：固定 3 人、judge 独立、merge 空。

    只验证 runner 骨架（上传→轮询→快照→检查→落盘），不验证 ER 质量。
    """

    def extract_chunk(self, text: str):
        from app.schemas.llm import ExtractionResult
        return ExtractionResult.model_validate({
            "characters": [{"name": "贾宝玉"}, {"name": "林黛玉"}, {"name": "王熙凤"}],
            "relationships": [],
        })

    def judge_aliases(self, chunk_text, pending):
        from app.schemas.llm import AliasJudgeResult
        return AliasJudgeResult.model_validate(
            {"resolutions": [{"mention": p.mention, "resolves_to": None} for p in pending]})

    def judge_merges(self, pairs):
        from app.schemas.llm import MergeJudgeResult
        return MergeJudgeResult.model_validate({"merges": []})


def _run_real(settings, epub_bytes: bytes, corpus_hash: str, out_dir: Path, tag: str) -> dict:
    import httpx
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.pipeline.llm_client import LLMClient

    app = create_app()
    with TestClient(app) as client:
        if app.state.settings.er_checkpoint_enabled:
            raise RuntimeError("app settings 仍为 checkpoint enabled（env 注入失败）")
        # eval 环境注入（同 eval_p19_resume）：300s 超时防 ReadTimeout 静默重试污染
        app.state.llm_client = LLMClient(
            base_url=app.state.settings.bailian_url,
            api_key=app.state.settings.bailian_api_key,
            model=app.state.settings.bailian_model,
            http_client=httpx.Client(timeout=REAL_HTTP_TIMEOUT),
        )
        return _run_single(settings, client, app.state.db, epub_bytes, corpus_hash, out_dir, tag)


def _run_smoke(settings, epub_bytes: bytes, corpus_hash: str, out_dir: Path, tag: str) -> dict:
    """smoke：mock LLM + 真实 Neo4j 自检骨架；自检数据按 AGENTS.md §3 自清（只清理自己的 novel_id）。"""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        app.state.llm_client = FakeLLMClient()
        result = _run_single(settings, client, app.state.db, epub_bytes, corpus_hash, out_dir, tag)
        client.app.state.db.delete_novel(result["novel_id"])
        print(f"[eval] smoke 自检数据已清理 novel={result['novel_id']}", flush=True)
        return result


def _dry_run(settings) -> int:
    from tools.eval_framework.checks import CHECKSET_V1

    head, dirty = _git_state()
    print("[dry-run] 前置校验全部通过：")
    print(f"  checkset v{CHECKSET_V1.checkset_version}（{len(CHECKSET_V1.checks)} 条检查）schema 合法")
    print(f"  corpus: {CHECKSET_V1.corpus['name']}（path={CHECKSET_V1.corpus['path']}）content_hash 匹配钉死值")
    print(f"  er_checkpoint_enabled=False（fresh novel 强制；P19 语义零改动）")
    print(f"  env: model={settings.bailian_model} chunk={settings.chunk_size}/{settings.chunk_overlap} "
          f"concurrency={settings.llm_concurrency} git={head[:8]}{'(dirty)' if dirty else ''}")
    print("  neo4j_version: n/a（dry-run 不连接 Neo4j）")
    print("[dry-run] 未创建 app / 未上传 / 未调用 LLM")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="P20 eval runner（Spec §6.1）")
    parser.add_argument("--runs", type=int, default=1, help="连续运行次数（每次全新 novel_id）")
    parser.add_argument("--tag", default="", help="结果标签（写入 result.tag）")
    parser.add_argument("--smoke", action="store_true", help="mock LLM + 真实 Neo4j 自检骨架")
    parser.add_argument("--dry-run", action="store_true", help="仅前置校验，不创建 app")
    parser.add_argument("--out-dir", type=Path, default=OUT_DEFAULT, help="结果输出目录")
    args = parser.parse_args(argv)

    # 约束 1：eval 强制 fresh novel（checkpoint 零接触）。须在 Settings() 之前设置。
    os.environ["ER_CHECKPOINT_ENABLED"] = "false"

    # 工作目录锚定到 backend 根：支持 `python -m backend.tools.eval_framework.runner`（repo 根）
    # 与 `cd backend && python -u tools/eval_framework/runner.py` 两种调用方式。
    # backend/.env 相对 backend cwd 解析（pydantic-settings env_file=".env"）；其余相对路径同此基准。
    os.chdir(_BACKEND_ROOT)

    from app.config import Settings

    try:
        settings = Settings()
    except Exception as exc:
        print(f"[eval] REFUSE: 配置加载失败（检查 .env）: {exc}")
        return 2
    if settings.er_checkpoint_enabled:
        print("[eval] REFUSE: er_checkpoint_enabled 必须为 False（eval 强制 fresh novel；P19 语义零改动）")
        return 2

    from tools.eval_framework.checks import CHECKSET_V1, validate_checkset

    errs = validate_checkset(CHECKSET_V1)
    if errs:
        print(f"[eval] REFUSE: checkset 校验失败: {errs}")
        return 2

    corpus_rel = Path(CHECKSET_V1.corpus["path"])
    epub_path = corpus_rel if corpus_rel.is_absolute() else _REPO_ROOT / corpus_rel
    if not epub_path.is_file():
        print(f"[eval] REFUSE: corpus 不存在: {epub_path}")
        return 2
    epub_bytes = epub_path.read_bytes()
    corpus_hash = _sha256_hex(epub_bytes)
    if corpus_hash != CHECKSET_V1.corpus["content_hash"]:
        print(f"[eval] REFUSE: corpus content_hash 漂移 {corpus_hash[:12]}… ≠ 钉死 "
              f"{CHECKSET_V1.corpus['content_hash'][:12]}…（检查语料文件是否被改动）")
        return 2

    print(f"[eval] checkset v{CHECKSET_V1.checkset_version} 校验通过；corpus={CHECKSET_V1.corpus['name']} "
          f"content_hash={corpus_hash[:12]}…", flush=True)

    if args.dry_run:
        return _dry_run(settings)

    if args.smoke and args.runs > 1:
        print("[eval] --smoke 仅支持单次运行（忽略 --runs）", flush=True)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        results = [_run_smoke(settings, epub_bytes, corpus_hash, out_dir, args.tag)]
    else:
        results = []
        for i in range(args.runs):
            print(f"[eval] run {i + 1}/{args.runs} 开始（{_now_iso()}）", flush=True)
            results.append(_run_real(settings, epub_bytes, corpus_hash, out_dir, args.tag))
    for r in results:
        print(f"[eval] {_summarize(r)}", flush=True)
    print(f"[eval] 完成；results 落盘 {out_dir}/runs/", flush=True)
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
