from __future__ import annotations

from typing import Iterator

from .config import Config
from .queue_backend import ConsumedMessage, create_queue_backend


class EventConsumer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.backend = create_queue_backend(cfg)

    def consume_events(self) -> Iterator[ConsumedMessage]:
        yield from self.backend.consume(
            topic=self.cfg.kafka_events_topic,
            group_id=self.cfg.kafka_consumer_group,
        )
