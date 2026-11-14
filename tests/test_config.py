import importlib
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_gateway_publish_address_is_configurable_and_private_by_default():
    compose = (PROJECT_ROOT / "deploy" / "compose.service.yml").read_text(
        encoding="utf-8"
    )
    example = (PROJECT_ROOT / ".env.service.example").read_text(encoding="utf-8")

    assert (
        '"${COASTAL_HTTP_BIND:-127.0.0.1}:${COASTAL_HTTP_PORT:-8080}:80"'
        in compose
    )
    assert "COASTAL_HTTP_BIND=127.0.0.1" in example


def test_settings_loads_multi_user_deployment_values(monkeypatch, tmp_path):
    spec = importlib.util.find_spec("coastal_web.config")
    assert spec is not None, "운영 환경설정 모듈이 필요합니다."

    module = importlib.import_module("coastal_web.config")
    settings_type = getattr(module, "Settings", None)
    assert settings_type is not None

    agent_root = tmp_path / "agent"
    artifact_root = tmp_path / "artifacts"
    agent_root.mkdir()
    artifact_root.mkdir()
    monkeypatch.setenv("COASTAL_ENV", "production")
    monkeypatch.setenv("COASTAL_AGENT_ROOT", str(agent_root))
    monkeypatch.setenv("COASTAL_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("COASTAL_DATABASE_URL", "postgresql://coastal:test@db/coastal")
    monkeypatch.setenv("COASTAL_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("COASTAL_SESSION_SECRET", "deployment-session-secret")
    monkeypatch.setenv(
        "COASTAL_ALLOWED_ORIGINS",
        "https://coastal.example.com, https://admin.example.com",
    )

    settings = settings_type.from_env()

    assert settings.environment == "production"
    assert settings.agent_root == agent_root.resolve()
    assert settings.artifact_root == artifact_root.resolve()
    assert settings.database_url == "postgresql://coastal:test@db/coastal"
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.session_secret == "deployment-session-secret"
    assert settings.allowed_origins == (
        "https://coastal.example.com",
        "https://admin.example.com",
    )
    assert settings.readiness_checks() == {
        "agent_root": True,
        "artifact_root": True,
    }
