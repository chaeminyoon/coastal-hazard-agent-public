from __future__ import annotations

import argparse
import os

from .auth import AuthService
from .database import create_database_engine


def main() -> int:
    parser = argparse.ArgumentParser(description="연안재해 에이전트 운영 정리")
    parser.add_argument(
        "command",
        choices=["purge-sessions"],
        help="실행할 유지보수 작업",
    )
    args = parser.parse_args()
    database_url = os.environ.get("COASTAL_DATABASE_URL")
    if not database_url:
        parser.error("COASTAL_DATABASE_URL 설정이 필요합니다.")

    engine = create_database_engine(database_url)
    try:
        if args.command == "purge-sessions":
            count = AuthService(
                engine,
                secret_key=os.environ.get(
                    "COASTAL_SESSION_SECRET",
                    "maintenance-only",
                ),
            ).purge_sessions()
            print(f"만료·폐기 세션 {count}건을 정리했습니다.")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
