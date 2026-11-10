## shop-web (App Service) started returning 5xx right after a site config write at 15:50 UTC. Success rate fell from 100% to 0% within about 10 minutes. The platform reports the app and plan as healthy, so this looks like a bad config change.

**Root cause** (medium confidence, `bad_config`): oncall@example.com wrote the site config (Microsoft.Web/sites/config/write, 15:50:54–15:50:56Z) and then updated the site again at 15:54:36Z. The last two metric buckets show the 5xx onset right after: 61 of 64 requests, then 84 of 84. Before the change, all traffic was 2xx (20 and 110 requests). The app is Running and Available, and the plan is healthy, so this is not a platform or capacity problem. The activity log shows the operation but not the new values, so which setting broke the app (for example startup command, runtime stack or app settings) is inferred. I did not read the app logs.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write by oncall@example.com at 15:50:54–15:50:56Z, then UpdateWebSite at 15:50:55–56Z. A further Microsoft.Web/sites/write by the same caller at 15:54:36Z. These are the last changes before the errors began.
- `azure_monitor_metrics_query`: 5-minute buckets for shop-web: Http2xx 20 then 110 with Http5xx 0. Next bucket: 64 requests, 3 2xx, 61 5xx. Last bucket: 84 requests, 0 2xx, 84 5xx. The onset follows the config write.
- `azure_appservice_webapp_get`: shop-web is state Running, Basic SKU, lastModifiedTimeUtc 2026-10-18T15:50:55Z. The app was modified at the time the errors started.
- `azure_resourcehealth_availability-status_get`: The shop-web site and the squero-plan App Service plan are both Available, with no platform issue. The failure is therefore at the application or config level.

**Recommendations**
1. Find what changed in the 15:50 config write and the 15:54 site update. Compare the current config (startup command, stack/runtime version, app settings, connection strings) with the last known good, and revert the offending setting.
2. If the change can't be identified quickly, roll back to the previous config or redeploy the last known good version. If a staging slot is in use, swap back.
3. Check the App Service logs (Log stream, App Service logs, Kudu) for the startup or runtime errors behind the 5xx.
4. After the fix, confirm that Http5xx returns to 0 and Http2xx recovers.
5. Ask oncall@example.com what they changed. Put production config changes through a slot or a reviewed pipeline.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20}
3. `azure_group_resource_list` {"resource-group": "shop-prod-rg"}
4. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T15:20:00Z"}
5. `azure_resourcehealth_availability-status_get` {"resourceId": "/subscriptions/00000000-0000-0000-0000-00000000a001/resourceGroups/shop-prod-rg/providers/Microsoft.Web/sites/shop-web"}
