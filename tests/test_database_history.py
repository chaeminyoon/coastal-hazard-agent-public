from coastal_web.database import create_database_engine, metadata
from coastal_web.repositories import UserRepository
from sqlalchemy import func, select


def _service_and_users():
    from coastal_web.database_history import DatabaseHistoryService

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    users = UserRepository(engine)
    first = users.create("first", "hash")
    second = users.create("second", "hash")
    return DatabaseHistoryService(engine), first, second


def test_database_history_is_isolated_by_user():
    service, first, second = _service_and_users()

    service.record(
        user_id=first["id"],
        kind="query",
        title="첫 사용자 질문",
        region="부산광역시 수영구",
        status="completed",
        summary="첫 사용자 답변",
        query_count=2,
    )
    service.record(
        user_id=second["id"],
        kind="comparison",
        title="둘째 사용자 질문",
        region="강원특별자치도 고성군",
        status="completed",
        summary="둘째 사용자 답변",
        query_count=3,
    )

    first_history = service.list(user_id=first["id"])
    second_history = service.list(user_id=second["id"])

    assert [item["title"] for item in first_history] == ["첫 사용자 질문"]
    assert first_history[0]["query_count"] == 2
    assert [item["title"] for item in second_history] == ["둘째 사용자 질문"]
    assert second_history[0]["kind"] == "comparison"


def test_database_conversations_and_reports_are_owner_scoped():
    service, first, second = _service_and_users()
    service.save_conversation(
        "session-1",
        user_id=first["id"],
        title="첫 대화",
        region=None,
        messages=[{"id": "m1", "role": "user", "text": "질문"}],
        analysis_context={},
        materials=[],
    )
    service.record(
        user_id=first["id"],
        kind="report",
        title="보고서 작성",
        region="부산광역시 수영구",
        status="running",
        job_id="job-1",
    )

    assert service.get_conversation("session-1", user_id=first["id"])["title"] == "첫 대화"
    assert service.get_conversation("session-1", user_id=second["id"]) is None
    assert service.update_report(
        "job-1", "completed", "완료", user_id=second["id"]
    ) is False
    assert service.update_report(
        "job-1", "completed", "완료", user_id=first["id"]
    ) is True
    assert service.list(user_id=second["id"]) == []
    assert service.list(user_id=first["id"])[0]["status"] == "completed"


def test_database_history_persists_sql_and_report_materials():
    from coastal_web.database import (
        analysis_runs,
        report_jobs,
        report_materials,
        sql_executions,
    )

    service, first, _ = _service_and_users()
    service.record(
        user_id=first["id"],
        kind="query",
        title="고위험 지역 조회",
        region="부산광역시 수영구",
        status="completed",
        summary="조회 완료",
        query_count=1,
        grounded=True,
        queries=[{
            "sql": "SELECT * FROM grid LIMIT 5",
            "row_count": 5,
            "success": True,
        }],
    )
    service.record(
        user_id=first["id"],
        kind="report",
        title="보고서 작성",
        region="부산광역시 수영구",
        status="running",
        job_id="job-with-material",
        options={"use_llm": True},
        materials=[{"question": "고위험 지역은?", "answer": "남천동"}],
    )

    with service.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(sql_executions)) == 1
        assert connection.scalar(select(func.count()).select_from(report_materials)) == 1
        execution = connection.execute(select(sql_executions)).mappings().one()
        analysis = connection.execute(select(analysis_runs)).mappings().one()
        options = connection.scalar(
            select(report_jobs.c.options).where(report_jobs.c.id == "job-with-material")
        )
    assert execution["row_count"] == 5
    assert analysis["grounded"] is True
    assert options["use_llm"] is True
    assert options["title"] == "보고서 작성"


def test_database_history_saves_and_updates_user_spatial_scenarios():
    service, first, second = _service_and_users()
    geometry = {
        "type": "Polygon",
        "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
    }

    saved = service.save_scenario(
        user_id=first["id"],
        name="수영구 고위험 선택영역",
        region="부산광역시 수영구",
        metric="overall",
        grades=["4", "5"],
        geometry=geometry,
    )
    service.update_scenario_result(
        saved["id"],
        {"stats": {"selected_count": 12}},
        user_id=first["id"],
    )

    assert service.list_scenarios(user_id=second["id"]) == []
    scenarios = service.list_scenarios(user_id=first["id"])
    assert scenarios[0]["name"] == "수영구 고위험 선택영역"
    assert scenarios[0]["grades"] == ["4", "5"]
    assert scenarios[0]["latest_result"]["stats"]["selected_count"] == 12
    assert service.delete_scenario(saved["id"], user_id=second["id"]) is False
    assert service.delete_scenario(saved["id"], user_id=first["id"]) is True
