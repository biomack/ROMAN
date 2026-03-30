import asyncio
import json
import os
import concurrent.futures
import importlib.util
from pathlib import Path
from typing import Annotated

from core.tool_registry import tool

NETBOX_MCP_URL = os.getenv("NETBOX_MCP_URL", "http://localhost:8000/mcp")
NETBOX_LLM_URL = os.getenv("NETBOX_LLM_URL", "http://172.16.92.9:1234/v1/")
NETBOX_LLM_MODEL = os.getenv("NETBOX_LLM_MODEL", "openai/gpt-oss-20b")
# IMPORTANT TUNING: cap total LLM-tool rounds to prevent endless loops.
NETBOX_MAX_TOOL_ROUNDS = int(os.getenv("NETBOX_MAX_TOOL_ROUNDS", "20"))
# IMPORTANT TUNING: stop when the same tool+args repeats this many times.
NETBOX_MAX_IDENTICAL_TOOL_CALLS = int(os.getenv("NETBOX_MAX_IDENTICAL_TOOL_CALLS", "3"))


def _load_local_netbox_runner():
    """
    Load run_netbox_query from skill-local netbox.py.
    IMPORTANT: do not use `import netbox` here — that may resolve to
    third-party `netbox` package from site-packages.
    """
    netbox_py = Path(__file__).resolve().parent / "netbox.py"
    if not netbox_py.exists():
        raise FileNotFoundError(f"Local netbox.py not found: {netbox_py}")

    spec = importlib.util.spec_from_file_location("roman_local_netbox", str(netbox_py))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec from: {netbox_py}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    runner = getattr(module, "run_netbox_query", None)
    if runner is None:
        raise ImportError("run_netbox_query not found in local netbox.py")
    return runner


RUN_NETBOX_QUERY = _load_local_netbox_runner()


def _run_async(coro):
    """Execute an async coroutine from a sync context, even if an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


@tool("Query NetBox via MCP server — devices, interfaces, cables, IPs, VLANs, etc.")
def netbox_query(
    query: Annotated[str, "User question about NetBox infrastructure (in any language)"],
) -> str:
    try:
        answer = _run_async(
            RUN_NETBOX_QUERY(
                query,
                lm_studio_url=NETBOX_LLM_URL,
                mcp_url=NETBOX_MCP_URL,
                model=NETBOX_LLM_MODEL,
                max_tool_rounds=NETBOX_MAX_TOOL_ROUNDS,
                max_identical_tool_calls=NETBOX_MAX_IDENTICAL_TOOL_CALLS,
            )
        )
        return answer or "NetBox sub-agent returned an empty answer."
    except Exception as exc:
        return json.dumps(
            {"error": str(exc), "hint": "Check NETBOX_MCP_URL and NETBOX_LLM_URL in .env"},
            ensure_ascii=False,
        )
