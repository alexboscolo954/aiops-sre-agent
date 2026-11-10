## Since about 15:53Z, shop-web has returned 5xx on nearly every request (2xx went from 110 to 3 to 0 across consecutive 5-minute buckets). This started right after oncall@example.com changed the site's web config at 15:50:56Z.

**Root cause** (medium confidence, `bad_config`): oncall@example.com changed the site's web config (Microsoft.Web/sites/config/write) at 15:50:54–15:50:56Z, and the site was updated at the same time (lastModified 15:50:55Z). In the bucket before the change there were 110 requests, all 2xx, and no 5xx. In the 15:53Z bucket there were 61 5xx out of 64 requests, and in the 15:58Z bucket 84 out of 84. A second site write by the same caller followed at 15:54:36Z. The activity log names the operations but not the values that changed, so which setting broke the app (for example startup command, stack/runtime version or app settings) is still unknown. I did not read the app logs.
**Severity:** critical  ·  **Affected:** shop-prod-rg/AppService/shop-web

**Evidence**
- `azure_monitor_activitylog_list`: oncall@example.com: Microsoft.Web/sites/config/write started 15:50:54Z, succeeded 15:50:56Z; UpdateWebSite at 15:50:56Z; Microsoft.Web/sites/write at 15:54:36Z; publishing profile fetched at 15:44:59Z.
- `azure_monitor_metrics_query`: 5-minute buckets: Requests 20, 110, 64, 84; Http2xx 20, 110, 3, 0; Http5xx 0, 0, 61, 84. The 5xx start in the bucket beginning about 15:53Z.
- `azure_appservice_webapp_get`: shop-web (Linux, Basic SKU) state Running, lastModifiedTimeUtc 2026-10-18T15:50:55Z.

**Recommendations**
1. Ask oncall@example.com what they changed in the site config at 15:50Z and in the site write at 15:54Z.
2. Compare the current site config (startup command, linuxFxVersion, app settings) with the earlier values, then revert the change. Reverting is a config write that restarts the app, so it needs approval.
3. Before or alongside the revert, check the App Service log stream or container logs for the startup error to confirm which setting caused it.
4. After the change, watch Http5xx and Http2xx until the 5xx rate is back to zero.

**Tool calls**
1. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24}
2. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
3. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "metric-names": "Http5xx,Requests", "metric-namespace": "Microsoft.Web/sites", "resource-type": "Microsoft.Web/sites", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T15:00:00Z", "end-time": "2026-10-18T16:30:00Z"}
