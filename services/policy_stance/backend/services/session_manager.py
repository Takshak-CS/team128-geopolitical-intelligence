from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class SessionStore:
    _sessions: dict[str, Any] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._sessions[key] = value

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._sessions.get(key)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


session_store = SessionStore()
