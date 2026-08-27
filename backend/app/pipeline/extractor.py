import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from app.pipeline.chunker import Chunk
from app.pipeline.llm_client import LLMClient, LLMRetryableError, LLMValidationError
from app.schemas.llm import ExtractionResult

# P19：抽取编排逻辑版本（extract 调用/重试语义变更时 +1；进入 checkpoint config_fingerprint）
EXTRACTOR_VERSION = "1"


@dataclass
class FailedBlock:
    chunk_id: int
    chapter_id: int
    error: str


@dataclass
class ExtractionBundle:
    results: list[tuple[Chunk, ExtractionResult]]
    failed: list[FailedBlock]


def extract_one(client: LLMClient, chunk: Chunk, retries: int = 1, on_chunk_result=None):
    """单块抽取。429/5xx 与意外异常重试 retries 次；validation error 不重试。

    on_chunk_result(chunk, outcome)：每 chunk 最终结果（(Chunk, ExtractionResult) 或 FailedBlock）
    恰好回调一次（P19 checkpoint 持久化钩子；None = 行为与现状逐字节一致）。
    """
    for attempt in range(retries + 1):
        try:
            result = client.extract_chunk(chunk.text)
            out: tuple | FailedBlock = (chunk, result)
            break
        except LLMRetryableError as exc:
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            out = FailedBlock(chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id, error=str(exc))
            break
        except LLMValidationError as exc:
            out = FailedBlock(chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id, error=str(exc))
            break
        except Exception as exc:  # 网络中断等意外错误，按可重试处理
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            out = FailedBlock(
                chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id,
                error=f"unexpected:{type(exc).__name__}",
            )
            break
    if on_chunk_result is not None:
        on_chunk_result(chunk, out)
    return out


def extract_all(client: LLMClient, chunks: list[Chunk], concurrency: int = 4,
                on_chunk_done=None, on_chunk_result=None) -> ExtractionBundle:
    """并发抽取全部 chunk。concurrency 必须来自配置，禁止写死。

    on_chunk_result：透传给 extract_one（每 chunk 结果回调；P19 checkpoint 钩子）。
    """
    results: list[tuple[Chunk, ExtractionResult]] = []
    failed: list[FailedBlock] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(extract_one, client, c, 1, on_chunk_result) for c in chunks]
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
