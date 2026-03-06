from __future__ import annotations

from typing import Any

from .models import Event


def mattermost_event_to_event(payload: dict[str, Any]) -> Event:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    post = data.get("post", {}) if isinstance(data.get("post"), dict) else {}

    thread_id = post.get("root_id") or post.get("id") or ""
    channel_id = post.get("channel_id") or "mattermost"
    session_id = thread_id or channel_id

    text = post.get("message", "") if isinstance(post, dict) else ""
    metadata = {
        "platform": "mattermost",
        "channel_id": channel_id,
        "thread_id": thread_id,
        "user_id": post.get("user_id") if isinstance(post, dict) else "",
    }

    return Event(
        session_id=session_id,
        source="mattermost",
        text=text,
        metadata=metadata,
    )
