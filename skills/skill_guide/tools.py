"""
Tools for the skill_guide skill.
Helps users create and validate agent skills.
"""

import json
import os
import re
from pathlib import Path
from typing import Annotated

from core.tool_registry import tool

SKILLS_DIR = Path(__file__).resolve().parent.parent


@tool("Generate a new skill directory with all required files following best practices")
def generate_skill_skeleton(
    name: Annotated[str, "Skill name in lowercase with underscores (e.g. log_analyzer)"],
    description: Annotated[str, "What the skill does and when to trigger it"],
    include_tools: Annotated[bool, "Generate a sample tools.py with @tool decorator example"] = True,
    include_references: Annotated[bool, "Create a references/ directory with a placeholder"] = False,
    include_assets: Annotated[bool, "Create an assets/ directory with a placeholder"] = False,
) -> str:
    """Create a skill directory skeleton with SKILL.md and optional tools.py, references/, assets/."""
    skill_dir = SKILLS_DIR / name

    if skill_dir.exists():
        return json.dumps({
            "ok": False,
            "error": f"Skill directory already exists: {skill_dir}",
        }, ensure_ascii=False, indent=2)

    skill_dir.mkdir(parents=True)

    skill_md = f'''---
name: {name}
description: >
  {description}
---

# {name.replace("_", " ").title()}

Brief purpose: describe what this skill does in one sentence.

## Workflow

1. Call `collect_context` with the user's message to extract structured input.
   If `missing_fields` is non-empty, ask the user for the missing data and stop.
2. Perform the main action — describe what tools to call and in what order.
3. Summarize results and present them to the user.
'''

    if include_references:
        skill_md += '''
## Reference files

- `references/guide.md` — describe when to read this file and what it contains.
'''

    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    if include_tools:
        tools_code = '''"""
Tools for {name} skill.
"""

import json
from typing import Annotated

from core.tool_registry import tool


@tool("Describe what this tool does in one sentence")
def example_tool(
    target: Annotated[str, "The main input parameter"],
    option: Annotated[str, "An optional configuration"] = "default",
) -> str:
    """Replace this with real implementation."""
    result = {{
        "target": target,
        "option": option,
        "status": "not implemented — replace with real logic",
    }}
    return json.dumps(result, ensure_ascii=False, indent=2)
'''.format(name=name)
        (skill_dir / "tools.py").write_text(tools_code, encoding="utf-8")

    if include_references:
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text(
            "# Reference Guide\n\nAdd reference documentation here.\n",
            encoding="utf-8",
        )

    if include_assets:
        assets_dir = skill_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / ".gitkeep").write_text("", encoding="utf-8")

    created_files = []
    for fpath in sorted(skill_dir.rglob("*")):
        if fpath.is_file():
            created_files.append(str(fpath.relative_to(SKILLS_DIR)))

    return json.dumps({
        "ok": True,
        "skill_name": name,
        "path": str(skill_dir),
        "created_files": created_files,
        "next_steps": [
            f"Edit {name}/SKILL.md — fill in the workflow and instructions",
            f"Edit {name}/tools.py — replace example_tool with real tools" if include_tools else None,
            "Run validate_skill to check the result",
        ],
    }, ensure_ascii=False, indent=2)


@tool("Validate an existing skill directory against best practices and report issues")
def validate_skill(
    skill_name: Annotated[str, "Name of the skill directory to validate"],
) -> str:
    """Check a skill for structural and content issues."""
    skill_dir = SKILLS_DIR / skill_name
    issues: list[dict[str, str]] = []
    good: list[str] = []

    if not skill_dir.exists():
        return json.dumps({
            "ok": False,
            "error": f"Skill directory not found: {skill_dir}",
        }, ensure_ascii=False, indent=2)

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        issues.append({"severity": "error", "message": "SKILL.md is missing (required)"})
    else:
        content = skill_md.read_text(encoding="utf-8")

        if not content.startswith("---"):
            issues.append({"severity": "error", "message": "SKILL.md has no YAML frontmatter"})
        else:
            parts = content.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                if "name:" not in fm:
                    issues.append({"severity": "error", "message": "Frontmatter missing 'name' field"})
                else:
                    good.append("Frontmatter has 'name'")

                if "description:" not in fm:
                    issues.append({"severity": "error", "message": "Frontmatter missing 'description' field"})
                else:
                    desc_match = re.search(r"description:\s*>?\s*\n?([\s\S]*?)(?:\n\w|\n---)", fm + "\n---")
                    desc_text = desc_match.group(1).strip() if desc_match else ""
                    if len(desc_text) < 50:
                        issues.append({
                            "severity": "warning",
                            "message": "Description is short — add trigger phrases so the model activates this skill reliably",
                        })
                    else:
                        good.append("Description is detailed")

                    trigger_words = ["use this skill", "whenever", "even if", "when the user"]
                    has_triggers = any(w in desc_text.lower() for w in trigger_words)
                    if not has_triggers:
                        issues.append({
                            "severity": "warning",
                            "message": "Description lacks explicit trigger phrases (e.g. 'Use this skill whenever...')",
                        })
                    else:
                        good.append("Description has trigger phrases")

                body = parts[2] if len(parts) >= 3 else ""
                line_count = len(body.strip().splitlines())
                if line_count > 500:
                    issues.append({
                        "severity": "warning",
                        "message": f"SKILL.md body is {line_count} lines — consider moving content to references/",
                    })
                else:
                    good.append(f"SKILL.md body is {line_count} lines (under 500)")

                if "## workflow" not in body.lower():
                    issues.append({"severity": "warning", "message": "No '## Workflow' section found"})
                else:
                    good.append("Has Workflow section")

    tools_py = skill_dir / "tools.py"
    if tools_py.exists():
        tools_content = tools_py.read_text(encoding="utf-8")
        if "@tool(" in tools_content:
            good.append("tools.py uses @tool decorator")
        elif "TOOLS" in tools_content and "TOOLS = [" in tools_content:
            issues.append({
                "severity": "warning",
                "message": "tools.py uses legacy TOOLS = [...] array — migrate to @tool decorator",
            })
        else:
            issues.append({"severity": "info", "message": "tools.py found but no @tool decorators or TOOLS array detected"})

    for dirname in ("references", "resources", "assets"):
        d = skill_dir / dirname
        if d.exists() and d.is_dir():
            good.append(f"{dirname}/ directory present")

    has_ref_dirs = any((skill_dir / d).exists() for d in ("references", "resources"))
    if has_ref_dirs:
        if skill_md.exists():
            content = skill_md.read_text(encoding="utf-8")
            if "references/" not in content and "resources/" not in content:
                issues.append({
                    "severity": "warning",
                    "message": "Reference directories exist but SKILL.md doesn't point to them — add explicit pointers",
                })
            else:
                good.append("SKILL.md has pointers to reference files")

    return json.dumps({
        "ok": len([i for i in issues if i["severity"] == "error"]) == 0,
        "skill_name": skill_name,
        "issues": issues,
        "good": good,
        "summary": f"{len(good)} checks passed, {len(issues)} issues found",
    }, ensure_ascii=False, indent=2)
