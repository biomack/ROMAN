# Best Practices for Writing Skills

## 1. Description — make it trigger-happy

The frontmatter `description` is the primary mechanism for skill activation.
The model reads all descriptions and decides which skill to load.

Bad (undertriggers):
```yaml
description: Analyze metrics from VictoriaMetrics.
```

Good (triggers reliably):
```yaml
description: >
  Analyze service metrics from VictoriaMetrics MCP tools, detect anomalies,
  and provide operational conclusions with evidence. Use this skill whenever the
  user asks about service health, metrics, latency, error rates, CPU/memory usage,
  monitoring dashboards, PromQL queries, or wants to investigate spikes, drops,
  or trends — even if they don't mention "metrics" explicitly.
```

Key patterns:
- Start with what the skill does.
- Add "Use this skill whenever..." with a list of trigger scenarios.
- End with "even if they don't explicitly say X" to catch indirect requests.

## 2. Instructions — imperative, explain why

Write instructions as direct commands, not suggestions.

Bad:
```markdown
You should probably call ping_host first. It's important to ALWAYS check reachability.
```

Good:
```markdown
Call `ping_host` first to check basic reachability — if the host doesn't respond
to ICMP, the user needs to know immediately before running slower checks.
```

Principles:
- Use imperative: "Call X", "Run Y", "Report Z".
- Explain the reason behind each step — the model makes better decisions when it understands *why*.
- Avoid MUST/ALWAYS/NEVER in caps — they feel authoritarian and don't improve compliance.

## 3. Progressive disclosure — keep SKILL.md lean

SKILL.md is always loaded into context when the skill activates.
Every line costs tokens. Keep the body under 500 lines.

Move large content to:
- `references/` — docs the model reads on demand.
- `assets/` — files consumed by tools, not by the model directly.

Always add explicit pointers in SKILL.md:
```markdown
## Reference files

- `references/api_docs.md` — full API reference. Read this when constructing API calls.
- `references/error_codes.md` — error code lookup table. Read when interpreting error responses.
```

## 4. Tools — self-documenting via @tool

Every tool should be understandable from its decorator and signature alone:

```python
@tool("Check if a TCP port is open on a remote host")
def check_port(
    host: Annotated[str, "Hostname or IP address"],
    port: Annotated[int, "TCP port number"],
    timeout: Annotated[float, "Connection timeout in seconds"] = 2.0,
) -> str:
```

From this, the model knows:
- What the tool does (decorator string).
- What parameters it needs (Annotated descriptions).
- Which parameters are optional (have defaults).
- What types to pass (type hints).

No separate documentation needed.

## 5. Workflow — be specific about tool calls

Don't just list tools. Describe the sequence, conditions, and what to do with results.

Bad:
```markdown
## Tools
- ping_host
- traceroute_host
- test_ssh_connection
```

Good:
```markdown
## Workflow
1. Call `ping_host` to test ICMP reachability and measure round-trip latency.
2. Call `traceroute_host` to inspect the network path and spot routing issues.
3. Call `test_ssh_connection` to verify SSH TCP reachability;
   enable `run_login_probe` only when the user provides credentials.
4. If the user wants a single answer, call `analyze_server_availability` —
   it combines all checks and returns UP/PARTIAL/DOWN.
```

## 6. Examples — show, don't just tell

Include concrete Input/Output examples when the format isn't obvious:

```markdown
## Example

**User**: "check if 10.0.0.5 is up"

**Agent calls**: `ping_host(host="10.0.0.5")`

**Result**: Host is reachable, latency 12ms. ICMP ping succeeded.
```

## 7. MCP tools — declare in frontmatter

If the skill uses tools from an MCP server, declare them in the frontmatter:

```yaml
mcp:
  server: victoriametrics-mcp
  expose_tools:
    - query
    - query_range
```

Only listed tools will be exposed. The model won't see other tools from that server.
The MCP server must be configured in `.env` with a matching name.
