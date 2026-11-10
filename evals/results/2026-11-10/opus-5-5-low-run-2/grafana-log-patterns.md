## About 8% of payments POST /charge requests are failing with 502. Payments can't reach its fraud-check dependency: connections to fraud-check.risk.svc.cluster.local:8443 are refused.

**Root cause** (medium confidence, `dependency_failure`): In the last hour the payments logs show 135 lines of 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused', against 636 successful charges. That is about 17.5% of the logged charges, which is higher than the alert's 8%. The two numbers cover different windows and sources, so treat both as rough. 'Connection refused' means the fraud-check service in the risk namespace has no ready endpoints or is not listening on 8443. I only checked the payments logs, not fraud-check itself, and I didn't check for a recent fraud-check rollout. A rollout there would make this a bad_rollout instead.
**Severity:** high  ·  **Affected:** payments (service_name=payments; namespace/kind/name not identified), risk/Service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: {service_name="payments"}, last hour: 135x 'failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' vs 636x 'charge ... status=200'. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. Check the fraud-check pods, service endpoints and recent rollouts in the risk namespace: kubectl -n risk get pods,endpoints fraud-check and kubectl -n risk rollout history.
2. If a recent fraud-check rollout broke it, roll it back. Otherwise fix why the pods are not ready or not listening on 8443.
3. Consider letting payments degrade gracefully, for example a circuit breaker or fallback, when the risk check is unavailable.

**Tool calls**
1. `grafana_list_datasources` {"type": "loki"}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"risk check unavailable\""}], "timeRange": {"from": "now-1h", "to": "now"}}
