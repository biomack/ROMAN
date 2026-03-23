---
name: skill_guide
description: >
  Interactive guide for creating, structuring, and writing agent skills.
  Use this skill whenever the user asks how to create a skill, wants to see
  skill examples, asks about SKILL.md format, tool decorators, skill structure,
  best practices for writing skills, or says anything like "help me build a skill",
  "show me a skill template", "how do skills work", or "teach me skills."
---

# Skill Guide

Teach the user how to create well-structured agent skills by explaining the anatomy,
showing real examples, and generating ready-to-use skeletons.

## Workflow

1. Start by understanding what the user needs:
   - If they want to **learn** — walk them through the skill anatomy and best practices.
   - If they want to **create** — gather requirements and generate a skeleton.
   - If they want to **validate** — run checks on an existing skill.

2. When explaining, use concrete examples from this project's existing skills
   (`server_diagnostics`, `install_node_exporter`, `metrics_observer`).
   Read `references/skill_anatomy.md` for the detailed structure breakdown.

3. When the user is ready to create a skill:
   - Call `generate_skill_skeleton` with the skill name and description.
   - Show them the generated files and explain what to fill in.
   - Read `references/best_practices.md` for writing guidelines to share.

4. When the user has a draft skill and wants feedback:
   - Call `validate_skill` pointing at the skill directory.
   - Report what's good and what needs improvement.

## Teaching approach

Adapt to the user's experience level. If they seem new to coding, avoid jargon
and explain terms like "frontmatter", "type hints", and "decorator" when first used.
If they're experienced, skip the basics and focus on the specific patterns that
make skills effective.

Always show a working example alongside any explanation — people learn faster
from code than from prose.

## Reference files

- `references/skill_anatomy.md` — detailed breakdown of every file and directory in a skill, with examples. Read this when the user asks "what goes where" or "what is the structure."
- `references/best_practices.md` — writing guidelines: description triggers, imperative style, progressive disclosure, reference pointers. Read this when the user asks "how do I write good instructions" or "what are the best practices."
- `assets/skill_template.md` — a ready-to-use SKILL.md template. Read this when the user asks for a template or starting point.
