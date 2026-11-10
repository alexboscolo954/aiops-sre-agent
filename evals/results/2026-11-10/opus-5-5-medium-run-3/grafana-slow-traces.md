## GET /product/{sku} on storefront is slow (2.5–3.3s per trace) because its call to inventory GET /stock/{sku} waits about 3s on a Postgres row lock. The query is `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` against inventory-db.shop.svc, with wait_event Lock:tuple. Catalog and pricing return in milliseconds.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in the inventory database (inventory-db.shop.svc, postgresql). In trace 45d31a48f074c35561c0353b3bdfe298 the storefront request took 3103ms. Of that, inventory GET /stock/{sku} took 3056ms, and nearly all of it was its child span 'SELECT stock' at 3050ms, with db.wait_event=Lock:tuple. That span runs `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE`. Catalog (14ms) and pricing (21ms) were not the problem. So a read path is taking an exclusive row lock with FOR UPDATE and queuing behind other transactions that hold locks on the same stock rows, possibly long-running ones. I only opened that one trace. The other slow storefront traces I found (2.5–3.3s) have the same span layout (catalog, pricing, two inventory spans), but I did not open them to confirm the lock wait. I couldn't see who holds the locks: I have no DB metrics or pg_locks data, Loki has no inventory-db logs, and inventory's own logs only show normal 'GET ... 200' lines. I also didn't check whether a recent inventory deploy added the FOR UPDATE.
**Severity:** medium  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: Many storefront 'GET /product/{sku}' traces over 2s in the last hour (2483–3284ms), each with spans from catalog, pricing and inventory (2 spans). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront 3103ms; inventory GET /stock/{sku} 3056ms -> 'SELECT stock' 3050ms, db.query.text='SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event=Lock:tuple, server.address=inventory-db.shop.svc; catalog 14ms, pricing 21ms.
- `grafana_query_loki_patterns`: The only inventory log pattern is 'GET <_> 200 <_> <_>' (346 lines). No errors, so requests succeed but slowly.

**Recommendations**
1. On inventory-db, look at pg_stat_activity and pg_locks (blocked vs. blocking PIDs, xact_start, state 'idle in transaction') to find which transactions hold locks on the stock rows.
2. If a stuck or long-running transaction is blocking, have a DBA review it and terminate it with pg_terminate_backend once approved.
3. Check whether a recent inventory change added FOR UPDATE to the stock read path. A read-only stock lookup shouldn't take an exclusive row lock: remove FOR UPDATE, or use SKIP LOCKED/NOWAIT where locking is really needed. If a new revision introduced it, roll it back.
4. Set lock_timeout/statement_timeout on the inventory DB role and a client timeout from storefront to inventory, so lock waits can't push storefront p99 past 2s.
5. Once fixed, confirm storefront p99 for /product/{sku} drops below 2s and inventory 'SELECT stock' span durations return to milliseconds in Tempo.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}"}
5. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "{resource.service.name=\"inventory\" && name=\"SELECT stock\" && duration > 2s}"}], "timeRange": {"from": "now-1h", "to": "now"}}
7. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceId", "query": "45d31a48f074c35561c0353b3bdfe298"}], "timeRange": {"from": "now-1h", "to": "now"}}
