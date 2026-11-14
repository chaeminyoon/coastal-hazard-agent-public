import importlib
import importlib.util

from sqlalchemy import event


def _database_module():
    spec = importlib.util.find_spec("coastal_web.database")
    assert spec is not None, "서비스 데이터베이스 모듈이 필요합니다."
    return importlib.import_module("coastal_web.database")


def _repository_module():
    spec = importlib.util.find_spec("coastal_web.repositories")
    assert spec is not None, "다중 사용자 저장소 모듈이 필요합니다."
    return importlib.import_module("coastal_web.repositories")


def _engine():
    database = _database_module()
    engine = database.create_database_engine("sqlite+pysqlite:///:memory:")
    database.metadata.create_all(engine)
    return engine


def test_service_schema_contains_multi_user_tables():
    database = _database_module()

    assert set(database.metadata.tables) == {
        "users",
        "user_sessions",
        "conversations",
        "messages",
        "analysis_runs",
        "sql_executions",
        "report_jobs",
        "report_materials",
        "artifacts",
        "provenance_entries",
        "audit_logs",
        "analysis_scenarios",
    }


def test_conversation_repository_isolates_conversations_by_user():
    repositories = _repository_module()
    engine = _engine()
    users = repositories.UserRepository(engine)
    conversations = repositories.ConversationRepository(engine)
    first_user = users.create("first", "hash-1")
    second_user = users.create("second", "hash-2")

    saved = conversations.save(
        first_user["id"],
        "session-1",
        title="수영구 고위험 지역을 알려줘",
        region="부산광역시 수영구",
        messages=[
            {"id": "m1", "role": "user", "kind": "text", "text": "고위험 지역을 알려줘"},
            {"id": "m2", "role": "assistant", "kind": "text", "text": "남천2동입니다."},
        ],
        analysis_context={"region": "부산광역시 수영구", "grades": ["5"]},
        materials=[],
    )

    assert saved["id"] == "session-1"
    restored = conversations.get(first_user["id"], "session-1")
    assert restored["messages"][1]["text"] == "남천2동입니다."
    assert conversations.get(second_user["id"], "session-1") is None
    assert conversations.list(first_user["id"])[0]["summary"] == "남천2동입니다."
    assert conversations.list(second_user["id"]) == []


def test_conversation_repository_only_owner_can_delete():
    repositories = _repository_module()
    engine = _engine()
    users = repositories.UserRepository(engine)
    conversations = repositories.ConversationRepository(engine)
    owner = users.create("owner", "hash-1")
    another = users.create("another", "hash-2")
    conversations.save(
        owner["id"],
        "session-1",
        title="대화",
        region=None,
        messages=[{"id": "m1", "role": "user", "kind": "text", "text": "질문"}],
        analysis_context={},
        materials=[],
    )

    assert conversations.delete(another["id"], "session-1") is False
    assert conversations.get(owner["id"], "session-1") is not None
    assert conversations.delete(owner["id"], "session-1") is True
    assert conversations.get(owner["id"], "session-1") is None


def test_message_ids_can_repeat_in_different_conversations():
    repositories = _repository_module()
    engine = _engine()
    user = repositories.UserRepository(engine).create("user", "hash")
    conversations = repositories.ConversationRepository(engine)

    for conversation_id in ("session-1", "session-2"):
        conversations.save(
            user["id"],
            conversation_id,
            title=conversation_id,
            region=None,
            messages=[{"id": "m1", "role": "user", "kind": "text", "text": conversation_id}],
            analysis_context={},
            materials=[],
        )

    assert conversations.get(user["id"], "session-1")["messages"][0]["text"] == "session-1"
    assert conversations.get(user["id"], "session-2")["messages"][0]["text"] == "session-2"


def test_conversation_repository_locks_user_before_replacing_messages():
    repositories = _repository_module()
    engine = _engine()
    user = repositories.UserRepository(engine).create("serial-user", "hash")
    conversations = repositories.ConversationRepository(engine)
    statements = []

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        conversations.save(
            user["id"],
            "session-serial",
            title="대화 저장",
            region=None,
            messages=[{"id": "m1", "role": "user", "kind": "text", "text": "질문"}],
            analysis_context={},
            materials=[],
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert "FROM users" in statements[0]
    assert "FROM conversations" in statements[1]


def test_report_job_repository_persists_worker_progress():
    repositories = _repository_module()
    engine = _engine()
    user = repositories.UserRepository(engine).create("report-user", "hash")
    jobs = repositories.ReportJobRepository(engine)
    jobs.create(
        user["id"],
        "job-1",
        region="부산광역시 수영구",
        options={"use_llm": True},
        materials=[{"question": "고위험 지역은?", "answer": "남천동"}],
    )

    jobs.update(
        "job-1",
        status="running",
        stage="analyze",
        progress=2,
        result={"stats": {"grid_count": 443}},
        errors=[],
    )
    restored = jobs.get(user["id"], "job-1")

    assert restored["status"] == "running"
    assert restored["stage"] == "analyze"
    assert restored["progress"] == 2
    assert restored["result"]["stats"]["grid_count"] == 443
    assert jobs.materials("job-1") == [{"question": "고위험 지역은?", "answer": "남천동"}]


def test_report_job_cancellation_is_owner_scoped():
    repositories = _repository_module()
    engine = _engine()
    owner = repositories.UserRepository(engine).create("job-owner", "hash")
    another = repositories.UserRepository(engine).create("job-other", "hash")
    jobs = repositories.ReportJobRepository(engine)
    jobs.create(owner["id"], "job-1", region=None, options={}, materials=[])

    assert jobs.request_cancel(another["id"], "job-1") is False
    assert jobs.request_cancel(owner["id"], "job-1") is True
    assert jobs.get(owner["id"], "job-1")["status"] == "cancel_requested"


def test_audit_log_repository_records_actor_resource_and_details():
    repositories = _repository_module()
    engine = _engine()
    user = repositories.UserRepository(engine).create("audit-admin", "hash", "admin")
    audit = repositories.AuditLogRepository(engine)

    created = audit.record(
        user_id=user["id"],
        action="admin.user.create",
        resource_type="user",
        resource_id="new-user-id",
        details={"username": "new-user", "role": "user"},
        ip_address="127.0.0.1",
    )

    assert created["action"] == "admin.user.create"
    assert audit.list(limit=10)[0] == created
