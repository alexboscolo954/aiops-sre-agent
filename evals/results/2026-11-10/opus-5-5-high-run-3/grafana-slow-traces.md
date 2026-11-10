## Storefront GET /product/{sku} has p99 latency above 2s because it waits on the inventory service. Inventory's Postgres query `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` on inventory-db.shop.svc is stuck waiting for a row lock (db.wait_event=Lock:tuple) for 2.5–3s. The catalog and pricing calls take only 14–21ms.

**Root cause** (medium confidence, `dependency_failure`): Requests are slow because of row-lock contention in the inventory database. In both traces I opened (45d31a48…: 3103ms total, aa889c27…: 2523ms total), the inventory span GET /stock/{sku} takes almost all of the time (3056ms and 2476ms). Inside it, the child span 'SELECT stock' runs `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` against postgresql inventory-db.shop.svc for 3050ms and 2470ms with db.wait_event=Lock:tuple. That means the read-only stock lookup asks for an exclusive row lock and queues behind other transactions holding locks on the same rows. Catalog (14ms) and pricing (21ms) are healthy, and storefront still returns 200. What I couldn't see: which session holds the locks (could be a long-running transaction, a batch job, or just concurrency on popular SKUs) and whether anything recently changed in inventory. There are no inventory logs in Loki (it only has payments and storefront), and I had no Kubernetes or rollout data. So I can't rule out a recent inventory rollout that added the FOR UPDATE.
**Severity:** high  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: TraceQL {resource.service.name="storefront" && duration > 2s} returns many GET /product/{sku} traces of 2.5–3.3s. Each one includes spans from catalog, pricing and inventory (2 inventory spans). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48f074c35561c0353b3bdfe298 (3103ms): inventory GET /stock/{sku} took 3056ms; its child 'SELECT stock' (SELECT qty FROM stock WHERE sku = $1 FOR UPDATE, inventory-db.shop.svc) took 3050ms with db.wait_event=Lock:tuple. Catalog took 14ms, pricing 21ms. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace aa889c27b4277ffe35150f32673a376f (2523ms) shows the same pattern: SELECT ... FOR UPDATE took 2470ms waiting on Lock:tuple, out of 2476ms in inventory /stock/{sku}.
- `grafana_query_loki_patterns`: Storefront logs contain only the pattern 'GET <_> 200 <_> <_>' (346 lines), so requests succeed and are only slow. Loki has no inventory logs (service_name values are only payments and storefront).

**Recommendations**
1. On inventory-db, find the lock holders with pg_stat_activity joined to pg_locks / pg_blocking_pids(): look for long-running or idle-in-transaction sessions on table stock. If a stuck transaction or batch job is holding row locks, terminate it after checking with the inventory owners.
2. Check the inventory deployment's rollout history and any recent batch or cron jobs that write to stock. If a recent change added `FOR UPDATE` to the read path of GET /stock/{sku} or lengthened transactions, roll it back.
3. Change the inventory read path to a plain SELECT, without FOR UPDATE, for stock display. Keep row locks only for reservation and checkout writes, and keep those transactions short.
4. As protection, set a lock_timeout or statement_timeout for the inventory read path. Consider having storefront time out the stock call and show stock as unknown or cached so product pages don't stall.
5. Check through the storefront p99 metric in Prometheus that latency returns below 2s after the fix.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "app"}
5. `grafana_list_loki_label_names` {"datasourceUid": "loki"}
6. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
7. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"storefront\"}"}
8. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{span.db.namespace=\"inventory\" && span.db.wait_event != \"Lock:tuple\"}"}
9. `grafana_list_tempo_attribute_values` {"datasourceUid": "tempo", "name": "resource.service.name"}
10. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "9c44528f8a843750cbbbde89d77624f2"} (error)
11. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "aa889c27b4277ffe35150f32673a376f"}
12. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}], "timeRange": {"from": "now-1h", "to": "now"}}
13. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceId", "query": "45d31a48f074c35561c0353b3bdfe298"}], "timeRange": {"from": "now-1h", "to": "now"}}
