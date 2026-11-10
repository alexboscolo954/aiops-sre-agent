## Since about 15:53Z almost every request to App Service shop-web/shop-prod-rg has failed with a 5xx (61 of 64, then 84 of 84 per 5-minute bucket). That started minutes after oncall@example.com wrote the site's web config at 15:50:54–56Z. Before that write the app returned only 2xx (130 requests).

**Root cause** (medium confidence, `bad_config`): A site config write (Microsoft.Web/sites/config/write on shop-web/config/web, caller oncall@example.com, 15:50:54–15:50:56Z) is the most likely cause. The app was created at 15:44:36–58Z and served 20, then 110 requests with 0 5xx in the 15:43 and 15:48 buckets. Right after the config write and the app restart that came with it (UpdateWebSite at 15:50:55–56Z), the 15:53 bucket shows 61 of 64 requests as 5xx and only 3 as 2xx. The 15:58 bucket shows 84 of 84 as 5xx. Nothing else changed in between apart from a site write at 15:54:36Z, which came after the errors started. The activity log only names operations, not the new values, so which setting broke the app (startup command, stack/runtime version, app settings, etc.) is not confirmed. The same caller did another site write at 15:54:36Z, so they may already be working on it.
**Severity:** critical  ·  **Affected:** shop-prod-rg/AppService/shop-web

**Evidence**
- `azure_monitor_metrics_query`: 5-minute buckets for shop-web: Requests 20, 110, 64, 84; Http2xx 20, 110, 3, 0; Http5xx 0, 0, 61, 84. The errors start in the bucket beginning 15:53Z.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write on shop-web/config/web by oncall@example.com: Started 15:50:54Z, Succeeded 15:50:56Z. UpdateWebSite Started/Succeeded 15:50:55–56Z.
- `azure_monitor_activitylog_list`: CreateWebSite and Microsoft.Web/sites/write by oncall@example.com at 15:44:36–58Z (2xx traffic followed), plus another Microsoft.Web/sites/write by oncall@example.com at 15:54:36Z, after the errors began.
- `azure_appservice_webapp_get`: shop-web: Linux app, Basic SKU, state Running, enabled, lastModifiedTimeUtc 2026-10-18T15:50:55Z, which matches the config write.

**Recommendations**
1. Ask oncall@example.com what they changed in the shop-web web config at 15:50Z (and in the site write at 15:54Z), and compare the current site config with the state before 15:50Z (az webapp config show, az webapp config appsettings list).
2. Revert that config change (for example the startup command, linuxFxVersion/runtime stack or app settings) to the version that served 2xx at 15:43–15:53Z. This needs a human to approve it.
3. Read the app's container/application logs (Log stream, or az webapp log tail) to confirm the startup or runtime error behind the 5xx.
4. Once reverted, check that Http5xx drops back to 0 in Azure Monitor metrics, then let the alert resolve.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20}
3. `read_more` {"result_id": "rd802f4", "fields": ["operationName.value", "eventTimestamp", "caller", "status.value"]}
4. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T15:00:00Z", "end-time": "2026-10-18T17:00:00Z"}
5. `read_more` {"result_id": "rd802f4", "start": 7800}
