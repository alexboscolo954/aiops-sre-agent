## Storefront GET /product/{sku} takes 2.5–3.3s because of one downstream call: inventory's GET /stock/{sku}. In the trace I opened, almost all of that time is spent in a Postgres `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` that is waiting on a row lock (wait_event Lock:tuple).

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in inventory-db.shop.svc. In trace 45d31a48 the request took 3103ms. Of that, inventory GET /stock/{sku} took 3056ms, and nearly all of it (3050ms) was the span `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` with db.wait_event=Lock:tuple. catalog (14ms) and pricing (21ms) were fast. Every slow trace in the search had the same span shape (storefront → catalog, pricing, 2× inventory). Inventory uses FOR UPDATE on a read path, so stock lookups queue behind whatever transaction holds those sku rows. I haven't identified that transaction: it could be a long-running transaction or hot-sku writes. I also didn't check rollout history or Loki logs, so a recent inventory change can't be ruled out. Confidence is medium because I opened only one trace in full.
**Severity:** medium  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory

**Evidence**
- `grafana_search_tempo_traces`: Many storefront GET /product/{sku} traces in the last hour took 2.48–3.28s, and every one called catalog, pricing and inventory (2 spans). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: request 3103ms. inventory GET /stock/{sku} 3056ms, of which 3050ms is the span 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' on inventory-db.shop.svc with db.wait_event=Lock:tuple. catalog took 14ms, pricing 21ms.

**Recommendations**
1. On inventory-db, look at pg_stat_activity and pg_locks (blocked versus blocking PIDs, 'idle in transaction' sessions, xact_start age) to find the transaction holding the stock row locks.
2. If one long-running or stuck transaction is blocking, have the inventory/DB owner decide whether to end it (pg_terminate_backend) after checking what it is doing.
3. Check inventory's recent rollouts or batch jobs (for example stock sync or reservation jobs) that might hold row locks for a long time.
4. Longer-term fix: take FOR UPDATE out of the read-only stock lookup (or use NOWAIT/SKIP LOCKED or a lock_timeout), keep write transactions short, and add a timeout on storefront's call to inventory.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceId", "query": "45d31a48f074c35561c0353b3bdfe298"}]}
5. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}]}
