---
name: metrics_observer
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
    - metrics_metadata
    - labels
    - label_values
    - series
    - tsdb_status
    - active_queries
    - top_queries
---

# Metrics Observer Skill

Analyze service metrics, detect anomalies, and build health verdicts from time-series data.

## Workflow

1. **Identify the target**: determine service name, metric patterns, and time window from the user's request.
   If the service name is unclear, ask — a broad query on a large dataset wastes time and tokens.

2. **Explore metrics** (when the user doesn't specify exact metric names):
   - Call `metrics` to list available metrics matching patterns.
   - Call `labels` and `label_values` to discover dimensions and find the exact service/instance.

3. **Query current state**:
   - Use `query` for point-in-time values (current error rate, latency p99, etc.).
   - Always include relevant label filters in the selector.

4. **Analyze trends**:
   - Use `query_range` with an appropriate step and time window.
   - Compare with baseline periods when relevant.
   - Read `resources/baseline_thresholds.md` for default SLO thresholds when the user hasn't provided their own.

5. **Build PromQL queries**:
   - Use `build_promql_suggestions` to generate starting-point queries for common metric types.
   - Read `references/query_patterns.md` for additional patterns and examples.

6. **Summarize findings** with concrete values and timestamps.
   Use `format_metrics_report` to produce a structured report.

## Report format

### Scope
- Service/component being analyzed
- Environment (if identifiable from labels)
- Time window examined

### Evidence
- Exact metric values with timestamps
- Comparison with baseline if applicable
- Notable patterns or anomalies

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
- If a query returns no data, check label filters and time range before concluding.
- For high-cardinality metrics, use label filters to limit result size.
- Avoid overly broad queries on large datasets — they slow down the MCP server.
