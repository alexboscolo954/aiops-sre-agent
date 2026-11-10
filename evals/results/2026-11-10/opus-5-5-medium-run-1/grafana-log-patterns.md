## POST /charge in payments (namespace shop) returns 502 when its risk check can't reach fraud-check.risk.svc.cluster.local:8443. That connection is being refused. Payments itself looks healthy: charges that get past the risk check return 200.

**Root cause** (medium confidence, `dependency_failure`): Payments depends on the fraud-check service in the risk namespace, and that service is refusing connections. In the last hour Loki shows 135 lines of 'charge order=<id> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' and 636 successful 'charge ... status=200' lines. That is about 17% of logged charges failing, roughly double the 8% in the alert annotation. I couldn't measure the alert's own 10-minute window, so the two numbers can't be compared directly. 'Connection refused' usually means the Service has no ready endpoints, or nothing is listening on 8443. Because only some charges fail, fraud-check is probably partly down, for example some pods not ready or restarting. I couldn't confirm any of this: Loki has no logs for fraud-check (the only service_name values are payments and storefront), and I had no Kubernetes or metrics tools to check its pods or rollout history. So I can't tell whether a fraud-check rollout caused it, which would make this a bad rollout instead.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: Patterns for {service_name="payments"} over the last hour: 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' x135, against 'charge order=<_> status=200' x636.
- `grafana_query_loki_logs`: Raw payments logs (service_namespace=shop) show ERROR lines such as 'charge order=o-c75499fd failed status=502: risk check unavailable: ... connection refused' mixed in with successful 200 charges. Failures are spread out, not one total outage. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_list_loki_label_values`: The service_name label only has the values payments and storefront, so Loki has no fraud-check logs to confirm what is wrong on its side.

**Recommendations**
1. Check fraud-check in the risk namespace: run `kubectl -n risk get pods,endpoints fraud-check` and `kubectl -n risk describe deploy fraud-check`. Look for pods that aren't ready, CrashLoopBackOff or OOMKilled, and for an empty or partial endpoint list on port 8443.
2. Run `kubectl -n risk rollout history deploy/fraud-check`. If a new revision went out just before the alert, roll back with `kubectl -n risk rollout undo` after approval, and treat this as a bad rollout.
3. Read fraud-check's container logs, including previous=true for restarted containers, and its recent events to find why it is refusing connections.
4. Once fraud-check is healthy, confirm the payments 502 pattern stops in Loki.
5. Follow-up: decide with the payments owners whether the risk check should have a timeout, retry or circuit breaker with a fallback. Also send fraud-check logs to Loki so this can be seen faster next time.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_query_loki_stats` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
4. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"status=502\"", "limit": 5}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"status=502\""}], "timeRange": {"from": "now-1h", "to": "now"}}
