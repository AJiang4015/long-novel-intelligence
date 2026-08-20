from enum import Enum
from threading import Lock

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    completed_with_errors = "completed_with_errors"
    failed = "failed"


class FailedBlock(BaseModel):
    chunk_id: int
    chapter_id: int
    error: str


class JobState(BaseModel):
    job_id: str
    novel_id: str
    status: JobStatus = JobStatus.pending
    done_chunks: int = 0
    total_chunks: int = 0
    failed_blocks: list[FailedBlock] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
    error: str | None = None


class JobStore:
    """进程内任务存储（V0.1 设计决策：单进程足够，不引入 Redis）。

    注意：进程重启后任务丢失，后续版本替换为持久化任务存储。
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = Lock()

    def create(self, job_id: str, novel_id: str) -> JobState:
        with self._lock:
            job = JobState(job_id=job_id, novel_id=novel_id)
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> JobState | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                setattr(job, key, value)
            return job

    def increment_done(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.done_chunks += 1
