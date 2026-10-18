## shop-web (App Service, shop-prod-rg) is returning almost only 5xx responses since about 15:53 UTC. The onset lines up with configuration writes by oncall@example.com at 15:50:54 to 15:50:56 and a site Update at 15:54:36. The likely cause is a bad configuration change. Confidence is medium because I could not see the config diff or application logs.

**Root cause** (medium confidence, `bad_config`): A configuration change to shop-web (Microsoft.Web/sites/config/write at 15:50:54-15:50:56 UTC, caller oncall@example.com, followed by an UpdateWebSite and a further site write at 15:54:36) coincided with the start of the 5xx errors. In the 15:53 bucket 61 of 64 requests returned 5xx, and in the 15:58 bucket all 84 did. The app was healthy before that, with 110 requests all returning 2xx in the 15:48 bucket. The specific setting is unknown. Likely candidates are a startup command, runtime or stack setting, app setting, or connection string.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_metrics_query (Http5xx, Http2xx, Requests, PT5M)`: Healthy until about 15:48 UTC: 110 requests, all 2xx. In the 15:53 bucket: 64 requests, 61 5xx, 3 2xx. In the 15:58 bucket: 84 requests, all 5xx. Bucket start times are inferred from the 14:03 series start plus 5-minute steps.
- `azure_monitor_activitylog_list (Error, 6h)`: No Error-level events were returned. The Error filter did not surface a failure, so the activity log shows only successful administrative operations.
- `azure_monitor_activitylog_list (all levels, 6h)`: Microsoft.Web/sites/config/write (Succeeded, caller oncall@example.com) at 15:50:54 and 15:50:56 UTC. UpdateWebSite Started at 15:50:55 and Succeeded at 15:50:56. Microsoft.Web/sites/write (Update website, Succeeded) at 15:54:36. Publishing profile was fetched at 15:44:59.
- `azure_appservice_webapp_get`: shop-web is Running, enabled, Linux (app,linux), Basic SKU, in centralus. Hostname shop-web.azurewebsites.net. lastModifiedTimeUtc is 2026-10-18T15:50:55.88 UTC, which matches the config change.

**Recommendations**
1. Review the shop-web configuration change made around 15:50 UTC by oncall@example.com and the 15:54 update. Compare the current configuration with the previous version, for example by checking app settings, startup command, and runtime stack.
2. If the change is confirmed as the cause, roll back to the previous configuration. This is a changing action and needs human approval before it is run.
3. Pull application logs from App Service (Log stream or Diagnostic logs, HTTP and application logs) for the 15:50 to 16:00 UTC window to get the actual error, such as a startup failure or a missing setting.
4. After the rollback, confirm that Http5xx drops to zero and that Http2xx returns to the normal rate.

**Tool calls**
1. `azure_appservice_webapp_get`
2. `azure_monitor_activitylog_list`
3. `azure_monitor_metrics_query`
4. `azure_monitor_activitylog_list`
