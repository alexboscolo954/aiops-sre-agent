## Almost every request to App Service shop-web (shop-prod-rg) has returned 5xx since about 15:53 UTC: 61 of 64 requests in the 15:53 bucket and 84 of 84 in the next. The failures began about 2 minutes after oncall@example.com changed the site config (Microsoft.Web/sites/config/write) at 15:50:54–15:50:56 UTC. Before that change, every request returned 2xx.

**Root cause** (medium confidence, `bad_config`): The most likely cause is the site config change (config/web) that oncall@example.com made at 15:50:54–15:50:56 UTC. It restarted the site (UpdateWebSite at 15:50:55–56; lastModifiedTimeUtc 15:50:55). Before it, requests succeeded: 20/20 in the 15:43 bucket and 110/110 in the 15:48 bucket, with zero 5xx. Right after it, Http2xx fell to 3 then 0 and Http5xx rose to 61/64 then 84/84. This was the only config write before the onset. The other entries are the site's creation (15:44:36–15:44:58), a publishing-profile fetch (15:44:59), and a sites/write at 15:54:36. That last write shares correlationId 34d49e3f with the creation-time write, so it probably belongs to the original create operation rather than being a separate change. Two things argue against a platform problem: Resource Health reports both the web app and the plan (squero-plan) as Available, and the app state is Running and enabled. So the platform seems up while the app's own responses fail. The activity log doesn't record the new config values, so I can't say which setting broke it (for example a startup command, stack/runtime version, or health-check path). That gap is why confidence is medium.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_metrics_query`: In 5-minute buckets: 15:43 had Requests 20 / 2xx 20 / 5xx 0; 15:48 had 110 / 110 / 0; 15:53 had 64 / 3 / 61; 15:58 had 84 / 0 / 84. The 5xx rate jumped from 0% to about 100% right after 15:51.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write on shop-web/config/web by oncall@example.com started at 15:50:54.72Z and succeeded at 15:50:56.27Z, with an UpdateWebSite at 15:50:55–56Z. It is the only config write before the 5xx onset.
- `azure_monitor_activitylog_list`: Earlier entries: CreateWebSite and sites/write at 15:44:36–15:44:58Z, then publishxml at 15:44:59Z. The sites/write at 15:54:36Z has the same correlationId (34d49e3f) as the creation write.
- `azure_appservice_webapp_get`: shop-web is Linux, Basic SKU, state Running, enabled. lastModifiedTimeUtc is 2026-10-18T15:50:55Z, which matches the config write.
- `azure_resourcehealth_availability-status_get`: The web app and the App Service plan squero-plan are both 'Available' / 'running normally' (transient event at 15:51:21Z), so there is no sign of a platform outage.

**Recommendations**
1. Ask oncall@example.com what they changed in site config at 15:50:55 UTC, or compare the current site config with the previous values (startup command, linuxFxVersion/runtime stack, health check path, app settings, connection strings) using the portal or `az webapp config show`.
2. Revert the config change to its pre-15:50 values. That is the lowest-risk fix, since every request succeeded before it. Then watch Http5xx return to 0.
3. Before or alongside the revert, check the app's container/application logs (Log stream or Diagnose and solve problems > Application Logs). The startup or request errors should show which setting broke it.
4. Once service is back, require staged changes (deployment slot plus swap) for config writes to shop-web in prod.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20}
3. `read_more` {"result_id": "r8f409d", "fields": ["operationName.value", "eventTimestamp", "caller", "status.value", "resourceId"]}
4. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Requests,Http5xx", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T14:30:00Z", "end-time": "2026-10-18T17:00:00Z"}
5. `read_more` {"result_id": "r8f409d", "start": 7800}
6. `azure_resourcehealth_availability-status_get` {"resourceId": "/subscriptions/00000000-0000-0000-0000-00000000a001/resourceGroups/shop-prod-rg/providers/Microsoft.Web/sites/shop-web"}
