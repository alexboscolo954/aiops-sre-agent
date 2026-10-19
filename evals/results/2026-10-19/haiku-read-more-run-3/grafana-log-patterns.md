## POST /charge 5xx errors in the payments service are caused by its risk check failing: every 502 in the logs is 'risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused'. The fraud-check dependency appears to be down or not listening; no fraud-check logs were found, so its own state is unconfirmed.

**Root cause** (medium confidence, `dependency_failure`): Payments calls fraud-check.risk.svc.cluster.local:8443 synchronously for each charge. The connection is refused, so payments returns HTTP 502 for those charges. Loki shows the pattern 'charge order=<_> failed status=502: risk check unavailable ... connection refused' 135 times in the last 30 minutes, while the 'charge ... status=200' pattern appears 636 times. The failures are therefore a subset of charges, consistent with the alert's roughly 8% 5xx rate. The refusals point to fraud-check having no ready endpoint or not listening on 8443. No rollout or config change was checked (no Kubernetes tools were available), so this is inferred from logs only. The Prometheus check for the error-rate metric returned no data, so the 8% figure is unverified.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: {service_name="payments"} over 30m: 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' totalCount 135, versus 'charge order=<_> status=200 latency_ms=<_>' totalCount 636. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: payments ERROR lines in the last 30m, e.g. 'charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' (level=error, with trace_id).
- `grafana_list_loki_label_values`: service_name values for {service_name=~".*fraud.*"} over the last 24h: only 'payments' and 'storefront'. No fraud-check service emitted logs, so its own state could not be checked.
- `grafana_query_loki_logs`: Searching storefront for error/refused/502/503 in the last 30m returned no storefront error lines, and the storefront pattern output matched payments' pattern output exactly.
- `grafana_list_loki_label_values`: Prometheus __name__ lookup for {service_name=~"payments|fraud.*"} over the last 1h returned 'no recorded data', so no metric confirmed the 8% 5xx rate or the fraud-check state.

**Recommendations**
1. Check the fraud-check deployment in namespace risk: pod status, endpoints for fraud-check.risk.svc.cluster.local, and whether it is listening on port 8443. Its logs and events are not in Loki, so check them directly.
2. If fraud-check was recently rolled out or scaled to zero, roll it back or restore replicas. Check its rollout history first.
3. Confirm that the Service selector and targetPort for fraud-check match its pods, since 'connection refused' can mean no endpoints or a port mismatch.
4. Consider a short-term mitigation in payments, such as a fallback or bypass for the risk check or a circuit breaker, only if the business approves. Do not change this without sign-off.
5. Confirm the 8% 5xx rate in Prometheus once metrics are available, and watch for recovery after the fraud-check fix.

**Tool calls**
1. `grafana_list_datasources` {"limit": 50, "name": "", "offset": 0, "type": ""}
2. `grafana_list_loki_label_values` {"datasourceUid": "loki", "endRfc3339": "now", "labelName": "service_name", "matcher": "{service_name=\"payments\"}", "startRfc3339": "now-1h"}
3. `grafana_query_loki_logs` {"datasourceUid": "loki", "direction": "backward", "endRfc3339": "now", "format": "compact", "limit": 30, "logql": "{service_name=\"payments\"} |~ \"(?i)error|exception|5[0-9][0-9]\"", "queryType": "range", "startRfc3339": "now-30m", "stepSeconds": 60}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "endRfc3339": "now", "logql": "{service_name=\"payments\"}", "startRfc3339": "now-30m", "step": "1m"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "direction": "backward", "endRfc3339": "now", "format": "compact", "limit": 10, "logql": "{service_name=~\".*fraud.*\"} or {service_name=\"payments\"} |~ \"(?i)fraud|refused|crash|panic|risk\"", "queryType": "range", "startRfc3339": "now-30m", "stepSeconds": 60}
6. `grafana_list_loki_label_values` {"datasourceUid": "loki", "endRfc3339": "now", "labelName": "service_name", "matcher": "{service_name=~\".*fraud.*\"}", "startRfc3339": "now-24h"}
7. `grafana_query_loki_logs` {"datasourceUid": "loki", "direction": "backward", "endRfc3339": "now", "format": "compact", "limit": 5, "logql": "{service_name=\"payments\"} |= \"fraud-check\"", "queryType": "range", "startRfc3339": "now-1h", "stepSeconds": 60}
8. `grafana_query_loki_stats` {"datasourceUid": "loki", "endRfc3339": "now", "logql": "{service_name=\"payments\"}", "startRfc3339": "now-30m"}
9. `grafana_query_loki_logs` {"datasourceUid": "loki", "direction": "backward", "endRfc3339": "now", "format": "compact", "limit": 10, "logql": "{service_name=\"storefront\"} |~ \"(?i)error|refused|502|503\"", "queryType": "range", "startRfc3339": "now-30m", "stepSeconds": 60}
10. `grafana_query_loki_patterns` {"datasourceUid": "loki", "endRfc3339": "now", "logql": "{service_name=\"storefront\"}", "startRfc3339": "now-30m", "step": "1m"}
11. `grafana_list_loki_label_values` {"datasourceUid": "prometheus", "endRfc3339": "now", "labelName": "__name__", "matcher": "{service_name=~\"payments|fraud.*\"}", "startRfc3339": "now-1h"} (error)
12. `grafana_query_loki_logs` {"datasourceUid": "loki", "direction": "backward", "endRfc3339": "now", "format": "compact", "limit": 5, "logql": "{service_name=\"payments\"} |= \"fraud-check\" |= \"status=502\"", "queryType": "instant", "startRfc3339": "now-1h", "stepSeconds": 60}
13. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "dashboardUid": "", "panelId": 0, "provisioningPreview": {"path": "", "pullRequestUrl": "", "ref": "", "repo": ""}, "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"fraud-check\" |= \"connection refused\""}], "queryParams": {},
