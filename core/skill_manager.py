"""
Skill discovery, indexing and progressive loading.

Implements the core Agent Skills pattern:
1. Discover all skills at startup (read only name + description from SKILL.md frontmatter)
2. Load full skill instructions + tools on demand (progressive disclosure)
"""

import asyncio
import importlib.util
import logging
import yaml
from pathlib import Path
from dataclasses import dataclass, field

from .mcp_bridge import MCPBridge, MCPBridgeManager
from .config import Config, MCPServerConfig
from .tool_registry import discover_tools

logger = logging.getLogger(__name__)


@dataclass
class SkillTool:
    name: str
    description: str
    parameters: dict
    function: callable
    tool_type: str = "python"
    mcp_server: str = ""


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    instructions: str = ""
    extra_files: dict[str, str] = field(default_factory=dict)
    tools: list[SkillTool] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    loaded: bool = False


class SkillManager:
    def __init__(
        self,
        skills_dir: str = "skills",
        *,
        mcp_bridge: MCPBridge | None = None,
        mcp_servers: dict[str, MCPServerConfig] | None = None,
        max_reference_file_bytes: int = 32768,
        max_reference_total_bytes: int = 262144,
    ):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}
        self.mcp_bridge = mcp_bridge or MCPBridge()
        self.mcp_bridge_manager = MCPBridgeManager()
        self.mcp_servers = mcp_servers or {}
        self.max_reference_file_bytes = max_reference_file_bytes
        self.max_reference_total_bytes = max_reference_total_bytes
        self._discover()

    # ------------------------------------------------------------------
    # Phase 1: Discovery (lightweight – frontmatter only)
    # ------------------------------------------------------------------

    def _discover(self):
        if not self.skills_dir.exists():
            return
        for entry in sorted(self.skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            meta = self._parse_frontmatter(skill_md)
            if meta and "name" in meta:
                self.skills[meta["name"]] = Skill(
                    name=meta["name"],
                    description=meta.get("description", ""),
                    path=entry,
                    meta=meta,
                )

    @staticmethod
    def _parse_frontmatter(path: Path) -> dict | None:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        try:
            return yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return None

    # ------------------------------------------------------------------
    # Phase 2: Full load (instructions + tools)
    # ------------------------------------------------------------------

    def load_skill(self, name: str) -> Skill | None:
        skill = self.skills.get(name)
        if skill is None or skill.loaded:
            return skill

        content = (skill.path / "SKILL.md").read_text(encoding="utf-8")
        parts = content.split("---", 2)
        skill.instructions = parts[2].strip() if len(parts) >= 3 else content

        skill.extra_files = self._load_references(skill.path)

        tools_py = skill.path / "tools.py"
        if tools_py.exists():
            skill.tools = self._load_tools(tools_py, skill.name)

        skill.tools.extend(self._build_mcp_tools(skill))
        skill.loaded = True
        return skill

    def _load_tools(self, tools_path: Path, skill_name: str) -> list[SkillTool]:
        spec = importlib.util.spec_from_file_location(
            f"skills.{skill_name}.tools", str(tools_path)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        decorated = discover_tools(module)
        if decorated:
            return [
                SkillTool(
                    name=td["name"],
                    description=td["description"],
                    parameters=td["parameters"],
                    function=td["function"],
                    tool_type="python",
                )
                for td in decorated
            ]

        results: list[SkillTool] = []
        for tool_def in getattr(module, "TOOLS", []):
            func = getattr(module, tool_def["function_name"], None)
            if func:
                results.append(
                    SkillTool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        function=func,
                        tool_type="python",
                    )
                )
        return results

    def _load_references(self, skill_path: Path) -> dict[str, str]:
        references: dict[str, str] = {}
        total_bytes = 0
        for folder_name in ("resources", "templates"):
            folder = skill_path / folder_name
            if not folder.exists() or not folder.is_dir():
                continue
            for fpath in sorted(folder.rglob("*")):
                if not fpath.is_file():
                    continue
                try:
                    raw = fpath.read_bytes()
                except Exception:
                    continue
                if len(raw) > self.max_reference_file_bytes:
                    continue
                if total_bytes + len(raw) > self.max_reference_total_bytes:
                    break
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                rel = fpath.relative_to(skill_path).as_posix()
                references[rel] = text
                total_bytes += len(raw)
        return references

    def _build_mcp_tools(self, skill: Skill) -> list[SkillTool]:
        mcp_meta = skill.meta.get("mcp")
        if not isinstance(mcp_meta, dict):
            return []

        server = str(mcp_meta.get("server", "")).strip()
        expose_tools = mcp_meta.get("expose_tools", [])
        if not server or not isinstance(expose_tools, list):
            return []

        server_config = self.mcp_servers.get(server)
        if not server_config:
            logger.warning(f"MCP server '{server}' not configured in mcp_servers dict")
            logger.warning(f"Available MCP servers: {list(self.mcp_servers.keys())}")
            return self._build_stub_tools(server, expose_tools)

        logger.info(f"Connecting to MCP server '{server}' at {server_config.url}")

        try:
            specs = self._run_async(
                self._fetch_mcp_tools(server, server_config, expose_tools)
            )
        except Exception as e:
            logger.error(f"Failed to fetch MCP tools from {server}: {e}", exc_info=True)
            return self._build_stub_tools(server, expose_tools)

        logger.info(f"Loaded {len(specs)} tools from MCP server '{server}'")
        results: list[SkillTool] = []

        for spec in specs:
            results.append(
                SkillTool(
                    name=spec.name,
                    description=spec.description,
                    parameters=spec.parameters,
                    function=self._make_mcp_tool_fn(server, spec.name, server_config),
                    tool_type="mcp",
                    mcp_server=server,
                )
            )
        return results

    def _make_mcp_tool_fn(self, server: str, tool_name: str, server_config: MCPServerConfig):
        """Create a callable function for MCP tool invocation."""
        manager = self.mcp_bridge_manager

        async def _async_call(**kwargs):
            await manager.ensure_connected(
                server, server_config.url, server_config.transport
            )
            return await manager.call_tool(server, tool_name, kwargs)

        def _mcp_fn(**kwargs):
            return self._run_async(_async_call(**kwargs))

        return _mcp_fn

    def _run_async(self, coro):
        """Run async coroutine from sync context safely."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result(timeout=60)
        else:
            return asyncio.run(coro)

    async def _fetch_mcp_tools(
        self,
        server: str,
        server_config: MCPServerConfig,
        expose_tools: list[str],
    ) -> list:
        """Fetch tools from MCP server asynchronously."""
        await self.mcp_bridge_manager.ensure_connected(
            server, server_config.url, server_config.transport
        )
        return await self.mcp_bridge_manager.list_tools(server, expose_tools)

    def _build_stub_tools(self, server: str, expose_tools: list[str]) -> list[SkillTool]:
        """Build stub tools when MCP server is not available."""
        results: list[SkillTool] = []
        for tool_name in expose_tools:
            def _make_stub_fn(srv: str, name: str):
                def _stub_fn(**kwargs):
                    return (
                        f"MCP server '{srv}' not connected. "
                        f"Tool '{name}' cannot be executed. "
                        f"Arguments: {kwargs}"
                    )
                return _stub_fn

            results.append(
                SkillTool(
                    name=str(tool_name),
                    description=f"MCP tool '{tool_name}' from server '{server}' (not connected)",
                    parameters={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                    function=_make_stub_fn(server, str(tool_name)),
                    tool_type="mcp",
                    mcp_server=server,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_catalog(self) -> str:
        if not self.skills:
            return "No skills installed."
        lines = []
        for s in self.skills.values():
            lines.append(f"  - {s.name}: {s.description}")
        return "\n".join(lines)

    def get_skill_names(self) -> list[str]:
        return list(self.skills.keys())

    def is_loaded(self, name: str) -> bool:
        s = self.skills.get(name)
        return s.loaded if s else False

    def create_skill(self, name: str, description: str, instructions: str, tools_code: str = "") -> str:
        """Create a new skill on disk (agent self-improvement)."""
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        meta = {"name": name, "description": description}
        frontmatter = yaml.dump(meta, default_flow_style=False)
        skill_md_content = f"---\n{frontmatter}---\n\n{instructions}"
        (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

        if tools_code.strip():
            (skill_dir / "tools.py").write_text(tools_code, encoding="utf-8")

        self.skills[name] = Skill(name=name, description=description, path=skill_dir, meta=meta)
        return f"Skill '{name}' created at {skill_dir}"
