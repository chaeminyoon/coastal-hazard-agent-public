from pathlib import Path

from sqlalchemy import create_engine, inspect

WEB_ROOT = Path(__file__).resolve().parents[1]


def test_initial_migration_creates_multi_user_schema(tmp_path):
    config_path = WEB_ROOT / "alembic.ini"
    assert config_path.is_file(), "Alembic 설정이 필요합니다."

    from alembic import command
    from alembic.config import Config

    database_path = tmp_path / "migration.db"
    config = Config(str(config_path))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+pysqlite:///{database_path.as_posix()}",
    )
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
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
