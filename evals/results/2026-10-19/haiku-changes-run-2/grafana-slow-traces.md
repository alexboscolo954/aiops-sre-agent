## StorefrontHighLatency is caused by slow GET /product/{sku} requests waiting on row locks in the inventory database. The inventory service runs SELECT ... FOR UPDATE on stock, and that query waits about 3s on Lock:tuple, which accounts for nearly all of the storefront latency. The trace shows the lock wait but not who holds the lock, and I could not read inventory or payments logs, so the holder and trigger are still unknown.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in inventory-db. The inventory service's SELECT qty FROM stock WHERE sku = $1 FOR UPDATE blocks on Lock:tuple for about 3050ms of a 3103ms storefront request. Some other transaction holds the stock row locks for long enough to stall reads. The holder (a long-running or idle-in-transaction session, a batch job, or a new code path) has not been identified. No rollout was found in the data I could read.
**Severity:** high  ·  **Affected:** shop/storefront (service storefront, GET /product/{sku}), shop/inventory (service inventory, GET /stock/{sku}), shop/inventory-db (PostgreSQL stock table)

**Evidence**
- `grafana_get_tempo_trace (tempo, trace 45d31a48f074c35561c0353b3bdfe298)`: Root GET /product/{sku} took 3103ms. Child GET /stock/{sku} on inventory took 3056ms. Its DB span 'SELECT stock' took 3050ms with db.query.text 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event 'Lock:tuple', server.address inventory-db.shop.svc. Catalog (14ms) and pricing (21ms) were fast.
- `grafana_search_tempo_traces (tempo, duration > 2s on storefront)`: Multiple recent storefront GET /product/{sku} traces between 2.4s and 3.3s. Each shows inventory as the slow dependency in the trace's service stats (inventory spanCount 2).
- `grafana_query_loki_logs (loki, service_name=storefront)`: Access log lines show many 'GET /product/skuNNNN 200 2500-3100ms slow' entries interleaved with ~55-60ms 'ok' entries, so the slowness is intermittent and tied to certain SKUs.
- `grafana_query_loki_patterns / grafana_list_loki_label_values`: Loki returned the same storefront pattern ('GET <_> 200 <_> <_>', 346 lines) for the inventory and payments selectors, and label values for namespace shop are only payments and storefront. Inventory logs were not retrievable, so no lock-holder or error evidence was found there.
- `grafana_search_tempo_traces (lock-wait query on inventory)`: The span-attribute query for inventory Lock:tuple waits returned the same storefront traces, so it did not independently confirm the lock-wait pattern across traces.

**Recommendations**
1. Identify the lock holder on inventory-db now: query pg_stat_activity and pg_locks for waiting sessions and their blockers, and look for 'idle in transaction' sessions or long-running transactions touching the stock table.
2. If a blocking session is a stuck or idle transaction, terminate it with pg_terminate_backend after confirming with the owning team. This is a state-changing action and needs human approval.
3. Check recent changes to the inventory service, its batch or stock-update jobs, and inventory-db over the last hour (deploys, cron jobs, migrations). Nothing was confirmed in the data I could read, so this is still open.
4. Shorten the lock scope in the stock update path (short transactions, consistent row ordering, SKIP LOCKED or no FOR UPDATE on reads where possible), and add a statement or lock timeout on the inventory read path so requests fail fast instead of holding storefront threads.
5. Confirm impact with Prometheus: p99 of storefront GET /product/{sku} against inventory p99 and inventory DB lock-wait metrics, to check whether the spike started at a specific time.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_patterns`
4. `grafana_query_loki_logs`
5. `grafana_get_tempo_trace`
6. `grafana_query_loki_patterns`
7. `grafana_query_loki_logs`
8. `grafana_list_loki_label_values`
9. `grafana_search_tempo_traces`
10. `grafana_query_loki_patterns`
11. `grafana_query_loki_logs`
