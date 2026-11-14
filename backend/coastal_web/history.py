from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


class HistoryService:
    def __init__(self, path: Path | str | None = None):
        web_root = Path(__file__).resolve().parents[2]
        self.path = Path(path or web_root / "outputs" / "history.json").resolve()
        self.conversation_path = self.path.with_name("conversations.json")
        self.scenario_path = self.path.with_name("spatial_scenarios.json")
        self.lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def _write(self, entries: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(entries[:500], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def record(
        self,
        *,
        kind: str,
        title: str,
        region: str | None,
        status: str,
        summary: str = "",
        query_count: int = 0,
        grounded: bool | None = None,
        job_id: str | None = None,
    ) -> dict:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "title": title,
            "region": region,
            "status": status,
            "summary": summary[:500],
            "query_count": int(query_count),
            "grounded": grounded,
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.lock:
            entries = self._read()
            entries.insert(0, entry)
            self._write(entries)
        return entry

    def list(self, limit: int = 100) -> list[dict]:
        with self.lock:
            return self._read()[: max(1, min(int(limit), 200))]

    def update_report(self, job_id: str, status: str, summary: str = "") -> None:
        with self.lock:
            entries = self._read()
            entry = next(
                (
                    item
                    for item in entries
                    if item.get("kind") == "report" and item.get("job_id") == job_id
                ),
                None,
            )
            if entry is None:
                return
            entry["status"] = status
            if summary:
                entry["summary"] = summary[:500]
            self._write(entries)

    def _read_conversations(self) -> list[dict]:
        if not self.conversation_path.is_file():
            return []
        try:
            value = json.loads(self.conversation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def _write_conversations(self, conversations: list[dict]) -> None:
        self.conversation_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.conversation_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(conversations[:200], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.conversation_path)

    @staticmethod
    def _conversation_summary(messages: list[dict]) -> str:
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            value = message.get("text")
            if not value and isinstance(message.get("query"), dict):
                value = message["query"].get("answer")
            if not value and isinstance(message.get("comparison"), dict):
                value = message["comparison"].get("answer")
            if value:
                return str(value)[:500]
        return ""

    def save_conversation(
        self,
        conversation_id: str,
        *,
        title: str,
        region: str | None,
        messages: list[dict],
        analysis_context: dict,
        materials: list[dict],
    ) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", conversation_id):
            raise ValueError("올바르지 않은 대화 세션 ID입니다.")
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            conversations = self._read_conversations()
            previous = next(
                (item for item in conversations if item.get("id") == conversation_id),
                None,
            )
            saved = {
                "id": conversation_id,
                "title": title[:120],
                "region": region,
                "messages": messages[:200],
                "analysis_context": analysis_context,
                "materials": materials[:10],
                "created_at": previous.get("created_at", now) if previous else now,
                "updated_at": now,
            }
            conversations = [
                item for item in conversations if item.get("id") != conversation_id
            ]
            conversations.insert(0, saved)
            self._write_conversations(conversations)
        return saved

    def list_conversations(self, limit: int = 100) -> list[dict]:
        with self.lock:
            conversations = self._read_conversations()
        return [
            {
                "id": item.get("id"),
                "title": item.get("title", "새 대화"),
                "region": item.get("region"),
                "summary": self._conversation_summary(item.get("messages") or []),
                "message_count": len(item.get("messages") or []),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
            for item in conversations[: max(1, min(int(limit), 200))]
        ]

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self.lock:
            return next(
                (
                    item
                    for item in self._read_conversations()
                    if item.get("id") == conversation_id
                ),
                None,
            )

    def delete_conversation(self, conversation_id: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", conversation_id):
            raise ValueError("올바르지 않은 대화 세션 ID입니다.")
        with self.lock:
            conversations = self._read_conversations()
            remaining = [
                item for item in conversations if item.get("id") != conversation_id
            ]
            if len(remaining) == len(conversations):
                return False
            self._write_conversations(remaining)
        return True

    def _read_scenarios(self) -> list[dict]:
        if not self.scenario_path.is_file():
            return []
        try:
            value = json.loads(self.scenario_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def _write_scenarios(self, scenarios: list[dict]) -> None:
        self.scenario_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.scenario_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(scenarios[:200], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.scenario_path)

    def save_scenario(self, **payload) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        saved = {
            "id": uuid.uuid4().hex,
            **payload,
            "latest_result": None,
            "created_at": now,
            "updated_at": now,
            "last_run_at": None,
        }
        with self.lock:
            scenarios = self._read_scenarios()
            scenarios.insert(0, saved)
            self._write_scenarios(scenarios)
        return saved

    def list_scenarios(self, limit: int = 100) -> list[dict]:
        with self.lock:
            return self._read_scenarios()[: max(1, min(int(limit), 200))]

    def get_scenario(self, scenario_id: str) -> dict | None:
        with self.lock:
            return next(
                (item for item in self._read_scenarios() if item.get("id") == scenario_id),
                None,
            )

    def update_scenario_result(self, scenario_id: str, result: dict) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            scenarios = self._read_scenarios()
            selected = next((item for item in scenarios if item.get("id") == scenario_id), None)
            if selected is None:
                return False
            selected["latest_result"] = result
            selected["updated_at"] = now
            selected["last_run_at"] = now
            self._write_scenarios(scenarios)
        return True

    def delete_scenario(self, scenario_id: str) -> bool:
        with self.lock:
            scenarios = self._read_scenarios()
            remaining = [item for item in scenarios if item.get("id") != scenario_id]
            if len(remaining) == len(scenarios):
                return False
            self._write_scenarios(remaining)
        return True
