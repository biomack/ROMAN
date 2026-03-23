# Query Patterns (Reference)

Use these patterns as starting points. Always adapt metric names and labels to your environment.

## Discovery-first patterns

- Metric families by name:
  - `topk(50, count by(__name__)({__name__=~".*(cpu|memory|postgres|kube|http).*"}))`
- Check if a metric has data:
  - `count(node_cpu_seconds_total)`
- Discover target labels for metric:
  - `count by(instance, job) (up)`

## Host / baremetal

- CPU usage % by instance:
  - `100 * (1 - avg by(instance) (rate(node_cpu_seconds_total{mode="idle",instance="$instance"}[5m])))`
- Memory usage % by instance:
  - `100 * (1 - (node_memory_MemAvailable_bytes{instance="$instance"} / node_memory_MemTotal_bytes{instance="$instance"}))`

## Kubernetes

- Pod CPU usage:
  - `sum(rate(container_cpu_usage_seconds_total{namespace="$namespace",pod="$pod"}[5m]))`
- Pod restarts in window:
  - `sum(increase(kube_pod_container_status_restarts_total{namespace="$namespace",pod="$pod"}[1h]))`

## PostgreSQL

- TPS:
  - `sum(rate(pg_stat_database_xact_commit{datname="$db"}[5m]) + rate(pg_stat_database_xact_rollback{datname="$db"}[5m]))`
- Active connections:
  - `sum(pg_stat_activity_count{datname="$db"})`

## Application HTTP metrics

- Error rate:
  - `sum(rate(http_requests_total{status=~"5..",service="$service"}[5m])) / sum(rate(http_requests_total{service="$service"}[5m]))`
- P95 latency:
  - `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="$service"}[5m])) by (le))`

When user asks "is service healthy", use both latency and error rate.
