## About 8% of POST /charge calls are returning 5xx. The payments service logs show each failure is a 502 from its risk check, which cannot reach fraud-check.risk.svc.cluster.local:8443 (connection refused). The failure is in the fraud-check dependency, not in payments code.

**Root cause** (medium confidence, `dependency_failure`): Payments calls fraud-check.risk.svc.cluster.local:8443 for each charge. Those calls fail with 'dial tcp ... connect: connection refused', and payments returns status=502 'risk check unavailable'. The 'risk check unavailable' pattern appears 135 times in the last 30 minutes, and the successful charges log status=200 in between. This points to fraud-check not accepting connections (down, crashlooping, or with no ready endpoints), not to a payments bug. I could not query fraud-check's own logs or pods because no Kubernetes tool was available and no fraud-check stream appeared in Loki, so the cause on the fraud-check side is unconfirmed. I also found no rollout evidence either way.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: Over the last 30m, {service_name="payments"} shows 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' 135 times, against 636 'charge order=<_> status=200' lines.
- `grafana_query_loki_logs`: Recent ERROR lines from payments (namespace shop) are all 'charge order=o-... failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused', interleaved with status=200 charges. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_stats`: {service_name="payments"} has 1908 entries in the last 30m, so the 135 risk-check failures are roughly 7% of all lines, in line with the 8% 5xx alert.
- `grafana_list_loki_label_values`: Searches for a fraud-check or risk service stream returned only 'payments' and 'storefront', so fraud-check logs are not in Loki and its health could not be checked.

**Recommendations**
1. Check fraud-check.risk.svc.cluster.local:8443 now: its Deployment readiness, Service endpoints, pod restarts, and whether the port is listening. Connection refused usually means no pod is listening or the pod is down.
2. Check fraud-check's recent rollout history and events. If a revision was deployed shortly before the alert started, roll it back, since that would be a bad_rollout.
3. Confirm the fraud-check Service name and port match what payments is configured to call (a wrong port or DNS name would also give connection refused).
4. While fraud-check is down, consider whether payments can safely fail open or use a fallback for risk checks. That is a business decision, so it needs the owning team's approval.
5. After recovery, confirm that the payments 502 count falls to zero and that the 5xx rate is back under the alert threshold.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_patterns`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_stats`
5. `grafana_list_loki_label_values`
6. `grafana_query_loki_logs`
7. `grafana_list_loki_label_values`
8. `grafana_query_loki_logs`
9. `grafana_generate_deeplink`
