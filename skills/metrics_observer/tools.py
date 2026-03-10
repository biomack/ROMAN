"""
Local tools for metrics_observer skill.
MCP tools (query, query_range, etc.) are provided by the VictoriaMetrics MCP server.
"""

import json
import re
from typing import Annotated, Any, Literal

from core.tool_registry import tool


@tool("Parse user request and extract context for metrics analysis (service, time window, metric patterns)")
def collect_context(
    user_request: Annotated[str, "The user's request text to analyze"],
) -> str:
    """Parse the user request and extract relevant context for metrics analysis."""
    context: dict[str, Any] = {
        "original_request": user_request,
        "service": None,
        "metric_patterns": [],
        "time_window": None,
        "analysis_type": None,
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

    metric_keywords = [
        "cpu", "memory", "mem", "disk", "network", "latency", "error",
        "request", "response", "throughput", "qps", "rps", "p99", "p95",
        "p50", "percentile", "rate", "count", "gauge", "histogram",
        "http", "grpc", "database", "db", "cache", "redis", "kafka",
    ]
    found_metrics = [kw for kw in metric_keywords if kw in request_lower]
    context["metric_patterns"] = found_metrics

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
        context["missing_fields"].append("service")
    if not context["metric_patterns"]:
        context["missing_fields"].append("metric_type")

    return json.dumps(context, ensure_ascii=False, indent=2)


@tool("Generate PromQL query suggestions for common metric types")
def build_promql_suggestions(
    service: Annotated[str, "Service name to query metrics for"],
    metric_type: Annotated[Literal["http", "cpu", "memory", "error"], "Type of metrics"] = "http",
    time_window: Annotated[str, "Time window for rate calculations (e.g., 5m, 1h)"] = "5m",
) -> str:
    """Generate PromQL query suggestions based on service and metric type."""
    suggestions: dict[str, list[dict[str, str]]] = {
        "http": [
            {
                "name": "Request Rate",
                "query": f'sum(rate(http_requests_total{{service="{service}"}}[{time_window}]))',
                "description": "Total HTTP request rate per second",
            },
            {
                "name": "Error Rate",
                "query": f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[{time_window}])) / sum(rate(http_requests_total{{service="{service}"}}[{time_window}]))',
                "description": "Ratio of 5xx errors to total requests",
            },
            {
                "name": "Latency P99",
                "query": f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{service="{service}"}}[{time_window}])) by (le))',
                "description": "99th percentile latency",
            },
            {
                "name": "Latency P50",
                "query": f'histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{{service="{service}"}}[{time_window}])) by (le))',
                "description": "Median latency",
            },
        ],
        "cpu": [
            {
                "name": "CPU Usage",
                "query": f'avg(rate(container_cpu_usage_seconds_total{{container="{service}"}}[{time_window}])) * 100',
                "description": "Average CPU usage percentage",
            },
            {
                "name": "CPU Throttling",
                "query": f'sum(rate(container_cpu_cfs_throttled_seconds_total{{container="{service}"}}[{time_window}]))',
                "description": "CPU throttling rate",
            },
        ],
        "memory": [
            {
                "name": "Memory Usage",
                "query": f'container_memory_usage_bytes{{container="{service}"}}',
                "description": "Current memory usage in bytes",
            },
            {
                "name": "Memory Usage Percentage",
                "query": f'container_memory_usage_bytes{{container="{service}"}} / container_spec_memory_limit_bytes{{container="{service}"}} * 100',
                "description": "Memory usage as percentage of limit",
            },
        ],
        "error": [
            {
                "name": "Error Count",
                "query": f'sum(increase(errors_total{{service="{service}"}}[{time_window}]))',
                "description": "Total error count in time window",
            },
            {
                "name": "Error Rate by Type",
                "query": f'sum(rate(errors_total{{service="{service}"}}[{time_window}])) by (error_type)',
                "description": "Error rate grouped by error type",
            },
        ],
    }

    metric_type_lower = metric_type.lower()
    if metric_type_lower in suggestions:
        result = suggestions[metric_type_lower]
    else:
        result = suggestions["http"]

    return json.dumps(
        {
            "service": service,
            "metric_type": metric_type,
            "time_window": time_window,
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
