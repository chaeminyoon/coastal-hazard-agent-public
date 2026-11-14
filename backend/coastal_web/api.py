import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class SpatialAnalysisContextRequest(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    metric: str = Field(default="overall", min_length=1, max_length=50)
    grades: list[Literal["1", "2", "3", "4", "5"]] = Field(
        default_factory=list,
        max_length=5,
    )
    geometry: dict[str, Any]


class AnalysisContextRequest(BaseModel):
    region: str | None = Field(default=None, max_length=100)
    grades: list[Literal["1", "2", "3", "4", "5"]] = Field(
        default_factory=list,
        max_length=5,
    )
    comparison_regions: list[str] = Field(default_factory=list, max_length=5)
    selection: SpatialAnalysisContextRequest | None = None
    metric_definition: Literal[
        "high_risk_ratio",
        "high_risk_share",
        "average_risk_grade",
        "high_risk_concentration",
    ] | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    region: str | None = None
    scope: Literal["selected_region", "national"] = "selected_region"
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=8)
    analysis_context: AnalysisContextRequest | None = None


class ComparisonRequest(BaseModel):
    regions: list[str] = Field(min_length=2, max_length=4)


class MetricResolveRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class McpChartSpec(BaseModel):
    chart: Literal[
        "bar",
        "stacked_bar",
        "line",
        "area",
        "scatter",
        "histogram",
        "boxplot",
        "violin",
        "correlation_heatmap",
        "pivot_heatmap",
    ]
    x_column: str | None = Field(default=None, max_length=100)
    y_column: str | None = Field(default=None, max_length=100)
    group_column: str | None = Field(default=None, max_length=100)
    stack_column: str | None = Field(default=None, max_length=100)
    columns: list[str] = Field(default_factory=list, max_length=20)
    aggregation: Literal["mean", "sum", "count", "min", "max", "median"] = "mean"
    top_n: int = Field(default=20, ge=1, le=50)
    bins: int = Field(default=10, ge=5, le=50)
    normalize: bool = False
    x_label: str | None = Field(default=None, max_length=150)
    y_label: str | None = Field(default=None, max_length=150)


class McpAnalysisRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    region: str | None = Field(default=None, max_length=100)
    columns: list[str] = Field(min_length=1, max_length=50)
    rows: list[list[Any]] = Field(min_length=1, max_length=2000)
    chart_spec: McpChartSpec | None = None
    # 선택 영역 스코프 — 질의와 동일하게 geometry를 받아 서버가 재교차한다.
    selection: SpatialAnalysisContextRequest | None = None
    # 직접 설정 차트에서 평가항목 원자료(강풍·강우 등) 축을 쓰기 위한 확장 요청
    use_grid_data: bool = False


class ReportResultTable(BaseModel):
    columns: list[str] = Field(max_length=200)
    rows: list[list[Any]] = Field(max_length=200)


class SpatialImageReference(BaseModel):
    image_id: str = Field(min_length=1, max_length=150, pattern=r"^[\w가-힣-]+$")
    filename: str = Field(min_length=1, max_length=180)
    caption: str = Field(min_length=1, max_length=300)


class McpChartReference(BaseModel):
    analysis_id: str = Field(pattern=r"^[A-Fa-f0-9]{32}$")
    asset_name: str = Field(
        min_length=5,
        max_length=180,
        pattern=r"^[^/\\]+\.png$",
    )
    caption: str = Field(min_length=1, max_length=300)
    chart: Literal[
        "bar",
        "stacked_bar",
        "line",
        "area",
        "scatter",
        "histogram",
        "boxplot",
        "violin",
        "correlation_heatmap",
        "pivot_heatmap",
    ]


class ReportMaterial(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    answer: str = Field(min_length=1, max_length=5000)
    region: str | None = Field(default=None, max_length=100)
    grounded: Literal[True]
    scope: dict[str, Any] | None = None
    queries: list[str] = Field(default_factory=list, max_length=10)
    results: list[ReportResultTable] = Field(default_factory=list, max_length=10)
    spatial_image: SpatialImageReference | None = None
    mcp_chart: McpChartReference | None = None


class SpatialExportRequest(BaseModel):
    region: str = Field(min_length=2, max_length=100)
    metric: str = Field(default="overall", min_length=1, max_length=50)
    grades: list[Literal["1", "2", "3", "4", "5"]] = Field(
        default_factory=list,
        max_length=5,
    )
    focus_names: list[str] = Field(default_factory=list, max_length=50)
    background: Literal["satellite", "composite", "transparent"] = "transparent"
    extent: Literal["region", "viewport", "selection"] = "region"
    geometry: dict[str, Any] | None = None


class SpatialSelectionRequest(BaseModel):
    region: str = Field(min_length=2, max_length=100)
    metric: str = Field(default="overall", min_length=1, max_length=50)
    grades: list[Literal["1", "2", "3", "4", "5"]] = Field(
        default_factory=list,
        max_length=5,
    )
    geometry: dict[str, Any]


class SpatialSelectionComparisonRequest(BaseModel):
    region: str = Field(min_length=2, max_length=100)
    metric: str = Field(default="overall", min_length=1, max_length=50)
    grades: list[Literal["1", "2", "3", "4", "5"]] = Field(
        default_factory=list,
        max_length=5,
    )
    geometry_a: dict[str, Any]
    geometry_b: dict[str, Any]


class SpatialNaturalFilterRequest(BaseModel):
    region: str = Field(min_length=2, max_length=100)
    question: str = Field(min_length=2, max_length=1000)


class SpatialNeighborhoodRequest(BaseModel):
    region: str = Field(min_length=2, max_length=100)
    ftr_id: str = Field(min_length=1, max_length=100)
    distance_m: float = Field(default=500, ge=0, le=5000)
    metric: str = Field(default="overall", min_length=1, max_length=50)
    grades: list[Literal["1", "2", "3", "4", "5"]] = Field(
        default_factory=list,
        max_length=5,
    )


class SpatialHotspotRequest(BaseModel):
    region: str = Field(min_length=2, max_length=100)
    metric: str = Field(default="overall", min_length=1, max_length=50)
    grades: list[Literal["1", "2", "3", "4", "5"]] = Field(
        default_factory=lambda: ["4", "5"],
        max_length=5,
    )
    min_cluster_size: int = Field(default=2, ge=1, le=100)


class SpatialQueryScopeRequest(BaseModel):
    region: str = Field(min_length=2, max_length=100)
    queries: list[str] = Field(min_length=1, max_length=10)


class SpatialScenarioRequest(SpatialSelectionRequest):
    name: str = Field(min_length=2, max_length=120)


class ReportRequest(BaseModel):
    region: str | None = None
    use_llm: bool = True
    use_judge: bool = True
    make_hwpx: bool = True
    materials: list[ReportMaterial] = Field(default_factory=list, max_length=10)


class RevisionRequest(BaseModel):
    section: str = Field(min_length=2, max_length=150)
    instruction: str = Field(min_length=2, max_length=2000)


class ReportContentRequest(BaseModel):
    markdown: str = Field(min_length=1, max_length=500_000)


class ConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=100)
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    analysis_context: AnalysisContextRequest
    materials: list[dict[str, Any]] = Field(default_factory=list, max_length=10)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=500)
    role: Literal["admin", "user"] = "user"


class UserStatusRequest(BaseModel):
    is_active: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=500)
    new_password: str = Field(min_length=8, max_length=500)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=500)


def _preview_markdown(markdown: str, job_id: str) -> str:
    pattern = r"(!\[[^\]]*\]\()\.\.[\\/]+figures[\\/]+([^\)\\/]+)(\))"
    return re.sub(
        pattern,
        lambda match: (
            f"{match.group(1)}/api/reports/{job_id}/assets/"
            f"{match.group(2)}{match.group(3)}"
        ),
        markdown,
    )


def _mcp_focus_names(columns: list[str], rows: list[list[Any]]) -> list[str]:
    place_index = next(
        (
            index
            for index, column in enumerate(columns)
            if re.fullmatch(
                r"ADM_NM|읍면동|읍·면·동|행정동|지역|지역명|region",
                column,
                re.IGNORECASE,
            )
        ),
        None,
    )
    if place_index is None:
        return []
    return list(dict.fromkeys(
        str(row[place_index]).strip()
        for row in rows
        if row[place_index] is not None and str(row[place_index]).strip()
    ))[:50]


def _mcp_chart_title(
    region: str | None,
    columns: list[str],
    chart_spec: McpChartSpec | None,
) -> str:
    prefix = f"{region} " if region else ""
    chart = chart_spec.chart if chart_spec else None
    x_column = chart_spec.x_column if chart_spec else None
    y_column = chart_spec.y_column if chart_spec else None
    if chart == "histogram" and x_column:
        return f"{prefix}{x_column} 분포"
    if chart in {"bar", "line", "area", "scatter", "boxplot", "violin"}:
        if x_column and y_column:
            connector = "관계" if chart == "scatter" else "비교"
            return f"{prefix}{x_column}별 {y_column} {connector}"
        if y_column:
            return f"{prefix}{y_column} 분포"
    if chart == "stacked_bar" and x_column:
        stack = chart_spec.stack_column or "등급"
        return f"{prefix}{x_column}별 {stack} 구성"
    if chart == "correlation_heatmap":
        return f"{prefix}주요 원자료 간 상관관계"
    if chart == "pivot_heatmap" and x_column:
        return f"{prefix}{x_column} 기준 교차 분포"
    subject = next((column for column in columns if column != "지역"), "주요 지표")
    return f"{prefix}{subject} 중심 주요 데이터 분포"


def _runtime_readiness(
    settings,
    database_engine=None,
    mcp_service=None,
) -> dict[str, bool]:
    checks = dict(settings.readiness_checks())
    if database_engine is not None:
        try:
            with database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            checks["database"] = False
    redis_url = getattr(settings, "redis_url", None)
    if redis_url:
        try:
            from redis import Redis

            redis = Redis.from_url(
                redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            checks["redis"] = bool(redis.ping())
        except Exception:
            checks["redis"] = False
    if mcp_service is not None and hasattr(mcp_service, "readiness_checks"):
        checks.update(mcp_service.readiness_checks())
    return checks


def create_app(
    query_service=None,
    report_manager=None,
    spatial_service=None,
    mcp_service=None,
    history_service=None,
    auth_service=None,
    report_dispatcher=None,
    audit_repository=None,
    settings=None,
) -> FastAPI:
    if settings is None:
        from .config import Settings

        settings = Settings.from_env()
    database_engine = None
    database_url = getattr(settings, "database_url", None)
    if auth_service is None and database_url:
        session_secret = getattr(settings, "session_secret", None)
        if not session_secret:
            raise RuntimeError("COASTAL_SESSION_SECRET 설정이 필요합니다.")
        from .auth import AuthService
        from .database import create_database_engine

        database_engine = create_database_engine(database_url)
        auth_service = AuthService(database_engine, secret_key=session_secret)
    if (
        query_service is None
        or report_manager is None
        or spatial_service is None
        or mcp_service is None
        or history_service is None
    ):
        from .database_history import DatabaseHistoryService
        from .history import HistoryService
        from .mcp_analysis import McpAnalysisService
        from .services import QueryService, ReportManager, SpatialService

        query_service = query_service or QueryService()
        spatial_root = settings.artifact_root / "spatial_maps"
        queue_enabled = bool(database_engine and getattr(settings, "redis_url", None))
        report_manager = report_manager or ReportManager(
            output_root=settings.artifact_root / "jobs",
            spatial_export_root=spatial_root,
            mcp_output_root=settings.artifact_root / "mcp",
            auto_start=not queue_enabled,
        )
        spatial_service = spatial_service or SpatialService(
            export_root=spatial_root,
            annotation_root=settings.artifact_root / "annotations",
        )
        mcp_service = mcp_service or McpAnalysisService(
            output_root=settings.artifact_root / "mcp",
        )
        history_service = history_service or (
            DatabaseHistoryService(database_engine)
            if database_engine is not None
            else HistoryService()
        )
    if report_dispatcher is None and database_engine is not None and settings.redis_url:
        from .report_queue import ReportDispatcher, ReportQueue
        from .repositories import ReportJobRepository

        report_dispatcher = ReportDispatcher(
            ReportJobRepository(database_engine),
            ReportQueue(settings.redis_url),
        )
    if audit_repository is None:
        audit_engine = database_engine or getattr(auth_service, "engine", None)
        if audit_engine is not None:
            from .repositories import AuditLogRepository

            audit_repository = AuditLogRepository(audit_engine)
    app = FastAPI(title="연안재해 위험평가 에이전트", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-CSRF-Token", "X-Auth-User"],
    )
    app.state.settings = settings
    app.state.database_engine = database_engine
    app.state.query_service = query_service
    app.state.report_manager = report_manager
    app.state.spatial_service = spatial_service
    app.state.mcp_service = mcp_service
    app.state.history_service = history_service
    app.state.auth_service = auth_service
    app.state.report_dispatcher = report_dispatcher
    app.state.audit_repository = audit_repository

    def write_audit(
        request: Request,
        action: str,
        *,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        if app.state.audit_repository is None:
            return
        app.state.audit_repository.record(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=request.client.host if request.client else None,
        )

    def history_options(request: Request) -> dict[str, str]:
        if not getattr(app.state.history_service, "user_scoped", False):
            return {}
        return {"user_id": request.state.user["id"]}

    def ensure_report_access(job_id: str, request: Request) -> None:
        if not getattr(app.state.history_service, "user_scoped", False):
            return
        if not app.state.history_service.owns_report(
            job_id,
            **history_options(request),
        ):
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    def ensure_report_loaded(job_id: str, request: Request) -> None:
        if app.state.report_dispatcher is None:
            return
        saved = app.state.report_dispatcher.get(request.state.user["id"], job_id)
        if saved is None:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        app.state.report_manager.restore(
            saved,
            materials=app.state.report_dispatcher.materials(job_id),
        )

    @app.middleware("http")
    async def require_authentication(request: Request, call_next):
        if auth_service is None or not request.url.path.startswith("/api/"):
            return await call_next(request)
        if request.url.path == "/api/auth/login":
            return await call_next(request)

        token = request.cookies.get("coastal_session")
        user = (
            await run_in_threadpool(auth_service.authenticate, token)
            if token
            else None
        )
        if user is None:
            return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
        request.state.user = user

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf_token = request.headers.get("X-CSRF-Token", "")
            if not await run_in_threadpool(
                auth_service.validate_csrf,
                token,
                csrf_token,
            ):
                return JSONResponse(
                    {"detail": "CSRF 토큰이 올바르지 않습니다."},
                    status_code=403,
                )
        response = await call_next(request)
        response.headers["X-CSRF-Token"] = auth_service.csrf_token(token)
        response.headers["X-Auth-User"] = quote(
            json.dumps(user, ensure_ascii=True, separators=(",", ":")),
            safe="",
        )
        return response

    @app.post("/api/auth/login")
    def login(request_body: LoginRequest, request: Request, response: Response):
        client_ip = request.client.host if request.client else None
        authenticated = auth_service.login(
            request_body.username,
            request_body.password,
            ip_address=client_ip,
        )
        if authenticated is None:
            write_audit(
                request,
                "auth.login.failed",
                details={"username": request_body.username},
            )
            raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
        write_audit(
            request,
            "auth.login.succeeded",
            user_id=authenticated["user"]["id"],
            resource_type="user",
            resource_id=authenticated["user"]["id"],
        )
        response.set_cookie(
            "coastal_session",
            authenticated["session_token"],
            max_age=auth_service.session_hours * 3600,
            httponly=True,
            secure=settings.environment == "production",
            samesite="lax",
            path="/",
        )
        return {
            "user": authenticated["user"],
            "csrf_token": authenticated["csrf_token"],
        }

    @app.get("/api/auth/me")
    def current_user(request: Request):
        return {"user": request.state.user}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get("coastal_session", "")
        app.state.auth_service.logout(token)
        write_audit(
            request,
            "auth.logout",
            user_id=request.state.user["id"],
            resource_type="user",
            resource_id=request.state.user["id"],
        )
        response.delete_cookie("coastal_session", path="/")
        return {"logged_out": True}

    @app.post("/api/auth/change-password")
    def change_password(request_body: ChangePasswordRequest, request: Request):
        changed = app.state.auth_service.change_password(
            request.state.user["id"],
            request_body.current_password,
            request_body.new_password,
            current_token=request.cookies.get("coastal_session", ""),
        )
        if not changed:
            raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다.")
        write_audit(
            request,
            "auth.password.change",
            user_id=request.state.user["id"],
            resource_type="user",
            resource_id=request.state.user["id"],
        )
        return {"changed": True}

    @app.get("/api/auth/sessions")
    def list_sessions(request: Request):
        return app.state.auth_service.list_sessions(
            request.state.user["id"],
            current_token=request.cookies.get("coastal_session", ""),
        )

    @app.delete("/api/auth/sessions/{session_id}")
    def revoke_session(session_id: str, request: Request, response: Response):
        revoked = app.state.auth_service.revoke_session(
            request.state.user["id"],
            session_id,
        )
        if not revoked:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        if session_id == hashlib.sha256(
            request.cookies.get("coastal_session", "").encode()
        ).hexdigest():
            response.delete_cookie("coastal_session", path="/")
        return {"revoked": True}

    def require_admin(request: Request) -> None:
        if request.state.user["role"] != "admin":
            raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")

    @app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
    def create_user(request_body: CreateUserRequest, request: Request):
        require_admin(request)
        try:
            created = app.state.auth_service.create_user(
                request_body.username,
                request_body.password,
                role=request_body.role,
            )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="이미 사용 중인 아이디입니다.",
            ) from exc
        write_audit(
            request,
            "admin.user.create",
            user_id=request.state.user["id"],
            resource_type="user",
            resource_id=created["id"],
            details={"username": created["username"], "role": created["role"]},
        )
        return created

    @app.get("/api/admin/users")
    def list_users(request: Request):
        require_admin(request)
        return app.state.auth_service.list_users()

    @app.get("/api/admin/audit-logs")
    def list_audit_logs(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        require_admin(request)
        if app.state.audit_repository is None:
            return []
        return app.state.audit_repository.list(limit=limit)

    @app.patch("/api/admin/users/{user_id}")
    def set_user_status(
        user_id: str,
        request_body: UserStatusRequest,
        request: Request,
    ):
        require_admin(request)
        user = app.state.auth_service.set_user_active(user_id, request_body.is_active)
        if user is None:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        write_audit(
            request,
            "admin.user.status.update",
            user_id=request.state.user["id"],
            resource_type="user",
            resource_id=user_id,
            details={"is_active": request_body.is_active},
        )
        return user

    @app.post("/api/admin/users/{user_id}/reset-password")
    def reset_user_password(
        user_id: str,
        request_body: ResetPasswordRequest,
        request: Request,
    ):
        require_admin(request)
        if not app.state.auth_service.reset_password(
            user_id,
            request_body.new_password,
        ):
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        write_audit(
            request,
            "admin.user.password.reset",
            user_id=request.state.user["id"],
            resource_type="user",
            resource_id=user_id,
        )
        return {"reset": True}

    @app.get("/api/admin/report-jobs")
    def list_report_jobs(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        require_admin(request)
        dispatcher = app.state.report_dispatcher
        if dispatcher is None or not hasattr(dispatcher, "jobs"):
            return []
        return dispatcher.jobs.list_all(limit)

    @app.get("/health/live", include_in_schema=False)
    def health_live():
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def health_ready(response: Response):
        checks = _runtime_readiness(settings, database_engine, app.state.mcp_service)
        ready = all(checks.values())
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if ready else "not_ready",
            "checks": checks,
        }

    @app.get("/api/regions")
    def regions():
        return app.state.query_service.regions()

    @app.get("/api/metrics/definitions")
    def metrics_definitions():
        from .metric_catalog import metric_definitions

        return metric_definitions()

    @app.post("/api/metrics/resolve")
    def resolve_metric(request_body: MetricResolveRequest):
        from .metric_catalog import resolve_metric_question

        return resolve_metric_question(request_body.question)

    @app.get("/api/data-quality")
    def data_quality(region: str | None = Query(default=None, max_length=100)):
        return app.state.query_service.data_quality(region)

    def execute_query(request: QueryRequest, http_request: Request) -> dict:
        analysis_context = (
            request.analysis_context.model_dump()
            if request.analysis_context
            else None
        )
        selection = (analysis_context or {}).get("selection")
        if selection:
            try:
                spatial_result = app.state.spatial_service.analyze_selection(
                    request.region or analysis_context.get("region"),
                    selection["geometry"],
                    selection["grades"],
                    selection["metric"],
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error))
            analysis_context["selected_ftr_ids"] = spatial_result.get(
                "selected_ftr_ids",
                [],
            )
        try:
            result = app.state.query_service.ask(
                request.question,
                region=request.region,
                scope=request.scope,
                history=[item.model_dump() for item in request.history],
                analysis_context=analysis_context,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        app.state.history_service.record(
            kind="query",
            title=request.question,
            region=request.region,
            status="completed",
            summary=result.get("answer", ""),
            query_count=len(result.get("queries") or []),
            grounded=bool(result.get("grounded")),
            **history_options(http_request),
            **(
                {
                    "queries": [
                        {
                            "sql": sql,
                            "row_count": len(
                                ((result.get("results") or [])[position]).get(
                                    "rows",
                                    [],
                                )
                            )
                            if position < len(result.get("results") or [])
                            else None,
                            "success": True,
                        }
                        for position, sql in enumerate(result.get("queries") or [])
                    ]
                }
                if getattr(app.state.history_service, "user_scoped", False)
                else {}
            ),
        )
        return result

    def query_stream_response(request: QueryRequest, http_request: Request):
        async def events():
            yield json.dumps(
                {
                    "type": "status",
                    "message": "DuckDB에서 근거 데이터를 조회하고 있습니다.",
                },
                ensure_ascii=False,
            ) + "\n"
            try:
                result = await run_in_threadpool(execute_query, request, http_request)
                yield json.dumps(
                    {"type": "result", "data": result},
                    ensure_ascii=False,
                    default=str,
                ) + "\n"
            except (HTTPException, ValueError) as error:
                detail = error.detail if isinstance(error, HTTPException) else str(error)
                yield json.dumps(
                    {"type": "error", "message": detail},
                    ensure_ascii=False,
                ) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.post("/api/queries")
    async def query(request: QueryRequest, http_request: Request):
        if "application/x-ndjson" in http_request.headers.get("accept", ""):
            return query_stream_response(request, http_request)
        return await run_in_threadpool(execute_query, request, http_request)

    @app.post("/api/queries/stream")
    async def query_stream(request: QueryRequest, http_request: Request):
        return query_stream_response(request, http_request)

    @app.post("/api/comparisons")
    def compare(request: ComparisonRequest, http_request: Request):
        result = app.state.query_service.compare(request.regions)
        app.state.history_service.record(
            kind="comparison",
            title=f"{' · '.join(request.regions)} 지역 비교",
            region=request.regions[0],
            status="completed",
            summary=result.get("answer", ""),
            query_count=len(result.get("queries") or []),
            **history_options(http_request),
            **(
                {"queries": result.get("queries") or []}
                if getattr(app.state.history_service, "user_scoped", False)
                else {}
            ),
        )
        return result

    @app.get("/api/mcp/grid-columns")
    def mcp_grid_columns(region: str = Query(min_length=2, max_length=100)):
        try:
            return {
                "columns": app.state.query_service.mcp_dataset_columns(region),
            }
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.post("/api/mcp/analyze")
    def mcp_analyze(request: McpAnalysisRequest, http_request: Request):
        try:
            analysis_columns = request.columns
            analysis_rows = request.rows
            dataset = {
                "source": "query_result",
                "row_count": len(analysis_rows),
                "column_count": len(analysis_columns),
            }
            selection_ftr_ids: list[str] | None = None
            if request.selection is not None and request.region:
                # 프런트가 보낸 격자 ID는 신뢰하지 않는다 — 질의 경로와
                # 동일하게 저장된 geometry로 교차 격자를 다시 계산한다.
                spatial_result = app.state.spatial_service.analyze_selection(
                    request.region,
                    request.selection.geometry,
                    request.selection.grades,
                    request.selection.metric,
                )
                selection_ftr_ids = spatial_result.get("selected_ftr_ids") or []
                if not selection_ftr_ids:
                    raise ValueError("선택 영역에 교차하는 격자가 없습니다.")
            if request.region and (
                request.chart_spec is None or request.use_grid_data
            ):
                expanded = app.state.query_service.mcp_dataset(
                    request.region,
                    focus_names=(
                        None
                        if selection_ftr_ids
                        else _mcp_focus_names(analysis_columns, analysis_rows)
                    ),
                    limit=None,
                    selection_ftr_ids=selection_ftr_ids,
                )
                if expanded["rows"]:
                    analysis_columns = expanded["columns"]
                    analysis_rows = expanded["rows"]
                    dataset = {
                        "source": expanded["source"],
                        "row_count": len(analysis_rows),
                        "column_count": len(analysis_columns),
                        "columns": list(analysis_columns),
                        "query": expanded["query"],
                    }
            if selection_ftr_ids:
                dataset["selection"] = {
                    "id": request.selection.id,
                    "selected_count": len(selection_ftr_ids),
                }
            owner_options = (
                {"owner_id": http_request.state.user["id"]}
                if getattr(app.state.history_service, "user_scoped", False)
                else {}
            )
            title_region = (
                f"{request.region} 선택 영역"
                if selection_ftr_ids and request.region
                else request.region
            )
            result = app.state.mcp_service.analyze(
                _mcp_chart_title(title_region, analysis_columns, request.chart_spec),
                analysis_columns,
                analysis_rows,
                request.chart_spec.model_dump() if request.chart_spec else None,
                **owner_options,
            )
            result["dataset"] = dataset
            app.state.history_service.record(
                kind="mcp",
                title=request.question,
                region=request.region,
                status="completed",
                summary=result.get("reason", ""),
                query_count=1 if dataset["source"].startswith("duckdb_") else 0,
                **history_options(http_request),
                **(
                    {
                        "queries": [{
                            "sql": dataset["query"],
                            "row_count": dataset["row_count"],
                            "success": True,
                        }]
                    }
                    if (
                        getattr(app.state.history_service, "user_scoped", False)
                        and dataset["source"].startswith("duckdb_")
                    )
                    else {}
                ),
            )
            return result
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error))

    @app.get("/api/mcp/analyses/{analysis_id}/assets/{name}")
    def mcp_analysis_asset(analysis_id: str, name: str, request: Request):
        owner_options = (
            {"owner_id": request.state.user["id"]}
            if getattr(app.state.history_service, "user_scoped", False)
            else {}
        )
        path = app.state.mcp_service.asset(analysis_id, name, **owner_options)
        if path is None:
            raise HTTPException(status_code=404, detail="MCP 분석 이미지를 찾을 수 없습니다.")
        return FileResponse(path)

    @app.get("/api/spatial/layer")
    def spatial_layer(region: str = Query(min_length=2, max_length=100)):
        return app.state.spatial_service.metadata(region)

    @app.get("/api/spatial/features")
    def spatial_features(
        region: str = Query(min_length=2, max_length=100),
        grades: str | None = Query(default=None, max_length=20),
        focus: str | None = Query(default=None, max_length=500),
        metric: str = Query(default="overall", min_length=1, max_length=50),
        limit: int = Query(default=0, ge=0, le=500000),
    ):
        selected_grades = grades.split(",") if grades else None
        focus_names = focus.split(",") if focus else None
        try:
            return app.state.spatial_service.features(
                region,
                selected_grades,
                limit,
                focus_names,
                metric,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.post("/api/spatial/exports", status_code=status.HTTP_201_CREATED)
    def spatial_export(request: SpatialExportRequest, http_request: Request):
        try:
            owner_options = (
                {"owner_id": http_request.state.user["id"]}
                if getattr(app.state.history_service, "user_scoped", False)
                else {}
            )
            exported = app.state.spatial_service.export_map(
                request.region,
                request.metric,
                request.grades,
                request.focus_names,
                request.background,
                request.extent,
                request.geometry,
                **owner_options,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        image_id = exported["image_id"]
        return {
            **exported,
            "image_url": f"/api/spatial/exports/{image_id}",
            "download_url": f"/api/spatial/exports/{image_id}/download",
        }

    def analyze_spatial_selection(request: SpatialSelectionRequest) -> dict:
        try:
            return app.state.spatial_service.analyze_selection(
                request.region,
                request.geometry,
                request.grades,
                request.metric,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.post("/api/spatial/selections")
    def spatial_selection(request: SpatialSelectionRequest):
        return analyze_spatial_selection(request)

    @app.post("/api/spatial/selections/compare")
    def spatial_selection_comparison(request: SpatialSelectionComparisonRequest):
        try:
            return app.state.spatial_service.compare_selections(
                request.region,
                request.geometry_a,
                request.geometry_b,
                request.grades,
                request.metric,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.post("/api/spatial/filter")
    def spatial_natural_filter(request: SpatialNaturalFilterRequest):
        try:
            return app.state.spatial_service.filter_from_question(
                request.region,
                request.question,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.post("/api/spatial/neighborhood")
    def spatial_neighborhood(request: SpatialNeighborhoodRequest):
        try:
            return app.state.spatial_service.analyze_neighborhood(
                request.region,
                request.ftr_id,
                request.distance_m,
                request.metric,
                request.grades,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.post("/api/spatial/hotspots")
    def spatial_hotspots(request: SpatialHotspotRequest):
        try:
            return app.state.spatial_service.analyze_hotspots(
                request.region,
                request.metric,
                request.grades,
                request.min_cluster_size,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.post("/api/spatial/query-scope")
    def spatial_query_scope(request: SpatialQueryScopeRequest):
        try:
            return app.state.spatial_service.scope_from_queries(
                request.region,
                request.queries,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.get("/api/spatial/features/{ftr_id}/explanation")
    def spatial_feature_explanation(
        ftr_id: str,
        region: str = Query(min_length=2, max_length=100),
        metric: str = Query(default="overall", min_length=1, max_length=50),
    ):
        try:
            return app.state.spatial_service.analyze_feature(region, ftr_id, metric)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.get("/api/spatial/scenarios")
    def spatial_scenarios(request: Request, limit: int = Query(default=100, ge=1, le=200)):
        return app.state.history_service.list_scenarios(
            limit,
            **history_options(request),
        )

    @app.post("/api/spatial/scenarios", status_code=status.HTTP_201_CREATED)
    def save_spatial_scenario(request: SpatialScenarioRequest, http_request: Request):
        return app.state.history_service.save_scenario(
            **request.model_dump(),
            **history_options(http_request),
        )

    @app.post("/api/spatial/scenarios/{scenario_id}/run")
    def run_spatial_scenario(scenario_id: str, request: Request):
        options = history_options(request)
        scenario = app.state.history_service.get_scenario(scenario_id, **options)
        if scenario is None:
            raise HTTPException(status_code=404, detail="공간분석 시나리오를 찾을 수 없습니다.")
        selection = SpatialSelectionRequest(
            region=scenario["region"],
            metric=scenario["metric"],
            grades=scenario["grades"],
            geometry=scenario["geometry"],
        )
        result = analyze_spatial_selection(selection)
        app.state.history_service.update_scenario_result(scenario_id, result, **options)
        return result

    @app.delete("/api/spatial/scenarios/{scenario_id}")
    def delete_spatial_scenario(scenario_id: str, request: Request):
        if not app.state.history_service.delete_scenario(
            scenario_id,
            **history_options(request),
        ):
            raise HTTPException(status_code=404, detail="공간분석 시나리오를 찾을 수 없습니다.")
        return {"id": scenario_id, "deleted": True}

    @app.post("/api/spatial/annotations", status_code=status.HTTP_201_CREATED)
    async def spatial_annotation(
        request: Request,
        files: list[UploadFile] = File(...),
    ):
        payload = []
        total_size = 0
        for uploaded in files:
            content = await uploaded.read()
            total_size += len(content)
            if total_size > 50 * 1024 * 1024:
                raise HTTPException(
                    status_code=413,
                    detail="업로드 파일은 합계 50MB 이하여야 합니다.",
                )
            payload.append((uploaded.filename or "", content))
        try:
            owner_options = (
                {"owner_id": request.state.user["id"]}
                if getattr(app.state.history_service, "user_scoped", False)
                else {}
            )
            return app.state.spatial_service.import_annotation(payload, **owner_options)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.get("/api/spatial/exports/{image_id}")
    def spatial_export_image(image_id: str, request: Request):
        owner_options = (
            {"owner_id": request.state.user["id"]}
            if getattr(app.state.history_service, "user_scoped", False)
            else {}
        )
        path = app.state.spatial_service.export_asset(image_id, **owner_options)
        if path is None:
            raise HTTPException(status_code=404, detail="공간분석 이미지를 찾을 수 없습니다.")
        return FileResponse(path)

    @app.get("/api/spatial/exports/{image_id}/download")
    def spatial_export_download(image_id: str, request: Request):
        owner_options = (
            {"owner_id": request.state.user["id"]}
            if getattr(app.state.history_service, "user_scoped", False)
            else {}
        )
        path = app.state.spatial_service.export_asset(image_id, **owner_options)
        if path is None:
            raise HTTPException(status_code=404, detail="공간분석 이미지를 찾을 수 없습니다.")
        return FileResponse(path, filename=path.name)

    @app.post("/api/reports", status_code=status.HTTP_202_ACCEPTED)
    def create_report(request: ReportRequest, http_request: Request):
        if app.state.report_dispatcher is not None:
            return app.state.report_dispatcher.submit(
                http_request.state.user["id"],
                request.model_dump(),
            )
        create_options = (
            {"owner_id": http_request.state.user["id"]}
            if getattr(app.state.history_service, "user_scoped", False)
            else {}
        )
        created = app.state.report_manager.create(request.model_dump(), **create_options)
        app.state.history_service.record(
            kind="report",
            title=f"{request.region or '전국'} 보고서 작성",
            region=request.region,
            status="running",
            job_id=created["job_id"],
            **history_options(http_request),
            **(
                {
                    "options": request.model_dump(exclude={"materials"}),
                    "materials": [item.model_dump() for item in request.materials],
                }
                if getattr(app.state.history_service, "user_scoped", False)
                else {}
            ),
        )
        return created

    @app.post("/api/reports/{job_id}/revisions")
    def revise_report(
        job_id: str,
        request: RevisionRequest,
        http_request: Request,
        response: Response,
    ):
        ensure_report_access(job_id, http_request)
        if app.state.report_dispatcher is not None:
            queued = app.state.report_dispatcher.submit_edit(
                http_request.state.user["id"],
                job_id,
                "revision",
                request.model_dump(),
            )
            if queued is None:
                raise HTTPException(
                    status_code=409,
                    detail="완료된 보고서만 수정할 수 있습니다.",
                )
            response.status_code = status.HTTP_202_ACCEPTED
            return queued
        ensure_report_loaded(job_id, http_request)
        try:
            revision = app.state.report_manager.revise(
                job_id,
                request.section,
                request.instruction,
            )
            if app.state.report_dispatcher is not None:
                app.state.report_dispatcher.persist(
                    app.state.report_manager.get(job_id)
                )
            app.state.history_service.record(
                kind="report_edit",
                title=f"{request.section} 대화 수정",
                region=None,
                status="completed",
                summary=request.instruction,
                job_id=job_id,
                **history_options(http_request),
            )
            return revision
        except KeyError:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.put("/api/reports/{job_id}/content")
    def save_report_content(
        job_id: str,
        request: ReportContentRequest,
        http_request: Request,
        response: Response,
    ):
        ensure_report_access(job_id, http_request)
        if app.state.report_dispatcher is not None:
            queued = app.state.report_dispatcher.submit_edit(
                http_request.state.user["id"],
                job_id,
                "content",
                request.model_dump(),
            )
            if queued is None:
                raise HTTPException(
                    status_code=409,
                    detail="완료된 보고서만 직접 편집할 수 있습니다.",
                )
            response.status_code = status.HTTP_202_ACCEPTED
            return queued
        ensure_report_loaded(job_id, http_request)
        try:
            revision = app.state.report_manager.save_content(job_id, request.markdown)
            if app.state.report_dispatcher is not None:
                app.state.report_dispatcher.persist(
                    app.state.report_manager.get(job_id)
                )
            app.state.history_service.record(
                kind="report_edit",
                title="보고서 직접 편집",
                region=None,
                status="completed",
                summary=f"v{revision['revision'] + 1} 저장",
                job_id=job_id,
                **history_options(http_request),
            )
            return revision
        except KeyError:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.get("/api/reports/{job_id}/content")
    def report_content(job_id: str, request: Request):
        ensure_report_access(job_id, request)
        ensure_report_loaded(job_id, request)
        path = app.state.report_manager.file(job_id, "md")
        if path is None:
            raise HTTPException(status_code=404, detail="편집할 보고서가 없습니다.")
        return {"markdown": path.read_text(encoding="utf-8")}

    @app.get("/api/reports/{job_id}/provenance")
    def report_provenance(job_id: str, request: Request):
        ensure_report_access(job_id, request)
        ensure_report_loaded(job_id, request)
        try:
            return app.state.report_manager.provenance(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error))

    @app.get("/api/reports/{job_id}/provenance/{evidence_id}")
    def report_provenance_detail(
        job_id: str,
        evidence_id: str,
        request: Request,
    ):
        ensure_report_access(job_id, request)
        ensure_report_loaded(job_id, request)
        try:
            return app.state.report_manager.provenance(job_id, evidence_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="문장 근거를 찾을 수 없습니다.")
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error))

    @app.get("/api/reports/{job_id}")
    def report_status(job_id: str, request: Request):
        ensure_report_access(job_id, request)
        if app.state.report_dispatcher is not None:
            job = app.state.report_dispatcher.get(request.state.user["id"], job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
            return job
        job = app.state.report_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        if job["status"] in {"completed", "failed"}:
            summary = "보고서 작성 완료" if job["status"] == "completed" else "보고서 작성 실패"
            app.state.history_service.update_report(
                job_id,
                job["status"],
                summary,
                **history_options(request),
            )
        return job

    @app.post("/api/reports/{job_id}/cancel")
    def cancel_report(job_id: str, request: Request):
        if app.state.report_dispatcher is None:
            raise HTTPException(status_code=409, detail="작업 큐가 활성화되지 않았습니다.")
        if not app.state.report_dispatcher.cancel(request.state.user["id"], job_id):
            raise HTTPException(status_code=409, detail="취소할 수 있는 작업이 아닙니다.")
        return {"job_id": job_id, "status": "cancel_requested"}

    @app.post("/api/reports/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
    def retry_report(job_id: str, request: Request):
        if app.state.report_dispatcher is None:
            raise HTTPException(status_code=409, detail="작업 큐가 활성화되지 않았습니다.")
        retried = app.state.report_dispatcher.retry(request.state.user["id"], job_id)
        if retried is None:
            raise HTTPException(status_code=409, detail="재시도할 수 있는 작업이 아닙니다.")
        return retried

    @app.get("/api/history")
    def analysis_history(
        request: Request,
        limit: int = Query(default=100, ge=1, le=200),
    ):
        return app.state.history_service.list(limit, **history_options(request))

    @app.get("/api/conversations")
    def conversations(
        request: Request,
        limit: int = Query(default=100, ge=1, le=200),
    ):
        return app.state.history_service.list_conversations(
            limit,
            **history_options(request),
        )

    @app.get("/api/conversations/{conversation_id}")
    def conversation(conversation_id: str, request: Request):
        saved = app.state.history_service.get_conversation(
            conversation_id,
            **history_options(request),
        )
        if saved is None:
            raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.")
        return saved

    @app.put("/api/conversations/{conversation_id}")
    def save_conversation(
        conversation_id: str,
        request: ConversationRequest,
        http_request: Request,
    ):
        try:
            return app.state.history_service.save_conversation(
                conversation_id,
                **request.model_dump(),
                **history_options(http_request),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, request: Request):
        try:
            deleted = app.state.history_service.delete_conversation(
                conversation_id,
                **history_options(request),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        if not deleted:
            raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.")
        return {"id": conversation_id, "deleted": True}

    @app.get("/api/reports/{job_id}/events")
    def report_events(job_id: str, request: Request, after: int = 0):
        ensure_report_access(job_id, request)
        if app.state.report_dispatcher is not None:
            user_id = request.state.user["id"]
            if app.state.report_dispatcher.get(user_id, job_id) is None:
                raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

            async def queued_event_stream():
                previous = None
                while True:
                    job = await run_in_threadpool(
                        app.state.report_dispatcher.get,
                        user_id,
                        job_id,
                    )
                    if job is None:
                        break
                    signature = (job["status"], job["stage"], job["progress"])
                    if signature != previous:
                        event_type = {
                            "completed": "job_completed",
                            "failed": "job_failed",
                            "cancelled": "job_cancelled",
                        }.get(job["status"], "stage_completed")
                        payload = json.dumps(job, ensure_ascii=False, default=str)
                        yield f"event: {event_type}\ndata: {payload}\n\n"
                        previous = signature
                    if job["status"] in {"completed", "failed", "cancelled"}:
                        break
                    await asyncio.sleep(1.0)

            return StreamingResponse(
                queued_event_stream(),
                media_type="text/event-stream",
            )
        if app.state.report_manager.get(job_id) is None:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

        async def event_stream():
            cursor = max(0, after)
            while True:
                events = app.state.report_manager.events(job_id)
                for event in events[cursor:]:
                    payload = json.dumps(event, ensure_ascii=False, default=str)
                    yield f"event: {event['type']}\ndata: {payload}\n\n"
                    cursor += 1
                job = app.state.report_manager.get(job_id)
                if job is None or job["status"] in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.2)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/reports/{job_id}/preview")
    def report_preview(job_id: str, request: Request):
        ensure_report_access(job_id, request)
        ensure_report_loaded(job_id, request)
        path = app.state.report_manager.file(job_id, "md")
        if path is None:
            raise HTTPException(status_code=404, detail="미리보기 파일이 없습니다.")
        markdown = path.read_text(encoding="utf-8")
        return {"markdown": _preview_markdown(markdown, job_id)}

    @app.get("/api/reports/{job_id}/download/{kind}")
    def report_download(
        job_id: str,
        kind: Literal["md", "hwpx"],
        request: Request,
    ):
        ensure_report_access(job_id, request)
        ensure_report_loaded(job_id, request)
        path = app.state.report_manager.file(job_id, kind)
        if path is None:
            raise HTTPException(status_code=404, detail="보고서 파일이 없습니다.")
        return FileResponse(path, filename=path.name)

    @app.get("/api/reports/{job_id}/assets/{name}")
    def report_asset(job_id: str, name: str, request: Request):
        ensure_report_access(job_id, request)
        ensure_report_loaded(job_id, request)
        path = app.state.report_manager.asset(job_id, name)
        if path is None:
            raise HTTPException(status_code=404, detail="이미지 파일이 없습니다.")
        return FileResponse(path)

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (frontend_dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API 경로를 찾을 수 없습니다.")
            candidate = (frontend_dist / path).resolve()
            if frontend_dist.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app
