from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default="default")
    source: str = Field(default="api")
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class EventAck(BaseModel):
    status: str = "queued"
    event_id: str
    session_id: str


class WorkerResult(BaseModel):
    event_id: str
    session_id: str
    response: str
    tools_called: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
