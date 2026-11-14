from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)

users = Table(
    "users",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("username", String(100), nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(20), nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("username"),
    CheckConstraint("role IN ('admin', 'user')", name="valid_role"),
)

user_sessions = Table(
    "user_sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_ip", String(64)),
)

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title", String(120), nullable=False),
    Column("region", String(100)),
    Column("summary", String(500), nullable=False),
    Column("message_count", Integer, nullable=False),
    Column("analysis_context", JSON, nullable=False),
    Column("materials", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

analysis_scenarios = Table(
    "analysis_scenarios",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(120), nullable=False),
    Column("region", String(100), nullable=False),
    Column("metric", String(50), nullable=False),
    Column("grades", JSON, nullable=False),
    Column("geometry", JSON, nullable=False),
    Column("latest_result", JSON),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("last_run_at", DateTime(timezone=True)),
)

messages = Table(
    "messages",
    metadata,
    Column("id", String(100), primary_key=True),
    Column(
        "conversation_id",
        String(100),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    ),
    Column("position", Integer, nullable=False),
    Column("role", String(20), nullable=False),
    Column("kind", String(50)),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("conversation_id", "position"),
)

analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("conversation_id", String(100), ForeignKey("conversations.id", ondelete="SET NULL")),
    Column("question", String(1000), nullable=False),
    Column("kind", String(30), nullable=False, server_default="query"),
    Column("region", String(100)),
    Column("status", String(30), nullable=False),
    Column("answer", Text),
    Column("grounded", Boolean),
    Column("query_count", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
)

sql_executions = Table(
    "sql_executions",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "analysis_run_id",
        String(32),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", Integer, nullable=False),
    Column("sql", Text, nullable=False),
    Column("row_count", Integer),
    Column("duration_ms", Float),
    Column("success", Boolean, nullable=False),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("analysis_run_id", "position"),
)

report_jobs = Table(
    "report_jobs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("conversation_id", String(100), ForeignKey("conversations.id", ondelete="SET NULL")),
    Column("region", String(100)),
    Column("status", String(30), nullable=False),
    Column("stage", String(30)),
    Column("progress", Integer, nullable=False),
    Column("options", JSON, nullable=False),
    Column("result", JSON, nullable=False),
    Column("errors", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
)

report_materials = Table(
    "report_materials",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "report_job_id",
        String(32),
        ForeignKey("report_jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("report_job_id", "position"),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("report_job_id", String(32), ForeignKey("report_jobs.id", ondelete="SET NULL")),
    Column("kind", String(50), nullable=False),
    Column("storage_key", String(500), nullable=False),
    Column("filename", String(255), nullable=False),
    Column("content_type", String(100)),
    Column("size_bytes", BigInteger),
    Column("sha256", String(64)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("storage_key"),
)

provenance_entries = Table(
    "provenance_entries",
    metadata,
    Column("id", String(100), primary_key=True),
    Column(
        "report_job_id",
        String(32),
        ForeignKey("report_jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("section", String(150)),
    Column("sentence", Text, nullable=False),
    Column("grounded", Boolean, nullable=False),
    Column("evidence", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(32), ForeignKey("users.id", ondelete="SET NULL")),
    Column("action", String(100), nullable=False),
    Column("resource_type", String(100)),
    Column("resource_id", String(100)),
    Column("details", JSON, nullable=False),
    Column("ip_address", String(64)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def create_database_engine(database_url: str) -> Engine:
    options = {"pool_pre_ping": True}
    if database_url.startswith("sqlite") and ":memory:" in database_url:
        options.update(
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    engine = create_engine(database_url, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
