## shop-web (App Service, shop-prod-rg, Basic SKU) is returning almost only 5xx responses since about 15:53Z. Its configuration was written by oncall@example.com at 15:50:54-15:50:56Z, about 2-3 minutes before the first 5xx bucket, so that config change is the leading suspect. The activity log does not show the new values, so this is inferred rather than confirmed.

**Root cause** (medium confidence, `bad_config`): A Microsoft.Web/sites/config/write (Update web sites config, correlation 1c74213a-b88f-4657-aedd-99dee0d3fe1c) plus a site Update were applied by oncall@example.com at 15:50:54-15:50:56Z. Http5xx went from 0 to 61 in the 15:53Z bucket and to 84 in the 15:58Z bucket, while Http2xx fell from 110 to 3 and then 0. Requests stayed up (64 and 84), so the app is receiving traffic but failing to serve it, which fits a bad app setting, startup command or runtime config. The activity log does not show the changed values, and no app-level logs were available to confirm the failing component.
**Severity:** critical  ·  **Affected:** shop-prod-rg/App Service/shop-web

**Evidence**
- `azure_appservice_webapp_get`: shop-web is Running, enabled, kind app,linux, location centralus, SKU Basic, lastModifiedTimeUtc 2026-10-18T15:50:55Z.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write 'Update web sites config' by oncall@example.com at 2026-10-18T15:50:54.7Z and 15:50:56.3Z (Succeeded); Microsoft.Web/sites/write 'Update website' at 15:50:55Z (Succeeded). Earlier writes by the same caller at 15:44:36-15:44:59Z, including a CreateWebSite event, and a publishxml action at 15:44:59Z. No restart events were listed.
- `azure_monitor_metrics_query`: Http5xx per 5-min bucket from 14:03Z: 0 until 15:53Z (61), then 84 at 15:58Z. Http2xx: 110 at 15:48Z, 3 at 15:53Z, 0 at 15:58Z. Requests: 20 at 15:43Z, 110 at 15:48Z, 64 at 15:53Z, 84 at 15:58Z.

**Recommendations**
1. Review the current app settings, startup command, runtime stack and connection strings for shop-web, and diff them against the values before 15:50Z. The activity log does not show the values, so this needs the portal or 'az webapp config show' and the app's configuration history.
2. Pull the application log stream or Kudu/diagnostic logs for shop-web from 15:50Z onward to identify the failing startup or request error.
3. If the diff points to the 15:50Z change, revert that setting or restore the prior configuration, with human approval, and then confirm that Http5xx falls and Http2xx recovers.
4. Confirm the 15:50Z writes were intended. Both 15:44Z and 15:50Z writes came from oncall@example.com, so check whether the 15:44Z create was a deliberate redeploy.

**Tool calls**
1. `azure_appservice_webapp_get`
2. `azure_monitor_activitylog_list`
3. `read_more`
4. `azure_monitor_metrics_query`
5. `read_more`
