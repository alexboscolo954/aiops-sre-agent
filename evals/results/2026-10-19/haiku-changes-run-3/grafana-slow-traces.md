## p99 latency on GET /product/{sku} is high because the inventory service's stock query is blocked on row locks in inventory-db. The slow trace shows about 3.05s in 'SELECT qty FROM stock ... FOR UPDATE' waiting on Lock:tuple, while catalog and pricing calls take 14-21ms. Storefront logs show only 200 responses, so this is slowness, not errors.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in inventory-db: 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' waits on Lock:tuple, so the inventory /stock/{sku} call inside GET /product/{sku} takes about 3s. Several other slow storefront traces (2.5-3.3s) show the same shape. I did not find a rollout or config change to blame, and I could not confirm the lock holder or whether the lock waits are from one hot SKU or a long-running transaction.
**Severity:** medium  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_get_tempo_trace (tempo, trace 45d31a48f074c35561c0353b3bdfe298)`: GET /product/{sku} took 3103ms. Child GET /stock/{sku} in inventory took 3056ms. Its DB span 'SELECT stock' took 3050ms with db.wait_event=Lock:tuple on server inventory-db.shop.svc. Catalog /items took 14ms and pricing /quote took 21ms. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_search_tempo_traces (tempo, {resource.service.name="storefront" && duration > 2s})`: Many recent GET /product/{sku} traces exceed 2s, typically 2.4-3.3s, all with inventory as the extra slow hop in the sampled trace. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_patterns ({service_name="storefront"}, last 1h)`: Only one pattern: 'GET <_> 200 <_> <_>' with 346 occurrences. No error lines, so the latency is not surfacing as application errors.
- `grafana_query_loki_stats ({service_name="storefront"}, last 1h)`: 1 stream, 313 entries in the last hour.

**Recommendations**
1. Check inventory-db for lock waiters and blockers: pg_stat_activity joined with pg_locks, filtering for waiting sessions on the stock table.
2. Identify the transaction holding the row locks (long-running or idle-in-transaction sessions) and find which SKUs are hot.
3. Inspect the inventory service code path for GET /stock/{sku} to confirm that FOR UPDATE is needed, and check for recent changes to it.
4. If a single session is blocking others, ending it is a possible short-term mitigation, but it needs human approval and care because it can roll back work.
5. Once the lock is cleared, confirm the p99 for /product/{sku} returns below 2s in Prometheus. I did not query Prometheus, so this is not yet confirmed.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_stats`
4. `grafana_get_tempo_trace`
5. `grafana_query_loki_patterns`
6. `grafana_list_loki_label_values`
7. `grafana_search_tempo_traces`
8. `grafana_generate_deeplink`
