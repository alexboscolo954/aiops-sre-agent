## POST /charge 5xx errors come from payments failing its risk check: calls to fraud-check.risk.svc.cluster.local:8443 are refused, and each one returns a 502. The payments service itself appears healthy, so the fix is likely on the fraud-check side, which I could not inspect.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check risk service at fraud-check.risk.svc.cluster.local:8443 is refusing connections (connection refused), so payments returns 502 'risk check unavailable' on charge requests. Likely causes are that fraud-check is down, has no ready endpoints, or is not listening on 8443. This is inferred from payments logs only; no Kubernetes or fraud-check logs were available to confirm.
**Severity:** high  ·  **Affected:** shop/Service/payments, risk/Service/fraud-check

**Evidence**
- `grafana_query_loki_patterns (loki, {service_name="payments"}, last 30m)`: Pattern 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' occurred 135 times in 30m, against 636 'charge order=<_> status=200' lines.
- `grafana_query_loki_logs (loki, {service_name="payments"} |~ error/exception/5xx, last 30m)`: Repeated ERROR lines, e.g. 'charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused', interleaved with successful 'charge ... status=200 latency_ms=85' lines. Failures are continuous across the window, not a single burst.
- `grafana_query_loki_logs (loki, {service_name="payments"} |= "risk check unavailable", last 2h)`: The same connection-refused error is present in the 2h window, so the dependency failure is ongoing and not limited to the last 10 minutes.
- `grafana_list_loki_label_values (loki, service_namespace="risk")`: Only service_name values 'payments' and 'storefront' were returned. No logs from a fraud-check service were found in Loki, so the risk service's own health is unverified.
- `grafana_generate_deeplink (explore, loki)`: Explore link for the payments logs (the returned link shows the payments selector; the risk-check filter may not be preserved in the link). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. Check the fraud-check service in the risk namespace: pod status, restarts, Service endpoints, and whether it listens on port 8443. A refused connection usually means no ready pods or a wrong port.
2. If fraud-check is down, restore it (roll back its latest change if it has one, or restart its pods after human approval) and confirm that payments 502s stop.
3. Page the risk/fraud-check owners now, since payments charges are failing for roughly 8% of requests.
4. If fraud-check cannot be restored quickly, decide with the payments owners whether to bypass or degrade the risk check. That is a business decision and should not be made by automation.
5. Once recovered, confirm the 502 pattern count in payments logs drops to zero and that the PaymentsHighErrorRate alert resolves.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_patterns`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_stats`
5. `grafana_list_loki_label_values`
6. `grafana_query_loki_logs`
7. `grafana_query_loki_logs`
8. `grafana_list_loki_label_values`
9. `grafana_generate_deeplink`
