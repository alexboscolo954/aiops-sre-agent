## Since about 15:53 UTC almost every request to App Service shop-web (shop-prod-rg) has returned 5xx: 61 of 64 requests, then 84 of 84. Shortly before, at 15:50:55 UTC, oncall@example.com wrote the site config (sites/config/write, which restarted the site), and the app had been serving 2xx without errors until then.

**Root cause** (medium confidence, `bad_config`): A site config write by oncall@example.com (Microsoft.Web/sites/config/write, 15:50:54–15:50:56 UTC) with a matching UpdateWebSite at the same time, followed by a sites/write at 15:54:36, is the only change near the onset. Before it, the app (created 15:44) served 20 and 110 requests per 5-minute bucket with all 2xx and 0 5xx. In the next bucket 61 of 64 requests were 5xx, then 84 of 84, with 2xx at 0. The activity log names the operation but not the new values, so the exact setting that broke it is still unknown. Likely candidates are startup command, stack/runtime version or app settings. I didn't read app or container logs, so this is inferred from timing only and confidence is medium.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_metrics_query`: 5-minute buckets ending at 15:58 UTC: Requests …20,110,64,84; Http2xx …20,110,3,0; Http5xx …0,0,61,84. The 5xx errors start in the bucket right after the config write and are close to 100%.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write by oncall@example.com: Started 15:50:54Z, Succeeded 15:50:56Z, with UpdateWebSite at 15:50:55–56Z. Also a Microsoft.Web/sites/write at 15:54:36Z. The site was created at 15:44:36–58Z.
- `azure_appservice_webapp_get`: shop-web: Linux app, Basic SKU, centralus, state Running, enabled, lastModifiedTimeUtc 2026-10-18T15:50:55Z (the time of the config write).

**Recommendations**
1. Ask oncall@example.com what they changed in the 15:50:55 UTC config write (startup command, linuxFxVersion/runtime, app settings, health check path) and what the 15:54:36 sites/write did.
2. Compare the current site config with the deployment template or source of truth, or with Configuration history if available, to find the setting that changed.
3. Check the app's log stream or Docker/container logs in Kudu/Log stream for startup or runtime errors after 15:50 UTC to confirm the cause.
4. Revert the changed setting to the value it had before 15:50 UTC (this needs human approval; it restarts the site), then confirm Http5xx goes back to 0 and Http2xx comes back in metrics.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20}
3. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T15:00:00Z"}
4. `read_more` {"result_id": "r187d25", "start": 6000, "fields": ["operationName.value", "eventTimestamp", "caller", "status.value"]}
