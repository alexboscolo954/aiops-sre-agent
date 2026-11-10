## p99 latency on storefront GET /product/{sku} is above 2s. The slow requests spend nearly all their time in the inventory service's `SELECT stock ... FOR UPDATE` query, which waits on a Postgres tuple lock (`Lock:tuple`) in inventory-db.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in inventory-db. The inventory service runs `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` on a read path (GET /stock/{sku}). Concurrent requests block each other, and the trace shows `db.wait_event=Lock:tuple`. In the first trace the SELECT took 3050ms of a 3103ms request. In the second it took 2470ms of 2523ms. The catalog (14ms) and pricing (21ms) spans are fast. Storefront itself is not at fault. Roughly one in four requests is slow (about 2.5–3.1s), the rest take about 60ms. I did not find a rollout or deployment change; the cause is inferred from traces only, and I could not check inventory-db or its deployment history.
**Severity:** medium  ·  **Affected:** shop/Service/storefront, shop/Service/inventory, shop/Service/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: Many storefront GET /product/{sku} traces last 2.4–3.3s (e.g. 3103ms, 2523ms, 3284ms). All have the same shape: catalog, pricing and 2 inventory spans. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48...: root 3103ms. catalog 14ms, pricing 21ms, inventory GET /stock/{sku} 3056ms. Its child span `SELECT stock` (FOR UPDATE, postgresql, inventory-db.shop.svc) took 3050ms with db.wait_event=Lock:tuple. Trace aa889c27... shows the same pattern: 2470ms of 2523ms.
- `grafana_query_loki_patterns`: Storefront logs show only 200 responses (346 lines), with no errors. Slow lines are about 2.5–3.1s and marked 'slow'; fast ones are about 60ms. The problem is latency only, not failures.

**Recommendations**
1. Look at inventory-db for lock holders and blockers: check pg_stat_activity and pg_locks for long-running transactions holding row locks on the stock table, and for idle-in-transaction sessions.
2. Review the inventory service's GET /stock/{sku} code. Replace `SELECT ... FOR UPDATE` with a plain read on the read-only path, and keep write locks short.
3. Check whether a recent inventory deploy, batch job or stock-update workload started recently and is holding locks. I did not check rollout history.
4. Consider a lock_timeout or statement_timeout on inventory queries, and a tighter timeout from storefront to inventory, so lock waits cannot stack up.
5. Confirm recovery by checking that p99 of GET /product/{sku} drops below 2s.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"}"}
4. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
5. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceId", "query": "45d31a48f074c35561c0353b3bdfe298"}]}
6. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}", "limit": 10}
7. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "{resource.service.name=\"inventory\" && span.db.wait_event=\"Lock:tuple\"}"}]}
8. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "aa889c27b4277ffe35150f32673a376f"}
