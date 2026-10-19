## p99 latency on GET /product/{sku} is high because storefront's calls to inventory are stalled waiting on a row lock in inventory-db. In the sampled slow trace, 3050ms of the 3103ms request sits in one SELECT ... FOR UPDATE on the stock table with db.wait_event=Lock:tuple. Other services (catalog, pricing) are fast, so inventory's DB lock contention is the bottleneck.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in inventory-db. Trace 45d31a48f074c35561c0353b3bdfe298 (storefront, 3103ms, GET /product/{sku}) shows the child span GET /stock/{sku} in inventory taking 3056ms, and its SELECT stock span taking 3050ms with query 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event 'Lock:tuple', server inventory-db.shop.svc. Catalog (14ms) and pricing (21ms) are fast, so the delay is the inventory row lock. Slow storefront requests in Loki (for example sku-1010 at 2606ms, sku-1088 at 2834ms) correlate with this path. Who holds the lock (a long transaction or a hot SKU) is not established. I had no Kubernetes tools, so I could not check for a recent rollout of inventory or inventory-db.
**Severity:** high  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returned multiple GET /product/{sku} traces of 2.4s to 3.3s in the last hour (for example 45d31a48f074c35561c0353b3bdfe298 at 3103ms). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront GET /product/{sku} 3103ms; inventory GET /stock/{sku} 3056ms; SELECT stock 3050ms with db.query.text 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event 'Lock:tuple', server.address inventory-db.shop.svc. catalog 14ms and pricing 21ms.
- `grafana_query_loki_logs`: Storefront access logs in the last hour show slow requests such as 'GET /product/sku-1010 200 2606ms slow', 'GET /product/sku-1088 200 2834ms slow' and 'GET /product/sku-1077 200 3131ms slow', interleaved with normal 55-62ms 'ok' lines.
- `grafana_query_loki_patterns`: Storefront log pattern 'GET <_> 200 <_> <_>' totals 346 lines in the last hour. The pattern does not distinguish slow from ok lines, so it does not show the failure on its own.

**Recommendations**
1. In inventory-db, check pg_stat_activity and pg_locks for sessions waiting on Lock:tuple against the stock table, and identify the blocking transaction and its query.
2. Look for long-running or idle-in-transaction sessions that hold row locks on stock (for example from a batch job or a missing commit), and end them only with approval.
3. Check whether the inventory or inventory-db workload changed recently (rollout history or config). The Kubernetes tools were unavailable, so this is unverified.
4. Review the stock update path: SELECT ... FOR UPDATE on hot SKUs serializes requests. Consider a shorter transaction scope, a lock timeout, or a non-locking read for the product page.
5. Confirm the trend in Prometheus (storefront p99 for /product/{sku} against inventory latency) to measure impact and when it started.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_patterns`
5. `grafana_get_tempo_trace`
6. `grafana_query_loki_patterns`
7. `grafana_query_loki_logs`
8. `grafana_generate_deeplink`
9. `read_more`
