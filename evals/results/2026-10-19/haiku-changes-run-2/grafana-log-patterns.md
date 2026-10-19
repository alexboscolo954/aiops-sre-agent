## POST /charge 5xx (about 8%) is caused by payments failing to reach the risk check service fraud-check.risk.svc.cluster.local:8443, which refuses connections. Charges that reach the risk check fail with 502, while the rest return 200. I could not verify fraud-check's own health or any recent rollout, so the cause of its refusals is still open.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check (risk check) service at fraud-check.risk.svc.cluster.local:8443 is refusing TCP connections, so payments fails each charge that needs a risk check with HTTP 502. Likely causes are that fraud-check has no ready endpoints (crashed, scaled to zero, or its Service has no backing pods), but the logs do not show which. No rollout was found for either service.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_patterns (Loki, {service_name="payments"}, last 30m)`: Pattern 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' occurred 135 times in 30 minutes, versus 636 'charge ... status=200' lines.
- `grafana_query_loki_logs (Loki, payments error lines, last 30m)`: Repeated ERROR lines, e.g. 'charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused', interleaved with successful charges with latency_ms 41-117.
- `grafana_list_loki_label_values (Loki, service_name where service_namespace="risk", last 1h)`: Only 'payments' and 'storefront' appear in the risk namespace. No 'fraud-check' service_name log stream exists in Loki, so its logs cannot be read from here.

**Recommendations**
1. Check fraud-check directly: kubectl -n risk get deploy,pods,svc,endpoints fraud-check. Look for zero ready replicas, crashloops, or a Service with no endpoints.
2. If fraud-check has crashed, read its previous logs and events (kubectl -n risk logs --previous, kubectl -n risk describe pod) to find the cause.
3. Check the risk namespace and cluster for recent rollouts or config/Service changes in the last hour, since none were checked here.
4. Confirm the fraud-check Service name and port 8443 match what payments is configured to call.
5. Until fraud-check recovers, consider whether payments can safely bypass or fail over the risk check for low-risk charges. This is a business decision and needs owner approval.
6. Watch the 5xx rate on POST /charge in Prometheus to confirm it drops after the dependency recovers.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_patterns`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_stats`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_logs`
7. `grafana_query_loki_label_values`
8. `grafana_list_loki_label_values`
9. `grafana_query_loki_logs`
10. `grafana_generate_deeplink`
