## p99 latency on GET /product/{sku} is above 2s because storefront requests spend most of their time waiting on the inventory service. In the sampled slow trace, the inventory span for SELECT stock ... FOR UPDATE ran for 3050ms with db.wait_event=Lock:tuple against inventory-db.shop.svc, so the bottleneck is row-lock contention in the inventory database, not storefront itself.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in inventory-db: the SELECT qty FROM stock WHERE sku = $1 FOR UPDATE query in the inventory service blocks on Lock:tuple waits, which stalls GET /stock/{sku} and pushes storefront's GET /product/{sku} past 2s. Probable triggers are long-running or uncommitted transactions holding stock row locks, or hot SKUs being locked concurrently. I did not confirm the trigger, and I could not check Kubernetes state or rollout history because no Kubernetes tools were available.
**Severity:** high  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returned many slow GET /product/{sku} traces, for example 45d31a48f074c35561c0353b3bdfe298 at 3103ms and aa889c27b4277ffe35150f32673a376f at 2523ms, all with rootServiceName storefront.
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298 (3103ms): storefront GET /product/{sku} calls catalog GET /items/{sku} (14ms), pricing GET /quote (21ms), and inventory GET /stock/{sku} (3056ms). The inventory child span SELECT stock runs 3050ms with db.wait_event=Lock:tuple, db.query.text 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', server.address inventory-db.shop.svc.
- `grafana_query_loki_logs`: storefront logs (service_name=storefront) show a mix of fast and slow requests, for example 'GET /product/sku-1010 200 2606ms slow' and 'GET /product/sku-1088 200 2834ms slow', while most requests show 'ok' at 55-62ms. The slow ones line up with the stock lookups in the trace.

**Recommendations**
1. Inspect inventory-db for blocking locks now, for example via pg_stat_activity and pg_locks joined on waiting sessions, to find the blocking transaction and its query and client.
2. Find which application path issues SELECT ... FOR UPDATE on stock and check whether it holds transactions open across slow calls or external calls. Shorten the transaction or move the lock to the write only.
3. Check whether a recent deployment of inventory or storefront, or a batch or job touching the stock table, coincides with the start of the slowdown. Use kubectl rollout history on shop/inventory and shop/storefront to confirm.
4. If the blocker is a stuck transaction, terminate it with pg_terminate_backend after human approval, then watch whether p99 recovers.
5. Add a lock_timeout on the stock query so requests fail fast instead of stalling storefront past 2s.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_stats`
4. `grafana_get_tempo_trace`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_patterns`
7. `grafana_query_loki_logs`
