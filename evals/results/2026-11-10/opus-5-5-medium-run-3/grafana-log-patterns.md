## POST /charge requests in shop/payments return 502 because payments can't connect to its fraud-check dependency: every failed charge logs 'risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused'. Nothing is listening on fraud-check:8443. I couldn't see fraud-check's own logs or state, so why it is down is still unknown.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check service (fraud-check.risk.svc.cluster.local:8443) is refusing connections. Payments seems to need a risk check before it charges, so when the call fails it returns 502. In the last hour Loki shows 135 lines of 'charge order=<_> failed status=502: risk check unavailable: ... connect: connection refused' and 636 successful 'status=200' charges. Charge lines are the only 5xx error pattern payments logs. The other warnings are 'slow serializer' messages that don't fail requests. 'Connection refused' means nothing is accepting connections at fraud-check:8443: either the service has no ready endpoints (pods down or crashing) or the port is wrong. Only some charges fail, so fraud-check is probably partly down (some pods or endpoints unavailable) or flapping, but I haven't checked this. I couldn't look at fraud-check itself: Loki only has logs for payments and storefront, and I had no Kubernetes tools. So I can't tell whether a fraud-check rollout caused it, which would make this a bad rollout instead.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: {service_name="payments"} last 1h: 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' x135 vs 'charge order=<_> status=200' x636; no other charge error pattern (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: Raw payments ERROR lines (namespace shop) with trace IDs, e.g. order o-c75499fd failed status=502, risk check unavailable, connection refused to fraud-check.risk.svc.cluster.local:8443, mixed in with successful charges
- `grafana_list_loki_label_values`: service_name values are only 'payments' and 'storefront', so Loki has no fraud-check logs

**Recommendations**
1. Check the fraud-check workload in namespace risk: kubectl -n risk get pods,endpoints fraud-check. Look for pods in CrashLoopBackOff or not Ready, endpoints with no addresses, or a port mismatch with 8443.
2. Check fraud-check's rollout history and recent events (kubectl -n risk rollout history / get events). If a new revision lines up with when the errors started, roll it back.
3. Describe the failing fraud-check pods and read their logs (use previous=true for restarted containers) to find out why they aren't listening on 8443.
4. Check whether NetworkPolicy or Service port changes in namespace risk could be causing connection refused for some connections.
5. When fraud-check is healthy again, confirm the 502 pattern in payments goes to zero. Also consider adding a timeout or retry, or a decision on whether to fail open or closed, for the risk check in payments.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_query_loki_stats` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
4. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"status=502\"", "limit": 5}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"fraud-check\""}], "timeRange": {"from": "now-1h", "to": "now"}}
