from __future__ import annotations

import logging
import traceback
from pathlib import Path

from core import Agent, Config, SkillManager, create_client
from core.kafka_consumer import EventConsumer
from core.kafka_producer import EventProducer
from core.models import Event, WorkerResult
from core.session_store import InMemorySessionStore

LOG_FILE = Path(__file__).resolve().parent.parent / "agent_debug.log"


def _setup_logging():
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console_handler])


_setup_logging()


def build_agent(cfg: Config) -> Agent:
    if cfg.provider == "ollama":
        base_url = cfg.ollama_base_url
        model = cfg.ollama_model
    else:
        base_url = cfg.openai_base_url
        model = cfg.openai_model

    client = create_client(
        cfg.provider,
        ollama_base_url=base_url,
        ollama_model=model,
        openai_base_url=base_url,
        openai_model=model,
        openai_api_key=cfg.openai_api_key,
    )

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
    return Agent(client=client, skill_manager=skill_manager, session_store=session_store)


def run_worker() -> None:
    cfg = Config.load()
    consumer = EventConsumer(cfg)
    producer = EventProducer(cfg)
    agent = build_agent(cfg)
    processed_event_ids: set[str] = set()

    for msg in consumer.consume_events():
        try:
            event = Event.model_validate(msg.value)
        except Exception:
            msg.ack()
            continue

        if event.event_id in processed_event_ids:
            msg.ack()
            continue

        try:
            if event.metadata.get("control") == "reset_session":
                agent.reset(session_id=event.session_id)
                result = WorkerResult(
                    event_id=event.event_id,
                    session_id=event.session_id,
                    response=f"Session '{event.session_id}' reset.",
                    tools_called=[],
                )
            else:
                response = agent.chat(
                    event.text,
                    session_id=event.session_id,
                    metadata=event.metadata,
                )
                result = WorkerResult(
                    event_id=event.event_id,
                    session_id=event.session_id,
                    response=response,
                    tools_called=agent.get_last_tool_calls(event.session_id),
                )

            producer.publish_outbox(event.session_id, result.model_dump())
            processed_event_ids.add(event.event_id)
            msg.ack()
        except Exception as exc:
            error_result = WorkerResult(
                event_id=event.event_id,
                session_id=event.session_id,
                response="",
                tools_called=agent.get_last_tool_calls(event.session_id),
                error=f"{exc}\n{traceback.format_exc()}",
            )
            producer.publish_outbox(event.session_id, error_result.model_dump())
            processed_event_ids.add(event.event_id)
            msg.ack()


if __name__ == "__main__":
    run_worker()
