## Some POST /charge requests on payments (namespace shop) fail with 502 because payments can't connect to its fraud-check dependency: fraud-check.risk.svc.cluster.local:8443 refuses the connection. Payments itself looks healthy and other charges succeed; I couldn't see fraud-check's own state.

**Root cause** (medium confidence, `dependency_failure`): Payments calls the risk/fraud-check service before each charge. That call fails with 'dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused', and payments then returns 502 'risk check unavailable'. In the last hour Loki logged 135 of these failures against 636 successful charges (status=200). 'Connection refused' means the address resolves but nothing accepts connections on 8443. Likely causes are no ready fraud-check pods behind the service, a crashing or restarting fraud-check, or a port mismatch. Fraud-check sends no logs to Loki and I had no Kubernetes or Prometheus query tools, so the cause inside the risk namespace is not confirmed, and I couldn't check for a recent rollout there. The 'slow serializer' warnings and 'pool stats ... idle=0' lines in payments don't show up as errors and look unrelated to the 5xx.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: Over the last hour {service_name="payments"} shows the pattern 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' 135 times, against 636 'charge order=<_> status=200'. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: Recent payments (service_namespace=shop) ERROR lines, e.g. order o-c75499fd and o-e022b341 'failed status=502: risk check unavailable ... connection refused' (trace_id fb954a35bf708d397bd3ca19b85ee09a). Successful charges in between show 41–117ms latency.
- `grafana_list_loki_label_values`: Loki has only 'payments' and 'storefront' as service_name values, so fraud-check's logs aren't collected and its health couldn't be checked here.

**Recommendations**
1. Check fraud-check in the risk namespace: `kubectl -n risk get pods,endpoints svc/fraud-check`. Look for no ready endpoints, CrashLoopBackOff, OOMKilled or failing readiness probes.
2. Run `kubectl -n risk rollout history deploy/fraud-check` and read recent events. If a new revision went out just before the errors started, roll it back. That would make this a bad rollout rather than a plain dependency failure.
3. Check that the fraud-check Service still exposes port 8443 and that its targetPort matches the port the container listens on.
4. Once fraud-check endpoints are healthy, confirm the payments 502 'risk check unavailable' rate drops to zero in Loki.
5. Follow-up: decide with the payments owners whether charges should fail fast with 502 when fraud-check is down, or use a circuit breaker or a defined fallback. Also start sending fraud-check logs to Loki.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_query_loki_stats` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
4. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"status=502\"", "limit": 5}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"fraud-check\""}], "timeRange": {"from": "now-1h", "to": "now"}}
