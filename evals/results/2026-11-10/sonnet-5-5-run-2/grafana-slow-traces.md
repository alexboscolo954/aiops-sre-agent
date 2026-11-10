## p99 latency on GET /product/{sku} is above 2s because the inventory service's `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` query waits about 3s on a Postgres tuple lock. The other downstream calls (catalog, pricing) take 14–21ms.

**Root cause** (medium confidence, `dependency_failure`): In the slow trace 45d31a48..., storefront takes 3103ms. The inventory GET /stock/{sku} span takes 3056ms, and its child span `SELECT stock` takes 3050ms. That span has db.wait_event=Lock:tuple and db.query.text 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' against inventory-db.shop.svc. The row-level FOR UPDATE lock is contended, so reads queue behind other transactions. Storefront returns 200 on every request, so this is latency only, with no errors. Slow requests (about 2.5–3.1s) are interleaved with fast ones (about 60ms), which fits contention on particular rows rather than a general slowdown. I did not check rollout history, and I did not identify what holds the locks.
**Severity:** medium  ·  **Affected:** shop/Service/storefront, shop/Service/inventory, shop/Service/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL search for storefront traces over 2s returned many traces of 2.4–3.3s on GET /product/{sku}. Each has the same shape: catalog, pricing, inventory (2 spans) and storefront. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48...: storefront 3103ms, catalog 14ms, pricing 21ms, inventory GET /stock/{sku} 3056ms. The child span 'SELECT stock' took 3050ms with db.wait_event=Lock:tuple and query 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' on inventory-db.shop.svc.
- `grafana_query_loki_logs`: Storefront logs show every request returning 200. Fast requests take about 55–62ms ('ok') and the slow ones take 2.5–3.1s ('slow'), so the problem is intermittent lock waits and not errors.

**Recommendations**
1. Look in inventory-db (Postgres) for blocking sessions: query pg_stat_activity and pg_locks for Lock:tuple waits, and find long-running or idle-in-transaction sessions holding row locks on the stock table.
2. Find which inventory code path or job holds FOR UPDATE locks on stock rows for long periods. Shorten those transactions, or have the read path stop taking FOR UPDATE (use a plain SELECT or SKIP LOCKED).
3. Set lock_timeout and statement_timeout on the inventory DB connections, and add a timeout on the storefront-to-inventory call so slow lock waits fail fast.
4. Check inventory's deployment history for a recent change that introduced FOR UPDATE or longer transactions, and roll it back if it lines up with the alert start.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"}"}
4. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}", "limit": 10, "format": "compact"}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "datasource": {"uid": "tempo"}, "queryType": "traceql", "query": "{resource.service.name=\"inventory\" && span.db.wait_event=\"Lock:tuple\"}"}]}
