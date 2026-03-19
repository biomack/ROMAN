"""
Local tools for logs_observer skill.
MCP tools (vl_query, vl_hits, etc.) are provided by the VictoriaLogs MCP server.
"""

import json
import re
from typing import Annotated, Any, Literal

from core.tool_registry import tool

_TIME_RANGE_PATTERNS = [
    # "за последние N часов/минут/дней"
    (r"(?:last|past|за последн\w*)\s+(\d+)\s*(?:hour|hours|час\w*|h)\b", "h"),
    (r"(?:last|past|за последн\w*)\s+(\d+)\s*(?:minute|minutes|минут\w*|m|min)\b", "m"),
    (r"(?:last|past|за последн\w*)\s+(\d+)\s*(?:day|days|день|дн\w*|d)\b", "d"),
    # compact: 2h, 30m, 1d
    (r"\b(\d+)h\b", "h"),
    (r"\b(\d+)m(?:in)?\b", "m"),
    (r"\b(\d+)d\b", "d"),
]

_EXPLICIT_RANGE_RE = re.compile(
    r"(?:с|from)\s+(\d{1,2}:\d{2})\s*(?:[-–—]|до|to)\s*(\d{1,2}:\d{2})",
    re.IGNORECASE,
)

_AMBIGUOUS_TIME_WORDS = {"утром", "вечером", "ночью", "днём", "днем", "недавно", "сегодня"}

_SERVICE_PATTERNS = [
    r"(?:service|сервис|app|application|приложение|компонент|component)\s+['\"]?([a-zA-Z0-9_.:-]+)['\"]?",
    r"(?:for|для|в|from|из)\s+([a-zA-Z0-9_.:-]+)\s+(?:service|сервис|логи|логах|logs)?",
    r"([a-zA-Z0-9_.:-]+)\s+(?:логи|логах|logs|log)",
]

_ENV_KEYWORDS: dict[str, str] = {
    "prod": "prod",
    "production": "prod",
    "прод": "prod",
    "stage": "stage",
    "staging": "stage",
    "стейдж": "stage",
    "dev": "dev",
    "develop": "dev",
    "development": "dev",
    "дев": "dev",
    "test": "test",
    "тест": "test",
}

_SEVERITY_KEYWORDS: dict[str, list[str]] = {
    "error": ["error", "err", "ошибк", "ошибок", "ошибки"],
    "warn": ["warn", "warning", "предупрежд"],
    "fatal": ["fatal", "panic", "критическ", "крит"],
    "info": ["info"],
    "debug": ["debug", "отладк"],
}


def _extract_time_range(text: str) -> dict[str, Any]:
    """Extract time range from user text. Returns start/end or duration."""
    lower = text.lower()

    explicit = _EXPLICIT_RANGE_RE.search(text)
    if explicit:
        return {
            "start": explicit.group(1),
            "end": explicit.group(2),
            "raw": explicit.group(0),
            "type": "explicit",
        }

    for pattern, unit in _TIME_RANGE_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            value = int(match.group(1))
            return {
                "duration": f"{value}{unit}",
                "logsql_start": f"now-{value}{unit}",
                "raw": match.group(0),
                "type": "relative",
            }

    for word in _AMBIGUOUS_TIME_WORDS:
        if word in lower:
            return {
                "duration": None,
                "raw": word,
                "type": "ambiguous",
            }

    return {
        "duration": "15m",
        "logsql_start": "now-15m",
        "raw": None,
        "type": "default",
    }


def _extract_identifiers(text: str) -> dict[str, str]:
    """Extract trace_id, request_id, user_id, order_id, pod, host from text."""
    ids: dict[str, str] = {}

    id_patterns: dict[str, str] = {
        "trace_id": r"(?:trace[_-]?id)\s*[:=]?\s*([a-fA-F0-9-]{8,})",
        "request_id": r"(?:request[_-]?id|req[_-]?id)\s*[:=]?\s*([a-fA-F0-9-]{8,})",
        "user_id": r"(?:user[_-]?id)\s*[:=]?\s*([a-zA-Z0-9_-]+)",
        "order_id": r"(?:order[_-]?id|заказ)\s*[:=]?\s*([a-zA-Z0-9_-]+)",
        "pod": r"(?:pod)\s+([a-zA-Z0-9_.:-]+)",
        "host": r"(?:host|хост|сервер|server)\s+([a-zA-Z0-9_.:-]+)",
    }
    for key, pattern in id_patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            ids[key] = match.group(1)

    return ids


@tool("Parse user request and extract context for log search (service, time range, filters, identifiers)")
def collect_context(
    user_request: Annotated[str, "The user's request text to analyze"],
) -> str:
    """Parse the user request and extract relevant context for log analysis."""
    context: dict[str, Any] = {
        "original_request": user_request,
        "service": None,
        "environment": None,
        "time_range": None,
        "severity": None,
        "search_text": None,
        "identifiers": {},
        "missing_fields": [],
    }

    request_lower = user_request.lower()

    context["time_range"] = _extract_time_range(user_request)

    if context["time_range"]["type"] == "ambiguous":
        context["missing_fields"].append("time_range")

    for pattern in _SERVICE_PATTERNS:
        match = re.search(pattern, user_request, re.IGNORECASE)
        if match:
            candidate = match.group(1)
            if candidate.lower() not in {
                "в", "из", "для", "от", "по", "the", "a", "an", "from", "for",
                "последние", "последних", "минут", "часов",
            }:
                context["service"] = candidate
                break

    for keyword, env_name in _ENV_KEYWORDS.items():
        if keyword in request_lower:
            context["environment"] = env_name
            break

    for severity, keywords in _SEVERITY_KEYWORDS.items():
        if any(kw in request_lower for kw in keywords):
            context["severity"] = severity
            break

    context["identifiers"] = _extract_identifiers(user_request)

    quoted = re.findall(r'["\u201c\u201d«»](.+?)["\u201c\u201d«»]', user_request)
    if quoted:
        context["search_text"] = quoted[0]

    if not context["service"] and not context["identifiers"]:
        context["missing_fields"].append("service")

    return json.dumps(context, ensure_ascii=False, indent=2)


@tool("Build a LogsQL query string from structured parameters")
def build_logsql_query(
    time_start: Annotated[str, "Start of time range in LogsQL format, e.g. 'now-15m' or '2024-01-01T10:00:00Z'"] = "now-15m",
    service: Annotated[str, "Service or component name to filter by"] = "",
    severity: Annotated[str, "Log severity/level to filter: error, warn, info, debug, fatal"] = "",
    search_text: Annotated[str, "Free-text substring to search in log messages"] = "",
    stream_filter: Annotated[str, "LogsQL stream filter, e.g. '{service=\"api\",env=\"prod\"}'"] = "",
    extra_filters: Annotated[str, "Additional LogsQL filter expressions"] = "",
) -> str:
    """Build a LogsQL query from structured parameters."""
    parts: list[str] = []

    if stream_filter:
        parts.append(stream_filter)
    elif service:
        safe_service = service.replace('"', '\\"')
        parts.append(f'service:"{safe_service}"')

    if severity:
        parts.append(f"level:{severity}")

    if search_text:
        safe_text = search_text.replace('"', '\\"')
        parts.append(f'"{safe_text}"')

    if extra_filters:
        parts.append(extra_filters)

    query = " AND ".join(parts) if parts else "*"

    result = {
        "query": query,
        "time_start": time_start,
        "parameters": {
            "service": service,
            "severity": severity,
            "search_text": search_text,
            "stream_filter": stream_filter,
        },
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("Format log analysis results into a structured report")
def format_logs_report(
    time_range: Annotated[str, "Time range used for search, e.g. 'now-15m .. now' or '10:00-10:30'"],
    total_records: Annotated[int, "Total number of log records found"],
    summary: Annotated[str, "Summary of key findings: errors, patterns, notable events"],
    hypothesis: Annotated[str, "Root cause hypothesis if enough data is available"] = "",
    needs_clarification: Annotated[str, "What additional info is needed from the user, empty if none"] = "",
    service: Annotated[str, "Service/component analyzed"] = "",
    environment: Annotated[str, "Environment (prod/stage/dev)"] = "",
) -> str:
    """Format log analysis results into a structured report."""
    report: dict[str, Any] = {
        "period": time_range,
        "scope": {},
        "findings": {
            "total_records": total_records,
            "summary": summary,
        },
    }

    if service:
        report["scope"]["service"] = service
    if environment:
        report["scope"]["environment"] = environment

    if hypothesis:
        report["hypothesis"] = hypothesis

    if needs_clarification:
        report["needs_clarification"] = needs_clarification

    return json.dumps(report, ensure_ascii=False, indent=2)
