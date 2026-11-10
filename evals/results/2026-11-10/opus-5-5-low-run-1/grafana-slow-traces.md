## Slow GET /product/{sku} requests in storefront (2.5–3.3s) are caused by the downstream inventory service. Its Postgres query `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` waits about 3s on a row lock (wait event Lock:tuple) in inventory-db.

**Root cause** (medium confidence, `dependency_failure`): In trace 45d31a48, the request takes 3103ms. Catalog takes 14ms and pricing 21ms. Inventory GET /stock/{sku} takes 3056ms, and 3050ms of that is the 'SELECT stock' span on postgresql at inventory-db.shop.svc, with db.wait_event=Lock:tuple. That means a stock-check read is using SELECT ... FOR UPDATE and waiting behind other transactions that hold the same rows. The backends reporting this lock wait are queued behind lock holders; what is holding the locks (long transactions, a batch job, or a code change) has not been checked. I only opened one trace in detail, but all the slow traces in the search have the same shape: storefront calls catalog, pricing and inventory (two spans).
**Severity:** medium  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory

**Evidence**
- `grafana_search_tempo_traces`: Many storefront GET /product/{sku} traces in the last hour took 2.5–3.3s (for example 3103ms, 3284ms, 3121ms), and each includes inventory spans. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48: inventory 'SELECT stock' takes 3050ms of the 3103ms total, with query 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' and db.wait_event=Lock:tuple on inventory-db.shop.svc. Catalog takes 14ms and pricing 21ms.

**Recommendations**
1. On inventory-db, look at pg_stat_activity and pg_locks (pg_blocking_pids) to find the sessions holding the stock-row locks and how long their transactions have been open.
2. If a long or idle-in-transaction session or a batch job is holding the locks, ask a human to approve terminating it with pg_terminate_backend, or pause the job.
3. Check whether inventory was recently deployed and whether the stock read path started using FOR UPDATE. A read-only stock check should use a plain SELECT. Roll back if a new release introduced this.
4. Add a lock_timeout or statement_timeout on inventory DB calls, and a timeout on storefront's calls to inventory, so slow inventory calls don't drag out the whole product page.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}]}
