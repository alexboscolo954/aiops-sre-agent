## p99 latency on GET /product/{sku} is high because storefront requests wait on inventory, and the slow span is a PostgreSQL row lock. The sampled slow trace shows inventory's 'SELECT qty FROM stock ... FOR UPDATE' waiting on Lock:tuple for about 3s. Only one trace was inspected and the inventory log query returned storefront lines, so this is not yet confirmed across traffic.

**Root cause** (medium confidence, `app_error`): Row-level lock contention in inventory-db. The inventory service runs 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' on the request path, so concurrent requests for the same SKUs serialize on the row lock (db.wait_event=Lock:tuple). Each waiting request adds about 3s to storefront's GET /product/{sku}, which pushes p99 above 2s. The likely fix is to avoid taking a write lock on a read path, or to shorten lock hold time. Whether this is new is unknown, because no rollout history was checked.
**Severity:** medium  ·  **Affected:** shop/Service/storefront, shop/Service/inventory, shop/Database/inventory-db

**Evidence**
- `grafana_search_tempo_traces (TraceQL: {resource.service.name="storefront" && duration > 2s})`: Many storefront GET /product/{sku} traces exceed 2s, in the 2.4s to 3.3s range, with rootServiceName storefront and the inventory service present in each trace.
- `grafana_get_tempo_trace (trace 45d31a48f074c35561c0353b3bdfe298)`: Root span GET /product/{sku} takes 3103ms. Child GET /stock/{sku} in inventory takes 3056ms. Its DB span 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' takes 3050ms with db.wait_event=Lock:tuple and server.address=inventory-db.shop.svc. Catalog (14ms) and pricing (21ms) are fast.
- `grafana_query_loki_logs ({service_name="storefront"} recent lines)`: Lines like 'GET /product/sku-1010 200 2606ms slow' and 'GET /product/sku-1077 200 3131ms slow' alternate with 'ok' lines at about 55-60ms. The slow requests are intermittent, not uniform. Last hour: 313 storefront log entries.
- `grafana_query_loki_logs ({service_name="inventory"} filtered for lock/timeout/wait)`: The query returned storefront log lines instead of inventory lines, so inventory-side lock or error logs were not confirmed.

**Recommendations**
1. Check inventory-db for lock waits now, e.g. pg_stat_activity and pg_locks where wait_event_type='Lock', and find the blocking session and query.
2. Review the inventory code path for GET /stock/{sku}. Remove FOR UPDATE from the read path if it is not required, or move the lock to a short write-only transaction.
3. Check inventory's recent deployments or config changes for when FOR UPDATE was introduced, and roll back if that change is recent.
4. Re-check the inventory service's own logs and metrics, since the earlier log query did not return inventory data. Confirm that the lock waits correlate with the latency spikes.
5. Consider a temporary mitigation if the lock is hot: cache SKU stock reads or reduce concurrency for the hot SKUs.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_stats`
4. `grafana_get_tempo_trace`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_patterns`
7. `grafana_query_loki_logs`
