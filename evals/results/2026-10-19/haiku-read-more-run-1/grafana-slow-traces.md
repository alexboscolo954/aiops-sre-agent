## p99 latency on storefront GET /product/{sku} is high because requests wait on inventory's stock query. The trace shows a 3050ms SELECT ... FOR UPDATE against inventory-db stuck on Lock:tuple, so row-lock contention in inventory-db is the likely cause. No Kubernetes tools were available, so I could not check for a recent rollout.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in inventory-db. In slow trace 45d31a48f074c35561c0353b3bdfe298 (storefront root span 3103ms), the inventory span GET /stock/{sku} took 3056ms, and its child query 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' against server inventory-db.shop.svc took 3050ms with db.wait_event=Lock:tuple. Catalog (14ms) and pricing (21ms) were fast, so the delay is entirely the inventory row lock. Storefront logs show about 1 in 8 requests at 2.5-3.3s, all tagged 'slow', while the rest are 55-62ms. The cause of the lock holder (a long transaction or a hot SKU) was not confirmed because the inventory log query returned storefront lines rather than inventory logs.
**Severity:** high  ·  **Affected:** shop/Service/storefront, shop/Service/inventory, shop/Database/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returned many GET /product/{sku} traces of 2.4-3.3s in the last hour, including 3103ms, 3121ms and 3060ms. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront GET /product/{sku} 3103ms. Inventory GET /stock/{sku} 3056ms. Child 'SELECT stock' on server inventory-db.shop.svc 3050ms, db.query.text 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event 'Lock:tuple'. Catalog 14ms and pricing 21ms were fast.
- `grafana_query_loki_patterns`: {service_name="storefront"} over the last hour: single pattern 'GET <_> 200 <_> <_>' with 346 occurrences. Slow lines such as 'GET /product/sku-1010 200 2606ms slow' are interleaved with 'ok' lines at 55-62ms.
- `grafana_query_loki_stats`: {service_name="storefront"} had 1 stream and 313 entries in the last hour.

**Recommendations**
1. Check inventory-db for lock waiters and the blocking session, e.g. pg_stat_activity and pg_locks joined on waiting sessions, and find the long-running or idle-in-transaction transaction holding row locks on the stock table.
2. Check whether the stock hot-spot (a few SKUs such as sku-1010, sku-1072, sku-1088) is getting concentrated writes or a stuck transaction, and look at the inventory service's recent changes or deploys to its stock-update code path.
3. As a mitigation, if the lock holder is confirmed as a stuck transaction, terminate that session (needs human approval). Otherwise, consider a short statement_timeout or fewer concurrent FOR UPDATE calls in inventory.
4. Pull inventory service logs and DB logs for the same window to confirm the lock holder. Note that the attempted inventory log query returned storefront lines, so this is still open.
5. Check whether a kubectl rollout history of the inventory deployment shows a recent revision, since a change to the FOR UPDATE path would make this a bad_rollout.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_patterns`
4. `grafana_query_loki_logs`
5. `grafana_get_tempo_trace`
6. `grafana_query_loki_stats`
7. `grafana_query_loki_logs`
8. `grafana_generate_deeplink`
