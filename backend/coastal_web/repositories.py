from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from .database import analysis_scenarios, audit_logs, conversations, report_jobs, report_materials, users
from .database import messages as message_records


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _conversation_summary(items: list[dict]) -> str:
    for message in reversed(items):
        if message.get("role") != "assistant":
            continue
        value = message.get("text")
        if not value and isinstance(message.get("query"), dict):
            value = message["query"].get("answer")
        if not value and isinstance(message.get("comparison"), dict):
            value = message["comparison"].get("answer")
        if value:
            return str(value)[:500]
    return ""


class UserRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, username: str, password_hash: str, role: str = "user") -> dict:
        now = _now()
        record = {
            "id": uuid.uuid4().hex,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            connection.execute(insert(users).values(record))
        return {
            **record,
            "created_at": _iso(record["created_at"]),
            "updated_at": _iso(record["updated_at"]),
        }


class AuditLogRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def record(
        self,
        *,
        user_id: str | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
    ) -> dict:
        record = {
            "id": uuid.uuid4().hex,
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details or {},
            "ip_address": ip_address,
            "created_at": _now(),
        }
        with self.engine.begin() as connection:
            connection.execute(insert(audit_logs).values(record))
        return {**record, "created_at": _iso(record["created_at"])}

    def list(self, *, limit: int = 100) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(audit_logs)
                .order_by(audit_logs.c.created_at.desc())
                .limit(limit)
            ).mappings()
            return [
                {**dict(row), "created_at": _iso(row["created_at"])}
                for row in rows
            ]


class ConversationRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _validate_id(conversation_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", conversation_id):
            raise ValueError("올바르지 않은 대화 세션 ID입니다.")

    def save(
        self,
        user_id: str,
        conversation_id: str,
        *,
        title: str,
        region: str | None,
        messages: list[dict],
        analysis_context: dict,
        materials: list[dict],
    ) -> dict:
        self._validate_id(conversation_id)
        now = _now()
        summary = _conversation_summary(messages)
        with self.engine.begin() as connection:
            connection.execute(
                select(users.c.id)
                .where(users.c.id == user_id)
                .with_for_update()
            ).scalar_one()
            previous = connection.execute(
                select(conversations.c.user_id, conversations.c.created_at).where(
                    conversations.c.id == conversation_id
                )
            ).mappings().first()
            if previous and previous["user_id"] != user_id:
                raise PermissionError("다른 사용자의 대화 세션입니다.")

            values = {
                "user_id": user_id,
                "title": title[:120],
                "region": region,
                "summary": summary,
                "message_count": len(messages[:200]),
                "analysis_context": analysis_context,
                "materials": materials[:10],
                "updated_at": now,
            }
            if previous:
                connection.execute(
                    update(conversations)
                    .where(
                        conversations.c.id == conversation_id,
                        conversations.c.user_id == user_id,
                    )
                    .values(values)
                )
                connection.execute(
                    delete(message_records).where(
                        message_records.c.conversation_id == conversation_id
                    )
                )
                created_at = previous["created_at"]
            else:
                created_at = now
                connection.execute(
                    insert(conversations).values(
                        id=conversation_id,
                        created_at=created_at,
                        **values,
                    )
                )

            message_rows = []
            for position, item in enumerate(messages[:200]):
                message_rows.append(
                    {
                        "id": str(item.get("id") or uuid.uuid4().hex),
                        "conversation_id": conversation_id,
                        "position": position,
                        "role": str(item.get("role") or "user"),
                        "kind": item.get("kind"),
                        "payload": item,
                        "created_at": now,
                    }
                )
            if message_rows:
                connection.execute(insert(message_records), message_rows)

        return {
            "id": conversation_id,
            "title": title[:120],
            "region": region,
            "messages": messages[:200],
            "analysis_context": analysis_context,
            "materials": materials[:10],
            "created_at": _iso(created_at),
            "updated_at": _iso(now),
        }

    def list(self, user_id: str, limit: int = 100) -> list[dict]:
        statement = (
            select(conversations)
            .where(conversations.c.user_id == user_id)
            .order_by(conversations.c.updated_at.desc())
            .limit(max(1, min(int(limit), 200)))
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "region": row["region"],
                "summary": row["summary"],
                "message_count": row["message_count"],
                "created_at": _iso(row["created_at"]),
                "updated_at": _iso(row["updated_at"]),
            }
            for row in rows
        ]

    def get(self, user_id: str, conversation_id: str) -> dict | None:
        self._validate_id(conversation_id)
        with self.engine.connect() as connection:
            conversation = connection.execute(
                select(conversations).where(
                    conversations.c.id == conversation_id,
                    conversations.c.user_id == user_id,
                )
            ).mappings().first()
            if conversation is None:
                return None
            saved_messages = connection.execute(
                select(message_records.c.payload)
                .where(message_records.c.conversation_id == conversation_id)
                .order_by(message_records.c.position)
            ).scalars().all()
        return {
            "id": conversation["id"],
            "title": conversation["title"],
            "region": conversation["region"],
            "messages": list(saved_messages),
            "analysis_context": conversation["analysis_context"],
            "materials": conversation["materials"],
            "created_at": _iso(conversation["created_at"]),
            "updated_at": _iso(conversation["updated_at"]),
        }

    def delete(self, user_id: str, conversation_id: str) -> bool:
        self._validate_id(conversation_id)
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(conversations).where(
                    conversations.c.id == conversation_id,
                    conversations.c.user_id == user_id,
                )
            )
        return result.rowcount > 0


class ScenarioRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _serialize(row) -> dict:
        return {
            **dict(row),
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "last_run_at": _iso(row["last_run_at"]),
        }

    def save(
        self,
        user_id: str,
        *,
        name: str,
        region: str,
        metric: str,
        grades: list[str],
        geometry: dict,
    ) -> dict:
        now = _now()
        record = {
            "id": uuid.uuid4().hex,
            "user_id": user_id,
            "name": name[:120],
            "region": region,
            "metric": metric,
            "grades": grades,
            "geometry": geometry,
            "latest_result": None,
            "created_at": now,
            "updated_at": now,
            "last_run_at": None,
        }
        with self.engine.begin() as connection:
            connection.execute(insert(analysis_scenarios).values(record))
        return self._serialize(record)

    def list(self, user_id: str, limit: int = 100) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(analysis_scenarios)
                .where(analysis_scenarios.c.user_id == user_id)
                .order_by(analysis_scenarios.c.updated_at.desc())
                .limit(max(1, min(int(limit), 200)))
            ).mappings().all()
        return [self._serialize(row) for row in rows]

    def get(self, user_id: str, scenario_id: str) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(analysis_scenarios).where(
                    analysis_scenarios.c.id == scenario_id,
                    analysis_scenarios.c.user_id == user_id,
                )
            ).mappings().first()
        return self._serialize(row) if row else None

    def update_result(self, user_id: str, scenario_id: str, result: dict) -> bool:
        now = _now()
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(analysis_scenarios)
                .where(
                    analysis_scenarios.c.id == scenario_id,
                    analysis_scenarios.c.user_id == user_id,
                )
                .values(latest_result=result, updated_at=now, last_run_at=now)
            )
        return updated.rowcount > 0

    def delete(self, user_id: str, scenario_id: str) -> bool:
        with self.engine.begin() as connection:
            deleted = connection.execute(
                delete(analysis_scenarios).where(
                    analysis_scenarios.c.id == scenario_id,
                    analysis_scenarios.c.user_id == user_id,
                )
            )
        return deleted.rowcount > 0


class ReportJobRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create(
        self,
        user_id: str,
        job_id: str,
        *,
        region: str | None,
        options: dict,
        materials: list[dict],
    ) -> dict:
        now = _now()
        with self.engine.begin() as connection:
            connection.execute(
                insert(report_jobs).values(
                    id=job_id,
                    user_id=user_id,
                    conversation_id=None,
                    region=region,
                    status="queued",
                    stage=None,
                    progress=0,
                    options=options,
                    result={},
                    errors=[],
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
            )
            if materials:
                connection.execute(
                    insert(report_materials),
                    [
                        {
                            "id": uuid.uuid4().hex,
                            "report_job_id": job_id,
                            "position": position,
                            "payload": material,
                        }
                        for position, material in enumerate(materials)
                    ],
                )
        return self.get(user_id, job_id)

    def get(self, user_id: str, job_id: str) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(report_jobs).where(
                    report_jobs.c.id == job_id,
                    report_jobs.c.user_id == user_id,
                )
            ).mappings().first()
        return self._serialize(row) if row else None

    def get_any(self, job_id: str) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(report_jobs).where(report_jobs.c.id == job_id)
            ).mappings().first()
        return self._serialize(row) if row else None

    def list_all(self, limit: int = 100) -> list[dict]:
        bounded_limit = max(1, min(int(limit), 500))
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    report_jobs.c.id,
                    users.c.username,
                    report_jobs.c.region,
                    report_jobs.c.status,
                    report_jobs.c.stage,
                    report_jobs.c.progress,
                    report_jobs.c.created_at,
                    report_jobs.c.updated_at,
                )
                .select_from(report_jobs.join(users, report_jobs.c.user_id == users.c.id))
                .order_by(report_jobs.c.created_at.desc())
                .limit(bounded_limit)
            ).mappings().all()
        return [{
            "job_id": row["id"],
            "username": row["username"],
            "region": row["region"],
            "status": row["status"],
            "stage": row["stage"],
            "progress": row["progress"],
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        } for row in rows]

    def materials(self, job_id: str) -> list[dict]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(report_materials.c.payload)
                    .where(report_materials.c.report_job_id == job_id)
                    .order_by(report_materials.c.position)
                ).scalars()
            )

    def update(
        self,
        job_id: str,
        *,
        status: str,
        stage: str | None,
        progress: int,
        result: dict,
        errors: list,
        preserve_cancellation: bool = False,
    ) -> bool:
        now = _now()
        condition = report_jobs.c.id == job_id
        if preserve_cancellation and status not in {"cancel_requested", "cancelled"}:
            condition = condition & report_jobs.c.status.not_in(
                ["cancel_requested", "cancelled"]
            )
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(report_jobs)
                .where(condition)
                .values(
                    status=status,
                    stage=stage,
                    progress=progress,
                    result=result,
                    errors=errors,
                    updated_at=now,
                    completed_at=(
                        now if status in {"completed", "failed", "cancelled"} else None
                    ),
                )
            )
        return updated.rowcount > 0

    def request_cancel(self, user_id: str, job_id: str) -> bool:
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(report_jobs)
                .where(
                    report_jobs.c.id == job_id,
                    report_jobs.c.user_id == user_id,
                    report_jobs.c.status.in_(["queued", "running"]),
                )
                .values(status="cancel_requested", updated_at=_now())
            )
        return updated.rowcount > 0

    @staticmethod
    def _serialize(row) -> dict:
        return {
            "job_id": row["id"],
            "user_id": row["user_id"],
            "region": row["region"],
            "status": row["status"],
            "stage": row["stage"],
            "progress": row["progress"],
            "options": row["options"],
            "result": row["result"],
            "errors": row["errors"],
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "completed_at": _iso(row["completed_at"]),
        }
