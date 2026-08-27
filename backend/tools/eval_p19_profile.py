"""P19 评估补充：真实 LLM 分阶段耗时剖析（纯观测，不修改业务代码/baseline）。

回答用户关注的问题：真实 ingest 中 judge 阶段耗时占比。
- 跑一次《边城》完整 ingest（checkpoint disabled，与评估 Run A 同配置：并发 4、300s 超时）；
- 逐调用记录 extract_chunk / judge_aliases / judge_merges 的耗时；
- 输出：分阶段总耗时、调用次数、单调用耗时分布（min/median/max）、阶段占比。

用法（backend 目录）：
    python -u tools/eval_p19_profile.py
环境：BAILIAN_API_KEY（Machine 级） + BAILIAN_MODEL（默认 .env，可环境变量覆盖）。
"""

import json
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline.chunker import chunk_chapters
from app.pipeline.epub_reader import read_epub
from app.pipeline.llm_client import LLMClient

OUT_DIR = Path(__file__).resolve().parents[1] / ".tmp" / "eval-p19-resume"
EPUB_PATH = Path(__file__).resolve().parents[2] / "books" / "边城_(沈从文)_(z-library.sk,_1lib.sk,_z-lib.sk).epub"


class ProfilingLLM:
    def __init__(self, inner: LLMClient, text_to_chunk: dict[str, int]):
        self.inner = inner
        self.text_to_chunk = text_to_chunk
        self.extract_times: list[float] = []
        self.judge_times: list[float] = []
        self.merge_times: list[float] = []

    def extract_chunk(self, text: str):
        t0 = time.time()
        try:
            result = self.inner.extract_chunk(text)
        finally:
            self.extract_times.append(time.time() - t0)
        return result

    def judge_aliases(self, chunk_text: str, pending):
        t0 = time.time()
        try:
            result = self.inner.judge_aliases(chunk_text, pending)
        finally:
            self.judge_times.append(time.time() - t0)
        return result

    def judge_merges(self, pairs):
        t0 = time.time()
        try:
            result = self.inner.judge_merges(pairs)
        finally:
            self.merge_times.append(time.time() - t0)
        return result


def _stats(times: list[float]) -> dict:
    if not times:
        return {"count": 0, "total_s": 0.0, "min_s": None, "median_s": None, "max_s": None}
    s = sorted(times)
    n = len(s)
    return {"count": n, "total_s": round(sum(s), 2),
            "min_s": round(s[0], 2), "median_s": round(s[n // 2], 2), "max_s": round(s[-1], 2)}


def main() -> None:
    from app.config import Settings

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    epub_bytes = EPUB_PATH.read_bytes()
    settings0 = Settings().model_copy(update={"llm_concurrency": 4, "er_checkpoint_enabled": False})
    chapters = read_epub(epub_bytes)
    chunks = chunk_chapters(chapters, settings0.chunk_size, settings0.chunk_overlap)
    text_to_chunk = {c.text: c.chunk_id for c in chunks}
    print(f"[profile] chunks={len(chunks)} model={settings0.bailian_model} concurrency={settings0.llm_concurrency}",
          flush=True)

    app = create_app()
    with TestClient(app) as client:
        inner = LLMClient(base_url=settings0.bailian_url, api_key=settings0.bailian_api_key,
                          model=settings0.bailian_model, http_client=httpx.Client(timeout=300))
        llm = ProfilingLLM(inner, text_to_chunk)
        app.state.llm_client = llm
        app.state.settings = settings0

        t_start = time.time()
        resp = client.post("/api/novels", files={
            "file": ("profile.epub", epub_bytes, "application/epub+zip")})
        data = resp.json()
        # TestClient 同步等待 background task 完成 → 返回时 pipeline 已跑完
        elapsed_total = time.time() - t_start
        job = client.get(f"/api/jobs/{data['job_id']}").json()
        print(f"[profile] job status={job['status']} failed={job['failed_blocks']}", flush=True)

        st_ext = _stats(llm.extract_times)
        st_judge = _stats(llm.judge_times)
        st_merge = _stats(llm.merge_times)
        stage_total = st_ext["total_s"] + st_judge["total_s"] + st_merge["total_s"]
        result = {
            "meta": {"model": settings0.bailian_model, "chunks": len(chunks),
                     "total_elapsed_s": round(elapsed_total, 2)},
            "extract": st_ext,
            "judge": st_judge,
            "merge": st_merge,
            "stage_total_s": round(stage_total, 2),
            "stage_share": {
                "extract_pct": round(100 * st_ext["total_s"] / stage_total, 1) if stage_total else 0,
                "judge_pct": round(100 * st_judge["total_s"] / stage_total, 1) if stage_total else 0,
                "merge_pct": round(100 * st_merge["total_s"] / stage_total, 1) if stage_total else 0,
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        (OUT_DIR / "profile.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        print(f"[profile] saved: {OUT_DIR / 'profile.json'}", flush=True)


if __name__ == "__main__":
    main()
