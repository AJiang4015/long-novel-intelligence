from pydantic import BaseModel

from app.models.job import FailedBlock, JobState, JobStatus


class NovelCreateResponse(BaseModel):
    novel_id: str
    job_id: str


class NovelListItem(BaseModel):
    id: str
    title: str


class JobProgress(BaseModel):
    done_chunks: int
    total_chunks: int


class JobResponse(BaseModel):
    job_id: str
    novel_id: str
    status: JobStatus
    progress: JobProgress
    failed_blocks: list[FailedBlock]
    stats: dict
    error: str | None = None

    @classmethod
    def from_state(cls, state: JobState) -> "JobResponse":
        return cls(
            job_id=state.job_id,
            novel_id=state.novel_id,
            status=state.status,
            progress=JobProgress(done_chunks=state.done_chunks, total_chunks=state.total_chunks),
            failed_blocks=state.failed_blocks,
            stats=state.stats,
            error=state.error,
        )


class NovelResponse(BaseModel):
    id: str
    title: str
    chapters: list[dict]
    stats: dict


class CharacterCandidate(BaseModel):
    id: str
    name: str
    mention_count: int


class EvidenceItem(BaseModel):
    chunk_id: int
    chapter_id: int
    chapter_title: str
    text: str


class GraphEdge(BaseModel):
    source_id: str
    target_id: str
    type: str
    weight: int
    confidence: float
    evidence: list[EvidenceItem]


class GraphNode(BaseModel):
    id: str
    name: str
    mention_count: int
    is_center: bool


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
