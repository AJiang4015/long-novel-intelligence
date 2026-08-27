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

    def get_or_create_running_job(self, novel_id: str, candidate_job_id: str) -> tuple[str, bool]:
        """P19 AC-8：单锁临界区内按 novel_id 查非终态 job → 命中返回既有 (job_id, False)；
        否则创建 candidate 并返回 (candidate_job_id, True)。

        闭合「查 + 建」的 TOCTOU 竞态：同 novel 并发上传最多产生一个非终态 job。
        """
        terminal = (JobStatus.completed, JobStatus.completed_with_errors, JobStatus.failed)
        with self._lock:
            for job in self._jobs.values():
                if job.novel_id == novel_id and job.status not in terminal:
                    return job.job_id, False
            job = JobState(job_id=candidate_job_id, novel_id=novel_id)
            self._jobs[candidate_job_id] = job
            return candidate_job_id, True
