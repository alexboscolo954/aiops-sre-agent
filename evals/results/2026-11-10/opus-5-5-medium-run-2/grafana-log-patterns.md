## The 5xx errors on payments POST /charge come from a failing dependency. Payments can't reach its fraud-check service at fraud-check.risk.svc.cluster.local:8443 (connection refused), so those charges fail with a 502.

**Root cause** (medium confidence, `dependency_failure`): In the last hour, Loki shows 135 lines of 'charge order=<id> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused', against 636 'status=200' charges. That is about 17% of logged charges over the hour; the alert reports 8% over 10 minutes. 'Connection refused' means nothing is accepting connections on the fraud-check service port in namespace risk. That points to no ready pods or endpoints, a pod that crashed or was restarted, or a wrong port. Loki has no logs for fraud-check (only payments and storefront are indexed), so I couldn't confirm why it's down or whether a recent rollout caused it. Payments itself looks healthy: the other charges return 200, and the other log patterns (settlement, webhook, cache) look routine.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: {service_name="payments"} over the last hour: 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' x135 vs 'charge order=<_> status=200' x636 (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: Raw payments (namespace shop) ERROR lines, e.g. order=o-c75499fd and o-e022b341, fail with status=502 'connection refused' to fraud-check:8443. Successful charges are mixed in between them, so payments is up and only the risk check fails.
- `grafana_list_loki_label_values`: Loki only has logs for service_name values 'payments' and 'storefront', so I couldn't read fraud-check logs.

**Recommendations**
1. Check fraud-check in namespace risk: kubectl -n risk get pods,endpoints svc/fraud-check. Look for pods that aren't ready, CrashLoopBackOff, or empty endpoints.
2. Check whether port 8443 still matches the fraud-check pods' container and target port.
3. Check fraud-check's rollout history (kubectl -n risk rollout history deploy/fraud-check) and recent events. If a new revision just went out, roll it back.
4. After fraud-check is back, confirm that the 'risk check unavailable' errors in payments stop and the 5xx rate drops.
5. Later: decide whether payments should fail open or degrade gracefully when the risk check is unavailable, and add fraud-check logs to Loki.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_query_loki_stats` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
4. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"status=502\"", "limit": 5}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"fraud-check\""}], "timeRange": {"from": "now-1h", "to": "now"}}
