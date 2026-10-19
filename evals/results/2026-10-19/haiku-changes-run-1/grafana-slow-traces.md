## Slow GET /product/{sku} requests are caused by row-lock contention in inventory: the inventory service's SELECT ... FOR UPDATE on stock waits on Lock:tuple in inventory-db for about 3s, which accounts for almost all of the 3.1s storefront request. Recent slow traces show the same shape, but I could not check for recent rollouts because no Kubernetes tools were available.

**Root cause** (medium confidence, `dependency_failure`): Lock contention on the inventory-db stock table. The inventory /stock/{sku} handler runs SELECT qty FROM stock WHERE sku = $1 FOR UPDATE, and the query waits on Lock:tuple for about 3050ms. Storefront latency is dominated by that wait. The lock holder and the trigger (a new code path, a long transaction, or a traffic spike on hot SKUs) are not yet identified.
**Severity:** high  ·  **Affected:** shop/service/storefront, shop/service/inventory, shop/service/catalog

**Evidence**
- `grafana_search_tempo_traces (TraceQL duration > 2s on storefront)`: Multiple recent storefront GET /product/{sku} traces between about 2.4s and 3.3s, for example trace 45d31a48f074c35561c0353b3bdfe298 at 3103ms. Storefront's root span is 3103ms. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace (trace 45d31a48f074c35561c0353b3bdfe298)`: Span GET /stock/{sku} in inventory took 3056ms, and its child SELECT stock took 3050ms with db.wait_event=Lock:tuple, db.query.text 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', server.address inventory-db.shop.svc. Catalog (14ms) and pricing (21ms) were fast.
- `grafana_query_loki_logs (storefront, 1h)`: Log lines such as 'GET /product/sku-1088 200 2834ms slow' and 'GET /product/sku-1077 200 3131ms slow' alternate with normal 55-62ms requests, so the slowness is intermittent rather than total.
- `grafana_query_loki_stats (storefront, 1h)`: 313 log entries for storefront in the last hour, one stream.

**Recommendations**
1. Check inventory-db for blocking sessions now (pg_stat_activity joined to pg_locks, or pg_blocking_pids) and identify the transaction holding the stock row lock and how long it has been open.
2. Check for recent deploys or config changes to inventory and any code that updates the stock table, since a new or slower writer could hold row locks. No Kubernetes tools were available, so this is unverified.
3. Look for a hot-SKU pattern: check whether the slow requests cluster on a few SKUs (the sample shows sku-1088, sku-1077, sku-1093), and whether concurrent stock updates are contending on them.
4. Mitigate by shortening the transaction holding the lock or moving the stock read off FOR UPDATE where a plain read is safe. Do not restart inventory-db without approval.
5. Add a Prometheus panel or alert on inventory-db lock waits and on inventory /stock p99 to confirm impact and timing. No Prometheus query was run here.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_stats`
4. `grafana_get_tempo_trace`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_patterns`
7. `grafana_query_loki_logs`
8. `grafana_generate_deeplink`
