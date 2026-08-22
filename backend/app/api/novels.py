import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile

from app.config import Settings
from app.db.neo4j import Neo4jDB
from app.models.job import JobStore, JobStatus
from app.pipeline.chunker import chunk_chapters
from app.pipeline.epub_reader import read_epub
from app.pipeline.extractor import extract_all
from app.pipeline.llm_client import LLMClient
from app.pipeline.merger import merge_extractions
from app.schemas.api import NovelCreateResponse, NovelListItem, NovelResponse

router = APIRouter(prefix="/api/novels", tags=["novels"])

MAX_EPUB_BYTES = 50 * 1024 * 1024  # 50MB


def _run_ingest(novel_id: str, job_id: str, title: str, epub_bytes: bytes,
                settings: Settings, db: Neo4jDB, job_store: JobStore, llm_client: LLMClient) -> None:
    """后台 ingest 任务：epub → 章节 → 切块 → 并发抽取 → 聚合 → 写库 → 更新 job。"""
    job_store.update(job_id, status=JobStatus.running)
    try:
        chapters = read_epub(epub_bytes)
        if not chapters:
            raise ValueError("epub 中没有可解析的章节内容")
        chunks = chunk_chapters(chapters, settings.chunk_size, settings.chunk_overlap)
        job_store.update(job_id, total_chunks=len(chunks))
        from app.pipeline.extractor import FailedBlock
        from app.pipeline.merger import apply_aliases
        from app.pipeline.resolver import EntityResolver

        # 抽取（并发，不变）
        bundle = extract_all(
            llm_client, chunks,
            concurrency=settings.llm_concurrency,
            on_chunk_done=lambda: job_store.increment_done(job_id),
        )
        # 实体消歧（顺序，整本一个 resolver）
        resolver = EntityResolver(judge=llm_client.judge_aliases)
        resolved: list[tuple] = []
        resolution_failed: list[FailedBlock] = []
        for chunk, result in bundle.results:  # 已按 chunk_id 升序
            out, failed = resolver.resolve(chunk, result)
            resolved.append((chunk, out))
            if failed:
                resolution_failed.append(FailedBlock(
                    chunk_id=chunk.chunk_id,
                    chapter_id=chunk.chapter_id,
                    error="alias_resolution_failed",
                ))
        merged = merge_extractions(resolved)
        apply_aliases(merged, resolver.canonical_aliases)
        # V0.2.3-b2：b1 decision → b2 apply（纯内存合并）+ 单事务写库
        merge_out = resolver.decide_merges(
            llm_client.judge_merges,
            confidence_threshold=settings.merge_confidence_threshold,
        )
        merge_map = merge_out["merge_map"]
        from app.pipeline.merger import apply_merges
        apply_merges(merged, merge_map)
        db.upsert_novel(novel_id, title, [{"id": c.chapter_id, "title": c.chapter_title} for c in chapters])
        db.upsert_graph(novel_id, merged, merge_map)
        stats = db.count_stats(novel_id)
        stats["entity_resolution"] = merge_out["stats"]["entity_resolution"]
        stats["mention_hygiene"] = resolver.hygiene_stats   # V0.2.4
        all_failed = bundle.failed + resolution_failed
        if all_failed:
            job_store.update(
                job_id, status=JobStatus.completed_with_errors,
                failed_blocks=[{"chunk_id": f.chunk_id, "chapter_id": f.chapter_id, "error": f.error}
                               for f in all_failed],
                stats=stats,
            )
        else:
            job_store.update(job_id, status=JobStatus.completed, stats=stats)
    except Exception as exc:
        job_store.update(job_id, status=JobStatus.failed, error=str(exc))


@router.post("", response_model=NovelCreateResponse)
async def create_novel(request: Request, background_tasks: BackgroundTasks,
                       file: UploadFile = File(...)) -> NovelCreateResponse:
    filename = file.filename or ""
    if not filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="仅支持 .epub 文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_EPUB_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 50MB 限制")

    db: Neo4jDB = request.app.state.db
    try:
        db.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Neo4j 不可达")

    novel_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    title = Path(filename).stem
    job_store: JobStore = request.app.state.job_store
    job_store.create(job_id, novel_id)
    background_tasks.add_task(
        _run_ingest, novel_id, job_id, title, data,
        request.app.state.settings, db, job_store, request.app.state.llm_client,
    )
    return NovelCreateResponse(novel_id=novel_id, job_id=job_id)


@router.get("", response_model=list[NovelListItem])
def list_novels(request: Request) -> list[NovelListItem]:
    db: Neo4jDB = request.app.state.db
    return db.list_novels()


@router.get("/{novel_id}", response_model=NovelResponse)
def get_novel(novel_id: str, request: Request) -> NovelResponse:
    db: Neo4jDB = request.app.state.db
    novel = db.get_novel(novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return NovelResponse(
        id=novel_id,
        title=novel["title"],
        chapters=novel["chapters"],
        stats=db.count_stats(novel_id),
    )
