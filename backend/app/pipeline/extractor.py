import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from app.pipeline.chunker import Chunk
from app.pipeline.llm_client import LLMClient, LLMRetryableError, LLMValidationError
from app.schemas.llm import ExtractionResult


@dataclass
class FailedBlock:
    chunk_id: int
    chapter_id: int
    error: str


@dataclass
class ExtractionBundle:
    results: list[tuple[Chunk, ExtractionResult]]
    failed: list[FailedBlock]


def extract_one(client: LLMClient, chunk: Chunk, retries: int = 1):
    """单块抽取。429/5xx 与意外异常重试 retries 次；validation error 不重试。"""
    for attempt in range(retries + 1):
        try:
            return chunk, client.extract_chunk(chunk.text)
        except LLMRetryableError as exc:
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return FailedBlock(chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id, error=str(exc))
        except LLMValidationError as exc:
            return FailedBlock(chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id, error=str(exc))
        except Exception as exc:  # 网络中断等意外错误，按可重试处理
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return FailedBlock(
                chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id,
                error=f"unexpected:{type(exc).__name__}",
            )


def extract_all(client: LLMClient, chunks: list[Chunk], concurrency: int = 4,
                on_chunk_done=None) -> ExtractionBundle:
    """并发抽取全部 chunk。concurrency 必须来自配置，禁止写死。"""
    results: list[tuple[Chunk, ExtractionResult]] = []
    failed: list[FailedBlock] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(extract_one, client, c) for c in chunks]
        for fut in as_completed(futures):
            out = fut.result()
            if isinstance(out, FailedBlock):
                failed.append(out)
            else:
                results.append(out)
            if on_chunk_done is not None:
                on_chunk_done()
    results.sort(key=lambda e: e[0].chunk_id)
    failed.sort(key=lambda f: f.chunk_id)
    return ExtractionBundle(results=results, failed=failed)
