## p99 latency on storefront GET /product/{sku} is above 2s because of a row-lock wait in the inventory service's Postgres query. The storefront, catalog and pricing spans are fast.

**Root cause** (medium confidence, `dependency_failure`): In the sampled slow trace, 3056ms of a 3103ms storefront request was the inventory GET /stock/{sku} span. Nearly all of that (3050ms) was the DB span `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` against inventory-db.shop.svc, with db.wait_event=Lock:tuple. The inventory read path takes a row-level lock (FOR UPDATE) and waits on tuple locks held by other transactions. Catalog took 14ms and pricing 21ms. Storefront logs show an intermittent pattern: most requests take about 60ms, and some take 2.5–3.1s and are marked slow. No rollout evidence was checked, so the trigger for the lock contention (concurrent writers, a long transaction, or a recent code change) is unconfirmed.
**Severity:** medium  ·  **Affected:** shop/Service/storefront, shop/Service/inventory, shop/Service/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: Many storefront GET /product/{sku} traces take 2.5–3.3s. Every sampled trace includes 2 inventory spans, plus one each from catalog, pricing and storefront. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298 (3103ms): inventory GET /stock/{sku} took 3056ms. Its child span 'SELECT stock' took 3050ms, with db.query.text 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' and db.wait_event 'Lock:tuple' on inventory-db.shop.svc. Catalog took 14ms and pricing 21ms. All spans returned status ok.
- `grafana_query_loki_logs`: Storefront logs show an intermittent pattern: most requests take about 55–62ms ('ok'), while some take 2.5–3.1s ('slow'), for example sku-1010 at 2606ms and sku-1077 at 3131ms. All returned 200, so the problem is latency rather than errors.

**Recommendations**
1. Inspect inventory-db for lock contention: query pg_stat_activity and pg_locks for sessions blocking on tuple locks, and look for long-running or idle-in-transaction sessions touching the stock table.
2. Change the inventory read path so it does not take row locks. Use a plain SELECT for the product page, and keep FOR UPDATE only in reservation or decrement flows.
3. Check recent inventory deploys or batch jobs that update stock, to find what started the lock contention.
4. Set lock_timeout and statement_timeout on inventory queries, and use short transactions, so a lock wait cannot stall product page requests for seconds.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}", "format": "compact"}
5. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "datasource": {"uid": "tempo"}, "queryType": "traceql", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}]}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "datasource": {"uid": "tempo"}, "queryType": "traceql", "query": "{resource.service.name=\"inventory\" && span.db.wait_event=\"Lock:tuple\"}"}]}
