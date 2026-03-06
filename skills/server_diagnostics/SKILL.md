---
name: server_diagnostics
description: >
  Diagnose whether a server is reachable and likely running by testing SSH connectivity,
  ping latency, traceroute path, and common open ports.
---

# Server Diagnostics Skill

Use this skill when the user asks to check if a server is running, reachable, or healthy.

## Trigger Scenarios
- "Check if server is up"
- "Test SSH connection"
- "Check ping and latency"
- "Run traceroute"
- "What ports are open?"

## Workflow
1. First call `collect_context` with the user's message and metadata.
2. If `collect_context` returns non-empty `missing_fields`, ask a clarifying question and stop.
3. Validate target host or IP from user input.
4. Run `ping_host` to test ICMP reachability and latency.
5. Run `traceroute_host` to inspect network path and possible routing issues.
6. Run `test_ssh_connection` to test SSH TCP reachability and optional login probe.
7. Run `scan_common_ports` to identify commonly open service ports.
8. Run `analyze_server_availability` when a user asks for one consolidated verdict.
9. Provide a clear result: `UP`, `PARTIAL`, or `DOWN`, with evidence.

## Reporting Rules
- Separate network reachability from service availability.
- If ping fails but TCP/SSH succeeds, report that ICMP may be blocked.
- If SSH TCP is open but login probe fails, report "SSH reachable, authentication failed."
- Always include the checks that were run and their outcomes.

## How It Works (Explain To User)
When asked "how it works," explain:
- Ping checks basic host reachability and round-trip latency.
- Traceroute shows the path and hops packets take to the destination.
- SSH check verifies TCP connectivity to SSH port and optionally attempts a non-interactive login probe.
- Port scan checks whether common service ports accept TCP connections.

## Available Tools
- `ping_host`
- `traceroute_host`
- `test_ssh_connection`
- `scan_common_ports`
- `analyze_server_availability`
