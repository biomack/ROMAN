from __future__ import annotations

import json
import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from .config import Config

try:
    from kafka import KafkaConsumer, KafkaProducer
except Exception:  # pragma: no cover - optional runtime dependency in local dev
    KafkaConsumer = None
    KafkaProducer = None


@dataclass
class ConsumedMessage:
    topic: str
    key: str
    value: dict
    ack: callable


class QueueBackend(ABC):
    @abstractmethod
    def publish(self, topic: str, key: str, value: dict) -> None:
        ...

    @abstractmethod
    def consume(self, topic: str, group_id: str) -> Iterator[ConsumedMessage]:
        ...


_LOCAL_QUEUES: dict[str, queue.Queue] = {}
_LOCAL_LOCK = threading.Lock()


class LocalQueueBackend(QueueBackend):
    def publish(self, topic: str, key: str, value: dict) -> None:
        with _LOCAL_LOCK:
            if topic not in _LOCAL_QUEUES:
                _LOCAL_QUEUES[topic] = queue.Queue()
            topic_queue = _LOCAL_QUEUES[topic]
        topic_queue.put({"key": key, "value": value})

    def consume(self, topic: str, group_id: str) -> Iterator[ConsumedMessage]:
        del group_id
        with _LOCAL_LOCK:
            if topic not in _LOCAL_QUEUES:
                _LOCAL_QUEUES[topic] = queue.Queue()
            topic_queue = _LOCAL_QUEUES[topic]
        while True:
            try:
                msg = topic_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            yield ConsumedMessage(
                topic=topic,
                key=str(msg.get("key", "")),
                value=msg.get("value", {}),
                ack=lambda: None,
            )


class KafkaQueueBackend(QueueBackend):
    def __init__(self, bootstrap_servers: str):
        if KafkaProducer is None or KafkaConsumer is None:
            raise RuntimeError("kafka-python is not installed.")
        self.bootstrap_servers = bootstrap_servers
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: str(k).encode("utf-8"),
            retries=3,
        )

    def publish(self, topic: str, key: str, value: dict) -> None:
        future = self._producer.send(topic, key=key, value=value)
        future.get(timeout=10)

    def consume(self, topic: str, group_id: str) -> Iterator[ConsumedMessage]:
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=self.bootstrap_servers,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            key_deserializer=lambda v: v.decode("utf-8") if v else "",
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        for msg in consumer:
            yield ConsumedMessage(
                topic=msg.topic,
                key=msg.key or "",
                value=msg.value or {},
                ack=consumer.commit,
            )


def create_queue_backend(cfg: Config) -> QueueBackend:
    if cfg.kafka_enabled:
        return KafkaQueueBackend(cfg.kafka_bootstrap_servers)
    return LocalQueueBackend()
