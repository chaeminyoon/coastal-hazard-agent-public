import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from coastal_web.database import create_database_engine
from coastal_web.repositories import ConversationRepository, UserRepository
from sqlalchemy import inspect

WEB_ROOT = Path(__file__).resolve().parents[1]


def test_postgres_migration_and_user_isolation():
    database_url = os.environ.get("COASTAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("COASTAL_TEST_DATABASE_URL이 설정되지 않았습니다.")

    config = Config(str(WEB_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    assert "users" in inspect(engine).get_table_names()

    users = UserRepository(engine)
    conversations = ConversationRepository(engine)
    owner = users.create("postgres-owner", "hash")
    another = users.create("postgres-another", "hash")
    conversations.save(
        owner["id"],
        "postgres-session",
        title="PostgreSQL 테스트",
        region="부산광역시 수영구",
        messages=[{"id": "m1", "role": "user", "kind": "text", "text": "질문"}],
        analysis_context={},
        materials=[],
    )

    assert conversations.get(owner["id"], "postgres-session") is not None
    assert conversations.get(another["id"], "postgres-session") is None
