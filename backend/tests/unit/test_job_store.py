import threading

from app.models.job import FailedBlock, JobStatus, JobStore


def test_job_lifecycle():
    store = JobStore()
    job = store.create("job-1", "novel-1")
    assert job.status == JobStatus.pending
    store.update("job-1", status=JobStatus.running, total_chunks=10)
    store.update("job-1", status=JobStatus.completed_with_errors,
                 done_chunks=9,
                 failed_blocks=[FailedBlock(chunk_id=3, chapter_id=1, error="validation_error")],
                 stats={"persons": 10, "relationships": 5})
    state = store.get("job-1")
    assert state.status == JobStatus.completed_with_errors
    assert state.stats["persons"] == 10
    assert state.failed_blocks[0].chunk_id == 3


def test_unknown_job_returns_none():
    store = JobStore()
    assert store.get("nope") is None


def test_increment_done_is_thread_safe():
    store = JobStore()
    store.create("job-1", "novel-1")
    errors = []

    def bump():
        try:
            for _ in range(100):
                store.increment_done("job-1")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert store.get("job-1").done_chunks == 400
