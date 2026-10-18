## Storefront p99 latency on GET /product/{sku} is high because requests wait on a row lock in the inventory database. Sampled slow traces show the inventory service spending about 3s in `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` with wait_event Lock:tuple, while the storefront, catalog and pricing spans are fast.

**Root cause** (medium confidence, `dependency_failure`): Row-level lock contention on the inventory-db stock table. The stock lookup uses SELECT ... FOR UPDATE, so concurrent requests for the same SKU queue behind a lock holder (likely a long or stuck transaction). The lock holder was not identified, and no deployment history or Kubernetes state was checked, so whether a recent change caused this is unconfirmed.
**Severity:** high  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory

**Evidence**
- `grafana_search_tempo_traces`: Multiple storefront traces in the last hour exceed 2s, for example 45d31a48f074c35561c0353b3bdfe298 at 3103ms and aa889c27b4277ffe35150f32673a376f at 2523ms, all with rootTraceName GET /product/{sku}.
- `grafana_get_tempo_trace (trace 45d31a48f074c35561c0353b3bdfe298)`: Storefront GET /product/{sku} took 3103ms. Inventory GET /stock/{sku} took 3056ms. Its child span SELECT stock took 3050ms with db.system=postgresql, db.wait_event=Lock:tuple, db.query.text='SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', server.address=inventory-db.shop.svc. Catalog (14ms) and pricing (21ms) were fast.
- `grafana_query_loki_logs (storefront)`: Slow storefront lines are mixed with normal ones, e.g. 'GET /product/sku-1010 200 2606ms slow' and 'GET /product/sku-1088 200 2834ms slow', while most requests return in about 55-60ms. Slow requests are a minority of the sample.
- `grafana_query_loki_patterns (storefront and inventory)`: The dominant pattern is 'GET <_> 200 <_> <_>' with 346 occurrences. Inventory logs are not present in Loki under service_name=inventory, so the inventory lock holder could not be found from logs.

**Recommendations**
1. Check pg_stat_activity and pg_locks on inventory-db for sessions in 'idle in transaction' or long-running transactions that hold row locks on the stock table, and identify the blocking PID and query.
2. Find the application or job that issues the transaction holding the lock (for example a stock update or batch job) and check whether it started or changed recently, using the inventory deployment rollout history.
3. If a stuck transaction is confirmed, terminate the blocking backend (pg_terminate_backend) after human approval. Clearing the blocker should restore latency quickly.
4. Long term, shorten transaction scope on stock updates, add lock_timeout to the stock query, or avoid FOR UPDATE on read-only paths, so that lock waits fail fast instead of adding seconds of latency.
5. Confirm impact with Prometheus p99 latency for the storefront /product/{sku} route and the inventory DB lock-wait metrics, since no metric queries were run in this triage.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_patterns`
4. `grafana_get_tempo_trace`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_logs`
7. `grafana_list_loki_label_values`
8. `grafana_list_tempo_attribute_values`
