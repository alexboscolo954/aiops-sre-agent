## Storefront p99 latency on GET /product/{sku} is high because the slow spans sit in inventory's stock query. In the sampled slow trace, the inventory span 'SELECT qty FROM stock ... FOR UPDATE' waited about 3050ms of a 3103ms request on a Lock:tuple wait in inventory-db. The root cause is row-lock contention in inventory-db, not storefront itself. The blocking transaction was not identified, and no Kubernetes state was checked.

**Root cause** (medium confidence, `app_error`): Row-lock contention in inventory-db. Inventory's read path runs SELECT ... FOR UPDATE on the stock table, and requests queue behind a lock held by another transaction (the holder was not identified). Storefront latency is inherited from the inventory call.
**Severity:** high  ·  **Affected:** shop/service/storefront, shop/service/inventory, shop/service/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returned many GET /product/{sku} traces of about 2.4-3.3s, e.g. 45d31a48f074c35561c0353b3bdfe298 at 3103ms and aa889c27b4277ffe35150f32673a376f at 2523ms. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront GET /product/{sku} 3103ms, catalog 14ms, pricing 21ms, inventory GET /stock/{sku} 3056ms, and child span 'SELECT stock' 3050ms with db.system=postgresql, db.query.text='SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event='Lock:tuple', server.address=inventory-db.shop.svc.
- `grafana_query_loki_logs`: Storefront log lines show slow requests mixed with normal ones, e.g. 'GET /product/sku-1010 200 2606ms slow' and 'GET /product/sku-1088 200 2834ms slow', while most lines show about 55-62ms ok.
- `grafana_query_loki_patterns`: The {service_name="storefront"} pattern 'GET <_> 200 <_> <_>' has 346 entries in the last hour. Patterns for inventory and inventory-db returned the same result, so they were not independently verified.

**Recommendations**
1. Query inventory-db (for example pg_stat_activity and pg_locks) to find the transaction holding row locks on the stock table and the sessions waiting on it.
2. Find the code path that issues SELECT ... FOR UPDATE for GET /stock/{sku} and check whether it is a read path that should be a plain SELECT, or whether it holds the transaction open too long.
3. If a long-running or idle-in-transaction session is the blocker, terminate it or fix the transaction scope. This is a DB-side action and needs human approval.
4. Check recent inventory deploys or config changes, since FOR UPDATE on a read path may be new. Confirm the Kubernetes rollout history for the shop namespace, which was not checked here.
5. Confirm that the inventory service logs show the same lock-wait pattern. The Loki inventory query returned storefront lines, so this is not yet verified.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_stats`
4. `grafana_get_tempo_trace`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_patterns`
7. `grafana_query_loki_patterns`
8. `grafana_query_loki_logs`
9. `grafana_generate_deeplink`
