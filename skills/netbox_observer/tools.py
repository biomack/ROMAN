"""
Local tools for netbox_observer skill.
MCP tools are provided by the NetBox MCP server.
"""

import json
import re
from typing import Annotated, Any, Literal

from core.tool_registry import tool

_OBJECT_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "devices": ("device", "devices", "сервер", "серверы", "устройство", "устройства"),
    "ip-addresses": ("ip", "ip address", "ip addresses", "ip-адрес", "адрес"),
    "prefixes": ("prefix", "prefixes", "префикс", "префиксы", "subnet", "подсеть"),
    "vlans": ("vlan", "vlans"),
    "sites": ("site", "sites", "сайт", "сайты", "дц", "dc"),
    "racks": ("rack", "racks", "стойка", "стойки"),
    "tenants": ("tenant", "tenants", "арендатор", "арендаторы"),
    "interfaces": ("interface", "interfaces", "интерфейс", "интерфейсы"),
    "circuits": ("circuit", "circuits", "канал", "каналы"),
}

_DEFAULT_FIELDS: dict[str, list[str]] = {
    "devices": ["id", "name", "status", "site", "device_type", "primary_ip4"],
    "ip-addresses": ["id", "address", "status", "dns_name", "description"],
    "prefixes": ["id", "prefix", "status", "site", "vlan", "description"],
    "vlans": ["id", "vid", "name", "status", "site", "tenant"],
    "sites": ["id", "name", "status", "region", "description"],
    "racks": ["id", "name", "site", "status", "u_height", "facility_id"],
    "tenants": ["id", "name", "slug", "group", "description"],
    "interfaces": ["id", "name", "device", "type", "enabled"],
    "circuits": ["id", "cid", "status", "provider", "type", "description"],
    "changelogs": ["id", "time", "action", "user", "object_type", "object_repr"],
}

_FILTER_HINT_KEYS = {
    "site",
    "status",
    "role",
    "tenant",
    "name",
    "address",
    "prefix",
    "device",
    "region",
}


def _extract_object_type(text: str) -> str | None:
    lower = text.lower()
    for object_type, keywords in _OBJECT_TYPE_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            return object_type
    return None


def _extract_mode(text: str) -> Literal["list", "detail", "changelog"]:
    lower = text.lower()
    if any(token in lower for token in ("changelog", "audit", "истор", "кто изменил", "изменил")):
        return "changelog"
    if re.search(r"\bid\s*[:=]?\s*\d+\b", lower) or "by id" in lower or "по id" in lower:
        return "detail"
    return "list"


def _extract_id(text: str) -> int | None:
    match = re.search(r"\bid\s*[:=]?\s*(\d+)\b", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _extract_filters(text: str) -> dict[str, str]:
    """
    Extract lightweight key=value style filter hints from plain text.
    Supported examples: "site=dc1 status=active", "tenant:acme".
    """
    filters: dict[str, str] = {}
    for key, value in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_-]*)\s*[:=]\s*([a-zA-Z0-9_.:/-]+)", text):
        key_norm = key.strip().lower()
        if key_norm in _FILTER_HINT_KEYS:
            filters[key_norm] = value.strip()
    return filters


@tool("Parse user request and extract NetBox query context (mode, object type, filters, id)")
def collect_context(
    user_request: Annotated[str, "The user's request text to analyze"],
) -> str:
    """Extract structured context for NetBox MCP calls."""
    mode = _extract_mode(user_request)
    object_type = _extract_object_type(user_request)
    object_id = _extract_id(user_request)
    filters = _extract_filters(user_request)

    context: dict[str, Any] = {
        "original_request": user_request,
        "mode": mode,
        "object_type": object_type,
        "object_id": object_id,
        "filters": filters,
        "missing_fields": [],
    }

    if mode in {"list", "detail"} and not object_type:
        context["missing_fields"].append("object_type")
    if mode == "detail" and object_id is None:
        context["missing_fields"].append("object_id")

    return json.dumps(context, ensure_ascii=False, indent=2)


@tool("Suggest a compact NetBox fields list for the chosen object type")
def suggest_fields(
    object_type: Annotated[str, "NetBox object type, e.g. devices, ip-addresses, prefixes, vlans"],
    profile: Annotated[
        Literal["compact", "full"],
        "compact returns a token-efficient minimal field set; full returns an empty list to request full objects",
    ] = "compact",
) -> str:
    """Return recommended fields list for token-efficient NetBox calls."""
    key = (object_type or "").strip().lower()
    if profile == "full":
        return json.dumps(
            {"object_type": key, "fields": [], "note": "Use empty fields list for full object payload."},
            ensure_ascii=False,
            indent=2,
        )

    fields = _DEFAULT_FIELDS.get(key, ["id", "name", "status", "description"])
    return json.dumps(
        {"object_type": key, "fields": fields},
        ensure_ascii=False,
        indent=2,
    )


@tool("Format NetBox analysis output into stable Scope/Evidence/Conclusion structure")
def format_netbox_report(
    scope: Annotated[str, "Search scope: object type, filters, period"],
    evidence: Annotated[str, "Observed evidence from NetBox results"],
    conclusion: Annotated[str, "Short answer derived from evidence"],
    next_action: Annotated[str, "One practical follow-up action"] = "",
) -> str:
    """Format final NetBox response payload."""
    report = {
        "scope": scope,
        "evidence": evidence,
        "conclusion": conclusion,
        "next_action": next_action,
    }
    return json.dumps(report, ensure_ascii=False, indent=2)
