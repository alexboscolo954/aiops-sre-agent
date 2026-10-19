## Storefront p99 latency on GET /product/{sku} is high because slow requests spend about 3 seconds waiting on a row lock in the inventory service's database (SELECT ... FOR UPDATE on stock, wait_event Lock:tuple). The slow path is inventory-db lock contention, not storefront code. I had no Kubernetes tools, so I could not check for a recent rollout.

**Root cause** (medium confidence, `dependency_failure`): In trace 45d31a48f074c35561c0353b3bdfe298 (3103 ms root span), the storefront request calls inventory GET /stock/{sku} (3056 ms). Inside it, the postgresql span 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' on inventory-db.shop.svc runs 3050 ms with db.wait_event=Lock:tuple. Catalog (14 ms) and pricing (21 ms) are fast, so the delay is row-lock contention on the stock table in inventory-db. Several other traces over the last hour show the same 2.4-3.3 s root duration with the same span shape (catalog 1 span, inventory 2 spans, pricing 1 span). The cause of the lock holder (a long transaction or a concurrent writer on the same SKU) is not confirmed from the evidence I gathered.
**Severity:** high  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_list_datasources`: Datasources available: loki (uid loki), prometheus (uid prometheus, default), pyroscope, tempo (uid tempo). No Prometheus or Kubernetes metrics were queried.
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returned many GET /product/{sku} traces at 2.4-3.3 s, for example 3103 ms, 3121 ms, 3284 ms and 2502 ms, all with the same inventory-heavy service span shape. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront GET /product/{sku} 3103 ms -> inventory GET /stock/{sku} 3056 ms -> postgresql SELECT stock ... FOR UPDATE 3050 ms, db.wait_event=Lock:tuple, server.address=inventory-db.shop.svc. catalog /items 14 ms and pricing /quote 21 ms are not the bottleneck.
- `grafana_query_loki_patterns`: Loki pattern for {service_name="storefront"} over the last hour: 'GET <_> 200 <_> <_>' with 346 occurrences. No error pattern appeared, so the storefront logs do not show failures.
- `grafana_query_loki_patterns`: Loki pattern for {service_name="inventory"} over the last hour returned the same single pattern 'GET <_> 200 <_> <_>' with 346 occurrences. The logs do not mention locks, so the lock evidence comes only from the trace span attributes.

**Recommendations**
1. Check inventory-db for lock waits and the blocking session now, for example with pg_stat_activity and pg_blocking_pids() filtered on the stock table. Identify the transaction holding row locks on the hot SKUs.
2. Find what holds the stock row locks: a long-running or idle-in-transaction session, a batch job, or a recent code path that runs SELECT ... FOR UPDATE and then calls out to another service before committing. Terminate a stuck blocker only after a human approves it.
3. Check whether a recent change in the inventory service or its database (deploy, migration, or new query path) introduced FOR UPDATE on the stock table. Kubernetes rollout history was not available to me, so this is unverified.
4. Short term, shorten the transaction scope around the stock read or reduce lock hold time so storefront latency recovers. Confirm with the p99 latency panel in Prometheus that the 2 s threshold is back under control.
5. Re-run the TraceQL duration query after the fix to confirm the slow traces stop.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_search_tempo_traces`
3. `grafana_query_loki_patterns`
4. `grafana_get_tempo_trace`
5. `grafana_query_loki_patterns`
6. `grafana_generate_deeplink`
7. `grafana_generate_deeplink`
