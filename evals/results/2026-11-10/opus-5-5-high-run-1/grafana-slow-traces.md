## Slow GET /product/{sku} requests in storefront (2.5–3.3s) come from its downstream call to inventory GET /stock/{sku}. That call spends almost all of its time in a Postgres `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE`, waiting on a row lock (db.wait_event=Lock:tuple) on inventory-db.shop.svc.

**Root cause** (medium confidence, `dependency_failure`): Storefront is fine; its inventory dependency is blocked on a database row lock. In trace 45d31a48f074c35561c0353b3bdfe298 the root span takes 3103ms. Catalog takes 14ms and pricing 21ms, but inventory GET /stock/{sku} takes 3056ms, and 3050ms of that is the child span 'SELECT stock'. That span runs `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` against inventory-db.shop.svc with db.wait_event=Lock:tuple. So a read-only stock lookup takes an exclusive row lock and waits behind other transactions holding the same rows. Each concurrent product-page request for a SKU lines up behind the others, or behind a long-running write transaction. Every slow storefront trace found (2.48–3.28s) has the same shape, with inventory spans in each. I could not identify the session holding the lock: no inventory-db logs or Postgres lock metrics were checked, and storefront logs show only 200 responses. No deploy or rollout data was available to tie this to a recent change.
**Severity:** medium  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returns many GET /product/{sku} traces of 2483–3284ms, each with spans from catalog, pricing and inventory (2 inventory spans). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront 3103ms; catalog 14ms; pricing 21ms; inventory GET /stock/{sku} 3056ms, whose child 'SELECT stock' takes 3050ms: db.query.text='SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event='Lock:tuple', server.address=inventory-db.shop.svc.
- `grafana_query_loki_patterns`: Storefront logs contain only the pattern 'GET <_> 200 <_> <_>' (346 lines): no errors, so the requests succeed but are slow.

**Recommendations**
1. On inventory-db, find the session holding the lock: query pg_stat_activity joined with pg_locks / pg_blocking_pids() for sessions blocking on the stock table, and look for long-running or 'idle in transaction' sessions.
2. If one stuck or long-running transaction is holding the rows, end it with pg_terminate_backend after confirming its owner. This needs a human decision; I am not changing anything.
3. Fix the inventory read path: GET /stock/{sku} is a read and should not use SELECT ... FOR UPDATE. Use a plain SELECT, or use FOR UPDATE NOWAIT/SKIP LOCKED with short transactions only on the write path.
4. Set lock_timeout or statement_timeout on the inventory DB role, and a client timeout from storefront to inventory, so lock waits fail fast instead of piling up.
5. Check recent inventory deploys or batch jobs that write to the stock table, to see whether a change brought in the FOR UPDATE query or long transactions.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}"}
5. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"inventory\" && span.db.system=\"postgresql\" && duration > 1s}"}
6. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
7. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "9c44528f8a843750cbbbde89d77624f2"} (error)
8. `grafana_list_tempo_attribute_values` {"datasourceUid": "tempo", "name": "resource.service.name"}
9. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"}"}
10. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceId", "query": "45d31a48f074c35561c0353b3bdfe298"}], "timeRange": {"from": "now-1h", "to": "now"}}
11. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}], "timeRange": {"from": "now-1h", "to": "now"}}
