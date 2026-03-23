# Skill Anatomy

Every skill is a directory inside `skills/` with this structure:

```
skill-name/
├── SKILL.md          (required)
├── tools.py          (optional)
├── scripts/          (optional)
├── references/       (optional)
└── assets/           (optional)
```

## SKILL.md — the core

The only required file. Has two parts:

### 1. YAML frontmatter

```yaml
---
name: my_skill
description: >
  What the skill does. Use this skill whenever the user mentions X, Y, or Z —
  even if they phrase it differently.
---
```

- `name` (required) — unique identifier, lowercase with hyphens or underscores.
- `description` (required) — tells the model WHEN to load this skill. Make it "pushy" — list specific trigger phrases and scenarios. The model tends to under-trigger skills, so be generous.
- `mcp` (optional) — declares MCP server tools to expose:
  ```yaml
  mcp:
    server: victoriametrics-mcp
    expose_tools:
      - query
      - query_range
  ```

### 2. Markdown body

Instructions for the model after the skill is loaded. This is injected into the system prompt.

Key sections to include:
- **Purpose** — one sentence about what this skill does.
- **Workflow** — numbered steps. Be specific: name the tools, explain the order, describe what to do with results.
- **Reference files** — explicit pointers to files in `references/` or `resources/`, with guidance on when to read them.

Keep the body under 500 lines. If you need more content, move it to `references/`.

## tools.py — Python tools

Optional. Contains functions decorated with `@tool` that become callable by the model.

```python
from typing import Annotated
from core.tool_registry import tool

@tool("Short description of what this tool does")
def my_tool(
    param1: Annotated[str, "What this parameter is"],
    param2: Annotated[int, "What this parameter controls"] = 10,
) -> str:
    ...
```

Rules:
- Functions must return `str` (typically JSON).
- Use `Annotated[type, "description"]` for every parameter.
- Parameters with default values become optional in the schema.
- Private functions (starting with `_`) are ignored.
- Supported types: `str`, `int`, `float`, `bool`, `list[str]`, `list[int]`, `dict`, `Literal["a", "b"]`.

## references/ — documentation loaded into context

Markdown files that the model can access when the skill is loaded.
These are automatically loaded as `extra_files` and injected into the system prompt.

Use for:
- API documentation
- Configuration guides
- Query pattern libraries
- Threshold tables

Point to these files explicitly in SKILL.md so the model knows when to consult them.

## assets/ — files used in output

Templates, configs, playbooks, and other files consumed by tools.
Also auto-loaded as `extra_files`.

Examples:
- Ansible playbooks
- Jinja templates
- Config file templates

## scripts/ — standalone executables

Scripts that can be run via shell. Not auto-loaded into context.
Useful for setup scripts, validation tools, or data processing pipelines.

## resources/ — legacy alias for references/

Works identically to `references/`. Both are scanned by the skill manager.
Prefer `references/` for new skills.
