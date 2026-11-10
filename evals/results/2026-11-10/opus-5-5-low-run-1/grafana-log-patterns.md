## About 8% of payments POST /charge requests return 502. In the last hour, payments couldn't reach its fraud-check dependency: fraud-check.risk.svc.cluster.local:8443 refused the connection.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check service in the risk namespace is refusing connections. Its service has no ready endpoints, or the pods are down. In the last hour, 135 payments log lines read 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused', next to 636 successful charges. That is roughly the error rate in the alert. I have not checked why fraud-check is down or whether it had a recent rollout.
**Severity:** high  ·  **Affected:** payments/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: In the last hour of {service_name="payments"} logs there are 135 lines like 'failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' and 636 lines like 'charge ... status=200'. The link opens the payments logs in Explore; the error filter did not carry into it. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. Check the fraud-check pods and endpoints in the risk namespace: kubectl -n risk get pods,endpoints fraud-check. Look for crashes, failing readiness checks, or zero replicas.
2. Check fraud-check's rollout history and recent events. If a new revision caused this, roll it back.
3. Check whether port 8443 still matches the service's targetPort, and whether a NetworkPolicy changed.
4. Once fraud-check is healthy, confirm the payments 502 rate drops. Consider having payments fail open or degrade gracefully when the risk check is unavailable.

**Tool calls**
1. `grafana_list_datasources` {"type": "loki"}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"risk check unavailable\""}], "timeRange": {"from": "now-1h", "to": "now"}}
