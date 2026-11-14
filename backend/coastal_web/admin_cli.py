from __future__ import annotations

import argparse
import getpass
import os

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from .auth import AuthService
from .database import create_database_engine


def create_admin(engine: Engine, username: str, password: str) -> dict:
    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    return AuthService(engine, secret_key="admin-bootstrap").create_user(
        username,
        password,
        role="admin",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="연안재해 에이전트 관리자 생성")
    parser.add_argument("username", help="생성할 관리자 아이디")
    args = parser.parse_args()

    database_url = os.environ.get("COASTAL_DATABASE_URL")
    if not database_url:
        parser.error("COASTAL_DATABASE_URL 설정이 필요합니다.")
    password = getpass.getpass("관리자 비밀번호: ")
    confirmation = getpass.getpass("관리자 비밀번호 확인: ")
    if password != confirmation:
        parser.error("비밀번호가 일치하지 않습니다.")

    engine = create_database_engine(database_url)
    try:
        created = create_admin(engine, args.username, password)
    except (IntegrityError, ValueError) as error:
        parser.error(str(error))
    finally:
        engine.dispose()
    print(f"관리자 '{created['username']}' 계정을 생성했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
