---
name: server_diagnostics
description: >
  Diagnose whether a server is reachable and likely running by testing SSH connectivity,
  ping latency, traceroute path, and common open ports. Use this skill whenever the user
  mentions checking a server, testing connectivity, diagnosing network issues, verifying
  if a host is up or down, scanning ports, or troubleshooting SSH access — even if they
  don't explicitly say "diagnostics."
---

# Server Diagnostics Skill

Check if a server is running, reachable, or healthy using network probes.

## Workflow

1. Call `collect_context` with the user's message and metadata.
   If `missing_fields` is non-empty, ask a clarifying question and stop — the target host is required.
2. Run `ping_host` to test ICMP reachability and measure round-trip latency.
3. Run `traceroute_host` to inspect the network path and spot routing issues.
4. Run `test_ssh_connection` to verify SSH TCP reachability; enable `run_login_probe` only when the user provides credentials.
5. Run `scan_common_ports` to discover which service ports accept connections.
6. When the user wants a single consolidated answer, call `analyze_server_availability` — it combines all checks above and returns an `UP`, `PARTIAL`, or `DOWN` verdict.

## Reporting

Separate network reachability from service availability — they are different things.
If ping fails but TCP/SSH succeeds, explain that ICMP may be blocked by a firewall.
If SSH TCP is open but the login probe fails, report "SSH reachable, authentication failed."
Always list the checks that were run and their outcomes so the user can see the evidence.

## Explaining to the user

When the user asks "how does this work," explain each probe in plain language:
- Ping checks basic host reachability and round-trip latency.
- Traceroute shows the path packets take and where delays occur.
- SSH check verifies TCP connectivity to the SSH port and optionally attempts a non-interactive login.
- Port scan checks whether common service ports accept TCP connections.
