# Query Patterns (Reference)

Use these patterns as starting points. Adapt labels and service names.

- Error rate:
  - `sum(rate(http_requests_total{status=~"5..",service="$service"}[5m])) / sum(rate(http_requests_total{service="$service"}[5m]))`
- P95 latency:
  - `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="$service"}[5m])) by (le))`
- CPU usage:
  - `avg(rate(process_cpu_seconds_total{service="$service"}[5m]))`
- Memory RSS:
  - `avg(process_resident_memory_bytes{service="$service"})`

When user asks "is service healthy", use both latency and error rate.
