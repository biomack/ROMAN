"""
In-memory session storage for agent conversations.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from .metrics import get_metrics
from .skill_manager import Skill


@dataclass
class SessionData:
    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[dict[str, Any]] = field(default_factory=list)
    active_skills: dict[str, Skill] = field(default_factory=dict)
    session_state: dict[str, Any] = field(default_factory=dict)


class InMemorySessionStore:
    def __init__(self, ttl_seconds: int | None = None, max_messages: int | None = None):
        self.ttl_seconds = (
            int(os.getenv("SESSION_TTL_SECONDS", "3600"))
            if ttl_seconds is None
            else max(0, int(ttl_seconds))
        )
        self.max_messages = (
            int(os.getenv("SESSION_MAX_MESSAGES", "100"))
            if max_messages is None
            else max(1, int(max_messages))
        )
        self._sessions: dict[str, SessionData] = {}
        get_metrics().set_active_sessions(0)

    def get_or_create(self, session_id: str) -> SessionData:
        self._prune_expired()
        session = self._sessions.get(session_id)
        if session is None:
            session = SessionData(session_id=session_id)
            self._sessions[session_id] = session
            get_metrics().set_active_sessions(len(self._sessions))
        return session

    def save(self, session: SessionData) -> None:
        session.updated_at = time.time()
        if self.max_messages > 0 and len(session.messages) > self.max_messages:
            session.messages = session.messages[-self.max_messages :]
        self._sessions[session.session_id] = session
        get_metrics().set_active_sessions(len(self._sessions))

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        get_metrics().set_active_sessions(len(self._sessions))

    def _prune_expired(self) -> None:
        if self.ttl_seconds <= 0:
            return
        now = time.time()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session.updated_at > self.ttl_seconds
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        if expired:
            get_metrics().set_active_sessions(len(self._sessions))
