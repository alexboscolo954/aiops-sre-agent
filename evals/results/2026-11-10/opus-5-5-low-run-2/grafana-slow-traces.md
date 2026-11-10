## Slow storefront GET /product/{sku} requests are caused by inventory's Postgres query `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE`, which waits on a row lock (Lock:tuple) for about 3s. Catalog and pricing are fast.

**Root cause** (medium confidence, `dependency_failure`): In trace 45d31a48 (3103ms total), the inventory call GET /stock/{sku} took 3056ms. Almost all of that (3050ms) was the child span SELECT ... FOR UPDATE against inventory-db.shop.svc, with db.wait_event=Lock:tuple. Catalog (14ms) and pricing (21ms) were fast. So requests are queuing behind each other for the same stock row lock, most likely a long-held transaction or a hot SKU with competing FOR UPDATE calls. I only opened one trace in full. The other slow traces I found (2.5–3.3s) have the same set of spans, but I haven't checked what is holding the lock or whether anything recently changed in inventory, so the exact source of the contention is still unconfirmed.
**Severity:** medium  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory

**Evidence**
- `grafana_search_tempo_traces`: Many storefront GET /product/{sku} traces take 2.5–3.3s, and each one calls catalog, pricing and inventory (2 inventory spans). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48: inventory SELECT stock span took 3050ms of the 3103ms request, query 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event=Lock:tuple, server inventory-db.shop.svc.

**Recommendations**
1. On inventory-db, look at pg_stat_activity and pg_locks to find the blocking session: a long-running or 'idle in transaction' session holding the stock row locks.
2. If one stuck session is the blocker, consider ending it with pg_terminate_backend, after approval.
3. Check whether the inventory service or a batch job recently changed and now holds FOR UPDATE transactions longer, and review its transaction scope.
4. Longer term, avoid FOR UPDATE on stock reads (plain SELECT, or SKIP LOCKED/NOWAIT) and set lock_timeout and idle_in_transaction_session_timeout.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "45d31a48f074c35561c0353b3bdfe298"}]}
