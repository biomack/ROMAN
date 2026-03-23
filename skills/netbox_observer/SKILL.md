---
name: netbox_observer
aliases:
  - netbox-observer
  - netbox_observer
  - netbox
description: >
  Analyze NetBox inventory, IPAM and audit trail via NetBox MCP tools. Use this
  skill whenever the user asks about devices, IP addresses, prefixes, VLANs,
  sites, racks, tenants, circuits, or "who changed what" in NetBox.
mcp:
  server: netbox-mcp
  expose_tools:
    - get_objects
    - get_object_by_id
    - get_changelogs
    - netbox_get_objects
    - netbox_get_object_by_id
    - netbox_get_changelogs
---

# NetBox Observer Skill

Read-only investigation skill for NetBox data through MCP (`netbox-mcp`).

## Trigger conditions

Activate this skill when the user asks to:
- find/list NetBox entities (devices, IPs, prefixes, VLANs, sites, racks, tenants)
- inspect a specific NetBox object by id
- investigate changes/audit history ("who changed", "what changed", "changelog")
- check inventory or IPAM state for a location/service/platform

## Workflow

1. Call `collect_context` with the latest user request.
   - If `missing_fields` is non-empty, ask one short clarifying question and stop.

2. Resolve object type and query mode:
   - For broad search/list questions -> use `get_objects` (or `netbox_get_objects`).
   - For object by id -> use `get_object_by_id` (or `netbox_get_object_by_id`).
   - For audit/history -> use `get_changelogs` (or `netbox_get_changelogs`).

3. Optimize response size:
   - Before list/detail calls, run `suggest_fields` and pass `fields` whenever possible.
   - Prefer a focused field set for large result sets to reduce tokens.

4. Query data:
   - Use strict, explicit filters from user intent (`site`, `status`, `role`, etc.).
   - If query returns nothing, relax one filter at a time and retry once.
   - Do not run broad unfiltered requests on large object types unless user explicitly asks.

5. For changelog requests:
   - Use explicit timeframe if provided by user.
   - If timeframe is missing, default to recent period and state it in the response.

6. Call `format_netbox_report` for a stable output structure.

## Deterministic contract

- Do not invent object types that are not in NetBox MCP results.
- Do not infer hidden changes if changelog data is missing.
- Always state when data is partial or unavailable.
- Keep output format stable: `Scope -> Evidence -> Conclusion -> Next action`.

## Reporting format

### Scope
- What was searched (object type, filters, time window if any)

### Evidence
- Key objects/fields returned by NetBox
- Counts and notable attributes
- Changelog records if requested

### Conclusion
- Short, evidence-based answer to the user question

### Next action
- One practical follow-up (for example, refine filter, inspect object id, expand period)

## MCP usage notes

- `get_objects`/`netbox_get_objects`: list objects by type + filters.
- `get_object_by_id`/`netbox_get_object_by_id`: fetch full details for one object.
- `get_changelogs`/`netbox_get_changelogs`: audit trail and history.
- This skill is read-only; no write operations are expected.
