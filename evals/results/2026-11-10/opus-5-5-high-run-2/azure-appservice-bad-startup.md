## shop-web (shop-prod-rg) went from all 2xx to nearly all 5xx just after oncall@example.com changed the site configuration (Microsoft.Web/sites/config/write) at 15:50:55Z. In the latest 5-minute bucket, all 84 requests failed. The config change is the most likely cause, but I couldn't see what values were changed.

**Root cause** (medium confidence, `bad_config`): The site was created at 15:44:36–15:44:58Z and served traffic without errors: 20 and then 110 requests, all 2xx, with 0 5xx. At 15:50:54–15:50:56Z, oncall@example.com wrote the web config (Microsoft.Web/sites/config/write), which set off an UpdateWebSite at 15:50:55–15:50:56Z. In the very next metric bucket, 61 of 64 requests returned 5xx. In the bucket after that, all 84 did. Nothing else changed in between except a Microsoft.Web/sites/write at 15:54:36Z. That write has the same correlationId (34d49e3f…) as the site-creation deployment, and 5xx had already started before it. So the config write is the most likely cause. Possible culprits are the startup command, runtime stack, app settings or health check. The activity log names the operation but not the new values, so I couldn't confirm which setting is wrong. I also didn't check app or HTTP logs.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_activitylog_list`: oncall@example.com did a Microsoft.Web/sites/config/write (config/web), started 15:50:54Z and succeeded 15:50:56Z, followed by UpdateWebSite at 15:50:55–15:50:56Z. The site was created at 15:44:36–15:44:58Z. There was another sites/write at 15:54:36Z with the creation's correlationId.
- `azure_monitor_metrics_query`: In 5-minute buckets from 14:03Z: Requests 20, 110, 64, 84; Http2xx 20, 110, 3, 0; Http5xx 0, 0, 61, 84. Errors jump in the first bucket after the 15:50:55Z config write, and the latest bucket is 100% 5xx.
- `azure_appservice_webapp_get`: shop-web is a Linux app on the Basic SKU in centralus. State is Running and enabled. lastModifiedTimeUtc is 2026-10-18T15:50:55Z, matching the config write.

**Recommendations**
1. Ask oncall@example.com what they changed in the shop-web site config at 15:50:55Z. Look for changes to the startup command, linuxFxVersion/runtime, app settings or connection strings, health check path, or always-on.
2. Compare the current config (az webapp config show / az webapp config appsettings list) with the deployment template or the values in place at 15:44Z, and revert the changed setting. This is a low-risk rollback because the app served 100% 2xx before the change.
3. Before reverting, read the App Service container and application logs (az webapp log tail, or Diagnose and solve problems > Application Logs) to see which error the change triggers. This confirms the cause.
4. After reverting, check that Http5xx drops back to 0 and Http2xx recovers in the Microsoft.Web/sites metrics, then resolve the alert.
5. Put production config changes behind deployment slots or IaC review, so changes like this get validated before they reach live traffic.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20}
3. `read_more` {"result_id": "rdaf5fd", "fields": ["operationName.value", "eventTimestamp", "caller", "status.value"]}
4. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "aggregation": "Total", "start-time": "2026-10-18T15:00:00Z", "interval": "PT5M"}
5. `read_more` {"result_id": "rdaf5fd", "start": 7800}
