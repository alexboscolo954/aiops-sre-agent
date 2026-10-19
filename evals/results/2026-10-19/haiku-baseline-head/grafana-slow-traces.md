## p99 latency on GET /product/{sku} is high because storefront requests spend most of their time waiting on a row lock in the inventory database. The slow trace shows the inventory call running 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' with wait event Lock:tuple for about 3.05s of a 3.1s request. Kubernetes state and rollout history were not available to me, so the lock holder and any recent change are unconfirmed.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in inventory-db on the stock table. The GET /stock/{sku} handler takes SELECT ... FOR UPDATE, and requests block on Lock:tuple, probably behind another long-running or idle-in-transaction session that holds the same SKU rows. Storefront's p99 rises because it waits on inventory. The lock holder has not been identified.
**Severity:** high  ·  **Affected:** shop/storefront (GET /product/{sku}), shop/inventory (GET /stock/{sku}, inventory-db)

**Evidence**
- `grafana_get_tempo_trace (trace 45d31a48f074c35561c0353b3bdfe298)`: Root span GET /product/{sku} took 3103ms. Child GET /stock/{sku} in inventory took 3056ms. Its child 'SELECT stock' took 3050ms with db.wait_event=Lock:tuple, db.query.text='SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', server.address=inventory-db.shop.svc. Catalog (14ms) and pricing (21ms) were fast.
- `grafana_search_tempo_traces ({resource.service.name="storefront" && duration > 2s})`: Multiple recent storefront GET /product/{sku} traces over 2s (about 2.5s to 3.3s), all with the same shape: inventory span count 2, with the slow time in inventory. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_patterns ({service_name="storefront"}, last 1h)`: Storefront logs: one pattern 'GET <_> 200 <_> <_>' with 346 lines. Slow requests are logged as '200 ~2500-3100ms slow', and normal ones as '200 ~55-62ms ok'.
- `grafana_list_loki_label_values (service_name)`: Only 'payments' and 'storefront' exist as service_name in Loki, so inventory logs were not queryable there. My inventory log queries returned storefront lines only, so there is no inventory-side log evidence.

**Recommendations**
1. On inventory-db, check pg_stat_activity and pg_locks for sessions blocked on Lock:tuple against the stock table, and find the blocking session and its query. Look especially for idle-in-transaction sessions or long transactions that hold FOR UPDATE locks on hot SKUs.
2. If a long-running or stuck transaction is the blocker, end it after confirming it is safe. This is a database-changing action, so get human approval first.
3. Check whether a recent deploy of inventory or a batch job changed the locking pattern, for example a new FOR UPDATE path or a longer transaction. Kubernetes rollout history was not checked here.
4. Consider shortening lock wait time (lock_timeout) or adding retries/fallback in inventory for the stock read, so one hot SKU cannot stall the whole product page.
5. Add log and metric coverage for inventory: the inventory service is not present under service_name in Loki, so its logs and DB wait metrics could not be checked.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_stats`
4. `grafana_get_tempo_trace`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_logs`
7. `grafana_query_loki_patterns`
8. `grafana_list_loki_label_values`
9. `grafana_generate_deeplink`
