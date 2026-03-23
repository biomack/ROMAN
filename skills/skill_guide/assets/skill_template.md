---
name: REPLACE_skill_name
description: >
  REPLACE with what this skill does. Use this skill whenever the user mentions
  REPLACE_trigger_1, REPLACE_trigger_2, or REPLACE_trigger_3 — even if they
  don't explicitly say "REPLACE_keyword."
---

# REPLACE Skill Name

REPLACE with a one-sentence purpose statement.

## Workflow

1. Call `collect_context` with the user's message to extract structured input.
   If `missing_fields` is non-empty, ask the user for the missing data and stop.

2. REPLACE — describe the main action. Name the specific tool to call,
   explain what arguments to pass, and what to do with the result.

3. REPLACE — describe the next step. If there are conditions
   (e.g., "if X then do Y, otherwise do Z"), spell them out.

4. Summarize results and present them to the user in a clear format.

## Reference files

- `references/REPLACE.md` — REPLACE with description of when to read this file.
