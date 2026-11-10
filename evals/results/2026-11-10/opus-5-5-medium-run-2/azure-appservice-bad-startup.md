## shop-web (shop-prod-rg) went from serving only 2xx to almost only 5xx: 61 of 64 requests failed in the 15:53 bucket and 84 of 84 in the 15:58 bucket. The failures began a few minutes after oncall@example.com changed the site config (Microsoft.Web/sites/config/write) at 15:50:56Z, which is the most likely trigger.

**Root cause** (medium confidence, `bad_config`): Most likely a bad site config change. oncall@example.com wrote Microsoft.Web/sites/config/write (config/web) at 2026-10-18T15:50:54–15:50:56Z, and this caused an UpdateWebSite at 15:50:55–56Z. Before the change, every request succeeded (bucket 14:03+100min: 20/20 2xx; next bucket: 110/110 2xx). In the bucket after it, 61 of 64 requests were 5xx, then 84 of 84. Nothing else changed the site in that window. The two Microsoft.Web/sites/write entries at 15:44 belong to the site's creation, and the one at 15:54:36 came after the 5xx had started. The activity log names the operation but not the new values, so I can't say which setting is wrong (for example startup command, runtime stack or app settings). That is why confidence is medium.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_metrics_query`: Requests/Http2xx/Http5xx in 5-minute buckets: 20 and 110 requests all 2xx before about 15:53Z, then 64 requests (3 2xx, 61 5xx) and 84 requests (0 2xx, 84 5xx).
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write on shop-web/config/web by oncall@example.com, Started 15:50:54Z and Succeeded 15:50:56Z, plus an UpdateWebSite at 15:50:55–56Z. This is the only config change shortly before the 5xx began.
- `azure_monitor_activitylog_list`: Earlier activity: CreateWebSite and sites/write at 15:44:36–15:44:58Z and publishing profile fetches at 15:44:59Z. Traffic after these succeeded, so they are not the trigger. One more sites/write at 15:54:36Z, after the onset.
- `azure_appservice_webapp_get`: shop-web is Linux, Basic SKU, state Running, enabled; lastModifiedTimeUtc 2026-10-18T15:50:55Z, which matches the config write.

**Recommendations**
1. Ask oncall@example.com which settings changed at 15:50:56Z (startup command, linuxFxVersion/runtime stack, app settings, health check path). The diff can also be checked in the portal or with `az webapp config show` / `az webapp config appsettings list`.
2. Read the container and application logs (Log stream / docker logs) for shop-web since 15:50Z to confirm the startup or runtime error behind the 5xx.
3. Revert the config/web change to its pre-15:50Z values (with approval). Then confirm that Http5xx drops and Http2xx comes back in Azure Monitor metrics.
4. Find out what the 15:54:36Z sites/write was meant to do. If it was a failed fix attempt, include it in the revert.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 20}
3. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T15:00:00Z", "end-time": "2026-10-18T17:00:00Z"}
4. `read_more` {"result_id": "r284006", "start": 7000}
