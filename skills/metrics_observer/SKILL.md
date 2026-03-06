---
name: metrics_observer
description: >
  Analyze service metrics from VictoriaMetrics MCP tools, detect anomalies,
  and provide operational conclusions with evidence.
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

Use this skill when the user asks to:
- Check service metrics or system health
- Investigate spikes, drops, latency, error rates
- Compare current values with baseline or historical data
- Build a health verdict from time-series signals
- Explore available metrics and labels
- Analyze cardinality and query performance

## Available MCP Tools

### Query Tools
- `query`: Execute instant PromQL/MetricsQL queries for current state
- `query_range`: Execute range queries over a time period for trend analysis

### Exploration Tools  
- `metrics`: List all available metric names
- `metrics_metadata`: Get metric type, help text, and units
- `labels`: List all available label names
- `label_values`: Get values for a specific label
- `series`: List time series matching a selector

### Status Tools
- `tsdb_status`: View TSDB cardinality statistics
- `active_queries`: View currently executing queries
- `top_queries`: View most frequent or slowest queries

## Required Workflow

1. **Identify the target**: Determine service name, metric patterns, and time window from user request.

2. **Explore metrics** (if needed):
   - Call `metrics` to list available metrics matching patterns
   - Call `labels` to discover available dimensions
   - Call `label_values` to find specific services/instances

3. **Query current state**:
   - Use `query` for point-in-time values (e.g., current error rate, latency p99)
   - Always include relevant labels in the selector

4. **Analyze trends**:
   - Use `query_range` with appropriate step and time window
   - Compare with baseline periods when relevant

5. **Summarize findings** with concrete values and timestamps.

## Query Examples

### Current error rate
```
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
```

### Latency percentiles
```
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))
```

### CPU usage by service
```
avg(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (container)
```

## Reporting Format

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
- `healthy`: All metrics within normal ranges
- `degraded`: Some metrics showing elevated values but service functional
- `critical`: Metrics indicate service failure or severe degradation

### Next Action
One practical follow-up step (e.g., "check logs for service X", "investigate pod Y restarts")

## Tool Usage Notes

- Always mention when data is missing or incomplete
- If a query returns no data, check label filters and time range
- For high-cardinality metrics, use label filters to limit results
- Consider query performance - avoid overly broad queries on large datasets
