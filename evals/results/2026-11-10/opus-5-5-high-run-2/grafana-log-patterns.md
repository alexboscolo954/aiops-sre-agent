## Payments POST /charge is returning 502s because its fraud check dependency is down. Every failed charge in the logs reads "risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused". Successful charges are still going through, so this looks like a partial outage of fraud-check in namespace `risk`.

**Root cause** (medium confidence, `dependency_failure`): payments (namespace `shop`) calls fraud-check.risk.svc.cluster.local:8443 for the risk check on each charge, and that connection is being refused. The payments log patterns for the last hour show 135 lines of "charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused" against 636 "status=200" charges. The failures are mixed in with the successes, so the problem is intermittent. Two causes would explain that: some fraud-check endpoints are not listening (pods restarting or not ready while still in the Service), or the Service port/targetPort is wrong for part of the backends. I can't check fraud-check itself: Loki only has logs for payments and storefront, and I have no Kubernetes tools. So I can't say why fraud-check refuses connections, or whether a rollout caused it. No other error pattern shows up in payments.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: Last hour of {service_name="payments"}: 135 lines of 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' against 636 of 'charge order=<_> status=200'. No other error pattern appears. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: Raw payments (namespace shop) lines show ERROR 'charge order=o-c75499fd failed status=502: risk check unavailable: ... connection refused' mixed in with successful 'status=200' charges, which fits a partial fraud-check outage. Example trace_id: fb954a35bf708d397bd3ca19b85ee09a.
- `grafana_list_loki_label_values`: Loki only has service_name values 'payments' and 'storefront', so there are no fraud-check logs here to confirm the cause on its side.

**Recommendations**
1. Check fraud-check in namespace risk: `kubectl -n risk get pods,endpoints fraud-check` and `kubectl -n risk rollout history deploy/fraud-check`. Look for CrashLoopBackOff, not-ready pods, or a recent revision.
2. Run `kubectl -n risk describe pod` and read previous=true logs on any restarting fraud-check pods to find why port 8443 refuses connections.
3. Make sure the fraud-check Service targetPort matches the port the container listens on (8443) for every ready endpoint.
4. If a new fraud-check revision lines up with when the errors started, roll it back with `kubectl -n risk rollout undo deploy/fraud-check` (needs approval).
5. Once fraud-check is healthy, confirm the 5xx rate on payments POST /charge drops and the 'risk check unavailable' pattern stops in Loki.
6. Consider making payments degrade gracefully when the risk check is unavailable (bounded retry, or a queue for later review), so a fraud-check outage doesn't fail charges outright.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
4. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"failed status=502\"", "limit": 5}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "sum(count_over_time({service_name=\"payments\"} |= \"connection refused\" [5m]))", "queryType": "range", "startRfc3339": "now-3h", "stepSeconds": 900}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"connection refused\""}], "timeRange": {"from": "now-1h", "to": "now"}}
