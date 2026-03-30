---
name: netbox
description: >
  Query NetBox DCIM/IPAM via MCP server — devices, interfaces, cables, IPs,
  VLANs, sites, racks, and more. Use when the user mentions NetBox, нетбокс,
  network infrastructure inventory, DCIM, IPAM, or asks about devices,
  interfaces, cables, IP addresses, VLANs, prefixes, sites, or racks
  managed in NetBox.
aliases:
  - нетбокс
  - netbox-query
  - netbox_query
---

# NetBox Skill

Query and explore network infrastructure data via a NetBox MCP server.

## Workflow

1. Call `collect_context` with the user's message.
   If `missing_fields` is non-empty, ask a clarifying question and stop.
2. Call `netbox_query` with the user's full question.
   The tool connects to the NetBox MCP server, discovers available API tools,
   uses an LLM sub-agent to pick and call the right tools, and returns a
   ready-made text answer.
3. Present the answer to the user, reformatting if needed.

## Notes

- The tool performs its own multi-step reasoning internally (sub-agent),
  so you only need to pass the user's question — no need to pick individual
  NetBox API calls yourself.
- If the answer is empty or unclear, ask the user to refine their query
  (e.g. provide a device name, ID, or site).
- Configuration is via environment variables: `NETBOX_MCP_URL`,
  `NETBOX_LLM_URL`, `NETBOX_LLM_MODEL`, `NETBOX_MAX_TOOL_ROUNDS`,
  `NETBOX_MAX_IDENTICAL_TOOL_CALLS` (see example.env).
