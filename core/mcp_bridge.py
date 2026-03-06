from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from httpx_sse import aconnect_sse

logger = logging.getLogger(__name__)


@dataclass
class MCPToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass
class MCPSession:
    server_name: str
    url: str
    transport: str
    session_id: str | None = None
    message_endpoint: str | None = None
    mcp_session_id: str | None = None  # HTTP transport session ID from header
    _tools_cache: list[MCPToolSpec] = field(default_factory=list)


class MCPBridge:
    """
    MCP client bridge that connects to MCP servers via SSE or HTTP transport.
    Supports the VictoriaMetrics MCP server and other MCP-compatible servers.
    """

    def __init__(self, timeout: float = 30.0):
        self._sessions: dict[str, MCPSession] = {}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def connect_sse(self, server_name: str, base_url: str) -> MCPSession:
        """Connect to an MCP server using SSE transport."""
        client = await self._get_client()
        sse_url = base_url.rstrip("/") + "/sse"

        session = MCPSession(
            server_name=server_name,
            url=base_url,
            transport="sse",
        )

        try:
            async with aconnect_sse(client, "GET", sse_url) as event_source:
                async for event in event_source.aiter_sse():
                    if event.event == "endpoint":
                        endpoint_data = event.data
                        if "?" in sse_url:
                            base_path = sse_url.split("?")[0].rsplit("/", 1)[0]
                        else:
                            base_path = sse_url.rsplit("/", 1)[0]
                        session.message_endpoint = base_path + endpoint_data
                        if "session_id=" in endpoint_data:
                            session.session_id = endpoint_data.split("session_id=")[1].split("&")[0]
                        break
        except Exception as e:
            logger.warning(f"SSE connection to {server_name} failed: {e}")
            session.message_endpoint = base_url.rstrip("/") + "/message"

        self._sessions[server_name] = session
        return session

    async def connect_http(self, server_name: str, base_url: str) -> MCPSession:
        """Connect to an MCP server using Streamable HTTP transport."""
        session = MCPSession(
            server_name=server_name,
            url=base_url,
            transport="http",
            message_endpoint=base_url.rstrip("/") + "/mcp",
        )
        self._sessions[server_name] = session
        return session

    async def connect(self, server_name: str, url: str, transport: str = "sse") -> MCPSession:
        """Connect to an MCP server with the specified transport."""
        if transport == "http":
            return await self.connect_http(server_name, url)
        return await self.connect_sse(server_name, url)

    async def _send_jsonrpc(
        self,
        session: MCPSession,
        method: str,
        params: dict | None = None,
        request_id: int | None = 1,
        is_notification: bool = False,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to the MCP server."""
        client = await self._get_client()

        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if not is_notification and request_id is not None:
            payload["id"] = request_id
        if params:
            payload["params"] = params

        endpoint = session.message_endpoint
        if not endpoint:
            raise RuntimeError(f"No message endpoint for server {session.server_name}")

        headers = {"Content-Type": "application/json"}

        if session.mcp_session_id:
            headers["Mcp-Session-Id"] = session.mcp_session_id

        if session.transport == "http":
            headers["Accept"] = "application/json, text/event-stream"
            response = await client.post(endpoint, json=payload, headers=headers)

            if "mcp-session-id" in response.headers:
                session.mcp_session_id = response.headers["mcp-session-id"]

            if is_notification:
                if response.status_code in (200, 202, 204):
                    return {"status": "ok"}
                logger.debug(f"Notification {method} returned {response.status_code}")
                return {"status": "ok"}

            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                result = await self._parse_sse_response(response.text)
                return result
            return response.json()
        else:
            response = await client.post(endpoint, json=payload, headers=headers)

            if is_notification:
                return {"status": "ok"}

            response.raise_for_status()
            return response.json()

    async def _parse_sse_response(self, text: str) -> dict[str, Any]:
        """Parse SSE response text to extract JSON-RPC result."""
        for line in text.split("\n"):
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    try:
                        return json.loads(data)
                    except json.JSONDecodeError:
                        continue
        return {"error": "No valid JSON-RPC response in SSE stream"}

    async def initialize(self, server_name: str) -> dict[str, Any]:
        """Initialize the MCP session with the server."""
        session = self._sessions.get(server_name)
        if not session:
            raise RuntimeError(f"Not connected to server {server_name}")

        result = await self._send_jsonrpc(
            session,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "clientInfo": {
                    "name": "llm-skills-mcp-client",
                    "version": "1.0.0",
                },
            },
        )

        await self._send_jsonrpc(
            session,
            "notifications/initialized",
            is_notification=True,
        )
        return result

    async def list_tools_async(
        self, server_name: str, expose_tools: list[str] | None = None
    ) -> list[MCPToolSpec]:
        """Fetch available tools from the MCP server."""
        session = self._sessions.get(server_name)
        if not session:
            raise RuntimeError(f"Not connected to server {server_name}")

        if session._tools_cache:
            tools = session._tools_cache
        else:
            result = await self._send_jsonrpc(session, "tools/list")
            tools_data = result.get("result", {}).get("tools", [])
            tools = [
                MCPToolSpec(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    parameters=t.get("inputSchema", {}),
                )
                for t in tools_data
            ]
            session._tools_cache = tools

        if expose_tools:
            tools = [t for t in tools if t.name in expose_tools]

        return tools

    async def call_tool_async(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> str:
        """Call a tool on the MCP server."""
        session = self._sessions.get(server_name)
        if not session:
            raise RuntimeError(f"Not connected to server {server_name}")

        result = await self._send_jsonrpc(
            session,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )

        if "error" in result:
            return json.dumps(result["error"], ensure_ascii=False, indent=2)

        tool_result = result.get("result", {})
        content = tool_result.get("content", [])

        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        texts.append(item.get("text", ""))
                    elif item.get("type") == "image":
                        texts.append(f"[Image: {item.get('mimeType', 'unknown')}]")
                    else:
                        texts.append(json.dumps(item, ensure_ascii=False))
                else:
                    texts.append(str(item))
            return "\n".join(texts) if texts else json.dumps(tool_result, ensure_ascii=False)

        return json.dumps(tool_result, ensure_ascii=False, indent=2)

    def list_tools(self, server: str, expose_tools: list[str]) -> list[MCPToolSpec]:
        """Synchronous wrapper for list_tools_async."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            future = asyncio.ensure_future(self.list_tools_async(server, expose_tools))
            return asyncio.get_event_loop().run_until_complete(future)

        return asyncio.run(self._list_tools_sync(server, expose_tools))

    async def _list_tools_sync(
        self, server: str, expose_tools: list[str]
    ) -> list[MCPToolSpec]:
        """Helper for synchronous list_tools when no event loop is running."""
        return await self.list_tools_async(server, expose_tools)

    def call_tool(self, server: str, tool_name: str, arguments: dict) -> str:
        """Synchronous wrapper for call_tool_async."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            future = asyncio.ensure_future(
                self.call_tool_async(server, tool_name, arguments)
            )
            return asyncio.get_event_loop().run_until_complete(future)

        return asyncio.run(self._call_tool_sync(server, tool_name, arguments))

    async def _call_tool_sync(
        self, server: str, tool_name: str, arguments: dict
    ) -> str:
        """Helper for synchronous call_tool when no event loop is running."""
        return await self.call_tool_async(server, tool_name, arguments)


class MCPBridgeManager:
    """
    Manages MCP bridge connections and provides a simple interface for skills.
    Creates a new bridge instance per event loop to avoid cross-loop issues.
    """

    _instance: MCPBridgeManager | None = None
    _bridges: dict[int, MCPBridge] = {}
    _initialized: dict[int, set[str]] = {}

    def __new__(cls) -> MCPBridgeManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._bridges = {}
            cls._initialized = {}
        return cls._instance

    def _get_loop_id(self) -> int:
        """Get current event loop id for tracking bridge instances."""
        try:
            loop = asyncio.get_running_loop()
            return id(loop)
        except RuntimeError:
            return 0

    @property
    def bridge(self) -> MCPBridge:
        """Get or create bridge for current event loop."""
        loop_id = self._get_loop_id()
        if loop_id not in self._bridges:
            self._bridges[loop_id] = MCPBridge()
            self._initialized[loop_id] = set()
        return self._bridges[loop_id]

    @property
    def _initialized_servers(self) -> set[str]:
        """Get initialized servers set for current event loop."""
        loop_id = self._get_loop_id()
        if loop_id not in self._initialized:
            self._initialized[loop_id] = set()
        return self._initialized[loop_id]

    async def ensure_connected(
        self, server_name: str, url: str, transport: str = "sse"
    ) -> None:
        """Ensure connection to the specified MCP server."""
        if server_name not in self._initialized_servers:
            logger.info(f"Connecting to MCP server '{server_name}' at {url} ({transport})")
            try:
                await self.bridge.connect(server_name, url, transport)
                await self.bridge.initialize(server_name)
                self._initialized_servers.add(server_name)
                logger.info(f"Successfully connected to MCP server '{server_name}'")
            except Exception as e:
                logger.error(f"Failed to connect to MCP server '{server_name}': {e}")
                raise

    async def list_tools(
        self, server_name: str, expose_tools: list[str] | None = None
    ) -> list[MCPToolSpec]:
        """List tools from a connected MCP server."""
        return await self.bridge.list_tools_async(server_name, expose_tools)

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> str:
        """Call a tool on a connected MCP server."""
        return await self.bridge.call_tool_async(server_name, tool_name, arguments)

    async def close(self) -> None:
        """Close all connections for current event loop."""
        loop_id = self._get_loop_id()
        if loop_id in self._bridges:
            await self._bridges[loop_id].close()
            del self._bridges[loop_id]
        if loop_id in self._initialized:
            del self._initialized[loop_id]

    def clear_all(self) -> None:
        """Clear all cached bridges (for testing/reset)."""
        self._bridges.clear()
        self._initialized.clear()
