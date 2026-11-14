from coastal_web.history import HistoryService


def test_history_service_persists_entries_newest_first(tmp_path):
    path = tmp_path / "history.json"
    service = HistoryService(path)

    first = service.record(
        kind="query",
        title="수영구 고위험 지역을 알려줘",
        region="부산광역시 수영구",
        status="completed",
        summary="남천2동의 고위험 비율이 가장 높습니다.",
        query_count=2,
    )
    second = service.record(
        kind="mcp",
        title="지역별 위험도를 시각화해줘",
        region="부산광역시 수영구",
        status="completed",
        summary="막대 차트를 생성했습니다.",
        query_count=0,
    )

    restored = HistoryService(path).list(limit=10)

    assert [entry["id"] for entry in restored] == [second["id"], first["id"]]
    assert restored[0]["kind"] == "mcp"
    assert restored[1]["query_count"] == 2


def test_history_service_updates_report_status_without_duplicate(tmp_path):
    service = HistoryService(tmp_path / "history.json")
    service.record(
        kind="report",
        title="수영구 보고서 작성",
        region="부산광역시 수영구",
        status="running",
        job_id="job-1",
    )
    service.record(
        kind="report_edit",
        title="보고서 내용 수정",
        region="부산광역시 수영구",
        status="completed",
        job_id="job-1",
    )

    service.update_report("job-1", status="completed", summary="보고서 작성 완료")

    entries = service.list()
    assert len(entries) == 2
    report = next(entry for entry in entries if entry["kind"] == "report")
    report_edit = next(entry for entry in entries if entry["kind"] == "report_edit")
    assert report["status"] == "completed"
    assert report["summary"] == "보고서 작성 완료"
    assert report_edit["summary"] == ""


def test_history_service_persists_and_restores_conversation_sessions(tmp_path):
    path = tmp_path / "history.json"
    service = HistoryService(path)
    saved = service.save_conversation(
        "session-1",
        title="수영구 고위험 지역을 알려줘",
        region="부산광역시 수영구",
        messages=[
            {"id": "m1", "role": "user", "kind": "text", "text": "수영구 고위험 지역을 알려줘"},
            {"id": "m2", "role": "assistant", "kind": "text", "text": "남천2동이 가장 높습니다."},
        ],
        analysis_context={"region": "부산광역시 수영구", "grades": ["5"], "comparison_regions": []},
        materials=[],
    )

    restored_service = HistoryService(path)
    summaries = restored_service.list_conversations()
    restored = restored_service.get_conversation("session-1")

    assert saved["id"] == "session-1"
    assert summaries[0]["message_count"] == 2
    assert summaries[0]["summary"] == "남천2동이 가장 높습니다."
    assert restored["messages"][0]["text"] == "수영구 고위험 지역을 알려줘"
    assert restored["analysis_context"]["grades"] == ["5"]


def test_history_service_deletes_one_conversation_session(tmp_path):
    service = HistoryService(tmp_path / "history.json")
    for session_id in ("session-1", "session-2"):
        service.save_conversation(
            session_id,
            title=session_id,
            region="부산광역시 수영구",
            messages=[{"id": session_id, "role": "user", "kind": "text", "text": session_id}],
            analysis_context={"region": "부산광역시 수영구", "grades": [], "comparison_regions": []},
            materials=[],
        )

    assert service.delete_conversation("session-1") is True
    assert service.get_conversation("session-1") is None
    assert service.get_conversation("session-2") is not None
    assert service.delete_conversation("missing") is False
