## shop-web is returning 5xx on nearly all requests. The errors began right after a site config change made by oncall@example.com at about 15:50 UTC on 2026-10-18. The new config values are not visible with the tools I had, so the exact bad setting is not confirmed.

**Root cause** (medium confidence, `bad_config`): A write to the site config (Microsoft.Web/sites/config/write) at 15:50:54–15:50:56Z, followed by a site update and another Microsoft.Web/sites/write at 15:54:36Z, all by oncall@example.com. Traffic was healthy before this: 20 and then 110 requests, all 2xx. In the 5-minute bucket starting about 15:53, 61 requests returned 5xx and 3 returned 2xx. In the next bucket, 84 of 84 returned 5xx and none returned 2xx. The likely culprit is a bad setting such as the startup command, runtime stack or app settings. The activity log shows the operation but not the values, and I did not read app logs. The change is inferred from timing, not seen directly.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_activitylog_list`: Config write on shop-web/config/web at 15:50:54–15:50:56Z and an UpdateWebSite event at 15:50:55Z, then a Microsoft.Web/sites/write at 15:54:36Z. All were by oncall@example.com and all succeeded. A publishing profile fetch at 15:44:59Z came before them.
- `azure_monitor_metrics_query`: Http5xx was 0 until the bucket starting about 15:53, then 61 and then 84. Http2xx dropped from 110 to 3 and then 0 while Requests stayed at 64–84 per bucket. This means nearly 100% 5xx right after the config change.
- `azure_appservice_webapp_get`: shop-web is state Running (Linux, Basic SKU) with lastModifiedTimeUtc 2026-10-18T15:50:55Z. The app is up but failing requests, which matches a config problem and not a stopped site.
- `azure_group_resource_list`: The resource group holds only the shop-web site and the squero-plan App Service plan, so there is no other dependency in the group to blame.

**Recommendations**
1. Confirm with oncall@example.com what was changed in the 15:50 config write and the 15:54 site update, such as the startup command, runtime stack, app settings or connection strings.
2. Roll back that change. Restore the previous site config and app settings, or redeploy the last known good slot or config. Then check that the 5xx rate drops.
3. Check the App Service log stream, container logs and Kudu for startup or runtime errors to confirm the exact failing setting.
4. In future, apply config changes through a staging slot with a swap, and alert on 5xx right after config writes.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20}
3. `azure_group_resource_list` {"resource-group": "shop-prod-rg"}
4. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "metric-names": "Http5xx,Requests", "metric-namespace": "Microsoft.Web/sites", "resource-type": "Microsoft.Web/sites", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T15:20:00Z"}
5. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20, "event-level": "Error"}
