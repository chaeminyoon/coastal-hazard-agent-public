from coastal_web.auth import AuthService
from coastal_web.database import create_database_engine, metadata


def test_create_initial_admin_can_log_in():
    from coastal_web.admin_cli import create_admin

    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)

    created = create_admin(engine, "first-admin", "first-admin-password")

    assert created["role"] == "admin"
    assert AuthService(engine, secret_key="test").login(
        "first-admin",
        "first-admin-password",
    ) is not None
