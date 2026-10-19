## About 8% of POST /charge requests are failing with 502s because payments cannot reach the fraud-check risk service at fraud-check.risk.svc.cluster.local:8443, which refuses connections. The likely cause is that fraud-check is down or not listening, but I found no fraud-check logs or cluster state to confirm this, so the root cause is inferred from payments' errors.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check dependency (risk namespace) is refusing TCP connections on port 8443, so payments' risk check fails and /charge returns 502. Likely causes are fraud-check pods crashed or scaled to zero, or no ready endpoints behind the service. I could not check this directly because no Kubernetes or Prometheus tools were available and Loki has no fraud-check stream.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_logs (Loki, {service_name="payments"})`: Repeated ERROR lines: "charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused", interleaved with status=200 charges.
- `grafana_query_loki_patterns (Loki, {service_name="payments"}, last 30m)`: Pattern "charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused" occurs 135 times, against 636 successful "charge ... status=200" lines.
- `grafana_list_loki_label_values (Loki, service_name, last 1h)`: Only "payments" and "storefront" service_name values exist. No fraud-check logs were found, so fraud-check's own state is unobserved.

**Recommendations**
1. Check fraud-check health in the risk namespace: pod status, restarts, and Service endpoints for port 8443. Ask the owning team if they are reachable and whether they are scaled down.
2. Look for recent rollouts, config or NetworkPolicy changes, or scaling events in the risk namespace or the Service that changed shortly before the alert start.
3. If fraud-check is down, restore it first. If the team confirms the outage, consider whether payments can fail over or degrade the risk check safely; that is a business decision, so get approval before changing the behaviour.
4. Confirm the impact with the Prometheus error-rate metric for POST /charge, which I could not query here, and check whether the 8% rate is holding or rising.
5. Once fraud-check is reachable, verify that the 502 lines in payments stop and the 200 rate recovers.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_list_loki_label_values`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_patterns`
5. `grafana_list_loki_label_values`
6. `grafana_query_loki_logs`
7. `grafana_query_loki_patterns`
8. `grafana_query_loki_logs`
