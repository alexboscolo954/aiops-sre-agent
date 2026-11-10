## Storefront p99 latency on GET /product/{sku} is above 2s. The slow traces spend nearly all their time in inventory's SELECT stock query against inventory-db, which is waiting on a row lock (Lock:tuple, FOR UPDATE). This is a lock contention issue in the inventory database path, not a storefront code fault.

**Root cause** (medium confidence, `dependency_failure`): Slow requests are caused by row-lock waits in inventory's stock query. In trace 45d31a48f074c35561c0353b3bdfe298 the storefront span takes 3103ms, and the inventory span GET /stock/{sku} takes 3056ms. Its child span "SELECT stock" takes 3050ms with db.wait_event=Lock:tuple and query "SELECT qty FROM stock WHERE sku = $1 FOR UPDATE" against inventory-db.shop.svc. Catalog (14ms) and pricing (21ms) are fast. The lock-wait pattern is the cause: a FOR UPDATE row lock is being held by another transaction. The only rollout-related lead I checked is none; I did not check deployment history or lock holders, so the trigger is unknown.
**Severity:** high  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/Database/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returned many GET /product/{sku} traces of 2.4s to 3.3s, with inventory and catalog spans in the trace.
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront GET /product/{sku} 3103ms -> inventory GET /stock/{sku} 3056ms -> SELECT stock 3050ms, db.wait_event=Lock:tuple, db.query.text="SELECT qty FROM stock WHERE sku = $1 FOR UPDATE", server.address=inventory-db.shop.svc. Catalog 14ms and pricing 21ms.
- `grafana_query_loki_logs`: storefront logs show GET /product/sku-XXXX 200 with 2.5-3.1s latencies tagged 'slow', alternating with normal 55-60ms 'ok' requests. Inventory and inventory-db logs returned no usable lines in the query window (service_name values seen: payments, storefront). No error or lock lines were found.
- `grafana_list_tempo_attribute_values`: span.db.wait_event values seen: pricing, inventory, storefront, catalog (service names, not wait events), so the wait-event attribute could not be enumerated further.

**Recommendations**
1. Check inventory-db for lock waiters and blockers now, e.g. pg_stat_activity filtered on wait_event_type='Lock', and pg_blocking_pids() to identify the holding transaction.
2. Find which transaction holds the row lock on the stock table for the affected SKUs (long-running or idle-in-transaction sessions that did SELECT ... FOR UPDATE). Terminate it only with approval.
3. Review recent changes to inventory's stock-update path, its transaction scope (FOR UPDATE held across external calls), and whether a batch job touches the same rows.
4. Check inventory and inventory-db deployment and rollout history for changes near the alert time, which I did not verify here.
5. Mitigation: shorten lock_timeout or transaction duration in inventory, and make storefront's stock lookup time out and degrade gracefully instead of waiting for 3s.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"}"}
4. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"} |~ \"(?i)error|warn|timeout|slow\"", "limit": 20}
6. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"inventory\" && name=\"SELECT stock\" && span.db.wait_event=\"Lock:tuple\"}"}
7. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}"}
8. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"} |~ \"(?i)error|lock|timeout|deadlock|warn\"", "limit": 10}
9. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"inventory-db\"} ", "limit": 10}
10. `grafana_query_loki_stats` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}"}
11. `grafana_query_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"} (error)
12. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
13. `grafana_list_tempo_attribute_values` {"datasourceUid": "tempo", "name": "span.db.wait_event"}
14. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"inventory\" && span.db.system=\"postgresql\" && duration > 1s}"}
15. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"}", "startRfc3339": "now-1h"}
16. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceId", "query": "45d31a48f074c35561c0353b3bdfe298"}]}
17. `TriageReport` {"summary": "Storefront p99 latency on GET /product/{sku} is above 2s. The slow traces spend nearly all their time in inventory's SELECT stock query against inventory-db, which is waiting on a row lock (Lock:tuple, FOR UPDATE). This is a lock contention issue in the inventory database path, not a st
