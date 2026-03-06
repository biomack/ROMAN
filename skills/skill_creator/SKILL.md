---
name: skill_creator
description: >
  Meta-skill for creating new reusable skills from experience.
  Use when the user asks to save an approach, create a skill, or automate a workflow.
---

# Skill Creator (Meta-Skill)

This skill helps you create new skills — packaging successful approaches
into reusable skill folders that the agent can load in future sessions.

## When to Create a Skill
- The user explicitly asks to save an approach as a skill.
- A complex workflow was completed successfully and could be reused.
- A pattern keeps repeating across conversations.

## How to Create a Skill

Use the built-in `create_new_skill` tool with these arguments:
- **name**: lowercase with underscores (e.g., `deploy_checker`)
- **description**: Clear description of what the skill does and when to use it.
- **instructions**: The full markdown body for SKILL.md — include guidelines, workflow steps, and examples.
- **tools_code** (optional): Python code for `tools.py` if the skill needs executable tools.

## Skill Structure Best Practices
1. Start with a clear one-line purpose.
2. Include a **Workflow** section with numbered steps.
3. Include a **Guidelines** section with do's and don'ts.
4. If adding tools, follow this pattern in `tools_code`:

```python
def my_tool(arg1: str, arg2: int = 10) -> str:
    # implementation
    return "result"

TOOLS = [
    {
        "name": "my_tool",
        "function_name": "my_tool",
        "description": "What this tool does",
        "parameters": {
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "..."},
                "arg2": {"type": "integer", "description": "..."},
            },
            "required": ["arg1"],
        },
    },
]
```

## Example
If a user frequently asks to generate project READMEs, create a `readme_generator` skill
with templates and formatting guidelines.
