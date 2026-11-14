from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from pwdlib import PasswordHash
from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.engine import Engine

from .database import user_sessions, users
from .repositories import UserRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, engine: Engine, *, secret_key: str, session_hours: int = 8):
        self.engine = engine
        self.secret_key = secret_key.encode()
        self.session_hours = session_hours
        self.passwords = PasswordHash.recommended()

    def create_user(self, username: str, password: str, role: str = "user") -> dict:
        created = UserRepository(self.engine).create(
            username,
            self.passwords.hash(password),
            role=role,
        )
        return {
            "id": created["id"],
            "username": created["username"],
            "role": created["role"],
        }

    def login(
        self,
        username: str,
        password: str,
        *,
        ip_address: str | None = None,
    ) -> dict | None:
        self.purge_sessions()
        with self.engine.connect() as connection:
            user = connection.execute(
                select(users).where(users.c.username == username)
            ).mappings().first()
        if user is None or not user["is_active"]:
            return None
        if not self.passwords.verify(password, user["password_hash"]):
            return None

        token = secrets.token_urlsafe(32)
        now = _now()
        with self.engine.begin() as connection:
            connection.execute(
                insert(user_sessions).values(
                    token_hash=_token_hash(token),
                    user_id=user["id"],
                    expires_at=now + timedelta(hours=self.session_hours),
                    created_at=now,
                    revoked_at=None,
                    created_ip=ip_address,
                )
            )
        return {
            "session_token": token,
            "csrf_token": self._csrf_token(token),
            "user": self._public_user(user),
        }

    def authenticate(self, token: str) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    users.c.id,
                    users.c.username,
                    users.c.role,
                    users.c.is_active,
                    user_sessions.c.expires_at,
                    user_sessions.c.revoked_at,
                )
                .select_from(
                    user_sessions.join(users, user_sessions.c.user_id == users.c.id)
                )
                .where(user_sessions.c.token_hash == _token_hash(token))
            ).mappings().first()
        if row is None or not row["is_active"] or row["revoked_at"] is not None:
            return None
        if _aware(row["expires_at"]) <= _now():
            return None
        return self._public_user(row)

    def validate_csrf(self, token: str, csrf_token: str) -> bool:
        if self.authenticate(token) is None:
            return False
        return hmac.compare_digest(self._csrf_token(token), csrf_token)

    def csrf_token(self, token: str) -> str:
        return self._csrf_token(token)

    def logout(self, token: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(user_sessions)
                .where(
                    user_sessions.c.token_hash == _token_hash(token),
                    user_sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=_now())
            )
        return result.rowcount > 0

    def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
        *,
        current_token: str,
    ) -> bool:
        with self.engine.connect() as connection:
            user = connection.execute(
                select(users.c.password_hash).where(users.c.id == user_id)
            ).mappings().first()
        if user is None or not self.passwords.verify(
            current_password,
            user["password_hash"],
        ):
            return False
        current_hash = _token_hash(current_token)
        now = _now()
        with self.engine.begin() as connection:
            connection.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(
                    password_hash=self.passwords.hash(new_password),
                    updated_at=now,
                )
            )
            connection.execute(
                update(user_sessions)
                .where(
                    user_sessions.c.user_id == user_id,
                    user_sessions.c.token_hash != current_hash,
                    user_sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        return True

    def reset_password(self, user_id: str, new_password: str) -> bool:
        now = _now()
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(
                    password_hash=self.passwords.hash(new_password),
                    updated_at=now,
                )
            )
            if updated.rowcount == 0:
                return False
            connection.execute(
                update(user_sessions)
                .where(
                    user_sessions.c.user_id == user_id,
                    user_sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        return True

    def list_sessions(self, user_id: str, *, current_token: str) -> list[dict]:
        current_hash = _token_hash(current_token)
        now = _now()
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(user_sessions)
                .where(
                    user_sessions.c.user_id == user_id,
                    user_sessions.c.revoked_at.is_(None),
                    user_sessions.c.expires_at > now,
                )
                .order_by(user_sessions.c.created_at.desc())
            ).mappings().all()
        return [{
            "id": row["token_hash"],
            "current": row["token_hash"] == current_hash,
            "created_at": _aware(row["created_at"]).isoformat(),
            "expires_at": _aware(row["expires_at"]).isoformat(),
            "created_ip": row["created_ip"],
        } for row in rows]

    def revoke_session(self, user_id: str, session_id: str) -> bool:
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(user_sessions)
                .where(
                    user_sessions.c.user_id == user_id,
                    user_sessions.c.token_hash == session_id,
                    user_sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=_now())
            )
        return updated.rowcount > 0

    def purge_sessions(self, *, revoked_retention_days: int = 30) -> int:
        now = _now()
        revoked_cutoff = now - timedelta(days=revoked_retention_days)
        with self.engine.begin() as connection:
            deleted = connection.execute(
                delete(user_sessions).where(or_(
                    user_sessions.c.expires_at <= now,
                    user_sessions.c.revoked_at <= revoked_cutoff,
                ))
            )
        return deleted.rowcount

    def list_users(self) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    users.c.id,
                    users.c.username,
                    users.c.role,
                    users.c.is_active,
                    users.c.created_at,
                ).order_by(users.c.created_at, users.c.username)
            ).mappings()
            return [dict(row) for row in rows]

    def set_user_active(self, user_id: str, is_active: bool) -> dict | None:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(is_active=is_active)
            )
            if result.rowcount == 0:
                return None
            user = connection.execute(
                select(
                    users.c.id,
                    users.c.username,
                    users.c.role,
                    users.c.is_active,
                    users.c.created_at,
                ).where(users.c.id == user_id)
            ).mappings().one()
        return dict(user)

    def _csrf_token(self, token: str) -> str:
        return hmac.new(self.secret_key, token.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _public_user(user) -> dict:
        return {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
        }
