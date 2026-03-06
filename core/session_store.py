from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionData:
    session_id: str
    messages: list[dict] = field(default_factory=list)
    active_skills: dict[str, Any] = field(default_factory=dict)
    session_state: dict[str, Any] = field(default_factory=dict)
    expires_at: float = 0.0


class InMemorySessionStore:
    def __init__(self, ttl_seconds: int = 3600, max_messages: int = 100):
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages
        self._sessions: dict[str, SessionData] = {}

    def get_or_create(self, session_id: str) -> SessionData:
        self._cleanup_expired()
        now = time.time()
        session = self._sessions.get(session_id)
        if session is None:
            session = SessionData(session_id=session_id, expires_at=now + self.ttl_seconds)
            self._sessions[session_id] = session
        else:
            session.expires_at = now + self.ttl_seconds
        return session

    def save(self, session: SessionData) -> None:
        if self.max_messages > 0 and len(session.messages) > self.max_messages:
            session.messages = session.messages[-self.max_messages :]
        session.expires_at = time.time() + self.ttl_seconds
        self._sessions[session.session_id] = session

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def clear(self) -> None:
        self._sessions.clear()

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expires_at <= now
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)
