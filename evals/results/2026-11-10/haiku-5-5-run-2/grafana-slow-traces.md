## p99 latency of storefront GET /product/{sku} is above 2s. Slow traces show the time is spent in inventory's SELECT on inventory-db, which is waiting on a row lock (Lock:tuple) on a SELECT ... FOR UPDATE. Storefront itself and the other downstream calls are fast.

**Root cause** (medium confidence, `dependency_failure`): In trace 45d31a48f074c35561c0353b3bdfe298 (storefront 3103ms), the GET /stock/{sku} span in inventory took 3056ms, and its child "SELECT stock" took 3050ms against inventory-db.shop.svc with db.wait_event=Lock:tuple. The query is "SELECT qty FROM stock WHERE sku = $1 FOR UPDATE", so requests are queuing on row locks held on the stock table. The catalog (14ms) and pricing (21ms) spans are fast. Other slow traces show the same pattern (2.4–3.3s totals). I could not find the lock holder: the inventory logs search returned no error/lock lines, and the Prometheus pattern query returned no data. The cause of the lock contention is not confirmed.
**Severity:** high  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/Database/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returned many GET /product/{sku} traces at 2.4–3.3s, e.g. 45d31a48f074c35561c0353b3bdfe298 at 3103ms.
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront GET /product/{sku} 3103ms → inventory GET /stock/{sku} 3056ms → SELECT stock 3050ms (db.system=postgresql, server.address=inventory-db.shop.svc, db.wait_event=Lock:tuple, query 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE'). catalog 14ms and pricing 21ms.
- `grafana_query_loki_logs`: storefront logs show a mix of fast 'GET /product/sku-XXXX 200 ~55-60ms ok' and 'slow' lines at 2500–3131ms, consistent with the trace data.
- `grafana_list_loki_label_values`: Loki service_name values are only 'payments' and 'storefront'; there are no inventory or inventory-db log streams to check for lock errors.
- `grafana_query_loki_patterns`: Pattern query on {service_name="storefront"} returned only 'GET <_> 200 <_> <_>' (346 lines), with no error patterns. The same pattern came back for inventory and inventory-db, which likely reflects the storefront stream and not those services.

**Recommendations**
1. Check inventory-db for the lock holder: query pg_stat_activity and pg_locks for waiting sessions on the stock table, and find long-running or idle-in-transaction sessions holding row locks.
2. If an idle-in-transaction session or a long batch job is holding locks, end it or fix the transaction that never commits, then confirm the p99 drops.
3. Review recent changes to inventory's /stock handler or to batch jobs that touch the stock table, since FOR UPDATE on a hot SKU serializes requests.
4. Consider removing FOR UPDATE on the read path if it is not required, or shortening the lock-holding transaction.
5. Add Loki/Prometheus coverage for the inventory and inventory-db services, since they were not visible in the logs queried here.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"}"}
4. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}", "limit": 20}
6. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}"}
7. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"inventory-db\"}"}
8. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
9. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"} |~ \"(?i)lock|deadlock|wait|error|timeout\"", "limit": 10}
10. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"inventory\" && span.db.system=\"postgresql\"}"}
11. `grafana_query_loki_patterns` {"datasourceUid": "prometheus", "logql": "{namespace=\"shop\"}"} (error)
12. `read_more` {"result_id": "r98006d", "grep": "SELECT stock"}
13. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "query": "45d31a48f074c35561c0353b3bdfe298", "queryType": "traceId"}]}
14. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "query": "{resource.service.name=\"storefront\" && duration > 2s}", "queryType": "traceql"}]}
15. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "query": "45d31a48f074c35561c0353b3bdfe298", "queryType": "traceId"}]}
16. `TriageReport` {"summary": "p99 latency of storefront GET /product/{sku} is above 2s. Slow traces show the time is spent in inventory's SELECT on inventory-db, which is waiting on a row lock (Lock:tuple) on a SELECT ... FOR UPDATE. Storefront itself and the other downstream calls are fast.", "category": "dependenc
