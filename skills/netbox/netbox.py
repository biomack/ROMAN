import asyncio
import json
from typing import Any

from fastmcp import Client
from openai import OpenAI

LM_STUDIO_URL = "http://172.16.92.9:1234/v1/"
MCP_URL = "http://localhost:8000/mcp"
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_MAX_TOOL_ROUNDS = 20
DEFAULT_MAX_IDENTICAL_TOOL_CALLS = 3


def _to_openai_tools_v3(tools):
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema
                or {"type": "object", "properties": {}, "additionalProperties": True},
            },
        }
        for tool in tools
    ]


def _tool_result_to_text(result):
    # fastmcp v3: prefer structured_content/content over data.
    # `data` may contain Root() wrappers from pydantic parsing and lose detail.
    if hasattr(result, "structured_content") and result.structured_content is not None:
        return json.dumps(result.structured_content, ensure_ascii=False, default=str)
    if hasattr(result, "content") and result.content is not None:
        blocks = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                blocks.append(text)
            else:
                blocks.append(str(block))
        if blocks:
            return "\n".join(blocks)
        return json.dumps(result.content, ensure_ascii=False, default=str)

    if hasattr(result, "data") and result.data is not None:
        return json.dumps(result.data, ensure_ascii=False, default=str)

    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


def _normalize_tool_name(tool_name, known_tool_names):
    candidate = (tool_name or "").strip()
    if candidate in known_tool_names:
        return candidate

    # LLMs occasionally output punctuation after function names, e.g. "tool_name>".
    candidate = candidate.rstrip(" \t\r\n.,;:!?)]}>\"'")
    if candidate in known_tool_names:
        return candidate
    return None


def _extract_message_text(msg):
    content = msg.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts).strip()
    return ""


def _preview(text, limit=500):
    if text is None:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _log(debug: bool, message: str) -> None:
    if debug:
        print(message)


def _tool_signature(tool_name: str, args: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(args or {}, ensure_ascii=False, sort_keys=True)}"


def _force_final_answer(
    llm: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    debug: bool,
) -> str:
    """Ask model for a final answer with tools disabled."""
    forced_messages = messages + [
        {
            "role": "user",
            "content": (
                "Stop calling tools. Provide a concise final text answer now "
                "using the collected tool results. If data is insufficient, say what is missing."
            ),
        }
    ]
    try:
        response = llm.chat.completions.create(
            model=model,
            messages=forced_messages,
            tools=tools,
            tool_choice="none",
        )
    except Exception as exc:
        _log(debug, f"[WARN] Forced final with tool_choice=none failed: {exc}")
        response = llm.chat.completions.create(
            model=model,
            messages=forced_messages,
        )
    final_text = _extract_message_text(response.choices[0].message)
    return final_text or "No textual answer was returned by the model."


async def run_netbox_query(
    user_request: str,
    *,
    lm_studio_url: str = LM_STUDIO_URL,
    mcp_url: str = MCP_URL,
    model: str = DEFAULT_MODEL,
    max_empty_final_retries: int = 2,
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    max_identical_tool_calls: int = DEFAULT_MAX_IDENTICAL_TOOL_CALLS,
    debug: bool = False,
) -> str:
    _log(debug, "[STEP] Script started")
    _log(debug, f"[CONFIG] LM Studio URL: {lm_studio_url}")
    _log(debug, f"[CONFIG] MCP URL: {mcp_url}")

    is_v3 = False
    try:
        _log(debug, "[STEP] Trying FastMCP v2-style client init")
        mcp = Client()
        await mcp.connect_http(name="netbox", url=mcp_url)
        tools = await mcp.get_openai_tools()
        _log(debug, "[STEP] Connected with FastMCP v2-style API")
    except TypeError:
        # fastmcp 3.x: transport must be passed into constructor
        is_v3 = True
        _log(debug, "[STEP] FastMCP v3 detected, using transport in constructor")
        mcp = Client(mcp_url)
        async with mcp:
            tools = _to_openai_tools_v3(await mcp.list_tools())
        _log(debug, "[STEP] Connected with FastMCP v3-style API")
    known_tool_names = {t.get("function", {}).get("name") for t in tools}
    known_tool_names = {name for name in known_tool_names if name}
    _log(debug, f"[STEP] Tools loaded: {len(known_tool_names)}")
    _log(debug, f"[TOOLS] {sorted(known_tool_names)}")

    llm = OpenAI(
        base_url=lm_studio_url,
        api_key="lm-studio",
    )
    _log(debug, "[STEP] LLM client initialized")

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Use tools only when needed. Avoid repeating identical tool calls. "
                "After collecting enough data, provide a final answer."
            ),
        },
        {"role": "user", "content": user_request},
    ]
    _log(debug, f"[INPUT] {messages[-1]['content']}")
    empty_final_retries = 0
    iteration = 0
    last_tool_sig = ""
    same_tool_sig_streak = 0

    while True:
        iteration += 1
        _log(debug, f"[STEP] LLM request #{iteration}, messages={len(messages)}")
        # IMPORTANT TUNING: hard cap for tool loop. Increase if tasks need more exploration.
        if iteration > max_tool_rounds:
            _log(
                debug,
                f"[WARN] Max tool rounds reached ({max_tool_rounds}), forcing final answer",
            )
            return _force_final_answer(llm, model, messages, tools, debug)

        response = llm.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        _log(debug, f"[LLM] finish_reason={response.choices[0].finish_reason}")

        msg = response.choices[0].message
        if not msg.tool_calls:
            final_text = _extract_message_text(msg)
            if final_text:
                _log(debug, "[STEP] Finished successfully")
                return final_text

            empty_final_retries += 1
            _log(debug, "[WARN] Model returned empty final answer, retrying...")
            _log(debug, f"[DEBUG] raw assistant message content: {_preview(msg.content)}")
            messages.append({"role": "assistant", "content": ""})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Provide a concise final text answer based on previous tool results. "
                        "If nothing is found, explicitly say so."
                    ),
                }
            )
            if empty_final_retries >= max_empty_final_retries:
                _log(debug, "[STEP] Finished with empty-output fallback")
                return "No textual answer was returned by the model."
            continue

        messages.append(msg)
        _log(debug, f"[STEP] Model requested {len(msg.tool_calls)} tool call(s)")

        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            resolved_tool_name = _normalize_tool_name(tool_name, known_tool_names)
            args = json.loads(tool_call.function.arguments or "{}")
            if not resolved_tool_name:
                err = (
                    f"Unknown tool from model: {tool_name}. "
                    f"Available tools: {sorted(known_tool_names)}"
                )
                _log(debug, f"[TOOL ERROR] {err}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": err,
                    }
                )
                continue

            if resolved_tool_name != tool_name:
                _log(debug, f"[TOOL NAME FIXED] {tool_name} -> {resolved_tool_name}")
            _log(debug, f"[TOOL CALL] {resolved_tool_name} {args}")
            current_tool_sig = _tool_signature(resolved_tool_name, args)
            if current_tool_sig == last_tool_sig:
                same_tool_sig_streak += 1
            else:
                same_tool_sig_streak = 1
                last_tool_sig = current_tool_sig

            # IMPORTANT TUNING: loop-guard for repeated identical tool calls.
            if same_tool_sig_streak >= max_identical_tool_calls:
                _log(
                    debug,
                    "[WARN] Repeated identical tool call detected "
                    f"({same_tool_sig_streak} times): {current_tool_sig}",
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": (
                            "Guard: repeated identical tool call blocked. "
                            "Use already collected results and produce final answer."
                        ),
                    }
                )
                return _force_final_answer(llm, model, messages, tools, debug)

            try:
                if is_v3:
                    async with mcp:
                        result = await mcp.call_tool(resolved_tool_name, args)
                else:
                    result = await mcp.call_tool(resolved_tool_name, args)
            except Exception as exc:
                err = f"Tool call failed for {resolved_tool_name}: {exc}"
                _log(debug, f"[TOOL ERROR] {err}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": err,
                    }
                )
                continue
            tool_content = _tool_result_to_text(result)
            _log(debug, f"[TOOL RESULT] {resolved_tool_name}: {_preview(tool_content)}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_content,
                }
            )


async def main():
    default_query = (
        "какие интерфейсы подключены у устройства с device id 1196 в netbox, "
        "отобрази кабель и соединение"
    )
    answer = await run_netbox_query(default_query, debug=True)
    print("LLM:", answer)


if __name__ == "__main__":
    asyncio.run(main())
