"""
Decorator-based tool registration for skills.

Instead of maintaining a separate TOOLS = [...] JSON manifest,
skill authors decorate functions with @tool and use Annotated
for parameter descriptions. The JSON schema is generated automatically
from the Python function signature.

Usage in skills/*/tools.py:

    from typing import Annotated
    from core.tool_registry import tool

    @tool("Ping a host and return reachability and latency")
    def ping_host(
        host: Annotated[str, "Hostname or IP address"],
        count: Annotated[int, "Number of ping packets"] = 4,
    ) -> str:
        ...
"""

from __future__ import annotations

import inspect
import types
from typing import Annotated, Any, Literal, Union, get_args, get_origin, get_type_hints

TOOL_MARKER = "_tool_meta"

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
}


def tool(description: str):
    """Mark a function as an agent tool and attach auto-generated schema."""

    def decorator(func):
        setattr(func, TOOL_MARKER, {
            "name": func.__name__,
            "description": description,
            "parameters": _build_parameters(func),
        })
        return func

    return decorator


def discover_tools(module) -> list[dict]:
    """Find all @tool-decorated functions in a module."""
    results = []
    for name in dir(module):
        obj = getattr(module, name, None)
        if callable(obj) and hasattr(obj, TOOL_MARKER):
            results.append({
                **getattr(obj, TOOL_MARKER),
                "function": obj,
            })
    return results


def _build_parameters(func) -> dict:
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}

    sig = inspect.signature(func)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        hint = hints.get(param_name, str)

        description = ""
        origin = get_origin(hint)
        if origin is Annotated:
            args = get_args(hint)
            hint = args[0]
            for extra in args[1:]:
                if isinstance(extra, str):
                    description = extra
                    break

        prop = _type_to_schema(hint)
        if description:
            prop["description"] = description

        properties[param_name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _type_to_schema(hint) -> dict:
    origin = get_origin(hint)
    args = get_args(hint)

    if origin is Literal:
        return {"type": "string", "enum": list(args)}

    if origin is list:
        items = _type_to_schema(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": items}

    if origin is Union or isinstance(origin, type) and issubclass(origin, types.UnionType if hasattr(types, "UnionType") else type):
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _type_to_schema(non_none[0])

    if hasattr(types, "UnionType") and isinstance(hint, types.UnionType):
        non_none = [a for a in get_args(hint) if a is not type(None)]
        if non_none:
            return _type_to_schema(non_none[0])

    if origin is dict or hint is dict:
        return {"type": "object"}

    return {"type": _PY_TO_JSON.get(hint, "string")}
