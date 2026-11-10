## Slow GET /product/{sku} requests on storefront are almost entirely time spent waiting in the inventory service. In the trace I opened, inventory's Postgres query `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` waited about 3s on a row lock (db.wait_event=Lock:tuple). Catalog and pricing answered in 14–21ms.

**Root cause** (medium confidence, `dependency_failure`): Row-lock contention in the inventory database (inventory-db.shop.svc, db inventory). In slow trace 45d31a48f074c35561c0353b3bdfe298 the request took 3103ms. Of that, inventory GET /stock/{sku} took 3056ms, and its child span 'SELECT stock' took 3050ms. That span ran `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` with db.wait_event=Lock:tuple, so the query was blocked behind another transaction holding the same stock row. Catalog (14ms) and pricing (21ms) were fast. The product page, a read path, takes a FOR UPDATE row lock, so it queues behind any transaction that holds the same SKU row for a long time. I could not see what is holding the locks (no inventory or DB logs in Loki, no DB metrics checked). I also did not check whether a recent inventory change added the FOR UPDATE, so this is a dependency failure and I have not tied it to a rollout. I opened only one trace in full. A second trace fetch returned no data, and a TraceQL search filtered on Lock:tuple returned exactly the same list as the plain slow-trace search, so I can't count it as separate confirmation.
**Severity:** high  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: Many storefront 'GET /product/{sku}' traces over 2s (about 2.5–3.3s) in the last hour. Each one has catalog, pricing and 2 inventory spans. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298: storefront took 3103ms. Inventory GET /stock/{sku} took 3056ms, and its 'SELECT stock' span took 3050ms: 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE', db.wait_event=Lock:tuple, server inventory-db.shop.svc. Catalog took 14ms, pricing 21ms.
- `grafana_query_loki_logs`: Storefront logs mix fast requests ('GET /product/sku-1017 200 61ms ok') with slow ones ('GET /product/sku-1010 200 2606ms slow', up to 3131ms), all returning 200. Loki holds logs only for storefront and payments, nothing for inventory. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22storefront%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_patterns`: The only log pattern in namespace shop is 'GET <_> 200 <_> <_>' (346 lines). No error pattern, so requests are slow but not failing.

**Recommendations**
1. On inventory-db, find the sessions holding the locks: query pg_stat_activity together with pg_locks (or pg_blocking_pids) and look for long-running or 'idle in transaction' sessions holding locks on the stock table.
2. If one batch job, migration or stuck transaction is holding the locks, stop it with pg_cancel_backend or pg_terminate_backend, but only after the owning team approves.
3. Check inventory's recent deploys and any CronJobs or Jobs in namespace shop for something that started holding long transactions on stock, or that added FOR UPDATE to the stock read path.
4. Lasting fix: the read-only GET /stock/{sku} path should not use SELECT ... FOR UPDATE. Use a plain SELECT, or add a lock_timeout / NOWAIT with a fallback, so product pages don't queue behind writers.
5. Add inventory logs and Postgres lock-wait metrics (e.g. postgres_exporter) so lock contention is visible next time, then check that storefront p99 drops back under 2s.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{namespace=\"shop\"}"}
5. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "app", "matcher": "{namespace=\"shop\"}"}
6. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{namespace=\"shop\"} |~ \"(?i)lock|deploy|version|migrat|batch|job\"", "limit": 20}
7. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "9c44528f8a843750cbbbde89d77624f2"} (error)
8. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"inventory\" && span.db.wait_event=\"Lock:tuple\"}"}
9. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "45d31a48f074c35561c0353b3bdfe298"}], "timeRange": {"from": "now-1h", "to": "now"}}
10. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}], "timeRange": {"from": "now-1h", "to": "now"}}
11. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{namespace=\"shop\", service_name=\"storefront\"} |= \"slow\""}], "timeRange": {"from": "now-1h", "to": "now"}}
