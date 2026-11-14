from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from .database import analysis_runs, conversations, report_jobs
from .repositories import ConversationRepository


def _read_list(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def import_json_history(engine: Engine, user_id: str, history_path: Path | str) -> dict:
    history_path = Path(history_path).resolve()
    conversation_path = history_path.with_name("conversations.json")
    repository = ConversationRepository(engine)
    counts = {"conversations": 0, "analysis_runs": 0, "report_jobs": 0}

    for item in _read_list(conversation_path):
        conversation_id = str(item.get("id") or "")
        if not conversation_id or repository.get(user_id, conversation_id) is not None:
            continue
        repository.save(
            user_id,
            conversation_id,
            title=str(item.get("title") or "새 대화"),
            region=item.get("region"),
            messages=item.get("messages") or [],
            analysis_context=item.get("analysis_context") or {},
            materials=item.get("materials") or [],
        )
        with engine.begin() as connection:
            connection.execute(
                update(conversations)
                .where(
                    conversations.c.id == conversation_id,
                    conversations.c.user_id == user_id,
                )
                .values(
                    created_at=_timestamp(item.get("created_at")),
                    updated_at=_timestamp(item.get("updated_at")),
                )
            )
        counts["conversations"] += 1

    for item in _read_list(history_path):
        kind = item.get("kind")
        created_at = _timestamp(item.get("created_at"))
        if kind in {"query", "comparison", "mcp"}:
            analysis_id = str(item.get("id") or uuid.uuid4().hex)
            with engine.begin() as connection:
                exists = connection.scalar(
                    select(analysis_runs.c.id).where(analysis_runs.c.id == analysis_id)
                )
                if exists:
                    continue
                connection.execute(
                    insert(analysis_runs).values(
                        id=analysis_id,
                        user_id=user_id,
                        conversation_id=None,
                        kind=str(kind),
                        question=str(item.get("title") or "이전 분석 이력"),
                        region=item.get("region"),
                        status=str(item.get("status") or "completed"),
                        answer=str(item.get("summary") or ""),
                        grounded=None,
                        query_count=int(item.get("query_count") or 0),
                        created_at=created_at,
                        completed_at=(
                            created_at if item.get("status") == "completed" else None
                        ),
                    )
                )
            counts["analysis_runs"] += 1
        elif kind == "report":
            job_id = str(item.get("job_id") or item.get("id") or uuid.uuid4().hex)
            with engine.begin() as connection:
                exists = connection.scalar(
                    select(report_jobs.c.id).where(report_jobs.c.id == job_id)
                )
                if exists:
                    continue
                status = str(item.get("status") or "completed")
                connection.execute(
                    insert(report_jobs).values(
                        id=job_id,
                        user_id=user_id,
                        conversation_id=None,
                        region=item.get("region"),
                        status=status,
                        stage=None,
                        progress=7 if status == "completed" else 0,
                        options={},
                        result={"summary": str(item.get("summary") or "")},
                        errors=[],
                        created_at=created_at,
                        updated_at=created_at,
                        completed_at=created_at if status == "completed" else None,
                    )
                )
            counts["report_jobs"] += 1

    return counts
