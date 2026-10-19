## shop-web (App Service, shop-prod-rg, Basic SKU) started returning 5xx responses at about 15:53 UTC, about 3 minutes after a configuration write (Microsoft.Web/sites/config/write) by oncall@example.com at 15:50:54. The 5xx share of requests in the last two buckets is about 95%, which matches the alert. The app's own state is 'Available' in Resource Health, and the App Service plan is healthy, so the likely cause is the config change, not the platform.

**Root cause** (medium confidence, `bad_config`): A web app configuration update at 15:50 UTC (Update web sites config, two writes, plus a site Update, all by oncall@example.com) was followed within about 3 minutes by a sharp rise in HTTP 5xx while successful 2xx responses dropped to near zero. This points to a bad app setting, startup command, or runtime setting in that change. The logs needed to confirm the exact setting were not available to me, so the specific setting is unconfirmed.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_appservice_webapp_get`: shop-web is Running and enabled, on Basic SKU, host shop-web.azurewebsites.net, lastModifiedTimeUtc 2026-10-18T15:50:55.88Z.
- `azure_monitor_activitylog_list (last 6h)`: Microsoft.Web/sites/config/write (Update web sites config) by oncall@example.com at 15:50:54-15:50:56 and UpdateWebSite succeeded at 15:50:56; a publishing profile was also fetched by the same caller at 15:44:59. Activity log output was truncated, so earlier or later events may be missing.
- `azure_monitor_metrics_query (Http5xx, Requests, PT5M)`: Requests were 0 until 15:43, then 20, 110, 64, 84. Http5xx was 0 until bucket 15:53 (61), then 84 at 15:58. Http2xx fell from 110 at 15:48 to 3 at 15:53 and 0 at 15:58, so nearly all requests now fail.
- `azure_resourcehealth_availability-status_get`: shop-web and aiops-plan both report Available. The platform is not reporting an outage, so the failure looks like the app's own behavior after the change.

**Recommendations**
1. Pull the diff between the pre-15:50 and current site config (app settings, startup command, runtime stack, health check path, and connection strings) and identify the setting changed by oncall@example.com.
2. Read the app's application and HTTP logs (Log stream or Kudu) from 15:50 to now for the first 5xx stack traces or startup errors.
3. If the change is confirmed as the cause and the owner agrees, roll back the configuration to its pre-15:50 state. This is a change action, so it needs human approval before it is run.
4. After rollback, confirm the Http5xx metric drops to zero and Http2xx recovers, and check the alert resolves.
5. Ask oncall@example.com for the change reason and whether a deployment or pipeline is expected to run alongside it.

**Tool calls**
1. `azure_appservice_webapp_get`
2. `azure_group_resource_list`
3. `azure_monitor_activitylog_list`
4. `azure_resourcehealth_availability-status_get`
5. `azure_monitor_metrics_query`
