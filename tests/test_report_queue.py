from pathlib import Path

from coastal_web.database import create_database_engine, metadata
from coastal_web.repositories import ReportJobRepository, UserRepository


class WorkerGraph:
    def stream(self, state, stream_mode="updates"):
        assert stream_mode == "updates"
        yield {"ingest": {"stats": {"grid_count": 443}}}
        report = Path(state["report_dir"]) / "report.md"
        report.write_text("# 보고서", encoding="utf-8")
        yield {"compose": {"report_md_path": str(report)}}


def _repository():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    user = UserRepository(engine).create("worker-user", "hash")
    return ReportJobRepository(engine), user


def test_report_worker_persists_engine_progress(tmp_path):
    from coastal_web.report_queue import ReportWorker
    from coastal_web.services import ReportManager

    jobs, user = _repository()
    jobs.create(
        user["id"],
        "job-1",
        region="부산광역시 수영구",
        options={"region": "부산광역시 수영구", "make_hwpx": False},
        materials=[],
    )
    worker = ReportWorker(
        jobs,
        output_root=tmp_path / "jobs",
        spatial_export_root=tmp_path / "maps",
        manager_factory=lambda **options: ReportManager(
            graph_factory=WorkerGraph,
            **options,
        ),
    )

    worker.run("job-1")
    restored = jobs.get(user["id"], "job-1")

    assert restored["status"] == "completed"
    assert restored["progress"] == 7
    assert restored["result"]["stats"]["grid_count"] == 443
    assert Path(restored["result"]["report_md_path"]).is_file()


def test_report_queue_uses_report_id_as_rq_job_id():
    from coastal_web.report_queue import ReportQueue

    calls = []

    class FakeQueue:
        def enqueue(self, function, *args, **kwargs):
            calls.append((function, args, kwargs))
            return type("Job", (), {"id": kwargs["job_id"]})()

    queue = ReportQueue(queue=FakeQueue())

    queued = queue.enqueue(
        "job-1",
    )

    assert queued == {"job_id": "job-1", "status": "queued"}
    assert calls[0][2]["job_id"] == "job-1"
    assert calls[0][1] == ("job-1",)
    assert "postgresql://" not in repr(calls[0])


def test_report_queue_enqueues_report_revision_as_a_distinct_task():
    from coastal_web.report_queue import ReportQueue

    calls = []

    class FakeQueue:
        def enqueue(self, function, *args, **kwargs):
            calls.append((function, args, kwargs))
            return type("Job", (), {"id": kwargs["job_id"]})()

    queue = ReportQueue(queue=FakeQueue())

    queued = queue.enqueue_edit(
        "job-1",
        "revision",
        {"section": "정책 제언", "instruction": "간결하게 수정해줘"},
    )

    assert queued["job_id"] == "job-1"
    assert queued["status"] == "queued"
    assert queued["task_id"].startswith("job-1-edit-")
    assert calls[0][1] == (
        "job-1",
        "revision",
        {"section": "정책 제언", "instruction": "간결하게 수정해줘"},
    )
    assert calls[0][2]["job_id"] == queued["task_id"]


def test_report_dispatcher_persists_before_enqueueing():
    from coastal_web.report_queue import ReportDispatcher

    jobs, user = _repository()

    class FakeQueue:
        def __init__(self):
            self.enqueued = []

        def enqueue(self, job_id, **options):
            self.enqueued.append((job_id, options))
            return {"job_id": job_id, "status": "queued"}

    queue = FakeQueue()
    dispatcher = ReportDispatcher(
        jobs,
        queue,
    )

    created = dispatcher.submit(
        user["id"],
        {
            "region": "부산광역시 수영구",
            "use_llm": True,
            "materials": [{"question": "위험지역은?", "answer": "남천동"}],
        },
    )

    assert jobs.get(user["id"], created["job_id"])["status"] == "queued"
    assert jobs.materials(created["job_id"])[0]["answer"] == "남천동"
    assert queue.enqueued[0][0] == created["job_id"]


def test_report_dispatcher_marks_job_failed_when_enqueue_fails():
    from coastal_web.report_queue import ReportDispatcher

    jobs, user = _repository()

    class FailingQueue:
        job_id = None

        def enqueue(self, job_id):
            self.job_id = job_id
            raise ConnectionError("redis unavailable")

    queue = FailingQueue()
    dispatcher = ReportDispatcher(jobs, queue)

    try:
        dispatcher.submit(user["id"], {"region": None, "materials": []})
    except ConnectionError:
        pass
    else:
        raise AssertionError("queue failure should be propagated")

    saved = jobs.get(user["id"], queue.job_id)
    assert saved["status"] == "failed"
    assert saved["errors"] == ["redis unavailable"]


def test_report_dispatcher_cancels_and_retries_owner_job():
    from coastal_web.report_queue import ReportDispatcher

    jobs, user = _repository()

    class FakeQueue:
        def __init__(self):
            self.cancelled = []
            self.enqueued = []

        def enqueue(self, job_id, **options):
            self.enqueued.append(job_id)
            return {"job_id": job_id, "status": "queued"}

        def cancel(self, job_id):
            self.cancelled.append(job_id)
            return True

    queue = FakeQueue()
    dispatcher = ReportDispatcher(
        jobs,
        queue,
    )
    created = dispatcher.submit(user["id"], {"region": None, "materials": []})

    assert dispatcher.cancel(user["id"], created["job_id"]) is True
    assert queue.cancelled == [created["job_id"]]
    jobs.update(
        created["job_id"],
        status="cancelled",
        stage=None,
        progress=0,
        result={},
        errors=[],
    )
    retried = dispatcher.retry(user["id"], created["job_id"])

    assert retried["job_id"] != created["job_id"]
    assert jobs.get(user["id"], retried["job_id"])["status"] == "queued"


def test_report_dispatcher_keeps_running_job_cancel_requested_until_worker_acknowledges():
    from coastal_web.report_queue import ReportDispatcher

    jobs, user = _repository()

    class FakeQueue:
        def cancel(self, _job_id):
            return True

    jobs.create(user["id"], "running-job", region=None, options={}, materials=[])
    jobs.update(
        "running-job",
        status="running",
        stage="visualize",
        progress=3,
        result={},
        errors=[],
    )
    dispatcher = ReportDispatcher(jobs, FakeQueue())

    assert dispatcher.cancel(user["id"], "running-job") is True
    assert jobs.get(user["id"], "running-job")["status"] == "cancel_requested"


def test_report_worker_does_not_lose_cancel_request_during_progress_persist(tmp_path):
    from coastal_web.report_queue import ReportWorker

    jobs, user = _repository()
    jobs.create(user["id"], "race-job", region=None, options={}, materials=[])

    class RacingManager:
        def __init__(self, *, on_update, should_cancel, **_options):
            self.on_update = on_update
            self.should_cancel = should_cancel

        def create(self, _options, owner_id=None, job_id=None):
            return {"job_id": job_id, "status": "queued"}

        def run(self, job_id):
            self.on_update({
                "job_id": job_id,
                "status": "running",
                "stage": None,
                "progress": 0,
                "result": {},
                "errors": [],
            })
            assert jobs.request_cancel(user["id"], job_id) is True
            self.on_update({
                "job_id": job_id,
                "status": "running",
                "stage": "visualize",
                "progress": 3,
                "result": {},
                "errors": [],
            })
            if self.should_cancel(job_id):
                self.on_update({
                    "job_id": job_id,
                    "status": "cancelled",
                    "stage": "visualize",
                    "progress": 3,
                    "result": {},
                    "errors": [],
                })
                return
            self.on_update({
                "job_id": job_id,
                "status": "completed",
                "stage": "convert",
                "progress": 7,
                "result": {},
                "errors": [],
            })

    worker = ReportWorker(
        jobs,
        output_root=tmp_path / "jobs",
        spatial_export_root=tmp_path / "maps",
        manager_factory=RacingManager,
    )
    worker.run("race-job")

    assert jobs.get(user["id"], "race-job")["status"] == "cancelled"


def test_report_dispatcher_persists_api_side_report_edits():
    from coastal_web.report_queue import ReportDispatcher

    jobs, user = _repository()
    jobs.create(user["id"], "job-1", region=None, options={}, materials=[])
    dispatcher = ReportDispatcher(jobs, queue=object())

    dispatcher.persist({
        "job_id": "job-1",
        "status": "completed",
        "stage": "convert",
        "progress": 7,
        "result": {"report_md_path": "/artifacts/report_v2.md", "revision_count": 1},
        "errors": [],
    })

    restored = jobs.get(user["id"], "job-1")
    assert restored["result"]["revision_count"] == 1


def test_report_dispatcher_queues_edit_without_losing_completed_result():
    from coastal_web.report_queue import ReportDispatcher

    jobs, user = _repository()
    jobs.create(user["id"], "job-1", region=None, options={}, materials=[])
    jobs.update(
        "job-1",
        status="completed",
        stage="convert",
        progress=7,
        result={"report_md_path": "/artifacts/report.md"},
        errors=[],
    )

    class FakeQueue:
        def enqueue_edit(self, job_id, operation, payload):
            assert operation == "revision"
            assert payload["section"] == "정책 제언"
            return {
                "job_id": job_id,
                "task_id": f"{job_id}-edit-1",
                "status": "queued",
            }

    dispatcher = ReportDispatcher(jobs, FakeQueue())

    queued = dispatcher.submit_edit(
        user["id"],
        "job-1",
        "revision",
        {"section": "정책 제언", "instruction": "간결하게 수정해줘"},
    )

    assert queued["status"] == "queued"
    saved = jobs.get(user["id"], "job-1")
    assert saved["status"] == "queued"
    assert saved["stage"] == "revision"
    assert saved["result"]["report_md_path"] == "/artifacts/report.md"


def test_report_worker_applies_queued_edit_and_persists_completion(tmp_path):
    from coastal_web.report_queue import ReportWorker

    jobs, user = _repository()
    jobs.create(user["id"], "job-1", region=None, options={}, materials=[])
    jobs.update(
        "job-1",
        status="queued",
        stage="revision",
        progress=7,
        result={"report_md_path": "/artifacts/report.md"},
        errors=[],
    )

    class EditingManager:
        def __init__(self, *, on_update, **_options):
            self.on_update = on_update

        def restore(self, saved, *, materials):
            assert saved["job_id"] == "job-1"
            assert materials == []

        def run_edit(self, job_id, operation, payload):
            assert operation == "revision"
            assert payload["instruction"] == "간결하게 수정해줘"
            self.on_update({
                "job_id": job_id,
                "status": "completed",
                "stage": "revision",
                "progress": 7,
                "result": {
                    "report_md_path": "/artifacts/report_v2.md",
                    "revision_count": 1,
                },
                "errors": [],
            })
            return {"revision": 1}

    worker = ReportWorker(
        jobs,
        output_root=tmp_path / "jobs",
        spatial_export_root=tmp_path / "maps",
        manager_factory=EditingManager,
    )

    worker.run_edit(
        "job-1",
        "revision",
        {"section": "정책 제언", "instruction": "간결하게 수정해줘"},
    )

    saved = jobs.get(user["id"], "job-1")
    assert saved["status"] == "completed"
    assert saved["result"]["revision_count"] == 1
