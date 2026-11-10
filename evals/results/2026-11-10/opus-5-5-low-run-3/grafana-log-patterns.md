## About 8% of payments POST /charge requests return 502. Payments can't reach its fraud-check dependency: fraud-check.risk.svc.cluster.local:8443 refuses connections.

**Root cause** (medium confidence, `dependency_failure`): Payments calls the fraud-check service (risk namespace) before charging. Connections to fraud-check.risk.svc.cluster.local:8443 are refused, so those charges fail with status=502 'risk check unavailable'. In the last hour that was 135 failed charges against 636 successful ones (status=200). A refused connection usually means the service has no ready endpoints or its pods are down. I only checked payments logs, so I haven't confirmed why fraud-check is down or whether it was recently rolled out.
**Severity:** high  ·  **Affected:** risk/Service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: Log pattern for {service_name="payments"}: 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' x135, against 'status=200' x636. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. Check the fraud-check pods and endpoints in the risk namespace for crashes, readiness failures or zero ready endpoints, and confirm the service is listening on port 8443.
2. Check the fraud-check rollout history. If a recent revision broke it, roll back.
3. Bring fraud-check back up, then confirm the payments 502 rate drops.
4. Consider giving payments a fallback or circuit breaker for when the risk check is unavailable.

**Tool calls**
1. `grafana_list_datasources` {"type": "loki"}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"risk check unavailable\""}], "timeRange": {"from": "now-1h", "to": "now"}}
