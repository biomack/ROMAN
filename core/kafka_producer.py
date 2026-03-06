from __future__ import annotations

from .config import Config
from .queue_backend import create_queue_backend


class EventProducer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.backend = create_queue_backend(cfg)

    def publish_event(self, session_id: str, payload: dict) -> None:
        self.backend.publish(
            topic=self.cfg.kafka_events_topic,
            key=session_id,
            value=payload,
        )

    def publish_outbox(self, session_id: str, payload: dict) -> None:
        self.backend.publish(
            topic=self.cfg.kafka_outbox_topic,
            key=session_id,
            value=payload,
        )
