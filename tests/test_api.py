import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT / "backend"))

try:
    API_SPEC = importlib.util.find_spec("coastal_web.api")
except ModuleNotFoundError:
    API_SPEC = None
create_app = None
if API_SPEC is not None:
    from coastal_web.api import create_app  # noqa: E402


def test_api_module_exists():
    assert API_SPEC is not None


def test_query_stream_emits_status_then_grounded_result():
    client = _client()

    with client.stream(
        "POST",
        "/api/queries/stream",
        json={
            "question": "수영구 고위험 지역을 알려줘",
            "region": "부산광역시 수영구",
            "scope": "selected_region",
        },
    ) as response:
        lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [__import__("json").loads(line) for line in lines]
    assert events[0] == {
        "type": "status",
        "message": "DuckDB에서 근거 데이터를 조회하고 있습니다.",
    }
    assert events[-1]["type"] == "result"
    assert events[-1]["data"]["grounded"] is True
    assert events[-1]["data"]["answer"].startswith("남천2동")


def test_spatial_selection_comparison_endpoint_returns_a_b_difference():
    response = _client().post(
        "/api/spatial/selections/compare",
        json={
            "region": "부산광역시 수영구",
            "metric": "overall",
            "grades": ["4", "5"],
            "geometry_a": {"type": "Polygon", "coordinates": []},
            "geometry_b": {"type": "Polygon", "coordinates": []},
        },
    )

    assert response.status_code == 200
    assert response.json()["area_a"]["stats"]["selected_count"] == 2
    assert response.json()["area_b"]["stats"]["selected_count"] == 3
    assert response.json()["difference"]["high_risk_pct_point"] == 10.0


@pytest.mark.parametrize(
    ("path", "payload", "operation"),
    [
        (
            "/api/spatial/filter",
            {"region": "부산광역시 수영구", "question": "강풍 4·5등급 격자를 찾아줘"},
            "filter",
        ),
        (
            "/api/spatial/neighborhood",
            {
                "region": "부산광역시 수영구", "ftr_id": "A", "distance_m": 500,
                "metric": "overall", "grades": ["4", "5"],
            },
            "buffer",
        ),
        (
            "/api/spatial/hotspots",
            {
                "region": "부산광역시 수영구", "metric": "overall",
                "grades": ["4", "5"], "min_cluster_size": 2,
            },
            "hotspot",
        ),
        (
            "/api/spatial/query-scope",
            {"region": "부산광역시 수영구", "queries": ["SELECT * FROM grid"]},
            "query_scope",
        ),
    ],
)
def test_spatial_operation_endpoints_return_grounded_layers(path, payload, operation):
    response = _client().post(path, json=payload)

    assert response.status_code == 200
    assert response.json()["operation"] == operation
    assert response.json()["feature_collection"]["type"] == "FeatureCollection"


def test_clicked_feature_explanation_endpoint_returns_one_grid_analysis():
    response = _client().get(
        "/api/spatial/features/A/explanation",
        params={"region": "부산광역시 수영구", "metric": "overall"},
    )

    assert response.status_code == 200
    assert response.json()["selected_ftr_ids"] == ["A"]


class FakeQueryService:
    def regions(self):
        return [
            {"name": "부산광역시", "districts": ["수영구", "해운대구"]},
            {"name": "전라남도", "districts": ["여수시"]},
        ]

    def ask(
        self,
        question,
        region=None,
        scope="selected_region",
        history=None,
        analysis_context=None,
    ):
        return {
            "question": question,
            "region": region,
            "history": history,
            "analysis_context": analysis_context,
            "answer": "남천2동의 고위험 비율은 21.4%다.",
            "queries": ["SELECT 21.4 AS high_pct"],
            "results": [
                {"columns": ["지역", "고위험비율"], "rows": [["남천2동", 21.4]]}
            ],
            "grounded": True,
        }

    def compare(self, regions):
        return {
            "regions": regions,
            "summary": [{
                "region": regions[0], "grid_count": 443, "avg_grade": 3.12,
                "high_risk_count": 56, "high_risk_pct": 12.6,
            }],
            "distribution": {regions[0]: [{"grade": "5", "count": 13, "pct": 2.9}]},
            "queries": ["SELECT comparison"],
            "results": [],
            "answer": "수영구의 고위험 비율이 더 높습니다.",
            "grounded": True,
        }


class FakeReportManager:
    def create(self, options, owner_id=None):
        assert options["region"] == "부산광역시 수영구"
        return {"job_id": "job-1", "status": "queued"}

    def get(self, job_id):
        if job_id == "job-complete":
            return {
                "job_id": job_id,
                "status": "completed",
                "stage": "convert",
                "progress": 7,
                "result": {},
                "errors": [],
            }
        if job_id != "job-1":
            return None
        return {
            "job_id": job_id,
            "status": "running",
            "stage": "analyze",
            "progress": 2,
            "result": {},
            "errors": [],
        }

    def events(self, job_id):
        if job_id != "job-complete":
            return []
        return [
            {"index": 0, "type": "stage_completed", "stage": "analyze", "data": {}},
            {"index": 1, "type": "job_completed", "stage": "completed", "data": {}},
        ]

    def revise(self, job_id, section, instruction):
        if job_id != "job-complete":
            raise KeyError(job_id)
        return {"revision": 1, "section": section, "instruction": instruction}

    def save_content(self, job_id, markdown):
        if job_id != "job-complete":
            raise KeyError(job_id)
        return {
            "revision": 1,
            "mode": "direct_edit",
            "report_md_path": "report_v2.md",
            "markdown": markdown,
        }

    def provenance(self, job_id, evidence_id=None):
        if job_id != "job-complete":
            raise KeyError(job_id)
        item = {
            "id": "s1",
            "sentence": "평가 대상 격자는 총 443개이다.",
            "grounded": True,
            "stats": [{"path": "데이터개요.총 격자 수", "value": 443}],
            "gpkg_fields": ["FTR_IDN"],
            "queries": [],
        }
        return item if evidence_id else [item]


class FakeSpatialService:
    @staticmethod
    def _operation(operation):
        return {
            "operation_id": f"{operation}-1",
            "operation": operation,
            "name": operation,
            "region": "부산광역시 수영구",
            "conditions": [],
            "stats": {"feature_count": 1},
            "summary": f"{operation} 공간분석",
            "feature_collection": {"type": "FeatureCollection", "features": []},
            "evidence": {"source": "GPKG", "queries": []},
            "report_material": {
                "question": operation, "answer": operation,
                "region": "부산광역시 수영구", "grounded": True,
                "queries": [], "results": [],
            },
        }

    def filter_from_question(self, region, question):
        return self._operation("filter")

    def analyze_neighborhood(self, region, ftr_id, distance_m, metric, grades):
        return self._operation("adjacent" if distance_m <= 0 else "buffer")

    def analyze_hotspots(self, region, metric, grades, min_cluster_size):
        return self._operation("hotspot")

    def scope_from_queries(self, region, queries):
        return self._operation("query_scope")

    def analyze_feature(self, region, ftr_id, metric):
        result = self.analyze_selection(region, {"type": "Polygon", "coordinates": []}, [], metric)
        result["selected_ftr_ids"] = [ftr_id]
        return result

    def metadata(self, region):
        return {
            "id": "risk_grid",
            "name": "연안재해 위험 격자",
            "feature_count": 443,
            "geometry_type": "Polygon",
            "source_crs": "EPSG:5179",
            "grade_counts": {"4": 32, "5": 11},
            "metrics": [{
                "id": "overall", "label": "종합 위험", "group": "종합",
                "grade_column": "위험성지수_등급", "grade_counts": {"4": 32, "5": 11},
            }],
        }

    def features(self, region, grades=None, limit=2000, focus_names=None, metric="overall"):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
                    },
                    "properties": {"FTR_IDN": "G1", "위험성지수_등급": "5"},
                }
            ],
            "metadata": {"count": 1, "truncated": False},
        }

    def analyze_selection(self, region, geometry, grades=None, metric="overall"):
        return {
            "selection_id": "selection-1",
            "region": region,
            "grades": grades or [],
            "selected_ftr_ids": ["G1", "G2"],
            "metric": {"id": metric, "label": "종합 위험", "grade_column": "위험성지수_등급"},
            "geometry": geometry,
            "stats": {
                "selected_count": 2, "average_grade": 4.0,
                "high_risk_count": 1, "high_risk_pct": 50.0,
                "grade_counts": {"3": 1, "5": 1},
            },
            "overlaps": [],
            "feature_collection": {"type": "FeatureCollection", "features": []},
            "summary": "선택 영역 격자 2개 중 고위험 격자는 1개(50.0%)입니다.",
            "report_material": {
                "question": "사용자 선택 영역 공간 중첩 분석",
                "answer": "선택 영역 격자 2개 중 고위험 격자는 1개(50.0%)입니다.",
                "region": region,
                "grounded": True,
                "queries": ["GPKG ST_Intersects"],
                "results": [{"columns": ["지표", "값", "단위"], "rows": [["격자 수", 2, "개"]]}],
            },
        }

    def compare_selections(
        self,
        region,
        geometry_a,
        geometry_b,
        grades=None,
        metric="overall",
    ):
        return {
            "region": region,
            "metric": {"id": metric, "label": "종합 위험"},
            "grades": grades or [],
            "area_a": {"geometry": geometry_a, "stats": {"selected_count": 2}},
            "area_b": {"geometry": geometry_b, "stats": {"selected_count": 3}},
            "difference": {"average_grade": 0.5, "high_risk_pct_point": 10.0},
            "summary": "B 영역의 고위험 비율이 A 영역보다 10.0%p 높습니다.",
        }


class FakeMcpAnalysisService:
    def __init__(self, asset_path=None):
        self.request = None
        self.asset_path = asset_path

    def analyze(self, question, columns, rows, chart_spec=None, owner_id=None):
        self.request = {
            "question": question,
            "columns": columns,
            "rows": rows,
            "chart_spec": chart_spec,
            "owner_id": owner_id,
        }
        return {
            "analysis_id": "analysis-1",
            "chart": "bar",
            "columns": columns,
            "reason": "지역별 값을 비교하기 적합합니다.",
            "chart_url": "/api/mcp/analyses/analysis-1/assets/chart.png",
            "tool_calls": ["recommend_visualizations", "plot_auto"],
            "tools_available": 60,
        }

    def asset(self, analysis_id, name, owner_id=None):
        if analysis_id == "analysis-1" and name == "chart.png":
            return self.asset_path
        return None

    def readiness_checks(self):
        return {"mcp_output_root": True, "mcp_runtime": True}


class FakeHistoryService:
    def __init__(self):
        self.entries = []
        self.updated = []
        self.conversations = {}
        self.scenarios = {}

    def record(self, **entry):
        saved = {"id": f"history-{len(self.entries) + 1}", **entry}
        self.entries.insert(0, saved)
        return saved

    def list(self, limit=100):
        return self.entries[:limit]

    def update_report(self, job_id, status, summary=""):
        self.updated.append({"job_id": job_id, "status": status, "summary": summary})

    def save_conversation(self, conversation_id, **payload):
        saved = {
            "id": conversation_id,
            **payload,
            "created_at": "2026-07-14T10:00:00+00:00",
            "updated_at": "2026-07-14T10:01:00+00:00",
        }
        self.conversations[conversation_id] = saved
        return saved

    def list_conversations(self, limit=100):
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "region": item["region"],
                "summary": item["messages"][-1].get("text", ""),
                "message_count": len(item["messages"]),
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
            for item in self.conversations.values()
        ][:limit]

    def get_conversation(self, conversation_id):
        return self.conversations.get(conversation_id)

    def delete_conversation(self, conversation_id):
        return self.conversations.pop(conversation_id, None) is not None

    def save_scenario(self, **payload):
        scenario_id = f"scenario-{len(self.scenarios) + 1}"
        saved = {"id": scenario_id, "latest_result": None, **payload}
        self.scenarios[scenario_id] = saved
        return saved

    def list_scenarios(self, limit=100):
        return list(self.scenarios.values())[:limit]

    def get_scenario(self, scenario_id):
        return self.scenarios.get(scenario_id)

    def update_scenario_result(self, scenario_id, result):
        if scenario_id not in self.scenarios:
            return False
        self.scenarios[scenario_id]["latest_result"] = result
        return True

    def delete_scenario(self, scenario_id):
        return self.scenarios.pop(scenario_id, None) is not None


def _client(
    report_manager=None,
    spatial_service=None,
    mcp_service=None,
    history_service=None,
    settings=None,
    auth_service=None,
    report_dispatcher=None,
    query_service=None,
):
    options = {}
    if settings is not None:
        options["settings"] = settings
    return TestClient(
        create_app(
            query_service=query_service or FakeQueryService(),
            report_manager=report_manager or FakeReportManager(),
            spatial_service=spatial_service or FakeSpatialService(),
            mcp_service=mcp_service or FakeMcpAnalysisService(),
            history_service=history_service or FakeHistoryService(),
            auth_service=auth_service,
            report_dispatcher=report_dispatcher,
            **options,
        )
    )


class FakeSettings:
    allowed_origins = ("https://coastal.example.com",)
    environment = "development"

    def __init__(self, checks):
        self._checks = checks

    def readiness_checks(self):
        return self._checks


def test_live_health_endpoint_reports_running_process():
    response = _client(
        settings=FakeSettings({"agent_root": True, "artifact_root": True})
    ).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metric_definition_endpoints_explain_and_resolve_ambiguous_ratio():
    client = _client()

    definitions = client.get("/api/metrics/definitions")
    resolved = client.post(
        "/api/metrics/resolve",
        json={"question": "고위험 비율이 가장 높은 읍면동을 알려줘"},
    )

    assert definitions.status_code == 200
    assert definitions.json()[0]["numerator"]
    assert definitions.json()[0]["denominator"]
    assert resolved.status_code == 200
    assert resolved.json()["ambiguous"] is True
    assert len(resolved.json()["choices"]) == 2


def test_data_quality_endpoint_reports_current_schema_readiness():
    class QualityQueryService(FakeQueryService):
        def data_quality(self, region=None):
            return {
                "region": region,
                "row_count": 443,
                "columns": [],
                "capabilities": {
                    "time_series": {"supported": False, "reason": "시간 컬럼이 없습니다."},
                },
            }

    response = _client(query_service=QualityQueryService()).get(
        "/api/data-quality",
        params={"region": "부산광역시 수영구"},
    )

    assert response.status_code == 200
    assert response.json()["row_count"] == 443
    assert response.json()["capabilities"]["time_series"]["supported"] is False


def test_ready_health_endpoint_rejects_missing_dependency():
    response = _client(
        settings=FakeSettings({"agent_root": False, "artifact_root": True})
    ).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "agent_root": False,
            "artifact_root": True,
            "mcp_output_root": True,
            "mcp_runtime": True,
        },
    }


def test_runtime_readiness_includes_database_and_redis(monkeypatch):
    from coastal_web.api import _runtime_readiness

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            return None

    class Engine:
        def connect(self):
            return Connection()

    class RedisConnection:
        def ping(self):
            return True

    from redis import Redis

    monkeypatch.setattr(Redis, "from_url", lambda *_args, **_kwargs: RedisConnection())
    settings = FakeSettings({"agent_root": True, "artifact_root": True})
    settings.redis_url = "redis://redis:6379/0"

    assert _runtime_readiness(settings, Engine()) == {
        "agent_root": True,
        "artifact_root": True,
        "database": True,
        "redis": True,
    }


def test_runtime_readiness_includes_mcp_service_checks():
    from coastal_web.api import _runtime_readiness

    settings = FakeSettings({"agent_root": True, "artifact_root": True})

    assert _runtime_readiness(
        settings,
        mcp_service=FakeMcpAnalysisService(),
    ) == {
        "agent_root": True,
        "artifact_root": True,
        "mcp_output_root": True,
        "mcp_runtime": True,
    }


def test_protected_api_requires_login_and_csrf_for_changes():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    auth.create_user("coastal-user", "correct-password")
    client = _client(auth_service=auth)

    assert client.get("/api/regions").status_code == 401
    login = client.post(
        "/api/auth/login",
        json={"username": "coastal-user", "password": "correct-password"},
    )
    assert login.status_code == 200
    csrf_token = login.json()["csrf_token"]
    assert login.json()["user"]["username"] == "coastal-user"
    assert client.get("/api/auth/me").status_code == 200
    protected = client.get("/api/regions")
    assert protected.status_code == 200
    assert protected.headers["X-CSRF-Token"] == csrf_token
    assert "coastal-user" in protected.headers["X-Auth-User"]

    payload = {
        "question": "고위험 지역을 알려줘",
        "region": "부산광역시 수영구",
    }
    assert client.post("/api/queries", json=payload).status_code == 403
    assert client.post(
        "/api/queries",
        json=payload,
        headers={"X-CSRF-Token": csrf_token},
    ).status_code == 200
    assert client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    ).status_code == 200
    assert client.get("/api/regions").status_code == 401


def test_authenticated_user_can_change_password_and_manage_sessions():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    auth.create_user("coastal-user", "current-password")
    client = _client(auth_service=auth)
    login = client.post(
        "/api/auth/login",
        json={"username": "coastal-user", "password": "current-password"},
    )
    csrf = login.json()["csrf_token"]

    sessions = client.get("/api/auth/sessions")
    assert sessions.status_code == 200
    assert sessions.json()[0]["current"] is True
    changed = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "current-password",
            "new_password": "updated-password",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert changed.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert _client(auth_service=auth).post(
        "/api/auth/login",
        json={"username": "coastal-user", "password": "updated-password"},
    ).status_code == 200


def test_admin_can_reset_user_password_and_review_report_jobs():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata
    from coastal_web.repositories import ReportJobRepository

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    auth.create_user("admin-user", "admin-password", role="admin")
    user = auth.create_user("regular-user", "regular-password")
    jobs = ReportJobRepository(engine)
    jobs.create(
        user["id"],
        "job-admin-list",
        region="부산광역시 수영구",
        options={"make_hwpx": True},
        materials=[],
    )

    class Dispatcher:
        def __init__(self):
            self.jobs = jobs

    client = _client(auth_service=auth, report_dispatcher=Dispatcher())
    login = client.post(
        "/api/auth/login",
        json={"username": "admin-user", "password": "admin-password"},
    )
    csrf = login.json()["csrf_token"]
    reset = client.post(
        f"/api/admin/users/{user['id']}/reset-password",
        json={"new_password": "reset-password"},
        headers={"X-CSRF-Token": csrf},
    )
    report_jobs = client.get("/api/admin/report-jobs")

    assert reset.status_code == 200
    assert report_jobs.status_code == 200
    assert report_jobs.json()[0] == {
        "job_id": "job-admin-list",
        "username": "regular-user",
        "region": "부산광역시 수영구",
        "status": "queued",
        "stage": None,
        "progress": 0,
        "created_at": report_jobs.json()[0]["created_at"],
        "updated_at": report_jobs.json()[0]["updated_at"],
    }
    assert _client(auth_service=auth).post(
        "/api/auth/login",
        json={"username": "regular-user", "password": "reset-password"},
    ).status_code == 200


def test_database_settings_enable_authentication_automatically(tmp_path):
    from coastal_web.config import Settings
    from coastal_web.database import create_database_engine, metadata

    database_url = f"sqlite+pysqlite:///{(tmp_path / 'service.db').as_posix()}"
    metadata.create_all(create_database_engine(database_url))
    settings = Settings(
        environment="development",
        agent_root=tmp_path,
        artifact_root=tmp_path,
        database_url=database_url,
        redis_url=None,
        session_secret="test-secret",
        allowed_origins=("http://localhost:5173",),
    )

    app = create_app(
        query_service=FakeQueryService(),
        report_manager=FakeReportManager(),
        spatial_service=FakeSpatialService(),
        mcp_service=FakeMcpAnalysisService(),
        history_service=FakeHistoryService(),
        settings=settings,
    )

    assert app.state.auth_service is not None


def test_only_admin_can_create_and_disable_users():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    auth.create_user("admin-user", "admin-password", role="admin")
    auth.create_user("regular-user", "regular-password", role="user")
    admin_client = _client(auth_service=auth)
    admin_login = admin_client.post(
        "/api/auth/login",
        json={"username": "admin-user", "password": "admin-password"},
    )
    admin_csrf = admin_login.json()["csrf_token"]

    created = admin_client.post(
        "/api/admin/users",
        json={"username": "new-user", "password": "new-password", "role": "user"},
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]
    assert any(
        item["username"] == "new-user"
        for item in admin_client.get("/api/admin/users").json()
    )
    disabled = admin_client.patch(
        f"/api/admin/users/{user_id}",
        json={"is_active": False},
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    disabled_client = _client(auth_service=auth)
    assert disabled_client.post(
        "/api/auth/login",
        json={"username": "new-user", "password": "new-password"},
    ).status_code == 401

    regular_client = _client(auth_service=auth)
    regular_login = regular_client.post(
        "/api/auth/login",
        json={"username": "regular-user", "password": "regular-password"},
    )
    regular_csrf = regular_login.json()["csrf_token"]
    assert regular_client.post(
        "/api/admin/users",
        json={"username": "forbidden", "password": "password", "role": "user"},
        headers={"X-CSRF-Token": regular_csrf},
    ).status_code == 403


def test_admin_can_review_user_management_audit_log():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    auth.create_user("audit-admin", "audit-password", role="admin")
    client = _client(auth_service=auth)
    login = client.post(
        "/api/auth/login",
        json={"username": "audit-admin", "password": "audit-password"},
    )
    csrf = login.json()["csrf_token"]

    created = client.post(
        "/api/admin/users",
        json={"username": "audited-user", "password": "audited-password", "role": "user"},
        headers={"X-CSRF-Token": csrf},
    )
    logs = client.get("/api/admin/audit-logs")

    assert created.status_code == 201
    assert logs.status_code == 200
    assert any(
        item["action"] == "admin.user.create"
        and item["resource_id"] == created.json()["id"]
        and item["details"] == {"username": "audited-user", "role": "user"}
        for item in logs.json()
    )


def test_authenticated_conversation_api_is_scoped_to_logged_in_user():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata
    from coastal_web.database_history import DatabaseHistoryService

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    auth.create_user("first-user", "first-password")
    auth.create_user("second-user", "second-password")
    history = DatabaseHistoryService(engine)

    first_client = _client(auth_service=auth, history_service=history)
    first_login = first_client.post(
        "/api/auth/login",
        json={"username": "first-user", "password": "first-password"},
    )
    first_csrf = first_login.json()["csrf_token"]
    payload = {
        "title": "첫 사용자 대화",
        "region": "부산광역시 수영구",
        "messages": [{"id": "m1", "role": "user", "kind": "text", "text": "질문"}],
        "analysis_context": {"region": "부산광역시 수영구", "grades": [], "comparison_regions": []},
        "materials": [],
    }
    assert first_client.put(
        "/api/conversations/first-session",
        json=payload,
        headers={"X-CSRF-Token": first_csrf},
    ).status_code == 200

    second_client = _client(auth_service=auth, history_service=history)
    second_login = second_client.post(
        "/api/auth/login",
        json={"username": "second-user", "password": "second-password"},
    )

    assert second_login.status_code == 200
    assert second_client.get("/api/conversations").json() == []
    assert second_client.get("/api/conversations/first-session").status_code == 404
    assert first_client.get("/api/conversations").json()[0]["title"] == "첫 사용자 대화"


def test_authenticated_report_status_and_history_are_scoped_to_owner():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata
    from coastal_web.database_history import DatabaseHistoryService

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    auth.create_user("report-owner", "owner-password")
    auth.create_user("other-user", "other-password")
    history = DatabaseHistoryService(engine)

    owner = _client(auth_service=auth, history_service=history)
    owner_login = owner.post(
        "/api/auth/login",
        json={"username": "report-owner", "password": "owner-password"},
    )
    created = owner.post(
        "/api/reports",
        json={"region": "부산광역시 수영구"},
        headers={"X-CSRF-Token": owner_login.json()["csrf_token"]},
    )
    assert created.status_code == 202

    other = _client(auth_service=auth, history_service=history)
    assert other.post(
        "/api/auth/login",
        json={"username": "other-user", "password": "other-password"},
    ).status_code == 200

    assert other.get("/api/reports/job-1").status_code == 404
    assert other.get("/api/history").json() == []
    assert owner.get("/api/history").json()[0]["job_id"] == "job-1"


def test_report_dispatcher_handles_create_status_cancel_and_retry():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    created_user = auth.create_user("queue-user", "queue-password")

    class FakeDispatcher:
        def __init__(self):
            self.submitted = []

        def submit(self, user_id, payload):
            self.submitted.append((user_id, payload))
            return {"job_id": "queue-job", "status": "queued"}

        def get(self, user_id, job_id):
            if user_id != created_user["id"] or job_id != "queue-job":
                return None
            return {
                "job_id": job_id,
                "status": "running",
                "stage": "analyze",
                "progress": 2,
                "result": {},
                "errors": [],
            }

        def cancel(self, user_id, job_id):
            return user_id == created_user["id"] and job_id == "queue-job"

        def retry(self, user_id, job_id):
            if user_id != created_user["id"] or job_id != "queue-job":
                return None
            return {"job_id": "retry-job", "status": "queued"}

    dispatcher = FakeDispatcher()
    client = _client(auth_service=auth, report_dispatcher=dispatcher)
    login = client.post(
        "/api/auth/login",
        json={"username": "queue-user", "password": "queue-password"},
    )
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}

    created = client.post(
        "/api/reports",
        json={"region": "부산광역시 수영구"},
        headers=headers,
    )

    assert created.status_code == 202
    assert dispatcher.submitted[0][0] == created_user["id"]
    assert client.get("/api/reports/queue-job").json()["stage"] == "analyze"
    assert client.post("/api/reports/queue-job/cancel", headers=headers).status_code == 200
    retried = client.post("/api/reports/queue-job/retry", headers=headers)
    assert retried.json()["job_id"] == "retry-job"


def test_queued_report_events_stream_persisted_terminal_status():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    user = auth.create_user("event-user", "event-password")

    class CompletedDispatcher:
        def get(self, user_id, job_id):
            if user_id != user["id"] or job_id != "done-job":
                return None
            return {
                "job_id": job_id,
                "status": "completed",
                "stage": "convert",
                "progress": 7,
                "result": {},
                "errors": [],
            }

    client = _client(auth_service=auth, report_dispatcher=CompletedDispatcher())
    login = client.post(
        "/api/auth/login",
        json={"username": "event-user", "password": "event-password"},
    )
    assert login.status_code == 200

    events = client.get("/api/reports/done-job/events")

    assert events.status_code == 200
    assert "event: job_completed" in events.text
    assert '"status": "completed"' in events.text


def test_queued_report_preview_restores_worker_result(tmp_path):
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata
    from coastal_web.services import ReportManager

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    user = auth.create_user("preview-user", "preview-password")
    report_dir = tmp_path / user["id"] / "job-1" / "reports"
    report_dir.mkdir(parents=True)
    report = report_dir / "report.md"
    report.write_text("# 큐 보고서", encoding="utf-8")

    class CompletedDispatcher:
        def get(self, user_id, job_id):
            if user_id != user["id"] or job_id != "job-1":
                return None
            return {
                "job_id": job_id,
                "user_id": user_id,
                "status": "completed",
                "stage": "convert",
                "progress": 7,
                "options": {"region": "부산광역시 수영구"},
                "result": {"report_md_path": str(report)},
                "errors": [],
            }

        def materials(self, job_id):
            return []

    manager = ReportManager(graph_factory=lambda: None, output_root=tmp_path, auto_start=False)
    client = _client(
        report_manager=manager,
        auth_service=auth,
        report_dispatcher=CompletedDispatcher(),
    )
    assert client.post(
        "/api/auth/login",
        json={"username": "preview-user", "password": "preview-password"},
    ).status_code == 200

    preview = client.get("/api/reports/job-1/preview")

    assert preview.status_code == 200
    assert preview.json()["markdown"] == "# 큐 보고서"


def test_queued_report_preview_refreshes_stale_api_state(tmp_path):
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata
    from coastal_web.services import ReportManager

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    user = auth.create_user("stale-preview-user", "preview-password")
    report_dir = tmp_path / user["id"] / "job-1" / "reports"
    report_dir.mkdir(parents=True)
    report = report_dir / "report.md"
    report.write_text("# 완료된 큐 보고서", encoding="utf-8")

    class CompletedDispatcher:
        def get(self, user_id, job_id):
            if user_id != user["id"] or job_id != "job-1":
                return None
            return {
                "job_id": job_id,
                "user_id": user_id,
                "status": "completed",
                "stage": "convert",
                "progress": 7,
                "options": {"region": "부산광역시 수영구"},
                "result": {"report_md_path": str(report)},
                "errors": [],
            }

        def materials(self, job_id):
            return []

    manager = ReportManager(graph_factory=lambda: None, output_root=tmp_path, auto_start=False)
    manager.create(
        {"region": "부산광역시 수영구"},
        owner_id=user["id"],
        job_id="job-1",
    )
    client = _client(
        report_manager=manager,
        auth_service=auth,
        report_dispatcher=CompletedDispatcher(),
    )
    assert client.post(
        "/api/auth/login",
        json={"username": "stale-preview-user", "password": "preview-password"},
    ).status_code == 200

    preview = client.get("/api/reports/job-1/preview")

    assert preview.status_code == 200
    assert preview.json()["markdown"] == "# 완료된 큐 보고서"


@pytest.mark.skipif(API_SPEC is None, reason="API module not implemented yet")
def test_regions_endpoint_returns_hierarchy():
    response = _client().get("/api/regions")

    assert response.status_code == 200
    assert response.json()[0] == {
        "name": "부산광역시",
        "districts": ["수영구", "해운대구"],
    }


@pytest.mark.skipif(API_SPEC is None, reason="API module not implemented yet")
def test_query_endpoint_returns_grounded_answer_and_result_table():
    response = _client().post(
        "/api/queries",
        json={
            "region": "부산광역시 수영구",
            "scope": "selected_region",
            "question": "고위험 비율이 가장 높은 읍면동은?",
            "history": [
                {"role": "user", "content": "4·5등급 현황을 알려줘"},
                {"role": "assistant", "content": "고위험 격자를 조회했습니다."},
            ],
            "analysis_context": {
                "region": "부산광역시 수영구",
                "grades": ["5"],
                "comparison_regions": ["부산광역시 해운대구"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["results"][0]["rows"] == [["남천2동", 21.4]]
    assert body["queries"] == ["SELECT 21.4 AS high_pct"]
    assert body["history"][0]["content"] == "4·5등급 현황을 알려줘"
    assert body["analysis_context"]["grades"] == ["5"]


def test_query_endpoint_resolves_spatial_selection_to_grid_ids():
    client = _client(spatial_service=FakeSpatialService())
    geometry = {
        "type": "Polygon",
        "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
    }

    response = client.post(
        "/api/queries",
        json={
            "region": "부산광역시 수영구",
            "scope": "selected_region",
            "question": "선택한 영역을 상세히 분석해줘",
            "analysis_context": {
                "region": "부산광역시 수영구",
                "grades": ["4", "5"],
                "comparison_regions": [],
                "selection": {
                    "id": "selection-1",
                    "metric": "overall",
                    "grades": ["4", "5"],
                    "geometry": geometry,
                },
            },
        },
    )

    assert response.status_code == 200
    context = response.json()["analysis_context"]
    assert context["selection"]["id"] == "selection-1"
    assert context["selected_ftr_ids"] == ["G1", "G2"]


def test_query_endpoint_recomputes_selection_ids_instead_of_trusting_client_values():
    class ChangedSpatialService(FakeSpatialService):
        def analyze_selection(self, region, geometry, grades=None, metric="overall"):
            result = super().analyze_selection(region, geometry, grades, metric)
            result["selected_ftr_ids"] = ["CHANGED-GRID"]
            return result

    client = _client(spatial_service=ChangedSpatialService())
    response = client.post(
        "/api/queries",
        json={
            "region": "부산광역시 수영구",
            "question": "선택 당시 격자만 분석해줘",
            "analysis_context": {
                "region": "부산광역시 수영구",
                "grades": [],
                "comparison_regions": [],
                "selection": {
                    "id": "selection-1",
                    "metric": "overall",
                    "grades": [],
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
                    },
                    "ftr_ids": ["G1", "G2"],
                },
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["analysis_context"]["selected_ftr_ids"] == ["CHANGED-GRID"]


def test_query_endpoint_accepts_large_legacy_selection_id_lists():
    class ChangedSpatialService(FakeSpatialService):
        def analyze_selection(self, region, geometry, grades=None, metric="overall"):
            result = super().analyze_selection(region, geometry, grades, metric)
            result["selected_ftr_ids"] = ["SERVER-GRID"]
            return result

    client = _client(spatial_service=ChangedSpatialService())
    response = client.post(
        "/api/queries",
        json={
            "region": "부산광역시 수영구",
            "question": "선택 영역을 분석해줘",
            "analysis_context": {
                "region": "부산광역시 수영구",
                "grades": [],
                "comparison_regions": [],
                "selection": {
                    "id": "selection-large",
                    "metric": "overall",
                    "grades": [],
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
                    },
                    "ftr_ids": [f"G{index}" for index in range(5001)],
                },
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["analysis_context"]["selected_ftr_ids"] == ["SERVER-GRID"]


def test_query_is_recorded_and_returned_by_analysis_history_endpoint():
    history = FakeHistoryService()
    client = _client(history_service=history)

    client.post(
        "/api/queries",
        json={
            "region": "부산광역시 수영구",
            "scope": "selected_region",
            "question": "고위험 비율이 가장 높은 지역은?",
        },
    )
    response = client.get("/api/history")

    assert response.status_code == 200
    assert response.json()[0] == {
        "id": "history-1",
        "kind": "query",
        "title": "고위험 비율이 가장 높은 지역은?",
        "region": "부산광역시 수영구",
        "status": "completed",
        "summary": "남천2동의 고위험 비율은 21.4%다.",
        "query_count": 1,
        "grounded": True,
    }


def test_conversation_endpoints_save_list_and_restore_full_session():
    client = _client(history_service=FakeHistoryService())
    payload = {
        "title": "수영구 고위험 지역을 알려줘",
        "region": "부산광역시 수영구",
        "messages": [
            {"id": "m1", "role": "user", "kind": "text", "text": "수영구 고위험 지역을 알려줘"},
            {"id": "m2", "role": "assistant", "kind": "text", "text": "남천2동이 가장 높습니다."},
        ],
        "analysis_context": {
            "region": "부산광역시 수영구",
            "grades": ["5"],
            "comparison_regions": [],
        },
        "materials": [],
    }

    saved = client.put("/api/conversations/session-1", json=payload)
    listed = client.get("/api/conversations")
    restored = client.get("/api/conversations/session-1")

    assert saved.status_code == 200
    assert listed.json()[0]["message_count"] == 2
    assert restored.json()["messages"] == payload["messages"]
    assert restored.json()["analysis_context"]["grades"] == ["5"]


def test_conversation_endpoint_deletes_saved_session():
    client = _client(history_service=FakeHistoryService())
    payload = {
        "title": "수영구 고위험 지역",
        "region": "부산광역시 수영구",
        "messages": [{"id": "m1", "role": "user", "kind": "text", "text": "질문"}],
        "analysis_context": {"region": "부산광역시 수영구", "grades": [], "comparison_regions": []},
        "materials": [],
    }
    client.put("/api/conversations/session-1", json=payload)

    deleted = client.delete("/api/conversations/session-1")
    missing = client.get("/api/conversations/session-1")

    assert deleted.status_code == 200
    assert deleted.json() == {"id": "session-1", "deleted": True}
    assert missing.status_code == 404


def test_spatial_endpoints_return_layer_metadata_and_filtered_geojson():
    client = _client()

    layer = client.get(
        "/api/spatial/layer",
        params={"region": "부산광역시 수영구"},
    )
    features = client.get(
        "/api/spatial/features",
        params={"region": "부산광역시 수영구", "grades": "4,5"},
    )

    assert layer.status_code == 200
    assert layer.json()["feature_count"] == 443
    assert features.status_code == 200
    assert features.json()["type"] == "FeatureCollection"
    assert features.json()["features"][0]["properties"]["위험성지수_등급"] == "5"


def test_spatial_selection_and_scenario_endpoints_analyze_and_replay():
    history = FakeHistoryService()
    client = _client(history_service=history)
    payload = {
        "region": "부산광역시 수영구",
        "metric": "overall",
        "grades": ["4", "5"],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
        },
    }

    analyzed = client.post("/api/spatial/selections", json=payload)
    saved = client.post(
        "/api/spatial/scenarios",
        json={"name": "수영구 선택영역", **payload},
    )
    listed = client.get("/api/spatial/scenarios")
    replayed = client.post(f"/api/spatial/scenarios/{saved.json()['id']}/run")

    assert analyzed.status_code == 200
    assert analyzed.json()["stats"]["selected_count"] == 2
    assert saved.status_code == 201
    assert listed.json()[0]["name"] == "수영구 선택영역"
    assert replayed.status_code == 200
    assert replayed.json()["stats"]["high_risk_pct"] == 50.0
    assert history.scenarios[saved.json()["id"]]["latest_result"]["selection_id"] == "selection-1"


def test_spatial_features_endpoint_passes_sentence_focus_names():
    class FocusSpatialService(FakeSpatialService):
        def __init__(self):
            self.focus_names = None

        def features(self, region, grades=None, limit=2000, focus_names=None, metric="overall"):
            self.focus_names = focus_names
            return super().features(region, grades, limit, focus_names, metric)

    service = FocusSpatialService()
    response = _client(spatial_service=service).get(
        "/api/spatial/features",
        params={"region": "부산광역시 수영구", "focus": "남천2동,민락동"},
    )

    assert response.status_code == 200
    assert service.focus_names == ["남천2동", "민락동"]


def test_spatial_features_endpoint_passes_selected_factor_metric():
    class MetricSpatialService(FakeSpatialService):
        def __init__(self):
            self.metric = None

        def features(self, region, grades=None, limit=2000, focus_names=None, metric="overall"):
            self.metric = metric
            return super().features(region, grades, limit, focus_names, metric)

    service = MetricSpatialService()
    response = _client(spatial_service=service).get(
        "/api/spatial/features",
        params={"region": "부산광역시 수영구", "grades": "4", "metric": "강풍"},
    )

    assert response.status_code == 200
    assert service.metric == "강풍"


def test_spatial_export_endpoint_creates_and_serves_a_png(tmp_path):
    image = tmp_path / "map-1.png"
    image.write_bytes(b"png-image")

    class ExportSpatialService(FakeSpatialService):
        def __init__(self):
            self.request = None

        def export_map(
            self,
            region,
            metric="overall",
            grades=None,
            focus_names=None,
            background="transparent",
            extent="region",
            geometry=None,
        ):
            self.request = {
                "region": region,
                "metric": metric,
                "grades": grades,
                "focus_names": focus_names,
                "background": background,
                "extent": extent,
                "geometry": geometry,
            }
            return {
                "image_id": "map-1",
                "filename": "부산광역시_수영구_파랑_4등급.png",
                "caption": "부산광역시 수영구 파랑 4등급 공간분석",
                "region": region,
                "metric": metric,
                "grades": grades,
                "feature_count": 32,
            }

        def export_asset(self, image_id):
            return image if image_id == "map-1" else None

    service = ExportSpatialService()
    client = _client(spatial_service=service)
    created = client.post("/api/spatial/exports", json={
        "region": "부산광역시 수영구",
        "metric": "파랑",
        "grades": ["4"],
        "focus_names": ["남천1동"],
        "background": "satellite",
        "extent": "viewport",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
        },
    })
    downloaded = client.get("/api/spatial/exports/map-1/download")

    assert created.status_code == 201
    assert created.json()["image_url"] == "/api/spatial/exports/map-1"
    assert created.json()["download_url"] == "/api/spatial/exports/map-1/download"
    assert service.request == {
        "region": "부산광역시 수영구",
        "metric": "파랑",
        "grades": ["4"],
        "focus_names": ["남천1동"],
        "background": "satellite",
        "extent": "viewport",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
        },
    }
    assert downloaded.status_code == 200
    assert downloaded.content == b"png-image"


def test_spatial_annotation_endpoint_passes_uploaded_shapefile_parts():
    class AnnotationSpatialService(FakeSpatialService):
        def __init__(self):
            self.files = None

        def import_annotation(self, files):
            self.files = files
            return {
                "id": "layer-1",
                "name": "district",
                "feature_count": 1,
                "geometry_type": "Polygon",
                "source_crs": "EPSG:5179",
                "display_crs": "EPSG:4326",
                "columns": ["지역명"],
                "suggested_label_field": "지역명",
                "geojson": {"type": "FeatureCollection", "features": []},
            }

    service = AnnotationSpatialService()
    response = _client(spatial_service=service).post(
        "/api/spatial/annotations",
        files=[
            ("files", ("district.shp", b"shp", "application/octet-stream")),
            ("files", ("district.dbf", b"dbf", "application/octet-stream")),
            ("files", ("district.prj", b"prj", "text/plain")),
        ],
    )

    assert response.status_code == 201
    assert service.files == [
        ("district.shp", b"shp"),
        ("district.dbf", b"dbf"),
        ("district.prj", b"prj"),
    ]


def test_comparison_endpoint_returns_deterministic_duckdb_result():
    response = _client().post(
        "/api/comparisons",
        json={"regions": ["부산광역시 수영구", "부산광역시 해운대구"]},
    )

    assert response.status_code == 200
    assert response.json()["grounded"] is True
    assert response.json()["summary"][0]["high_risk_pct"] == 12.6


def test_mcp_analysis_endpoint_delegates_duckdb_result_table():
    service = FakeMcpAnalysisService()
    response = _client(mcp_service=service).post(
        "/api/mcp/analyze",
        json={
            "question": "지역별 위험도를 고급 분석해줘",
            "columns": ["지역", "위험도"],
            "rows": [["수영구", 72.5], ["해운대구", 64.1]],
        },
    )

    assert response.status_code == 200
    assert response.json()["tools_available"] == 60
    assert service.request["columns"] == ["지역", "위험도"]


def test_mcp_analysis_endpoint_replaces_sql_with_a_natural_korean_chart_title():
    service = FakeMcpAnalysisService()
    response = _client(mcp_service=service).post(
        "/api/mcp/analyze",
        json={
            "question": "SELECT 위험도 FROM grid ORDER BY 위험도 DESC",
            "region": "부산광역시 수영구",
            "columns": ["위험도"],
            "rows": [[1.2], [3.4], [4.5]],
            "chart_spec": {
                "chart": "histogram",
                "x_column": "위험도",
            },
        },
    )

    assert response.status_code == 200
    assert service.request["question"] == "부산광역시 수영구 위험도 분포"
    assert "SELECT" not in service.request["question"]


def test_mcp_analysis_endpoint_expands_the_selected_region_with_all_grid_rows():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata

    class EnrichingQueryService(FakeQueryService):
        def __init__(self):
            self.enrichment_request = None

        def mcp_dataset(self, region, focus_names=None, limit=None, selection_ftr_ids=None):
            self.enrichment_request = {
                "region": region,
                "focus_names": focus_names,
                "limit": limit,
                "selection_ftr_ids": selection_ftr_ids,
            }
            return {
                "source": "duckdb_grid_raw",
                "query": "SELECT raw factors FROM grid",
                "columns": ["지역", "강우 (mm/h)", "고령인구 (명)"],
                "rows": [
                    ["민락동", 20.5, 1200],
                    ["광안동", 12.1, 950],
                ],
            }

    class UserScopedHistoryService(FakeHistoryService):
        user_scoped = True

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth_service = AuthService(engine, secret_key="test-secret")
    auth_service.create_user("mcp-auditor", "correct-password")
    query_service = EnrichingQueryService()
    mcp_service = FakeMcpAnalysisService()
    history_service = UserScopedHistoryService()
    client = _client(
        query_service=query_service,
        mcp_service=mcp_service,
        history_service=history_service,
        auth_service=auth_service,
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "mcp-auditor", "password": "correct-password"},
    )
    response = client.post(
        "/api/mcp/analyze",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
        json={
            "question": "고위험 비율이 높은 지역을 분석해줘",
            "region": "부산광역시 수영구",
            "columns": [
                "ADM_NM",
                "grid_count",
                "high_risk_grids",
                "high_risk_ratio",
                "avg_grade",
                "max_grade",
            ],
            "rows": [
                ["민락동", 100, 30, 30.0, 3.4, 5],
                ["광안동", 90, 20, 22.2, 3.1, 5],
            ],
        },
    )

    assert response.status_code == 200
    assert query_service.enrichment_request == {
        "region": "부산광역시 수영구",
        "focus_names": ["민락동", "광안동"],
        "limit": None,
        "selection_ftr_ids": None,
    }
    assert mcp_service.request["columns"] == [
        "지역",
        "강우 (mm/h)",
        "고령인구 (명)",
    ]
    assert response.json()["dataset"] == {
        "source": "duckdb_grid_raw",
        "row_count": 2,
        "column_count": 3,
        "columns": ["지역", "강우 (mm/h)", "고령인구 (명)"],
        "query": "SELECT raw factors FROM grid",
    }
    assert history_service.entries[0]["query_count"] == 1
    assert history_service.entries[0]["queries"] == [{
        "sql": "SELECT raw factors FROM grid",
        "row_count": 2,
        "success": True,
    }]


def test_mcp_analysis_endpoint_scopes_expansion_to_the_shared_selection():
    class SelectionScopedQueryService(FakeQueryService):
        def __init__(self):
            self.enrichment_request = None

        def mcp_dataset(self, region, focus_names=None, limit=None, selection_ftr_ids=None):
            self.enrichment_request = {
                "region": region,
                "focus_names": focus_names,
                "selection_ftr_ids": selection_ftr_ids,
            }
            return {
                "source": "duckdb_selected_grid",
                "query": "SELECT raw factors FROM selected_grid",
                "columns": ["지역", "고령인구 (명)"],
                "rows": [["민락동", 1200], ["민락동", 950]],
            }

    query_service = SelectionScopedQueryService()
    mcp_service = FakeMcpAnalysisService()
    client = _client(query_service=query_service, mcp_service=mcp_service)
    geometry = {
        "type": "Polygon",
        "coordinates": [[[129.1, 35.1], [129.2, 35.1], [129.2, 35.2], [129.1, 35.1]]],
    }
    response = client.post(
        "/api/mcp/analyze",
        json={
            "question": "선택 영역을 시각화해줘",
            "region": "부산광역시 수영구",
            "columns": ["항목", "값"],
            "rows": [["교차 격자", 2]],
            "selection": {
                "id": "selection-1",
                "metric": "overall",
                "grades": ["4", "5"],
                "geometry": geometry,
            },
        },
    )

    assert response.status_code == 200
    # 서버가 재계산한 격자 ID(FakeSpatialService: G1, G2)가 스코프로 전달되고
    # focus_names 축소는 selection이 대체한다.
    assert query_service.enrichment_request == {
        "region": "부산광역시 수영구",
        "focus_names": None,
        "selection_ftr_ids": ["G1", "G2"],
    }
    payload = response.json()
    assert payload["dataset"]["source"] == "duckdb_selected_grid"
    assert payload["dataset"]["selection"] == {
        "id": "selection-1",
        "selected_count": 2,
    }
    # 차트 제목에도 선택 영역이 표기된다.
    assert "선택 영역" in mcp_service.request["question"]


def test_mcp_grid_columns_endpoint_lists_axis_candidates():
    class ColumnsQueryService(FakeQueryService):
        def mcp_dataset_columns(self, region):
            assert region == "부산광역시 수영구"
            return ["지역", "종합 위험 (등급)", "강풍 (m/s)", "강우 (mm/h)"]

    client = _client(query_service=ColumnsQueryService())
    response = client.get(
        "/api/mcp/grid-columns",
        params={"region": "부산광역시 수영구"},
    )

    assert response.status_code == 200
    assert response.json()["columns"] == [
        "지역", "종합 위험 (등급)", "강풍 (m/s)", "강우 (mm/h)",
    ]


def test_mcp_analysis_endpoint_expands_for_custom_grid_chart_spec():
    class GridChartQueryService(FakeQueryService):
        def __init__(self):
            self.enrichment_request = None

        def mcp_dataset(self, region, focus_names=None, limit=None, selection_ftr_ids=None):
            self.enrichment_request = {"region": region, "selection_ftr_ids": selection_ftr_ids}
            return {
                "source": "duckdb_grid_raw",
                "query": "SELECT raw factors FROM grid",
                "columns": ["지역", "강풍 (m/s)", "고령인구 (명)"],
                "rows": [["민락동", 20.5, 1200], ["광안동", 12.1, 950]],
            }

    query_service = GridChartQueryService()
    mcp_service = FakeMcpAnalysisService()
    client = _client(query_service=query_service, mcp_service=mcp_service)
    response = client.post(
        "/api/mcp/analyze",
        json={
            "question": "강풍과 고령인구의 관계",
            "region": "부산광역시 수영구",
            "columns": ["항목", "값"],
            "rows": [["교차 격자", 2]],
            "use_grid_data": True,
            "chart_spec": {
                "chart": "scatter",
                "x_column": "강풍 (m/s)",
                "y_column": "고령인구 (명)",
            },
        },
    )

    assert response.status_code == 200
    # 직접 설정(chart_spec)이라도 use_grid_data면 격자 원자료로 확장되고,
    # MCP에는 확장된 컬럼·행이 전달된다.
    assert query_service.enrichment_request == {
        "region": "부산광역시 수영구",
        "selection_ftr_ids": None,
    }
    assert mcp_service.request["columns"] == ["지역", "강풍 (m/s)", "고령인구 (명)"]
    assert mcp_service.request["chart_spec"]["x_column"] == "강풍 (m/s)"
    assert response.json()["dataset"]["columns"] == ["지역", "강풍 (m/s)", "고령인구 (명)"]


def test_mcp_analysis_endpoint_forwards_custom_chart_spec():
    service = FakeMcpAnalysisService()
    response = _client(mcp_service=service).post(
        "/api/mcp/analyze",
        json={
            "question": "강우와 위험도의 관계를 보여줘",
            "columns": ["강우", "위험도", "지역"],
            "rows": [[20.5, 4.2, "민락동"], [12.1, 3.1, "광안동"]],
            "chart_spec": {
                "chart": "scatter",
                "x_column": "강우",
                "y_column": "위험도",
                "group_column": "지역",
                "x_label": "강우 (mm/h)",
                "y_label": "위험도",
            },
        },
    )

    assert response.status_code == 200
    assert service.request["chart_spec"] == {
        "chart": "scatter",
        "x_column": "강우",
        "y_column": "위험도",
        "group_column": "지역",
        "stack_column": None,
        "columns": [],
        "aggregation": "mean",
        "top_n": 20,
        "bins": 10,
        "normalize": False,
        "x_label": "강우 (mm/h)",
        "y_label": "위험도",
    }


def test_mcp_analysis_asset_endpoint_serves_generated_chart(tmp_path):
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    response = _client(mcp_service=FakeMcpAnalysisService(chart)).get(
        "/api/mcp/analyses/analysis-1/assets/chart.png"
    )

    assert response.status_code == 200
    assert response.content == b"png"


@pytest.mark.skipif(API_SPEC is None, reason="API module not implemented yet")
def test_report_endpoint_creates_job_and_exposes_status():
    client = _client()
    created = client.post(
        "/api/reports",
        json={
            "region": "부산광역시 수영구",
            "use_llm": True,
            "use_judge": True,
            "make_hwpx": True,
        },
    )

    assert created.status_code == 202
    assert created.json() == {"job_id": "job-1", "status": "queued"}

    status = client.get("/api/reports/job-1")
    assert status.status_code == 200
    assert status.json()["stage"] == "analyze"


def test_report_endpoint_accepts_selected_result_with_full_grid_columns():
    columns = [f"column_{index}" for index in range(102)]
    created = _client().post(
        "/api/reports",
        json={
            "region": "부산광역시 수영구",
            "materials": [{
                "question": "위험지역 자료를 보고서에 추가해줘",
                "answer": "선택한 격자 자료입니다.",
                "grounded": True,
                "results": [{"columns": columns, "rows": [[0] * len(columns)]}],
            }],
        },
    )

    assert created.status_code == 202


def test_report_endpoint_preserves_valid_mcp_chart_reference():
    class CapturingReportManager(FakeReportManager):
        def __init__(self):
            self.options = None

        def create(self, options, owner_id=None):
            self.options = options
            return {"job_id": "job-1", "status": "queued"}

    manager = CapturingReportManager()
    created = _client(report_manager=manager).post(
        "/api/reports",
        json={
            "region": "부산광역시 수영구",
            "materials": [{
                "question": "MCP 상관관계 분석",
                "answer": "실제 데이터 213행을 분석했습니다.",
                "grounded": True,
                "mcp_chart": {
                    "analysis_id": "a" * 32,
                    "asset_name": "correlation_heatmap.png",
                    "caption": "고위험 격자 원자료 상관관계",
                    "chart": "correlation_heatmap",
                },
            }],
        },
    )

    assert created.status_code == 202
    assert manager.options["materials"][0]["mcp_chart"] == {
        "analysis_id": "a" * 32,
        "asset_name": "correlation_heatmap.png",
        "caption": "고위험 격자 원자료 상관관계",
        "chart": "correlation_heatmap",
    }


def test_report_endpoint_rejects_unsafe_mcp_chart_asset_name():
    created = _client().post(
        "/api/reports",
        json={
            "region": "부산광역시 수영구",
            "materials": [{
                "question": "MCP 상관관계 분석",
                "answer": "검증된 분석입니다.",
                "grounded": True,
                "mcp_chart": {
                    "analysis_id": "a" * 32,
                    "asset_name": "../other-user/chart.png",
                    "caption": "상관관계",
                    "chart": "correlation_heatmap",
                },
            }],
        },
    )

    assert created.status_code == 422


def test_report_endpoint_rejects_material_without_grounding_state():
    created = _client().post(
        "/api/reports",
        json={
            "region": "부산광역시 수영구",
            "materials": [{
                "question": "선택 영역을 전체와 비교해줘",
                "answer": "비교 결과입니다.",
            }],
        },
    )

    assert created.status_code == 422


def test_report_endpoint_rejects_ungrounded_query_material():
    created = _client().post(
        "/api/reports",
        json={
            "region": "부산광역시 수영구",
            "materials": [{
                "question": "선택 영역을 전체와 비교해줘",
                "answer": "비교 결과입니다.",
                "grounded": False,
            }],
        },
    )

    assert created.status_code == 422


@pytest.mark.skipif(API_SPEC is None, reason="API module not implemented yet")
def test_unknown_job_returns_404():
    response = _client().get("/api/reports/missing")

    assert response.status_code == 404


def test_report_revision_endpoint_rewrites_one_section():
    response = _client().post(
        "/api/reports/job-complete/revisions",
        json={"section": "정책 제언", "instruction": "간결하게 수정해줘"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "revision": 1,
        "section": "정책 제언",
        "instruction": "간결하게 수정해줘",
    }


def test_report_content_endpoint_saves_direct_markdown_edit():
    response = _client().put(
        "/api/reports/job-complete/content",
        json={"markdown": "# 보고서\n\n웹에서 직접 수정한 본문"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "direct_edit"
    assert response.json()["markdown"] == "# 보고서\n\n웹에서 직접 수정한 본문"


def test_report_revision_endpoint_queues_edit_when_dispatcher_is_available():
    from coastal_web.auth import AuthService
    from coastal_web.database import create_database_engine, metadata

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    auth = AuthService(engine, secret_key="test-secret")
    user = auth.create_user("revision-user", "revision-password")

    class EditDispatcher:
        def get(self, user_id, job_id):
            if user_id != user["id"] or job_id != "job-complete":
                return None
            return {
                "job_id": job_id,
                "user_id": user_id,
                "status": "completed",
                "stage": "convert",
                "progress": 7,
                "options": {},
                "result": {},
                "errors": [],
            }

        def materials(self, _job_id):
            return []

        def submit_edit(self, user_id, job_id, operation, payload):
            assert user_id == user["id"]
            assert job_id == "job-complete"
            assert operation == "revision"
            assert payload == {
                "section": "정책 제언",
                "instruction": "간결하게 수정해줘",
            }
            return {
                "job_id": job_id,
                "task_id": "job-complete-edit-1",
                "status": "queued",
            }

    client = _client(auth_service=auth, report_dispatcher=EditDispatcher())
    login = client.post(
        "/api/auth/login",
        json={"username": "revision-user", "password": "revision-password"},
    )

    response = client.post(
        "/api/reports/job-complete/revisions",
        json={"section": "정책 제언", "instruction": "간결하게 수정해줘"},
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": "job-complete",
        "task_id": "job-complete-edit-1",
        "status": "queued",
    }


def test_report_provenance_endpoints_return_sentence_evidence():
    client = _client()

    index = client.get("/api/reports/job-complete/provenance")
    detail = client.get("/api/reports/job-complete/provenance/s1")

    assert index.status_code == 200
    assert index.json()[0]["sentence"] == "평가 대상 격자는 총 443개이다."
    assert detail.status_code == 200
    assert detail.json()["stats"][0]["path"] == "데이터개요.총 격자 수"


def test_report_events_stream_as_server_sent_events():
    response = _client().get("/api/reports/job-complete/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: stage_completed' in response.text
    assert '"stage": "analyze"' in response.text
    assert 'event: job_completed' in response.text


def test_report_preview_and_download_use_job_files(tmp_path):
    class FileManager(FakeReportManager):
        def __init__(self):
            self.md = tmp_path / "report.md"
            self.hwpx = tmp_path / "report.hwpx"
            self.md.write_text(
                "# 수영구 보고서\n\n![위험도](..\\figures\\risk_map.png)",
                encoding="utf-8",
            )
            self.hwpx.write_bytes(b"hwpx")

        def file(self, job_id, kind):
            if job_id != "job-complete":
                return None
            return {"md": self.md, "hwpx": self.hwpx}.get(kind)

    client = _client(FileManager())

    preview = client.get("/api/reports/job-complete/preview")
    content = client.get("/api/reports/job-complete/content")
    download = client.get("/api/reports/job-complete/download/hwpx")

    assert preview.status_code == 200
    assert preview.json() == {
        "markdown": (
            "# 수영구 보고서\n\n"
            "![위험도](/api/reports/job-complete/assets/risk_map.png)"
        )
    }
    assert content.status_code == 200
    assert content.json() == {
        "markdown": "# 수영구 보고서\n\n![위험도](..\\figures\\risk_map.png)"
    }
    assert download.status_code == 200
    assert download.content == b"hwpx"
    assert "attachment" in download.headers["content-disposition"]


def test_built_frontend_is_served_from_root():
    response = _client().get("/")

    assert response.status_code == 200
    assert "연안 인텔리전스 스튜디오" in response.text
