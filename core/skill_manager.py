"""
Skill discovery, indexing and progressive loading.

Implements the core Agent Skills pattern:
1. Discover all skills at startup (read only name + description from SKILL.md frontmatter)
2. Load full skill instructions + tools on demand (progressive disclosure)
"""

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .tool_registry import discover_tools

@dataclass
class SkillTool:
    name: str
    description: str
    parameters: dict
    function: callable


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
        max_reference_file_bytes: int = 32768,
        max_reference_total_bytes: int = 262144,
    ):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}
        self.skill_aliases: dict[str, str] = {}
        self.max_reference_file_bytes = max_reference_file_bytes
        self.max_reference_total_bytes = max_reference_total_bytes
        self._discover()

    # ------------------------------------------------------------------
    # Phase 1: Discovery (lightweight - frontmatter only)
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
                canonical_name = str(meta["name"])
                self.skills[canonical_name] = Skill(
                    name=canonical_name,
                    description=meta.get("description", ""),
                    path=entry,
                    meta=meta,
                )
                self._register_skill_aliases(canonical_name, meta.get("aliases"))

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
        skill = self.skills.get(self._resolve_skill_name(name))
        if skill is None or skill.loaded:
            return skill

        content = (skill.path / "SKILL.md").read_text(encoding="utf-8")
        parts = content.split("---", 2)
        skill.instructions = parts[2].strip() if len(parts) >= 3 else content

        skill.extra_files = self._load_references(skill.path)

        tools_py = skill.path / "tools.py"
        if tools_py.exists():
            skill.tools = self._load_tools(tools_py, skill.name)

        skill.loaded = True
        return skill

    def _register_skill_aliases(self, canonical_name: str, aliases: object) -> None:
        candidates: set[str] = {canonical_name}
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias.strip():
                    candidates.add(alias.strip())

        for candidate in candidates:
            normalized = self._normalize_skill_name(candidate)
            if normalized:
                self.skill_aliases[normalized] = canonical_name

    @staticmethod
    def _normalize_skill_name(name: str) -> str:
        return (
            (name or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )

    def _resolve_skill_name(self, name: str) -> str:
        normalized = self._normalize_skill_name(name)
        if normalized in self.skill_aliases:
            return self.skill_aliases[normalized]
        return name

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
                    )
                )
        return results

    def _load_references(self, skill_path: Path) -> dict[str, str]:
        references: dict[str, str] = {}
        total_bytes = 0
        for folder_name in ("resources", "references", "templates", "assets"):
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
