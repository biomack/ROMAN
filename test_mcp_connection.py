#!/usr/bin/env python3
"""
Test script to verify MCP server connection and list available tools.
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from core.config import Config
from core.mcp_bridge import MCPBridge


async def test_connection():
    cfg = Config.load()

    print("\n=== MCP Configuration ===")
    print(f"MCP Servers configured: {list(cfg.mcp_servers.keys())}")

    if not cfg.mcp_servers:
        print("ERROR: No MCP servers configured!")
        print("Check your .env file has:")
        print("  MCP_SERVERS=VICTORIAMETRICS")
        print("  MCP_VICTORIAMETRICS_NAME=victoriametrics-mcp")
        print("  MCP_VICTORIAMETRICS_URL=http://localhost:8080")
        print("  MCP_VICTORIAMETRICS_TRANSPORT=sse")
        return False

    for name, server_cfg in cfg.mcp_servers.items():
        print(f"\n=== Testing MCP Server: {name} ===")
        print(f"URL: {server_cfg.url}")
        print(f"Transport: {server_cfg.transport}")

        bridge = MCPBridge(timeout=30.0)

        try:
            print(f"\n1. Connecting to {name}...")
            session = await bridge.connect(name, server_cfg.url, server_cfg.transport)
            print(f"   Session created: endpoint={session.message_endpoint}")

            print(f"\n2. Initializing session...")
            init_result = await bridge.initialize(name)
            print(f"   Init result: {init_result}")

            print(f"\n3. Listing tools...")
            tools = await bridge.list_tools_async(name)
            print(f"   Found {len(tools)} tools:")
            for tool in tools[:10]:
                print(f"   - {tool.name}: {tool.description[:60]}...")

            if len(tools) > 10:
                print(f"   ... and {len(tools) - 10} more")

            print(f"\n4. Testing query tool...")
            if any(t.name == "query" for t in tools):
                result = await bridge.call_tool_async(
                    name,
                    "query",
                    {"query": "up", "time": "now"},
                )
                print(f"   Query 'up' result (first 500 chars):")
                print(f"   {result[:500]}...")

            print(f"\nSUCCESS: MCP server '{name}' is working!")
            return True

        except Exception as e:
            print(f"\nERROR: Failed to connect to {name}: {e}")
            logger.exception("Connection failed")
            return False

        finally:
            await bridge.close()


def main():
    print("Testing MCP Connection...")
    print("Make sure the MCP server is running:")
    print("  docker-compose up victoriametrics-mcp")
    print("")

    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
