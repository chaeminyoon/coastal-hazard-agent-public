import importlib
import importlib.util
import json

from coastal_web.database import (
    analysis_runs,
    conversations,
    create_database_engine,
    metadata,
    report_jobs,
)
from coastal_web.repositories import ConversationRepository, UserRepository
from sqlalchemy import func, select


def _import_module():
    spec = importlib.util.find_spec("coastal_web.history_import")
    assert spec is not None, "기존 JSON 이력 가져오기 모듈이 필요합니다."
    return importlib.import_module("coastal_web.history_import")


def test_json_history_import_is_idempotent(tmp_path):
    history_path = tmp_path / "history.json"
    conversation_path = tmp_path / "conversations.json"
    history_path.write_text(
        json.dumps(
            [
                {
                    "id": "history-1",
                    "kind": "query",
                    "title": "고위험 지역을 알려줘",
                    "region": "부산광역시 수영구",
                    "status": "completed",
                    "summary": "남천2동입니다.",
                    "query_count": 2,
                    "created_at": "2026-07-20T01:00:00+00:00",
                },
                {
                    "id": "history-2",
                    "kind": "report",
                    "title": "수영구 보고서 작성",
                    "region": "부산광역시 수영구",
                    "status": "completed",
                    "summary": "보고서 작성 완료",
                    "job_id": "job-1",
                    "created_at": "2026-07-20T02:00:00+00:00",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    conversation_path.write_text(
        json.dumps(
            [
                {
                    "id": "session-1",
                    "title": "수영구 고위험 지역",
                    "region": "부산광역시 수영구",
                    "messages": [
                        {"id": "m1", "role": "user", "kind": "text", "text": "질문"},
                        {"id": "m2", "role": "assistant", "kind": "text", "text": "답변"},
                    ],
                    "analysis_context": {"region": "부산광역시 수영구"},
                    "materials": [],
                    "created_at": "2026-07-20T01:00:00+00:00",
                    "updated_at": "2026-07-20T01:10:00+00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    user = UserRepository(engine).create("migration-user", "disabled")
    importer = _import_module()

    first = importer.import_json_history(engine, user["id"], history_path)
    second = importer.import_json_history(engine, user["id"], history_path)

    assert first == {"conversations": 1, "analysis_runs": 1, "report_jobs": 1}
    assert second == {"conversations": 0, "analysis_runs": 0, "report_jobs": 0}
    restored = ConversationRepository(engine).get(user["id"], "session-1")
    assert restored["created_at"] == "2026-07-20T01:00:00+00:00"
    assert restored["updated_at"] == "2026-07-20T01:10:00+00:00"
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(conversations)) == 1
        assert connection.scalar(select(func.count()).select_from(analysis_runs)) == 1
        assert connection.scalar(select(func.count()).select_from(report_jobs)) == 1
