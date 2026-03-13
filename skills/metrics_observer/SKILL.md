---
name: metrics_observer
aliases:
  - top_queries
  - top-queries
description: >
  Analyze service metrics from VictoriaMetrics MCP tools, detect anomalies,
  and provide operational conclusions with evidence. Use this skill whenever the
  user asks about service health, metrics, latency, error rates, CPU/memory usage,
  monitoring dashboards, PromQL queries, or wants to investigate spikes, drops,
  or trends — even if they don't mention "metrics" explicitly.
mcp:
  server: victoriametrics-mcp
  expose_tools:
    - query
    - query_range
    - metrics
    - labels
    - label_values
---

# Metrics Observer Skill

Analyze metrics across heterogeneous environments (k8s workloads, postgres, baremetal/VM hosts, and custom app metrics), detect anomalies, and build health verdicts from time-series data.

This skill is designed for deterministic execution: same input intent should produce the same tool-call flow and output structure.

## Workflow

1. Call `collect_context` first.
   - Use the latest user request as input.
   - If `missing_fields` is non-empty, ask one clarifying question and stop.

2. Resolve analysis scope from `collect_context`.
   - Required: target (`service` / `pod` / `instance` / `namespace` / `db`), domain, and time window.
   - Default `time_window` to `1h` only when user did not specify it.

3. Run deterministic discovery in this exact order:
   - Call `metrics` with a domain-aligned pattern (`cpu`, `memory`, `kube`, `postgres`, `http`, `latency`, `error`).
   - Select a candidate metric family.
   - Call `labels` for that metric.
   - Call `label_values` for the chosen target label.
   - If target value is not found in `label_values`, ask a clarifying question and stop.

4. Build candidate PromQL templates.
   - Call `build_promql_suggestions` with explicit `service`, `metric_type`, `time_window`, and `target_label`.
   - Use only selectors validated by `labels` + `label_values`.
   - Read `references/query_patterns.md` when composing final query expressions.

5. Query current state.
   - Call `query` for point-in-time values.
   - Use explicit label filters; never use broad unfiltered queries.

6. Query trend for the same expression.
   - Call `query_range` with fixed step by window:
     - `<= 1h` -> step `60s`
     - `> 1h and <= 6h` -> step `300s`
     - `> 6h` -> step `900s`
   - If the response is empty, return to discovery (step 3) and adjust labels/metric family.

7. Evaluate against baseline.
   - Read `resources/baseline_thresholds.md` when user thresholds are not provided.
   - Mark each metric as `ok`, `warning`, or `critical` with explicit evidence.

8. Produce final structured output.
   - Call `format_metrics_report` using collected values, baseline comparison, and timestamps.
   - Return only evidence-based conclusions.

## Deterministic execution contract

- Do not skip `collect_context`.
- Do not call `query` or `query_range` before `metrics` + `labels` + `label_values`.
- Do not invent label keys or metric names that were not observed during discovery.
- If data is missing, explicitly report `insufficient_data` rather than guessing.
- Keep output format stable: `Scope -> Evidence -> Conclusion -> Next action`.

## Report format

### Scope
- Service/component being analyzed
- Environment (if identifiable from labels)
- Time window examined

### Evidence
- Exact metric values with timestamps
- Comparison with baseline if applicable
- Notable patterns or anomalies
- Explicit note when data is missing (`insufficient_data`)

### Conclusion
Rate the health status:
- `healthy` — all metrics within normal ranges
- `degraded` — some metrics elevated but service functional
- `critical` — metrics indicate service failure or severe degradation

### Next action
One practical follow-up step (e.g., "check logs for service X", "investigate pod Y restarts").

## Reference files

- `resources/baseline_thresholds.md` — default operational thresholds for error rate, latency, availability. Read this when comparing metric values against SLOs.
- `references/query_patterns.md` — reusable PromQL patterns for common scenarios. Read this when constructing queries for a new metric type.

## Tips

- Always mention when data is missing or incomplete.
- If a query returns no data, re-check metric name and label keys first (`instance` vs `pod` vs `service` vs `container`).
- For high-cardinality metrics, use label filters to limit result size.
- Avoid overly broad queries on large datasets — they slow down the MCP server.
