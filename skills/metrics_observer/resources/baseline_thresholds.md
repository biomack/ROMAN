# Baseline Thresholds (Reference)

Default operational thresholds (adjust per service):

- Error rate:
  - healthy: `< 1%`
  - degraded: `1%..3%`
  - critical: `> 3%`
- P95 latency:
  - healthy: `< 300ms`
  - degraded: `300ms..800ms`
  - critical: `> 800ms`
- Availability:
  - healthy: `>= 99.9%`
  - degraded: `99.0%..99.9%`
  - critical: `< 99.0%`

If user provides custom SLO/SLA, prefer user-defined thresholds.
