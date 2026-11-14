import hashlib
import importlib
import importlib.util
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select

from coastal_web.database import metadata, user_sessions, users
from coastal_web.database import create_database_engine


def _auth_module():
    spec = importlib.util.find_spec("coastal_web.auth")
    assert spec is not None, "다중 사용자 인증 모듈이 필요합니다."
    return importlib.import_module("coastal_web.auth")


def _service():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    service = _auth_module().AuthService(engine, secret_key="test-secret")
    return engine, service


def test_auth_service_stores_password_and_session_as_hashes():
    engine, service = _service()
    created = service.create_user("coastal-user", "very-long-password", role="user")

    login = service.login("coastal-user", "very-long-password", ip_address="127.0.0.1")

    assert login is not None
    assert login["user"] == {
        "id": created["id"],
        "username": "coastal-user",
        "role": "user",
    }
    assert service.authenticate(login["session_token"])["id"] == created["id"]
    assert service.validate_csrf(login["session_token"], login["csrf_token"]) is True
    with engine.connect() as connection:
        password_hash = connection.scalar(
            select(users.c.password_hash).where(users.c.id == created["id"])
        )
        token_hash = connection.scalar(select(user_sessions.c.token_hash))
    assert password_hash != "very-long-password"
    assert token_hash == hashlib.sha256(login["session_token"].encode()).hexdigest()


def test_auth_service_rejects_wrong_password_and_revoked_session():
    _engine, service = _service()
    service.create_user("admin-user", "correct-password", role="admin")

    assert service.login("admin-user", "wrong-password") is None
    login = service.login("admin-user", "correct-password")
    assert login["user"]["role"] == "admin"
    assert service.logout(login["session_token"]) is True
    assert service.authenticate(login["session_token"]) is None
    assert service.logout(login["session_token"]) is False


def test_auth_service_rejects_csrf_token_from_another_session():
    _engine, service = _service()
    service.create_user("user-1", "password-1")
    service.create_user("user-2", "password-2")
    first = service.login("user-1", "password-1")
    second = service.login("user-2", "password-2")

    assert service.validate_csrf(first["session_token"], second["csrf_token"]) is False


def test_user_can_change_password_and_other_sessions_are_revoked():
    _engine, service = _service()
    user = service.create_user("user-1", "password-1")
    current = service.login("user-1", "password-1")
    other = service.login("user-1", "password-1")

    assert service.change_password(
        user["id"],
        "password-1",
        "password-2",
        current_token=current["session_token"],
    ) is True
    assert service.login("user-1", "password-1") is None
    assert service.login("user-1", "password-2") is not None
    assert service.authenticate(current["session_token"]) is not None
    assert service.authenticate(other["session_token"]) is None
    assert service.change_password(
        user["id"],
        "wrong",
        "password-3",
        current_token=current["session_token"],
    ) is False


def test_admin_reset_password_revokes_all_user_sessions():
    _engine, service = _service()
    user = service.create_user("user-1", "password-1")
    login = service.login("user-1", "password-1")

    assert service.reset_password(user["id"], "password-reset") is True
    assert service.authenticate(login["session_token"]) is None
    assert service.login("user-1", "password-reset") is not None
    assert service.reset_password("missing", "password-reset") is False


def test_user_can_list_and_revoke_own_sessions():
    _engine, service = _service()
    user = service.create_user("user-1", "password-1")
    first = service.login("user-1", "password-1", ip_address="10.0.0.1")
    second = service.login("user-1", "password-1", ip_address="10.0.0.2")

    sessions = service.list_sessions(user["id"], current_token=first["session_token"])
    assert len(sessions) == 2
    assert next(item for item in sessions if item["current"])["created_ip"] == "10.0.0.1"
    other = next(item for item in sessions if not item["current"])
    assert service.revoke_session(user["id"], other["id"]) is True
    assert service.authenticate(second["session_token"]) is None


def test_expired_and_old_revoked_sessions_can_be_purged():
    engine, service = _service()
    user = service.create_user("user-1", "password-1")
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(insert(user_sessions), [
            {
                "token_hash": "a" * 64,
                "user_id": user["id"],
                "expires_at": now - timedelta(days=1),
                "created_at": now - timedelta(days=2),
                "revoked_at": None,
                "created_ip": None,
            },
            {
                "token_hash": "b" * 64,
                "user_id": user["id"],
                "expires_at": now + timedelta(days=1),
                "created_at": now - timedelta(days=40),
                "revoked_at": now - timedelta(days=31),
                "created_ip": None,
            },
        ])

    assert service.purge_sessions() == 2
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(user_sessions)) == 0
