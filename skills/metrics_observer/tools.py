"""
Local tools for metrics_observer skill.
MCP tools (query, query_range, etc.) are provided by the VictoriaMetrics MCP server.
"""

import json
import re
from typing import Annotated, Any, Literal

from core.tool_registry import tool

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cpu": ("cpu", "core", "load"),
    "memory": ("memory", "mem", "rss", "heap", "oom"),
    "disk": ("disk", "fs", "filesystem", "io", "iops", "storage"),
    "network": ("network", "net", "traffic", "bandwidth", "packet", "tcp", "udp"),
    "latency": ("latency", "duration", "response", "p95", "p99", "percentile"),
    "error": ("error", "5xx", "4xx", "exception", "failure"),
    "availability": ("availability", "uptime", "downtime", "slo", "sla"),
    "kubernetes": ("k8s", "kube", "pod", "namespace", "node", "deployment", "statefulset"),
    "postgres": ("postgres", "postgresql", "pg_", "database", "db", "sql"),
    "http": ("http", "request", "rps", "qps", "throughput"),
}


def _guess_target_label(target_value: str, target_label: str) -> str:
    if target_label != "auto":
        return target_label

    value = (target_value or "").strip()
    if not value:
        return "service"
    if _IP_RE.search(value) or ":" in value:
        return "instance"
    if value.startswith("pod-") or "-pod-" in value:
        return "pod"
    if value.startswith("node-"):
        return "node"
    return "service"


def _build_selector(label: str, value: str) -> str:
    if not value:
        return ""
    safe = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{{{label}="{safe}"}}'


def _escape_regex(value: str) -> str:
    return re.escape(value).replace("/", r"\/")


def _build_hint_selector(metric_name_hint: str) -> str:
    hint = metric_name_hint.strip()
    if not hint:
        return '{__name__=~".+"}'
    escaped = _escape_regex(hint)
    return f'{{__name__=~".*{escaped}.*"}}'


@tool("Parse user request and extract context for metrics analysis (service, time window, metric patterns)")
def collect_context(
    user_request: Annotated[str, "The user's request text to analyze"],
) -> str:
    """Parse the user request and extract relevant context for metrics analysis."""
    context: dict[str, Any] = {
        "original_request": user_request,
        "service": None,
        "metric_patterns": [],
        "metric_name_hints": [],
        "target": {},
        "time_window": None,
        "analysis_type": None,
        "domains": [],
        "missing_fields": [],
    }

    request_lower = user_request.lower()

    service_patterns = [
        r"(?:service|сервис|app|application|приложение)\s+['\"]?([a-zA-Z0-9_-]+)['\"]?",
        r"(?:for|для)\s+([a-zA-Z0-9_-]+)\s+(?:service|сервис)?",
        r"([a-zA-Z0-9_-]+)\s+(?:metrics|метрики|health|состояние)",
    ]
    for pattern in service_patterns:
        match = re.search(pattern, user_request, re.IGNORECASE)
        if match:
            context["service"] = match.group(1)
            break

    ips = _IP_RE.findall(user_request)
    if ips:
        context["target"] = {
            "kind": "instance",
            "label": "instance",
            "value": ips[0],
        }
        if not context["service"]:
            context["service"] = ips[0]

    pod_match = re.search(r"(?:pod)\s+([a-zA-Z0-9_.:-]+)", user_request, re.IGNORECASE)
    if pod_match and not context["target"]:
        context["target"] = {
            "kind": "pod",
            "label": "pod",
            "value": pod_match.group(1),
        }

    ns_match = re.search(r"(?:namespace|ns)\s+([a-zA-Z0-9_.:-]+)", user_request, re.IGNORECASE)
    if ns_match and not context["target"]:
        context["target"] = {
            "kind": "namespace",
            "label": "namespace",
            "value": ns_match.group(1),
        }

    domain_matches = []
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(keyword in request_lower for keyword in keywords):
            domain_matches.append(domain)
    context["domains"] = domain_matches
    context["metric_patterns"] = domain_matches

    metric_like_tokens = set(
        re.findall(r"\b[a-zA-Z_:][a-zA-Z0-9_:]{3,}\b", user_request)
    )
    filtered_metric_hints = [
        token
        for token in sorted(metric_like_tokens)
        if "_" in token or token.startswith(("node_", "container_", "kube_", "pg_", "http_"))
    ]
    context["metric_name_hints"] = filtered_metric_hints[:10]

    time_patterns = [
        (r"(?:last|past|за последн\w*)\s+(\d+)\s*(hour|hours|час\w*|h)", "hours"),
        (r"(?:last|past|за последн\w*)\s+(\d+)\s*(minute|minutes|минут\w*|m|min)", "minutes"),
        (r"(?:last|past|за последн\w*)\s+(\d+)\s*(day|days|день|дн\w*|d)", "days"),
        (r"(\d+)h", "hours"),
        (r"(\d+)m(?:in)?", "minutes"),
        (r"(\d+)d", "days"),
    ]
    for pattern, unit in time_patterns:
        match = re.search(pattern, request_lower)
        if match:
            value = int(match.group(1))
            if unit == "hours":
                context["time_window"] = f"{value}h"
            elif unit == "minutes":
                context["time_window"] = f"{value}m"
            elif unit == "days":
                context["time_window"] = f"{value}d"
            break

    if not context["time_window"]:
        context["time_window"] = "1h"

    analysis_keywords = {
        "spike": "anomaly_detection",
        "drop": "anomaly_detection",
        "anomaly": "anomaly_detection",
        "аномал": "anomaly_detection",
        "всплеск": "anomaly_detection",
        "падение": "anomaly_detection",
        "compare": "comparison",
        "сравн": "comparison",
        "baseline": "comparison",
        "health": "health_check",
        "status": "health_check",
        "состояние": "health_check",
        "здоровье": "health_check",
        "trend": "trend_analysis",
        "тренд": "trend_analysis",
        "динамик": "trend_analysis",
    }
    for keyword, analysis_type in analysis_keywords.items():
        if keyword in request_lower:
            context["analysis_type"] = analysis_type
            break

    if not context["analysis_type"]:
        context["analysis_type"] = "general"

    if not context["service"]:
        context["service"] = "unknown"
    if not context["metric_patterns"] and not context["metric_name_hints"]:
        context["missing_fields"].append("metric_or_domain_hint")

    return json.dumps(context, ensure_ascii=False, indent=2)


@tool("Generate PromQL query suggestions for any metric domain (k8s, postgres, baremetal, app)")
def build_promql_suggestions(
    service: Annotated[str, "Service name or target value (service/pod/instance/IP)"],
    metric_type: Annotated[
        Literal[
            "http",
            "cpu",
            "memory",
            "error",
            "network",
            "disk",
            "latency",
            "availability",
            "postgres",
            "kubernetes",
            "any",
        ],
        "Metric domain to focus on",
    ] = "any",
    time_window: Annotated[str, "Time window for rate calculations (e.g., 5m, 1h)"] = "5m",
    target_label: Annotated[
        Literal["service", "instance", "pod", "container", "job", "namespace", "node", "db", "auto"],
        "Prometheus label to filter by",
    ] = "auto",
    metric_name_hint: Annotated[str, "Optional metric name or regex hint"] = "",
) -> str:
    """Generate PromQL query suggestions for broad infrastructure and app metrics."""
    resolved_label = _guess_target_label(service, target_label)
    selector = _build_selector(resolved_label, service)
    custom_hint = metric_name_hint.strip()
    hint_selector = _build_hint_selector(custom_hint)
    target_or_any_selector = selector if selector else '{__name__=~".+"}'

    suggestions: dict[str, list[dict[str, str]]] = {
        "any": [
            {
                "name": "Discover metrics by hint",
                "query": f"count({hint_selector})",
                "description": "Quickly test whether metrics matching a hint exist",
            },
            {
                "name": "Top active series by metric name",
                "query": f"topk(20, count by(__name__)({target_or_any_selector}))",
                "description": "Find dominant metric families for a target",
            },
        ],
        "http": [
            {
                "name": "Request Rate",
                "query": f"sum(rate(http_requests_total{selector}[{time_window}]))",
                "description": "Total HTTP request rate per second",
            },
            {
                "name": "Error Rate",
                "query": (
                    f'sum(rate(http_requests_total{{status=~"5..",{resolved_label}="{service}"}}[{time_window}])) '
                    f'/ sum(rate(http_requests_total{{{resolved_label}="{service}"}}[{time_window}]))'
                ),
                "description": "Ratio of 5xx errors to total requests",
            },
            {
                "name": "Latency P95",
                "query": f"histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{selector}[{time_window}])) by (le))",
                "description": "95th percentile latency",
            },
        ],
        "cpu": [
            {
                "name": "CPU usage from node exporter",
                "query": f'100 * (1 - avg(rate(node_cpu_seconds_total{{mode="idle",{resolved_label}="{service}"}}[{time_window}])))',
                "description": "CPU usage percent for host/instance-like targets",
            },
            {
                "name": "Container CPU usage",
                "query": f"sum(rate(container_cpu_usage_seconds_total{selector}[{time_window}]))",
                "description": "CPU usage for containerized workloads",
            },
        ],
        "memory": [
            {
                "name": "Host memory usage percent",
                "query": f'100 * (1 - (node_memory_MemAvailable_bytes{{{resolved_label}="{service}"}} / node_memory_MemTotal_bytes{{{resolved_label}="{service}"}}))',
                "description": "Memory pressure on host/instance",
            },
            {
                "name": "Container memory working set",
                "query": f"sum(container_memory_working_set_bytes{selector})",
                "description": "Memory usage for containerized workloads",
            },
        ],
        "error": [
            {
                "name": "HTTP 5xx rate",
                "query": f'sum(rate(http_requests_total{{status=~"5..",{resolved_label}="{service}"}}[{time_window}]))',
                "description": "5xx error throughput",
            },
            {
                "name": "Application errors by type",
                "query": f"sum(rate(errors_total{selector}[{time_window}])) by (error_type)",
                "description": "Error rate grouped by type",
            },
        ],
        "network": [
            {
                "name": "Network receive bytes rate",
                "query": f"sum(rate(node_network_receive_bytes_total{{{resolved_label}=\"{service}\"}}[{time_window}]))",
                "description": "Inbound bandwidth",
            },
            {
                "name": "Network transmit bytes rate",
                "query": f"sum(rate(node_network_transmit_bytes_total{{{resolved_label}=\"{service}\"}}[{time_window}]))",
                "description": "Outbound bandwidth",
            },
        ],
        "disk": [
            {
                "name": "Disk read bytes rate",
                "query": f"sum(rate(node_disk_read_bytes_total{{{resolved_label}=\"{service}\"}}[{time_window}]))",
                "description": "Disk read throughput",
            },
            {
                "name": "Disk write bytes rate",
                "query": f"sum(rate(node_disk_written_bytes_total{{{resolved_label}=\"{service}\"}}[{time_window}]))",
                "description": "Disk write throughput",
            },
        ],
        "latency": [
            {
                "name": "Generic request latency p95",
                "query": f"histogram_quantile(0.95, sum(rate(request_duration_seconds_bucket{selector}[{time_window}])) by (le))",
                "description": "P95 latency from histogram metrics",
            }
        ],
        "availability": [
            {
                "name": "Target up ratio",
                "query": f"avg_over_time(up{{{resolved_label}=\"{service}\"}}[{time_window}]) * 100",
                "description": "Availability estimate from up metric",
            }
        ],
        "kubernetes": [
            {
                "name": "Pod restart rate",
                "query": f"sum(increase(kube_pod_container_status_restarts_total{selector}[{time_window}]))",
                "description": "Restart activity for k8s workloads",
            },
            {
                "name": "K8s container CPU usage",
                "query": f"sum(rate(container_cpu_usage_seconds_total{selector}[{time_window}])) by (pod, namespace)",
                "description": "CPU usage grouped by pod/namespace",
            },
        ],
        "postgres": [
            {
                "name": "Postgres transaction rate",
                "query": f"sum(rate(pg_stat_database_xact_commit{selector}[{time_window}]) + rate(pg_stat_database_xact_rollback{selector}[{time_window}]))",
                "description": "Committed + rolled back transactions per second",
            },
            {
                "name": "Postgres active connections",
                "query": f"sum(pg_stat_activity_count{selector})",
                "description": "Current active connections",
            },
        ],
    }

    metric_type_lower = metric_type.lower()
    if metric_type_lower in suggestions:
        result = suggestions[metric_type_lower]
    else:
        result = suggestions["any"]

    return json.dumps(
        {
            "service": service,
            "metric_type": metric_type,
            "time_window": time_window,
            "target_label": resolved_label,
            "metric_name_hint": metric_name_hint,
            "discovery_flow": [
                "Call metrics with a name pattern (e.g. cpu, postgres, kube, http).",
                "Call labels for the chosen metric to inspect available dimensions.",
                "Call label_values to find exact target values (instance/pod/service/db).",
                "Run query/query_range with the selected metric + exact label filters.",
            ],
            "suggestions": result,
        },
        ensure_ascii=False,
        indent=2,
    )


@tool("Format metrics analysis results into a structured report")
def format_metrics_report(
    service: Annotated[str, "Service name being analyzed"],
    metrics_data: Annotated[dict, "Metrics data with values, environment, and time_window"],
    conclusion: Annotated[Literal["healthy", "degraded", "critical"], "Health conclusion"] = "healthy",
    next_action: Annotated[str, "Recommended next action"] = "",
) -> str:
    """Format metrics analysis results into a structured report."""
    report = {
        "scope": {
            "service": service,
            "environment": metrics_data.get("environment", "unknown"),
            "time_window": metrics_data.get("time_window", "unknown"),
        },
        "evidence": [],
        "conclusion": conclusion,
        "next_action": next_action,
    }

    for metric_name, value in metrics_data.get("values", {}).items():
        report["evidence"].append({
            "metric": metric_name,
            "value": value.get("current"),
            "baseline": value.get("baseline"),
            "timestamp": value.get("timestamp"),
            "status": value.get("status", "ok"),
        })

    return json.dumps(report, ensure_ascii=False, indent=2)
