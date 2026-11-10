## shop-web (App Service, Basic SKU, shop-prod-rg) is returning mostly 5xx responses. The activity log shows a site config write and site update by oncall@example.com about 15:50 to 15:54 UTC, which is the most likely trigger. The log does not show the changed values, so the exact cause is not confirmed.

**Root cause** (medium confidence, `bad_config`): A configuration change to shop-web was written at 15:50:54 to 15:50:56 UTC (Microsoft.Web/sites/config/write, Update web sites config, status Succeeded), followed by a site update at 15:54:36 UTC by oncall@example.com. In the Http5xx metric, the final two 5-minute buckets show 61 and 84 5xx responses while 2xx dropped to 3 and 0. Requests in those buckets were 64 and 84, so most requests were failing. The earlier buckets were healthy, with 110 2xx responses in one bucket. The activity log does not show which settings changed, and the metric bucket timestamps in the tool output are ambiguous, so the link between the config write and the 5xx onset is inferred from timing, not confirmed.
**Severity:** critical  ·  **Affected:** shop-prod/AppService/shop-web

**Evidence**
- `azure_appservice_webapp_get`: shop-web is Running and enabled, kind app,linux, location centralus, SKU Basic, lastModifiedTimeUtc 2026-10-18T15:50:55.8833333+00:00. Hostname shop-web.azurewebsites.net.
- `azure_monitor_activitylog_list`: Within the last 6 hours, caller oncall@example.com made Microsoft.Web/sites/config/write (web config) at 15:50:54 to 15:50:56 UTC, status Succeeded. A Microsoft.Web/sites/write (Update website) followed at 15:54:36 UTC, status Succeeded. The log does not show the new values.
- `azure_monitor_metrics_query`: Http5xx and Requests, PT5M buckets from 2026-10-18T15:00Z. Requests were 20, 110, 64, 84, and Http2xx was 20, 110, 3, 0. Http5xx was 0 until the last two buckets, which were 61 and 84.

**Recommendations**
1. Check the current app settings and general configuration of shop-web against the values before the 15:50 UTC write, for example with az webapp config show and az webapp config appsettings list. Look for changed connection strings, runtime or startup command, or health check path.
2. Compare the changed values with the application logs (App Service log stream or Application Insights exceptions) to confirm the failure mode.
3. If the 15:50 change is confirmed as the cause and the previous values are known, roll the configuration back to the previous values. This is a change and needs human approval before it is run.
4. Confirm recovery by watching Http5xx and Http2xx for shop-web over the next 15 minutes after any rollback.
5. Check the activity log for any other changes by oncall@example.com in the same window, and check whether this was a deliberate deployment that needs its own fix.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg", "subscription": "null", "tenant": "null"}
2. `azure_monitor_activitylog_list` {"event-level": "null", "hours": 6, "resource-group": "shop-prod-rg", "resource-name": "shop-web", "resource-type": "Microsoft.Web/sites", "subscription": "null", "tenant": "null", "top": 20}
3. `read_more` {"result_id": "r3e463e", "start": 0, "grep": "restart|swap|deploy|stop|start", "fields": ["eventTimestamp", "operationName", "caller", "status"]}
4. `azure_monitor_metrics_query` {"aggregation": "Total", "end-time": "2026-10-18T17:00:00Z", "filter": "null", "interval": "PT5M", "max-buckets": 50, "metric-names": "Http5xx,Requests", "metric-namespace": "Microsoft.Web/sites", "resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "star
5. `read_more` {"result_id": "r3e463e", "start": 0, "grep": "shop-web", "fields": ["eventTimestamp", "operationName", "caller", "status"]}
