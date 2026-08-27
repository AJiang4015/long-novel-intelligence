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


def test_get_or_create_running_job_returns_existing():
    """P19 AC-8：同 novel 已有非终态 job → 返回既有，不新建。"""
    store = JobStore()
    store.create("job-a", "novel-1")
    store.update("job-a", status=JobStatus.running)
    job_id, created = store.get_or_create_running_job("novel-1", "job-b")
    assert job_id == "job-a"
    assert created is False
    assert store.get("job-b") is None


def test_get_or_create_running_job_creates_when_none():
    store = JobStore()
    job_id, created = store.get_or_create_running_job("novel-1", "job-x")
    assert job_id == "job-x"
    assert created is True
    assert store.get("job-x").novel_id == "novel-1"
    assert store.get("job-x").status == JobStatus.pending


def test_get_or_create_running_job_ignores_terminal_jobs():
    """终态 job 不阻塞新建（旧 job 不复活；P19：完整重传创建新的 terminal job）。"""
    store = JobStore()
    store.create("job-done", "novel-1")
    store.update("job-done", status=JobStatus.completed)
    store.create("job-err", "novel-1")
    store.update("job-err", status=JobStatus.completed_with_errors)
    job_id, created = store.get_or_create_running_job("novel-1", "job-new")
    assert job_id == "job-new"
    assert created is True


def test_get_or_create_running_job_is_thread_safe():
    """多线程并发同 novel → 仅一个非终态 job（TOCTOU 闭合）。"""
    store = JobStore()
    results = []

    def race(i):
        job_id, created = store.get_or_create_running_job("novel-1", f"job-{i}")
        results.append((job_id, created))

    threads = [threading.Thread(target=race, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    created_count = sum(1 for _jid, created in results if created)
    assert created_count == 1
    running = [j for j in store._jobs.values() if j.novel_id == "novel-1"
               and j.status not in (JobStatus.completed, JobStatus.completed_with_errors, JobStatus.failed)]
    assert len(running) == 1
