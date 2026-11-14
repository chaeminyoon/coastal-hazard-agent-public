from __future__ import annotations

import uuid
from pathlib import Path

from .database import create_database_engine
from .repositories import ReportJobRepository
from .services import ReportManager


class ReportWorker:
    def __init__(
        self,
        jobs: ReportJobRepository,
        *,
        output_root: Path | str,
        spatial_export_root: Path | str,
        mcp_output_root: Path | str | None = None,
        manager_factory=ReportManager,
    ):
        self.jobs = jobs
        self.output_root = Path(output_root)
        self.spatial_export_root = Path(spatial_export_root)
        self.mcp_output_root = Path(
            mcp_output_root or self.output_root.parent / "mcp"
        )
        self.manager_factory = manager_factory

    def run(self, job_id: str) -> dict:
        saved = self.jobs.get_any(job_id)
        if saved is None:
            raise KeyError(job_id)
        if saved["status"] in {"cancel_requested", "cancelled"}:
            self.jobs.update(
                job_id,
                status="cancelled",
                stage=saved["stage"],
                progress=saved["progress"],
                result=saved["result"],
                errors=saved["errors"],
            )
            return self.jobs.get_any(job_id)

        def persist(update: dict) -> None:
            self.jobs.update(
                job_id,
                status=update["status"],
                stage=update["stage"],
                progress=update["progress"],
                result=update["result"],
                errors=update["errors"],
                preserve_cancellation=True,
            )

        def should_cancel(_job_id: str) -> bool:
            current = self.jobs.get_any(job_id)
            return current is not None and current["status"] in {
                "cancel_requested",
                "cancelled",
            }

        options = {
            **saved["options"],
            "materials": self.jobs.materials(job_id),
        }
        manager = self.manager_factory(
            output_root=self.output_root,
            spatial_export_root=self.spatial_export_root,
            mcp_output_root=self.mcp_output_root,
            auto_start=False,
            on_update=persist,
            should_cancel=should_cancel,
        )
        manager.create(
            options,
            owner_id=saved["user_id"],
            job_id=job_id,
        )
        manager.run(job_id)
        return self.jobs.get_any(job_id)

    def run_edit(self, job_id: str, operation: str, payload: dict) -> dict:
        saved = self.jobs.get_any(job_id)
        if saved is None:
            raise KeyError(job_id)

        def persist(update: dict) -> None:
            self.jobs.update(
                job_id,
                status=update["status"],
                stage=update["stage"],
                progress=update["progress"],
                result=update["result"],
                errors=update["errors"],
            )

        manager = self.manager_factory(
            output_root=self.output_root,
            spatial_export_root=self.spatial_export_root,
            mcp_output_root=self.mcp_output_root,
            auto_start=False,
            on_update=persist,
        )
        manager.restore(saved, materials=self.jobs.materials(job_id))
        manager.run_edit(job_id, operation, payload)
        return self.jobs.get_any(job_id)


def execute_report_job(job_id: str) -> dict:
    from .config import Settings

    settings = Settings.from_env()
    if not settings.database_url:
        raise RuntimeError("COASTAL_DATABASE_URL 설정이 필요합니다.")
    engine = create_database_engine(settings.database_url)
    try:
        return ReportWorker(
            ReportJobRepository(engine),
            output_root=settings.artifact_root / "jobs",
            spatial_export_root=settings.artifact_root / "spatial_maps",
            mcp_output_root=settings.artifact_root / "mcp",
        ).run(job_id)
    finally:
        engine.dispose()


def execute_report_edit_job(job_id: str, operation: str, payload: dict) -> dict:
    from .config import Settings

    settings = Settings.from_env()
    if not settings.database_url:
        raise RuntimeError("COASTAL_DATABASE_URL 설정이 필요합니다.")
    engine = create_database_engine(settings.database_url)
    try:
        return ReportWorker(
            ReportJobRepository(engine),
            output_root=settings.artifact_root / "jobs",
            spatial_export_root=settings.artifact_root / "spatial_maps",
            mcp_output_root=settings.artifact_root / "mcp",
        ).run_edit(job_id, operation, payload)
    finally:
        engine.dispose()


class ReportQueue:
    def __init__(self, redis_url: str | None = None, *, queue=None):
        if queue is None:
            if not redis_url:
                raise ValueError("Redis URL이 필요합니다.")
            from redis import Redis
            from rq import Queue

            queue = Queue("reports", connection=Redis.from_url(redis_url))
        self.queue = queue

    def enqueue(
        self,
        job_id: str,
    ) -> dict:
        job = self.queue.enqueue(
            execute_report_job,
            job_id,
            job_id=job_id,
            job_timeout="2h",
            result_ttl=86400,
            failure_ttl=604800,
        )
        return {"job_id": job.id, "status": "queued"}

    def enqueue_edit(self, job_id: str, operation: str, payload: dict) -> dict:
        task_id = f"{job_id}-edit-{uuid.uuid4().hex[:8]}"
        job = self.queue.enqueue(
            execute_report_edit_job,
            job_id,
            operation,
            payload,
            job_id=task_id,
            job_timeout="30m",
            result_ttl=86400,
            failure_ttl=604800,
        )
        return {"job_id": job_id, "task_id": job.id, "status": "queued"}

    def cancel(self, job_id: str) -> bool:
        job = self.queue.fetch_job(job_id)
        if job is None:
            return False
        job.cancel()
        return True


class ReportDispatcher:
    def __init__(
        self,
        jobs: ReportJobRepository,
        queue: ReportQueue,
    ):
        self.jobs = jobs
        self.queue = queue

    def submit(self, user_id: str, payload: dict) -> dict:
        job_id = uuid.uuid4().hex[:12]
        options = dict(payload)
        materials = list(options.pop("materials", []))
        self.jobs.create(
            user_id,
            job_id,
            region=options.get("region"),
            options=options,
            materials=materials,
        )
        try:
            return self.queue.enqueue(job_id)
        except Exception as exc:
            self.jobs.update(
                job_id,
                status="failed",
                stage=None,
                progress=0,
                result={},
                errors=[str(exc)],
            )
            raise

    def get(self, user_id: str, job_id: str) -> dict | None:
        return self.jobs.get(user_id, job_id)

    def materials(self, job_id: str) -> list[dict]:
        return self.jobs.materials(job_id)

    def persist(self, job: dict) -> bool:
        return self.jobs.update(
            job["job_id"],
            status=job["status"],
            stage=job["stage"],
            progress=job["progress"],
            result=job["result"],
            errors=job["errors"],
            preserve_cancellation=True,
        )

    def cancel(self, user_id: str, job_id: str) -> bool:
        current = self.jobs.get(user_id, job_id)
        if current is None or current["status"] not in {"queued", "running"}:
            return False
        if not self.jobs.request_cancel(user_id, job_id):
            return False
        if current["status"] == "queued" and self.queue.cancel(job_id):
            latest = self.jobs.get(user_id, job_id)
            self.jobs.update(
                job_id,
                status="cancelled",
                stage=latest["stage"],
                progress=latest["progress"],
                result=latest["result"],
                errors=latest["errors"],
            )
        return True

    def retry(self, user_id: str, job_id: str) -> dict | None:
        previous = self.jobs.get(user_id, job_id)
        if previous is None or previous["status"] not in {"failed", "cancelled"}:
            return None
        return self.submit(
            user_id,
            {
                **previous["options"],
                "materials": self.jobs.materials(job_id),
            },
        )

    def submit_edit(
        self,
        user_id: str,
        job_id: str,
        operation: str,
        payload: dict,
    ) -> dict | None:
        current = self.jobs.get(user_id, job_id)
        if current is None or current["status"] != "completed":
            return None
        self.jobs.update(
            job_id,
            status="queued",
            stage="revision",
            progress=current["progress"],
            result=current["result"],
            errors=current["errors"],
        )
        try:
            return self.queue.enqueue_edit(job_id, operation, payload)
        except Exception:
            self.jobs.update(
                job_id,
                status="completed",
                stage=current["stage"],
                progress=current["progress"],
                result=current["result"],
                errors=current["errors"],
            )
            raise
