## About 8% of POST /charge requests are failing with 502s because the payments service cannot reach fraud-check.risk.svc.cluster.local:8443 (connection refused). The failures come from the risk-check dependency, not from a payments code change. I could not confirm the state of fraud-check itself.

**Root cause** (medium confidence, `dependency_failure`): Payments logs repeat 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' 135 times in the last 30 minutes, against 636 successful 'charge ... status=200' lines. Each failed charge is a risk-check call that was refused at the TCP level, so the fraud-check endpoint was not accepting connections, not timing out. No rollout or config change was visible in the data I could query. Loki has no logs from any fraud-check service, so its health is unverified. Confidence is medium because the failure signature is direct but the dependency's own state was not observed.
**Severity:** high  ·  **Affected:** shop/unknown/payments

**Evidence**
- `grafana_query_loki_patterns`: Over the last 30m, {service_name="payments"} produced 636 'charge order=<_> status=200 latency_ms=<_>' lines and 135 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' lines.
- `grafana_query_loki_logs`: Recent raw error lines, e.g. 'charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' (level=error), alternate with status=200 charges, so the failures are intermittent rather than total. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_patterns`: A query for {service_name=~".*fraud.*"} over the last 30m returned no fraud-check stream or pattern, so there are no logs from the dependency itself.
- `grafana_list_loki_label_values`: service_name values in namespace shop over the last hour are only 'payments' and 'storefront'. No fraud-check service is shipping logs to Loki.

**Recommendations**
1. Check the fraud-check service in the risk namespace: whether its pods are running, its Service endpoints, and its recent events. Connection refused usually means no pod is listening or the Service has no endpoints.
2. If fraud-check is down or crash-looping, restore it first, or escalate to the risk team that owns it.
3. As a mitigation while fraud-check is down, consider whether payments can fail open or bypass the risk check for low-value charges. This is a business and risk decision, so get explicit sign-off first.
4. Check whether a recent change to fraud-check or its Service/NetworkPolicy caused the refusals, and roll it back if so.
5. After recovery, confirm the 5xx ratio on POST /charge falls below the alert threshold and that the 'connection refused' pattern stops appearing in payments logs.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_patterns`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_stats`
5. `grafana_query_loki_patterns`
6. `grafana_list_loki_label_values`
7. `grafana_query_loki_logs`
8. `grafana_query_loki_stats`
9. `grafana_generate_deeplink`
