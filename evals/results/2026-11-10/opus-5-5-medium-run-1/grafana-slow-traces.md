## Storefront GET /product/{sku} is slow because of the inventory service. In the slow trace I opened, inventory's Postgres query `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` sat waiting on a row lock (wait_event Lock:tuple) for about 3.05s of the 3.1s request. Catalog and pricing each answered in about 20ms.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in the inventory Postgres database (inventory-db.shop.svc). In trace 45d31a48…, the inventory span GET /stock/{sku} took 3056ms. Almost all of that was its child span 'SELECT stock' (3050ms), running `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` with db.wait_event=Lock:tuple, meaning it was waiting for another transaction to release a lock on the same stock rows. Catalog (14ms) and pricing (21ms) were fast. All the slow storefront traces have the same inventory spans, and storefront logs mix slow requests (about 2.5–3.1s) with normal ones (about 60ms), which looks like per-row locking rather than a general slowdown. I could not tell which transaction holds the locks: Loki has no logs for inventory or its database, and I did not query metrics. Using FOR UPDATE on a read-only stock lookup is also suspicious in itself.
**Severity:** medium  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory

**Evidence**
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298 took 3103ms in total. Inventory GET /stock/{sku} took 3056ms, of which its child span SELECT stock took 3050ms: 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event=Lock:tuple, server inventory-db.shop.svc. Catalog took 14ms and pricing 21ms.
- `grafana_search_tempo_traces`: Many storefront GET /product/{sku} traces over 2s (about 2.5–3.3s), each including 2 inventory spans plus catalog and pricing spans. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: Storefront logs mix slow requests ('GET /product/sku-1077 200 3131ms slow') with fast ones (about 55–62ms 'ok'); no errors, all 200s. No inventory or DB logs exist in Loki (only the storefront and payments apps). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22storefront%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. On inventory-db, find what holds the locks: query pg_stat_activity joined to pg_locks (or use pg_blocking_pids()) and look for long-running or idle-in-transaction sessions on the stock table.
2. If one stuck transaction or batch job is holding the locks, coordinate with its owner, then end it with pg_terminate_backend (needs DBA approval).
3. Check for recent deploys or scheduled jobs (stock syncs, migrations, bulk updates) on inventory that started around when latency rose.
4. Longer term: remove FOR UPDATE from the read-only stock lookup used by GET /stock/{sku}, or use NOWAIT/SKIP LOCKED or a timeout, and set lock_timeout / idle_in_transaction_session_timeout on inventory-db.
5. Add log shipping for inventory and inventory-db to Loki so the next investigation can see their logs.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{namespace=\"shop\"}"}
5. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "app", "matcher": "{namespace=\"shop\"}"}
6. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{namespace=\"shop\"} |~ \"(?i)lock|deadlock|vacuum|migration|error|slow\"", "limit": 20}
7. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceId", "query": "45d31a48f074c35561c0353b3bdfe298"}]}
8. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{namespace=\"shop\"} |= \"slow\""}], "timeRange": {"from": "now-1h", "to": "now"}}
