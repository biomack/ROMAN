"""
Prometheus metrics for ROMAN agent runtime and LLM usage.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    _PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover - defensive fallback
    Counter = Gauge = Histogram = None  # type: ignore[assignment]
    _PROMETHEUS_AVAILABLE = False

    def start_http_server(*_args, **_kwargs):  # type: ignore[no-redef]
        return None

logger = logging.getLogger(__name__)


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


@dataclass
class UsageStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_usage(cls, usage: dict | None) -> "UsageStats":
        usage = usage or {}
        prompt = _safe_int(usage.get("prompt_tokens"))
        completion = _safe_int(usage.get("completion_tokens"))
        total = _safe_int(usage.get("total_tokens"))
        if total == 0:
            total = prompt + completion
        return cls(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


class AgentMetrics:
    def __init__(self):
        self._process_started_at = time.time()
        self._server_started = False
        self._lock = threading.Lock()

        if not _PROMETHEUS_AVAILABLE:
            logger.warning(
                "prometheus_client is not installed, metrics are disabled. "
                "Install dependencies from requirements.txt."
            )
            self.llm_requests_total = _NoopMetric()
            self.llm_request_duration_seconds = _NoopMetric()
            self.llm_tokens_total = _NoopMetric()
            self.user_responses_total = _NoopMetric()
            self.user_response_duration_seconds = _NoopMetric()
            self.user_response_tokens_total = _NoopMetric()
            self.turn_tokens_total = _NoopMetric()
            self.tool_calls_total = _NoopMetric()
            self.errors_total = _NoopMetric()
            self.active_sessions = _NoopMetric()
            self.uptime_seconds = _NoopMetric()
            return

        self.llm_requests_total = Counter(
            "roman_agent_llm_requests_total",
            "Total number of outbound LLM API requests.",
            ["provider", "model", "status"],
        )
        self.llm_request_duration_seconds = Histogram(
            "roman_agent_llm_request_duration_seconds",
            "Duration of outbound LLM API requests.",
            ["provider", "model"],
            buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
        )
        self.llm_tokens_total = Counter(
            "roman_agent_llm_tokens_total",
            "Total LLM token usage by token type.",
            ["provider", "model", "token_type"],
        )
        self.user_responses_total = Counter(
            "roman_agent_user_responses_total",
            "Total number of handled user turns.",
            ["source", "status"],
        )
        self.user_response_duration_seconds = Histogram(
            "roman_agent_user_response_duration_seconds",
            "End-to-end response time for user requests.",
            ["source", "status"],
            buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 180, 300),
        )
        self.user_response_tokens_total = Counter(
            "roman_agent_user_response_tokens_total",
            "Completion tokens spent on final user-facing responses.",
            ["source"],
        )
        self.turn_tokens_total = Counter(
            "roman_agent_turn_tokens_total",
            "Total tokens spent per user turn (all internal rounds).",
            ["source"],
        )
        self.tool_calls_total = Counter(
            "roman_agent_tool_calls_total",
            "Total number of tool calls executed by the agent.",
            ["tool_name", "status"],
        )
        self.errors_total = Counter(
            "roman_agent_errors_total",
            "Total number of errors in major agent components.",
            ["component"],
        )
        self.active_sessions = Gauge(
            "roman_agent_active_sessions",
            "Current number of active in-memory sessions.",
        )
        self.uptime_seconds = Gauge(
            "roman_agent_uptime_seconds",
            "Agent process uptime in seconds.",
        )
        self.uptime_seconds.set_function(lambda: max(0.0, time.time() - self._process_started_at))

    def start_server(self, host: str, port: int) -> None:
        if not _PROMETHEUS_AVAILABLE:
            return
        with self._lock:
            if self._server_started:
                return
            start_http_server(port=int(port), addr=host)
            self._server_started = True
        logger.info("Prometheus metrics server started on %s:%s", host, port)

    def observe_llm_request(
        self,
        *,
        provider: str,
        model: str,
        duration_seconds: float,
        status: str,
        usage: dict | None,
    ) -> UsageStats:
        provider = provider or "unknown"
        model = model or "unknown"
        status = status or "unknown"

        self.llm_requests_total.labels(provider=provider, model=model, status=status).inc()
        self.llm_request_duration_seconds.labels(provider=provider, model=model).observe(
            max(0.0, float(duration_seconds))
        )

        stats = UsageStats.from_usage(usage)
        self.llm_tokens_total.labels(
            provider=provider, model=model, token_type="prompt"
        ).inc(stats.prompt_tokens)
        self.llm_tokens_total.labels(
            provider=provider, model=model, token_type="completion"
        ).inc(stats.completion_tokens)
        self.llm_tokens_total.labels(
            provider=provider, model=model, token_type="total"
        ).inc(stats.total_tokens)
        return stats

    def observe_user_turn(
        self,
        *,
        source: str,
        status: str,
        duration_seconds: float,
        turn_total_tokens: int,
        user_response_tokens: int,
    ) -> None:
        source = source or "unknown"
        status = status or "unknown"
        self.user_responses_total.labels(source=source, status=status).inc()
        self.user_response_duration_seconds.labels(source=source, status=status).observe(
            max(0.0, float(duration_seconds))
        )
        self.turn_tokens_total.labels(source=source).inc(_safe_int(turn_total_tokens))
        self.user_response_tokens_total.labels(source=source).inc(_safe_int(user_response_tokens))

    def observe_tool_call(self, tool_name: str, status: str) -> None:
        self.tool_calls_total.labels(
            tool_name=tool_name or "unknown",
            status=status or "unknown",
        ).inc()

    def observe_error(self, component: str) -> None:
        self.errors_total.labels(component=component or "unknown").inc()

    def set_active_sessions(self, value: int) -> None:
        self.active_sessions.set(_safe_int(value))


class _NoopMetric:
    def labels(self, **_kwargs):
        return self

    def inc(self, *_args, **_kwargs):
        return None

    def observe(self, *_args, **_kwargs):
        return None

    def set(self, *_args, **_kwargs):
        return None

    def set_function(self, *_args, **_kwargs):
        return None


_METRICS = AgentMetrics()


def get_metrics() -> AgentMetrics:
    return _METRICS
