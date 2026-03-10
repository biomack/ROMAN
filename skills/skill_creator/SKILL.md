---
name: skill_creator
description: >
  Meta-skill for creating new reusable skills from experience.
  Use when the user asks to save an approach, create a skill, automate a workflow,
  or package a successful conversation into something reusable — even if they just
  say "let's make this repeatable" or "save this for next time."
---

# Skill Creator

Package successful approaches into reusable skill folders that the agent can load in future sessions.

## When to create a skill

- The user explicitly asks to save an approach as a skill.
- A complex workflow was completed successfully and could be reused.
- A pattern keeps repeating across conversations.

## How to create a skill

Use the built-in `create_new_skill` tool with these arguments:
- **name**: lowercase with underscores (e.g., `deploy_checker`)
- **description**: what the skill does AND when to trigger it — be specific and "pushy" so the model doesn't under-trigger.
- **instructions**: the full markdown body for SKILL.md — include workflow steps, guidelines, and examples.
- **tools_code** (optional): Python code for `tools.py` if the skill needs executable tools.

## Skill structure

```
skill-name/
├── SKILL.md          (required — frontmatter + instructions)
├── tools.py          (optional — Python tools with @tool decorator)
├── scripts/          (optional — standalone executable scripts)
├── references/       (optional — docs loaded into context as needed)
└── assets/           (optional — files used in output: templates, configs)
```

## SKILL.md format

```markdown
---
name: my_skill
description: >
  What this skill does. Use this skill whenever the user mentions X, Y, or Z.
---

# My Skill

Brief purpose statement.

## Workflow

1. Step one — explain what to do and why.
2. Step two — be specific about tool calls.
3. Step three — describe expected output.

## Reference files

- `references/foo.md` — when to read this file and what it contains.
```

## Writing tools with @tool decorator

When a skill needs Python tools, use the `@tool` decorator instead of
a `TOOLS` JSON manifest. The decorator auto-generates JSON schema from
type hints and `Annotated` descriptions:

```python
from typing import Annotated
from core.tool_registry import tool

@tool("Check if a service is healthy by querying its /health endpoint")
def check_health(
    host: Annotated[str, "Hostname or IP address"],
    port: Annotated[int, "Service port"] = 8080,
    timeout: Annotated[int, "Request timeout in seconds"] = 5,
) -> str:
    import json, socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return json.dumps({"host": host, "healthy": True})
    except OSError as e:
        return json.dumps({"host": host, "healthy": False, "error": str(e)})
```

Private helper functions (starting with `_`) are not registered as tools.

## Best practices

- Keep SKILL.md under 500 lines. Move large reference material into `references/`.
- Make the frontmatter `description` specific and trigger-happy — include phrases users might say.
- Use imperative form in instructions ("Call X", not "You should call X").
- Explain *why* each step matters instead of relying on MUST/ALWAYS directives.
- Include examples where they help clarify expected input/output.
- For reference files over 300 lines, add a table of contents.
