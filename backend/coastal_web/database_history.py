from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from .database import analysis_runs, report_jobs, sql_executions
from .database import report_materials as report_material_records
from .repositories import ConversationRepository, ScenarioRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class DatabaseHistoryService:
    user_scoped = True

    def __init__(self, engine: Engine):
        self.engine = engine
        self.conversations = ConversationRepository(engine)
        self.scenarios = ScenarioRepository(engine)

    def record(
        self,
        *,
        user_id: str,
        kind: str,
        title: str,
        region: str | None,
        status: str,
        summary: str = "",
        query_count: int = 0,
        grounded: bool | None = None,
        job_id: str | None = None,
        queries: list | None = None,
        options: dict | None = None,
        materials: list[dict] | None = None,
    ) -> dict:
        now = _now()
        if kind == "report":
            entry_id = job_id or uuid.uuid4().hex
            with self.engine.begin() as connection:
                connection.execute(
                    insert(report_jobs).values(
                        id=entry_id,
                        user_id=user_id,
                        conversation_id=None,
                        region=region,
                        status=status,
                        stage=None,
                        progress=0,
                        options={**(options or {}), "title": title},
                        result={"summary": summary[:500]},
                        errors=[],
                        created_at=now,
                        updated_at=now,
                        completed_at=now if status == "completed" else None,
                    )
                )
                if materials:
                    connection.execute(
                        insert(report_material_records),
                        [
                            {
                                "id": uuid.uuid4().hex,
                                "report_job_id": entry_id,
                                "position": position,
                                "payload": material,
                            }
                            for position, material in enumerate(materials)
                        ],
                    )
        else:
            entry_id = uuid.uuid4().hex
            with self.engine.begin() as connection:
                connection.execute(
                    insert(analysis_runs).values(
                        id=entry_id,
                        user_id=user_id,
                        conversation_id=None,
                        question=title[:1000],
                        kind=kind,
                        region=region,
                        status=status,
                        answer=summary[:500],
                        grounded=grounded,
                        query_count=int(query_count),
                        created_at=now,
                        completed_at=now if status == "completed" else None,
                    )
                )
                if queries:
                    connection.execute(
                        insert(sql_executions),
                        [
                            {
                                "id": uuid.uuid4().hex,
                                "analysis_run_id": entry_id,
                                "position": position,
                                "sql": (
                                    str(query.get("sql") or query)
                                    if isinstance(query, dict)
                                    else str(query)
                                ),
                                "row_count": (
                                    query.get("row_count")
                                    if isinstance(query, dict)
                                    else None
                                ),
                                "duration_ms": (
                                    query.get("duration_ms")
                                    if isinstance(query, dict)
                                    else None
                                ),
                                "success": (
                                    bool(query.get("success", True))
                                    if isinstance(query, dict)
                                    else True
                                ),
                                "error": (
                                    query.get("error")
                                    if isinstance(query, dict)
                                    else None
                                ),
                                "created_at": now,
                            }
                            for position, query in enumerate(queries)
                        ],
                    )
        return {
            "id": entry_id,
            "kind": kind,
            "title": title,
            "region": region,
            "status": status,
            "summary": summary[:500],
            "query_count": int(query_count),
            "job_id": job_id,
            "created_at": _iso(now),
        }

    def list(self, limit: int = 100, *, user_id: str) -> list[dict]:
        bounded_limit = max(1, min(int(limit), 200))
        with self.engine.connect() as connection:
            analyses = connection.execute(
                select(analysis_runs)
                .where(analysis_runs.c.user_id == user_id)
                .order_by(analysis_runs.c.created_at.desc())
                .limit(bounded_limit)
            ).mappings().all()
            reports = connection.execute(
                select(report_jobs)
                .where(report_jobs.c.user_id == user_id)
                .order_by(report_jobs.c.created_at.desc())
                .limit(bounded_limit)
            ).mappings().all()

        entries = [
            {
                "id": row["id"],
                "kind": row["kind"],
                "title": row["question"],
                "region": row["region"],
                "status": row["status"],
                "summary": row["answer"] or "",
                "query_count": row["query_count"],
                "grounded": row["grounded"],
                "job_id": None,
                "created_at": _iso(row["created_at"]),
            }
            for row in analyses
        ]
        entries.extend(
            {
                "id": row["id"],
                "kind": "report",
                "title": row["options"].get("title") or f"{row['region'] or '전국'} 보고서 작성",
                "region": row["region"],
                "status": row["status"],
                "summary": row["result"].get("summary", ""),
                "query_count": 0,
                "job_id": row["id"],
                "created_at": _iso(row["created_at"]),
            }
            for row in reports
        )
        entries.sort(key=lambda item: item["created_at"] or "", reverse=True)
        return entries[:bounded_limit]

    def update_report(
        self,
        job_id: str,
        status: str,
        summary: str = "",
        *,
        user_id: str,
    ) -> bool:
        now = _now()
        with self.engine.begin() as connection:
            current = connection.execute(
                select(report_jobs.c.result).where(
                    report_jobs.c.id == job_id,
                    report_jobs.c.user_id == user_id,
                )
            ).scalar_one_or_none()
            if current is None:
                return False
            result = dict(current)
            if summary:
                result["summary"] = summary[:500]
            updated = connection.execute(
                update(report_jobs)
                .where(
                    report_jobs.c.id == job_id,
                    report_jobs.c.user_id == user_id,
                )
                .values(
                    status=status,
                    result=result,
                    updated_at=now,
                    completed_at=now if status in {"completed", "failed"} else None,
                )
            )
        return updated.rowcount > 0

    def owns_report(self, job_id: str, *, user_id: str) -> bool:
        with self.engine.connect() as connection:
            owner = connection.scalar(
                select(report_jobs.c.user_id).where(report_jobs.c.id == job_id)
            )
        return owner == user_id

    def save_conversation(self, conversation_id: str, *, user_id: str, **payload) -> dict:
        return self.conversations.save(user_id, conversation_id, **payload)

    def list_conversations(self, limit: int = 100, *, user_id: str) -> list[dict]:
        return self.conversations.list(user_id, limit)

    def get_conversation(self, conversation_id: str, *, user_id: str) -> dict | None:
        return self.conversations.get(user_id, conversation_id)

    def delete_conversation(self, conversation_id: str, *, user_id: str) -> bool:
        return self.conversations.delete(user_id, conversation_id)

    def save_scenario(self, *, user_id: str, **payload) -> dict:
        return self.scenarios.save(user_id, **payload)

    def list_scenarios(self, limit: int = 100, *, user_id: str) -> list[dict]:
        return self.scenarios.list(user_id, limit)

    def get_scenario(self, scenario_id: str, *, user_id: str) -> dict | None:
        return self.scenarios.get(user_id, scenario_id)

    def update_scenario_result(self, scenario_id: str, result: dict, *, user_id: str) -> bool:
        return self.scenarios.update_result(user_id, scenario_id, result)

    def delete_scenario(self, scenario_id: str, *, user_id: str) -> bool:
        return self.scenarios.delete(user_id, scenario_id)
