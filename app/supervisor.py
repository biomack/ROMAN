from __future__ import annotations

import time
from uuid import uuid4

from core import Config
from core.kafka_producer import EventProducer
from core.models import Event


def run_supervisor() -> None:
    cfg = Config.load()
    producer = EventProducer(cfg)
    interval = max(5, cfg.supervisor_interval_seconds)

    while True:
        services = cfg.supervisor_services or ["default-service"]
        for service in services:
            event = Event(
                event_id=str(uuid4()),
                session_id=f"supervisor:{service}",
                source="supervisor",
                text=f"Run health-check for service '{service}' and summarize status.",
                metadata={"service": service, "kind": "scheduled_health_check"},
            )
            producer.publish_event(event.session_id, event.model_dump())
        time.sleep(interval)


if __name__ == "__main__":
    run_supervisor()
