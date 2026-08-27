import datetime
import hashlib
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.checkpoint import CHECKPOINT_SCHEMA_VERSION, CheckpointStore
from app.config import Settings
from app.db.neo4j import Neo4jDB
from app.models.job import FailedBlock, JobStore, JobStatus
from app.pipeline.chunker import CHUNKER_VERSION, Chunk, chunk_chapters
from app.pipeline.epub_reader import read_epub
from app.pipeline.extractor import EXTRACTOR_VERSION, extract_all
from app.pipeline.lineage import create_lineage_recorder
from app.pipeline.llm_client import (ALIAS_JUDGE_SYSTEM_PROMPT, ALIAS_JUDGE_USER_PROMPT,
                                     EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT,
                                     LLMClient, MERGE_JUDGE_SYSTEM_PROMPT, MERGE_JUDGE_USER_PROMPT)
from app.pipeline.merger import merge_extractions
from app.schemas.api import NovelCreateResponse, NovelListItem, NovelResponse
from app.schemas.llm import AliasJudgeResult, MergeJudgeResult, MergePair, PendingMention

router = APIRouter(prefix="/api/novels", tags=["novels"])

MAX_EPUB_BYTES = 50 * 1024 * 1024  # 50MB


# ======================================================================
# P19：版本指纹与 canonical serializer（编排层；CheckpointStore 不做兼容判定）
# ======================================================================


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _prompt_hash(*prompts: str) -> str:
    return _sha256_hex("\n".join(prompts).encode("utf-8"))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _version_tuple(settings: Settings) -> dict:
    """checkpoint 版本元组（进入 manifest 与 config_fingerprint）。

    prompt 变更必须作废 checkpoint（A-1 教训：prompt 一变旧 extraction/judge 语义即失效）。
    """
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "chunking_version": CHUNKER_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "extraction_prompt_hash": _prompt_hash(EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT),
        "judge_prompt_hash": _prompt_hash(ALIAS_JUDGE_SYSTEM_PROMPT, ALIAS_JUDGE_USER_PROMPT),
        "merge_prompt_hash": _prompt_hash(MERGE_JUDGE_SYSTEM_PROMPT, MERGE_JUDGE_USER_PROMPT),
        "model": settings.bailian_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }


def _config_fingerprint(settings: Settings) -> str:
    return _sha256_hex(json.dumps(_version_tuple(settings), sort_keys=True, ensure_ascii=False).encode("utf-8"))


def _chunk_dict(chunk: Chunk) -> dict:
    d = asdict(chunk)
    d["section_type"] = chunk.section_type.value
    return d


def _structure_hash(chunks: list[Chunk]) -> str:
    """chunking 产物 integrity check（非版本兼容职责；防 chunker 实际产物漂移）。"""
    payload = [{k: d[k] for k in ("chunk_id", "chapter_id", "chapter_title", "start_offset",
                                  "end_offset", "section_type", "text")}
               for d in (_chunk_dict(c) for c in chunks)]
    return _sha256_hex(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def _judge_input_fingerprint(chunk_text: str, pending: list[PendingMention]) -> str:
    """judge 输入指纹：基于 resolver 实际传入的最终 (text, pending) 的 canonical serialization。"""
    payload = {
        "text": chunk_text,
        "pending": [{"mention": p.mention,
                     "candidates": [{"canonical": c.canonical, "matched_names": c.matched_names}
                                    for c in p.candidates]}
                    for p in pending],
    }
    return _sha256_hex(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def _merge_input_fingerprint(pairs: list[MergePair]) -> str:
    """merge judge 输入指纹：基于传给 judge_merges 的最终 pairs 的 canonical serialization（非中间对象）。"""
    payload = [
        {"a": {"canonical": p.a.canonical, "aliases": p.a.aliases,
               "first_seen_chunk": p.a.first_seen_chunk, "mention_count": p.a.mention_count,
               "chapters": sorted(p.a.chapters)},
         "b": {"canonical": p.b.canonical, "aliases": p.b.aliases,
               "first_seen_chunk": p.b.first_seen_chunk, "mention_count": p.b.mention_count,
               "chapters": sorted(p.b.chapters)},
         "bridge_evidence": [{"chunk_id": e.chunk_id, "chapter_id": e.chapter_id,
                              "mention": e.mention, "text": e.text}
                             for e in p.bridge_evidence]}
        for p in pairs]
    return _sha256_hex(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def _judge_version(settings: Settings, fingerprint: str) -> dict:
    v = _version_tuple(settings)
    return {"judge_prompt_hash": v["judge_prompt_hash"], "model": v["model"],
            "config_fingerprint": fingerprint}


def _merge_version(settings: Settings, fingerprint: str) -> dict:
    v = _version_tuple(settings)
    return {"merge_prompt_hash": v["merge_prompt_hash"], "model": v["model"],
            "config_fingerprint": fingerprint}


# ======================================================================
# P19：Replay 包装器（编排层；resolver / llm_client 零改动）
# ======================================================================


class ReplayJudge:
    """judge 包装器：命中兼容 checkpoint → 重放；否则调 LLM 并持久化（成功才写）。

    - 兼容判定（judge_version + input_fingerprint）在此层完成；
    - judge 失败不持久化 → resume 重试；judge_failed_chunks 供 COMPLETED 准入（v1.2 R1）。
    """

    def __init__(self, cp: CheckpointStore, llm_client: LLMClient, novel_id: str, judge_version: dict):
        self._cp = cp
        self._llm = llm_client
        self._novel_id = novel_id
        self._judge_version = judge_version
        self._chunk_id = 0
        self.judge_failed_chunks: set[int] = set()

    def set_chunk(self, chunk_id: int) -> None:
        self._chunk_id = chunk_id

    def judge_aliases(self, chunk_text: str, pending: list[PendingMention]) -> AliasJudgeResult:
        fp = _judge_input_fingerprint(chunk_text, pending)
        hit = self._cp.load_judge(self._novel_id, self._chunk_id, fp)
        if hit is not None and hit.get("judge_version") == self._judge_version:
            return AliasJudgeResult.model_validate(hit["result"])
        try:
            result = self._llm.judge_aliases(chunk_text, pending)
        except Exception:
            self.judge_failed_chunks.add(self._chunk_id)
            raise
        self._cp.save_judge(self._novel_id, self._chunk_id, fp, {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "chunk_id": self._chunk_id,
            "judge_version": self._judge_version,
            "input_fingerprint": fp,
            "result": result.model_dump(),
        })
        return result


class ReplayMergeJudge:
    """merge judge 包装器（同 ReplayJudge 语义；末尾一次 batch）。"""

    def __init__(self, cp: CheckpointStore, llm_client: LLMClient, novel_id: str, merge_version: dict):
        self._cp = cp
        self._llm = llm_client
        self._novel_id = novel_id
        self._merge_version = merge_version
        self.merge_failed = False

    def judge_merges(self, pairs: list[MergePair]) -> MergeJudgeResult:
        fp = _merge_input_fingerprint(pairs)
        hit = self._cp.load_merge_judge(self._novel_id, fp)
        if hit is not None and hit.get("merge_version") == self._merge_version:
            return MergeJudgeResult.model_validate(hit["result"])
        try:
            result = self._llm.judge_merges(pairs)
        except Exception:
            self.merge_failed = True
            raise
        self._cp.save_merge_judge(self._novel_id, fp, {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "merge_version": self._merge_version,
            "input_fingerprint": fp,
            "result": result.model_dump(),
        })
        return result


class _ExtractionHook:
    """P19：extraction 结果持久化钩子（每 chunk 恰好一次；成功 → COMPLETED，失败 → FAILED 标记）。

    warnings：checkpoint 写失败计数（观测；CPython GIL 下近似线程安全）。
    """

    def __init__(self, cp: CheckpointStore, novel_id: str, fingerprint: str):
        self._cp = cp
        self._novel_id = novel_id
        self._fingerprint = fingerprint
        self.warnings = 0

    def __call__(self, chunk: Chunk, outcome) -> None:
        from app.pipeline.extractor import FailedBlock
        prev = self._cp.load_extraction(self._novel_id, chunk.chunk_id) or {}
        attempts = prev.get("attempts", 0) + 1
        if isinstance(outcome, FailedBlock):
            self._cp.save_extraction(self._novel_id, chunk.chunk_id, {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "chunk_id": chunk.chunk_id,
                "chapter_id": chunk.chapter_id,
                "status": "FAILED",
                "attempts": attempts,
                "error": outcome.error,
                "config_fingerprint": self._fingerprint,
                "result": None,
            })
        else:
            ok = self._cp.save_extraction(self._novel_id, chunk.chunk_id, {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "chunk_id": chunk.chunk_id,
                "chapter_id": chunk.chapter_id,
                "status": "COMPLETED",
                "attempts": attempts,
                "error": None,
                "config_fingerprint": self._fingerprint,
                "result": outcome[1].model_dump(),
            })
            if not ok:
                self.warnings += 1


# ======================================================================
# ingest 编排
# ======================================================================


def _run_ingest(novel_id: str, job_id: str, title: str, epub_bytes: bytes,
                settings: Settings, db: Neo4jDB, job_store: JobStore, llm_client: LLMClient) -> None:
    """后台 ingest 任务（P19 resume-aware）：epub → 章节 → 切块 → 并发抽取 → 聚合 → 写库 → 更新 job。

    - checkpoint 启用时：已完成 extraction 跳过（零 LLM 调用）、judge 结果重放（零 LLM 调用）；
    - job 终态与 manifest 状态解耦（v1.2 R1）：有可恢复缺口 → manifest 保持 IN_PROGRESS。
    """
    job_store.update(job_id, status=JobStatus.running)
    # V0.2.7 Task A：lineage recorder（ER_LINEAGE=1 启用；否则 no-op）。
    # 纯旁路观测：不改变任何判定；job 终态（含 except 失败分支）统一 flush 落盘。
    lineage = create_lineage_recorder(settings, novel_id, job_id)
    try:
        chapters = read_epub(epub_bytes)
        if not chapters:
            raise ValueError("epub 中没有可解析的章节内容")
        chunks = chunk_chapters(chapters, settings.chunk_size, settings.chunk_overlap)
        job_store.update(job_id, total_chunks=len(chunks))
        from app.pipeline.merger import apply_aliases, apply_merges, drop_unconfirmed_entities
        from app.pipeline.resolver import EntityResolver

        fingerprint = _config_fingerprint(settings)
        cp: CheckpointStore | None = None
        if settings.er_checkpoint_enabled:
            cp = CheckpointStore(settings.er_checkpoint_dir)
            if cp.load_manifest(novel_id) is None:
                version = _version_tuple(settings)
                now = _now_iso()
                cp.save_manifest(novel_id, {
                    "schema_version": CHECKPOINT_SCHEMA_VERSION,
                    "novel_id": novel_id,
                    "title": title,
                    "content_hash": _sha256_hex(epub_bytes),
                    **version,
                    "config_fingerprint": fingerprint,
                    "structure_hash": _structure_hash(chunks),
                    "chunk_count": len(chunks),
                    "status": "IN_PROGRESS",
                    "created_at": now,
                    "updated_at": now,
                    "final_stats": {},
                })
            cp.save_chunks(novel_id, [_chunk_dict(c) for c in chunks])

        # ---- 抽取阶段（P19：只处理未完成 chunk；每结果立即持久化）----
        done_ids = cp.completed_extraction_ids(novel_id, fingerprint) if cp else set()
        job_store.update(job_id, done_chunks=len(done_ids))
        hook = _ExtractionHook(cp, novel_id, fingerprint) if cp else None
        todo = [c for c in chunks if c.chunk_id not in done_ids]
        bundle = extract_all(
            llm_client, todo,
            concurrency=settings.llm_concurrency,
            on_chunk_done=lambda: job_store.increment_done(job_id),
            on_chunk_result=hook,
        )
        # ---- V0.2.7 lineage：extraction_raw（可选 debug，ER_LINEAGE_RAW_EXTRACTION=1 时）----
        if lineage.enabled and lineage.raw_extraction:
            for chunk, result in bundle.results:
                lineage.extraction_raw(
                    chunk_id=chunk.chunk_id, chapter_id=chunk.chapter_id,
                    characters=[{"name": c.name,
                                 "category": c.category.value if c.category is not None else None}
                                for c in result.characters],
                    relationships=[{"source": r.source, "target": r.target,
                                    "type": r.type.value, "confidence": r.confidence}
                                   for r in result.relationships],
                )
        # ---- P19：全部结果 = 已持久化（重放）+ 本次新增，按 chunk_id 升序；失败 = markers + 本次 ----
        if cp is not None:
            from app.schemas.llm import ExtractionResult
            done = cp.completed_extraction_ids(novel_id, fingerprint)
            results: list[tuple[Chunk, object]] = []
            for chunk in chunks:  # chunk_id 升序
                if chunk.chunk_id not in done:
                    continue
                payload = cp.load_extraction(novel_id, chunk.chunk_id)
                if payload and isinstance(payload.get("result"), dict):
                    results.append((chunk, ExtractionResult.model_validate(payload["result"])))
            seen = {c.chunk_id for c, _ in results}
            results += [(c, r) for c, r in bundle.results if c.chunk_id not in seen]
            results.sort(key=lambda e: e[0].chunk_id)
            failed: list[FailedBlock] = []
            seen_failed: set[int] = set()
            chapter_by_chunk = {c.chunk_id: c.chapter_id for c in chunks}
            for m in cp.load_failed_chunks(novel_id):
                cid = m.get("chunk_id")
                if cid in seen_failed:
                    continue
                seen_failed.add(cid)
                failed.append(FailedBlock(
                    chunk_id=cid,
                    chapter_id=m.get("chapter_id") or chapter_by_chunk.get(cid, 0),
                    error=m.get("error", "unknown"),
                ))
            for f in bundle.failed:
                if f.chunk_id in seen_failed:
                    continue
                seen_failed.add(f.chunk_id)
                failed.append(f)
        else:
            results = bundle.results
            failed = list(bundle.failed)

        # 实体消歧（顺序，整本一个 resolver；P19：judge 走 ReplayJudge 重放）
        replay: ReplayJudge | None = None
        if cp is not None:
            replay = ReplayJudge(cp, llm_client, novel_id, _judge_version(settings, fingerprint))
            resolver = EntityResolver(judge=replay.judge_aliases, lineage=lineage)
        else:
            resolver = EntityResolver(judge=llm_client.judge_aliases, lineage=lineage)
        resolved: list[tuple] = []
        resolution_failed: list[FailedBlock] = []
        for chunk, result in results:  # 已按 chunk_id 升序
            if replay is not None:
                replay.set_chunk(chunk.chunk_id)
            out, failed_flag = resolver.resolve(chunk, result)
            resolved.append((chunk, out))
            if failed_flag:
                resolution_failed.append(FailedBlock(
                    chunk_id=chunk.chunk_id,
                    chapter_id=chunk.chapter_id,
                    error="alias_resolution_failed",
                ))
        merged = merge_extractions(resolved)
        apply_aliases(merged, resolver.canonical_aliases)
        # V0.2.3-b2：b1 decision → b2 apply（纯内存合并）+ 单事务写库；P19：merge judge 重放
        replay_merge: ReplayMergeJudge | None = None
        if cp is not None:
            replay_merge = ReplayMergeJudge(cp, llm_client, novel_id, _merge_version(settings, fingerprint))
            merge_judge = replay_merge.judge_merges
        else:
            merge_judge = llm_client.judge_merges
        merge_out = resolver.decide_merges(
            merge_judge,
            confidence_threshold=settings.merge_confidence_threshold,
        )
        merge_map = merge_out["merge_map"]
        # ---- V0.2.7 lineage：merge 层（canonical 级旁路；merge_stats + merge_drop 逐条）----
        lineage.merge_stats(stats=merge_out["stats"]["entity_resolution"])
        for drop, keep in merge_map.items():
            lineage.merge_drop(canonical=drop, merge_keep=keep)
        apply_merges(merged, merge_map)
        # V0.2.5-a：flush 未获正文确认的 provisional canonical（不入图；端点关系丢弃）
        dropped = resolver.finalize()
        if dropped:
            merged = drop_unconfirmed_entities(merged, dropped)
        # ---- V0.2.7 lineage：canonical_snapshot（merge + finalize 后的图内最终状态）----
        lineage.canonical_snapshot(canonicals=[
            {"canonical": name, "aliases": list(p.aliases),
             "mention_count": p.mention_count, "chapters": sorted(p.chapters)}
            for name, p in sorted(merged.persons.items())
        ])
        db.upsert_novel(novel_id, title, [{"id": c.chapter_id, "title": c.chapter_title} for c in chapters])
        db.upsert_graph(novel_id, merged, merge_map)
        stats = db.count_stats(novel_id)
        stats["entity_resolution"] = merge_out["stats"]["entity_resolution"]
        stats["mention_hygiene"] = resolver.hygiene_stats   # V0.2.4
        if cp is not None and hook is not None:
            stats["checkpoint"] = {"warnings": hook.warnings}   # P19 观测（写失败降级计数）
        all_failed = failed + resolution_failed
        # ---- P19 v1.2 R1：COMPLETED 准入（无可恢复缺口 + 写库成功才允许）----
        if cp is not None:
            failed_ids = {f.chunk_id for f in failed}
            gaps: list = [c.chunk_id for c in chunks if c.chunk_id in failed_ids]
            if replay is not None:
                gaps += sorted(replay.judge_failed_chunks)
            if replay_merge is not None and replay_merge.merge_failed:
                gaps.append("merge")
            if not gaps:
                cp.mark_complete(novel_id, stats)
        if all_failed:
            failed_blocks = [{"chunk_id": f.chunk_id, "chapter_id": f.chapter_id, "error": f.error}
                             for f in all_failed]
            job_store.update(
                job_id, status=JobStatus.completed_with_errors,
                failed_blocks=failed_blocks,
                stats=stats,
            )
            lineage.job_end(status="completed_with_errors", failed_blocks=failed_blocks, stats=stats)
        else:
            job_store.update(job_id, status=JobStatus.completed, stats=stats)
            lineage.job_end(status="completed", failed_blocks=[], stats=stats)
    except Exception as exc:
        lineage.job_end(status="failed", failed_blocks=[], stats={"error": str(exc)})
        job_store.update(job_id, status=JobStatus.failed, error=str(exc))
    finally:
        # V0.2.7 lineage：失败 job 也落盘（except 分支已记 job_end；flush 幂等、不抛异常）
        lineage.flush()


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

    settings: Settings = request.app.state.settings
    job_store: JobStore = request.app.state.job_store
    novel_id = str(uuid.uuid4())
    title = Path(filename).stem
    manifest: dict | None = None

    if settings.er_checkpoint_enabled:
        # P19：EPUB sha256 内容身份 + 复合索引（content_hash:config_fingerprint，AC-11）
        content_hash = _sha256_hex(data)
        fingerprint = _config_fingerprint(settings)
        cp = CheckpointStore(settings.er_checkpoint_dir)
        manifest = cp.find_manifest(content_hash, fingerprint)
        if manifest is not None:
            # integrity check：同配置下 chunking 产物必须一致（structure_hash），否则视为不同分析
            try:
                chapters = await run_in_threadpool(read_epub, data)
                chunks = await run_in_threadpool(
                    chunk_chapters, chapters, settings.chunk_size, settings.chunk_overlap)
                structure_ok = _structure_hash(chunks) == manifest.get("structure_hash")
            except Exception:
                structure_ok = False
            if structure_ok:
                novel_id = manifest["novel_id"]      # 复用（resume 或幂等）
                title = manifest.get("title") or title
            else:
                manifest = None                      # 产物漂移 → 全新分析（不复用 checkpoint）

    job_id = str(uuid.uuid4())
    if manifest is not None:
        # 复用 novel_id 路径：原子防重（AC-8，TOCTOU 闭合）
        job_id, created = job_store.get_or_create_running_job(novel_id, job_id)
        if not created:
            return NovelCreateResponse(novel_id=novel_id, job_id=job_id)   # 已有非终态 job → 幂等返回
        if manifest.get("status") == "COMPLETED":
            # P19 幂等：完整完成重传 → 新的 terminal job（零 LLM，不启动 background task，不复活历史 job）
            job_store.update(
                job_id, status=JobStatus.completed,
                done_chunks=manifest.get("chunk_count", 0),
                total_chunks=manifest.get("chunk_count", 0),
                stats=manifest.get("final_stats") or {},
            )
            return NovelCreateResponse(novel_id=novel_id, job_id=job_id)
        # IN_PROGRESS（含 job 曾 completed_with_errors 但有可恢复缺口，v1.2 R1）→ 继续 resume
    else:
        job_store.create(job_id, novel_id)

    background_tasks.add_task(
        _run_ingest, novel_id, job_id, title, data,
        settings, db, job_store, request.app.state.llm_client,
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
