from __future__ import annotations

from fastapi import FastAPI

from core import Config, SkillManager
from core.kafka_producer import EventProducer
from core.models import Event, EventAck
from core.session_store import InMemorySessionStore


cfg = Config.load()
producer = EventProducer(cfg)
skill_manager = SkillManager(
    skills_dir=cfg.skills_dir,
    mcp_servers=cfg.mcp_servers,
    max_reference_file_bytes=cfg.reference_file_max_bytes,
    max_reference_total_bytes=cfg.reference_files_total_max_bytes,
)
session_store = InMemorySessionStore(
    ttl_seconds=cfg.session_ttl_seconds,
    max_messages=cfg.session_max_messages,
)

app = FastAPI(title="llm_new_skils API", version="0.1.0")


@app.get("/v1/health")
def health() -> dict:
    return {
        "status": "ok",
        "kafka_enabled": cfg.kafka_enabled,
        "events_topic": cfg.kafka_events_topic,
        "outbox_topic": cfg.kafka_outbox_topic,
    }


@app.post("/v1/events", response_model=EventAck)
def enqueue_event(event: Event) -> EventAck:
    producer.publish_event(event.session_id, event.model_dump())
    return EventAck(event_id=event.event_id, session_id=event.session_id)


@app.get("/v1/skills")
def list_skills() -> list[dict]:
    result = []
    for skill in skill_manager.skills.values():
        result.append(
            {
                "name": skill.name,
                "description": skill.description,
                "loaded": skill.loaded,
                "meta": skill.meta,
            }
        )
    return result


@app.post("/v1/sessions/{session_id}/reset")
def reset_session(session_id: str) -> dict:
    session_store.reset(session_id)
    control_event = Event(
        session_id=session_id,
        source="api",
        text=f"Reset session {session_id}",
        metadata={"control": "reset_session"},
    )
    producer.publish_event(session_id, control_event.model_dump())
    return {"status": "ok", "session_id": session_id, "event_id": control_event.event_id}
