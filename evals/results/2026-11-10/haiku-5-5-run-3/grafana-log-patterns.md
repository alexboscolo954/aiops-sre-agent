## POST /charge 5xx (about 8%) in the payments service is caused by its calls to fraud-check.risk.svc.cluster.local:8443 being refused. Each failed charge returns 502 "risk check unavailable: connection refused". The root cause sits in the fraud-check dependency, not in payments itself.

**Root cause** (medium confidence, `dependency_failure`): The payments service fails charges with "status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused". Connections to fraud-check are refused, so nothing is listening on that port. Successful charges (status=200) are interleaved with these failures in the same window, which fits a partial outage of the fraud-check dependency. Logs show no failing rollout of payments. I could not inspect the fraud-check workload itself: the Loki datasource only holds the payments and storefront services, and no Kubernetes tools were available, so fraud-check pod state and recent changes are unverified.
**Severity:** high  ·  **Affected:** payments/Service/payments (POST /charge), risk/Service/fraud-check (dependency, refusing connections on 8443)

**Evidence**
- `grafana_query_loki_patterns`: Pattern 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' occurs 135 times, against 636 'charge ... status=200' lines in the same window.
- `grafana_query_loki_logs`: Error lines from payments show repeated 'charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' (level=error), with trace IDs attached.
- `grafana_query_loki_logs`: Filtering on the fraud-check address returned only the same 502 'connection refused' errors. No timeouts or other error types appeared.
- `grafana_list_loki_label_values`: service_name values in Loki are only 'payments' and 'storefront'. There are no logs from fraud-check, so its health could not be checked.
- `grafana_generate_deeplink`: Explore link for the payments fraud-check query. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. Check the fraud-check workload in namespace risk: are its pods Running and Ready, does its Service have endpoints, and is port 8443 served? Use kubectl get pods,svc,endpoints -n risk.
2. Check whether fraud-check was rolled out or scaled recently. If a recent rollout broke it, roll it back.
3. If fraud-check stays down, consider degrading the risk check in payments (fail open or queue), but only after a risk and compliance decision and with approval.
4. Watch the 502 pattern rate until fraud-check recovers, and confirm the 5xx ratio drops back below the alert threshold.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"error\" or \"ERROR\" or \"5\"", "limit": 20}
4. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"fraud-check\"", "limit": 5, "direction": "forward"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=~\".*fraud.*\"}", "limit": 10}
6. `grafana_query_loki_stats` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
7. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=~\".*\"} |= \"fraud-check.risk\"", "limit": 5, "format": "compact"}
8. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
9. `grafana_query_loki_logs` {"datasourceUid": "prometheus", "logql": "{service_name=\"payments\"} |= \"fraud-check\"", "limit": 1} (error)
10. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"} |= \"error\"", "limit": 5}
11. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"fraud-check\""}]}
12. `grafana_list_datasources` {"type": "prometheus"}
13. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "count_over_time({service_name=\"payments\"} |= \"fraud-check.risk.svc.cluster.local:8443: connect: connection refused\" [1h])", "queryType": "instant", "limit": 5}
14. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"fraud-check.risk.svc.cluster.local:8443\""}]}
15. `read_more` {"result_id": "r30dab8", "grep": "fraud-check", "fields": ["line"]}
16. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"fraud-check.risk.svc.cluster.local:8443\""}], "timeRange": {"from": "now-1h", "to": "now"}}
17. `TriageReport` {"summary": "POST /charge 5xx (about 8%) in the payments service is caused by its calls to fraud-check.risk.svc.cluster.local:8443 being refused. Each failed charge returns 502 \"risk check unavailable: connection refused\". The root cause sits in the fraud-check dependency, not in payments itself."
18. `TriageReport` {"summary": "POST /charge 5xx (about 8%) in the payments service is caused by its calls to fraud-check.risk.svc.cluster.local:8443 being refused. Each failed charge returns 502 \"risk check unavailable: connection refused\". The root cause sits in the fraud-check dependency, not in payments itself."
