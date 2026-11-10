## Storefront's GET /product/{sku} is slow (sampled traces take 2.5 to 3.3s) because its call to inventory GET /stock/{sku} is slow. Almost all of that time is the inventory query `SELECT qty FROM stock WHERE sku = $1 FOR UPDATE` against inventory-db, which is waiting on a Postgres row lock (wait event Lock:tuple).

**Root cause** (medium confidence, `dependency_failure`): In trace 45d31a48f074c35561c0353b3bdfe298, the root span took 3103ms. catalog (14ms) and pricing (21ms) were fast. inventory GET /stock/{sku} took 3056ms, and 3050ms of that was the child DB span 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' on postgresql inventory-db.shop.svc, with db.wait_event=Lock:tuple. So the time is lock waiting, not query work. A read path takes an exclusive row lock (FOR UPDATE), so it queues behind other transactions that hold locks on the same stock rows. I couldn't see which session or transaction holds the locks, or what changed: Loki has no inventory or DB logs (service_name values: payments, storefront only). I didn't check Prometheus metrics or rollout history.
**Severity:** medium  ·  **Affected:** shop/Deployment/storefront, shop/Deployment/inventory, shop/StatefulSet/inventory-db

**Evidence**
- `grafana_search_tempo_traces`: Many storefront 'GET /product/{sku}' traces over 2s (2483ms to 3284ms) in the last hour, each touching catalog, pricing and inventory (2 inventory spans). (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22tempo%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22tempo%22%7D%2C%22query%22%3A%22%7Bresource.service.name%3D%5C%22storefront%5C%22+%5Cu0026%5Cu0026+duration+%5Cu003e+2s%7D%22%2C%22queryType%22%3A%22traceql%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_get_tempo_trace`: Trace 45d31a48: root 3103ms; catalog 14ms, pricing 21ms; inventory GET /stock/{sku} 3056ms, of which 3050ms is 'SELECT qty FROM stock WHERE sku = $1 FOR UPDATE' on inventory-db.shop.svc with db.wait_event=Lock:tuple.
- `grafana_query_loki_patterns`: Only pattern for {service_name="inventory"} is 'GET <_> 200 <_> <_>' (346); there are no errors or lock messages in logs.
- `grafana_list_loki_label_values`: Loki service_name values are only payments and storefront, so there are no inventory-db logs to identify the lock holder.

**Recommendations**
1. On inventory-db, query pg_stat_activity and pg_locks (for example, pg_blocking_pids()) to find the session or transaction holding locks on the stock rows. Look for long-running or idle-in-transaction sessions.
2. If one stuck or idle-in-transaction session is the blocker, terminate it with pg_terminate_backend after the owning team approves.
3. Check recent rollouts or batch jobs for inventory and other writers to the stock table (for example, a bulk stock update) that started around when latency rose.
4. Change the inventory read path for GET /stock/{sku} to a plain SELECT without FOR UPDATE, or add lock_timeout / SKIP LOCKED, so reads don't queue behind writers.
5. Set idle_in_transaction_session_timeout on inventory-db and add DB lock-wait metrics and logs to Loki and Prometheus.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_search_tempo_traces` {"datasourceUid": "tempo", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}
3. `grafana_get_tempo_trace` {"datasourceUid": "tempo", "trace_id": "45d31a48f074c35561c0353b3bdfe298"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"inventory\"}"}
5. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "45d31a48f074c35561c0353b3bdfe298"}], "timeRange": {"from": "now-1h", "to": "now"}}
7. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "tempo", "queries": [{"refId": "A", "queryType": "traceql", "query": "{resource.service.name=\"storefront\" && duration > 2s}"}], "timeRange": {"from": "now-1h", "to": "now"}}
