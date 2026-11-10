## Since about 15:53Z, nearly every request to App Service shop-web returns 5xx (61 of 64, then 84 of 84). This began a few minutes after oncall@example.com changed the site's web config at 15:50:56Z.

**Root cause** (medium confidence, `bad_config`): Most likely cause: the site config change (Microsoft.Web/sites/config/write) made by oncall@example.com at 2026-10-18T15:50:54–15:50:56Z, which restarted the site (UpdateWebSite). The site was fully healthy in the buckets starting 15:43Z and 15:48Z (20/20 and 110/110 2xx). In the next bucket, starting 15:53Z, 61 of 64 requests returned 5xx, and from 15:58Z all 84 did. A site write followed at 15:54:36Z. The activity log names the operation but not the values changed, so I don't know which setting broke it. I also couldn't read app logs, so I'm inferring the cause from timing alone.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write by oncall@example.com, started 15:50:54Z and succeeded 15:50:56Z (UpdateWebSite at the same time), followed by Microsoft.Web/sites/write at 15:54:36Z. A publishing profile was fetched at 15:44:59Z.
- `azure_monitor_metrics_query`: Http5xx is 0 in the buckets starting 15:43Z and 15:48Z (Requests 20 and 110, all 2xx), then 61 of 64 at 15:53Z and 84 of 84 at 15:58Z.
- `azure_appservice_webapp_get`: shop-web is Running on a Linux Basic plan; lastModifiedTimeUtc is 2026-10-18T15:50:55Z, matching the config write.

**Recommendations**
1. Ask oncall@example.com what they changed at 15:50Z and 15:54Z (for example the startup command, runtime stack/linuxFxVersion, app settings or connection strings).
2. Compare the site config with the last known-good version and roll it back if it differs. This is a change, so it needs human approval.
3. Check the App Service log stream and Docker/application logs for startup or runtime errors after 15:51Z to confirm which setting is at fault.
4. Once the rollback is done, confirm the Http5xx metric drops back to 0.

**Tool calls**
1. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24}
2. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
3. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "aggregation": "Total", "start-time": "2026-10-18T15:00:00Z", "end-time": "2026-10-18T17:00:00Z", "interval": "PT5M"}
