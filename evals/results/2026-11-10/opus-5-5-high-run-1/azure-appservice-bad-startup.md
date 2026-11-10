## shop-web (App Service, shop-prod-rg) has failed nearly every request with a 5xx since about 15:53 UTC. This began a few minutes after oncall@example.com changed the site's web config at 15:50:55 UTC. Before that change the app served only 2xx responses.

**Root cause** (medium confidence, `bad_config`): The most likely cause is a site config change. oncall@example.com wrote Microsoft.Web/sites/config/write (config/web) at 2026-10-18T15:50:55–56Z, and the platform ran UpdateWebSite at the same time. The app's lastModifiedTimeUtc is 15:50:55.88Z, which matches. Before the change the app served 20 and then 110 requests per 5-minute bucket, all 2xx, with 0 5xx. In the bucket after the change, 61 of 64 requests were 5xx. In the next bucket all 84 of 84 were 5xx. The app still shows state Running and enabled, so the platform has not stopped it; the app itself is answering with errors after the new config took effect. The activity log names the operation but not the values that changed. The specific setting (for example startup command, stack/runtime version, or a connection string or app setting) has not been confirmed. That is why confidence is medium. A second sites/write by the same caller at 15:54:36 came after the errors started, so it may have made things worse but did not start them.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_metrics_query`: shop-web, 5-minute buckets from 14:03Z. Requests: 20, 110, 64, 84. Http2xx: 20, 110, 3, 0. Http5xx: 0, 0, 61, 84. The app went from all 2xx to almost all 5xx starting in the bucket after about 15:53.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write (config/web) by oncall@example.com, started 15:50:54.72Z and succeeded 15:50:56.27Z. UpdateWebSite started 15:50:55Z and succeeded 15:50:56Z. This is the only config write between the site's creation at 15:44:36–15:44:58Z and the 5xx onset.
- `azure_monitor_activitylog_list`: oncall@example.com fetched the publishing profile at 15:44:59Z. The same caller ran another Microsoft.Web/sites/write at 15:54:36Z, after the 5xx had already started.
- `azure_appservice_webapp_get`: shop-web: kind app,linux, SKU Basic, state Running, enabled true, lastModifiedTimeUtc 2026-10-18T15:50:55.88Z, which matches the config write.

**Recommendations**
1. Ask oncall@example.com what was changed in the site config at 15:50:55Z and in the sites/write at 15:54:36Z. Look for changes to the startup command, linuxFxVersion (runtime), app settings or connection strings.
2. Compare the current config with the pre-change state. You can use the Activity Log change history (Change Analysis) for shop-web, or the config snapshots under App Service > Diagnose and solve problems.
3. Read the app's runtime and container logs (Log stream, or docker/application logs in Kudu) for the startup or request exception behind the 5xx.
4. With the owner's approval, roll the config change back to its previous values. App Service restarts the site when config is saved. Then check that Http5xx falls back to 0 and Http2xx recovers.
5. If the change has to stay, fix the setting it got wrong. In future, test config changes in a deployment slot and swap the slot into production.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20}
3. `read_more` {"result_id": "rba2334", "fields": ["operationName.value", "eventTimestamp", "caller", "status.value"]}
4. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "aggregation": "Total", "start-time": "2026-10-18T15:00:00Z", "interval": "PT5M"}
5. `read_more` {"result_id": "rba2334", "start": 7800}
