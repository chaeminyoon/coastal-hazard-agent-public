from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGENT_ROOT = WEB_ROOT.parent / "analysis-engine"
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _origins(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_ALLOWED_ORIGINS
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    environment: str
    agent_root: Path
    artifact_root: Path
    database_url: str | None
    redis_url: str | None
    session_secret: str | None
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            environment=os.environ.get("COASTAL_ENV", "development"),
            agent_root=Path(
                os.environ.get("COASTAL_AGENT_ROOT", DEFAULT_AGENT_ROOT)
            ).resolve(),
            artifact_root=Path(
                os.environ.get("COASTAL_ARTIFACT_ROOT", WEB_ROOT / "outputs")
            ).resolve(),
            database_url=os.environ.get("COASTAL_DATABASE_URL"),
            redis_url=os.environ.get("COASTAL_REDIS_URL"),
            session_secret=os.environ.get("COASTAL_SESSION_SECRET"),
            allowed_origins=_origins(os.environ.get("COASTAL_ALLOWED_ORIGINS")),
        )

    def readiness_checks(self) -> dict[str, bool]:
        return {
            "agent_root": self.agent_root.is_dir(),
            "artifact_root": self.artifact_root.is_dir(),
        }
