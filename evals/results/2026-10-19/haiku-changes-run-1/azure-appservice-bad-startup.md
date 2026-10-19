## shop-web (shop-prod-rg, Basic plan) began returning mostly 5xx at about 15:53 UTC, roughly 3 minutes after oncall@example.com wrote the site config (Microsoft.Web/sites/config/write at 15:50:54 and 15:50:55, with an Update website at 15:50:56). Azure Resource Health reports the app and its plan as Available, so the platform is likely fine and the fault is probably in the app or its configuration. The config change content was not visible in the tool output, so this is a strong correlation, not a confirmed cause.

**Root cause** (medium confidence, `bad_config`): A configuration change to shop-web made at about 15:50 UTC by oncall@example.com, likely an app setting, startup command, or runtime setting, broke the app. Requests were healthy until 15:48 and then shifted to 5xx from 15:53, with almost no 2xx responses. The exact change is unconfirmed because the activity log did not show what was modified and no app logs were available.
**Severity:** critical  ·  **Affected:** shop-prod/AppService/shop-web

**Evidence**
- `azure_monitor_metrics_query (Http5xx, Requests, Http2xx, PT5M)`: Requests were 20 and 110 in the 15:43 and 15:48 buckets, with 2xx at 20 and 110 and no 5xx. In the 15:53 bucket there were 64 requests, 61 5xx and 3 2xx. In the 15:58 bucket there were 84 requests, 84 5xx and 0 2xx. The failure started at 15:53.
- `azure_monitor_activitylog_list (shop-web, 6h)`: Microsoft.Web/sites/config/write by oncall@example.com at 15:50:54 and 15:50:55 (Succeeded), then Update website (UpdateWebSite) at 15:50:55 to 15:50:56. The config changes came about 2-3 minutes before the 5xx spike.
- `azure_resourcehealth_availability-status_get (shop-web)`: availabilityState Available: 'The Web app is running normally.' The App Service plan aiops-plan is also Available. This points to an application or config problem, not a platform outage.
- `azure_monitor_activitylog_list (aiops-plan, Error level)`: No error-level events recorded for the App Service plan in the last 6 hours.
- `azure_appservice_webapp_get (shop-web)`: state Running, enabled true, lastModifiedTimeUtc 2026-10-18T15:50:55Z, sku Basic, hostname shop-web.azurewebsites.net.

**Recommendations**
1. Confirm what changed: review the config diff for shop-web (app settings, connection strings, startup command, runtime stack) from the 15:50 write by oncall@example.com, and check who made it and why.
2. Pull application logs and stderr/HTTP logs for shop-web since 15:50 UTC to find the actual 5xx error, such as startup failure, missing setting, or dependency connection error.
3. If the change is confirmed as the cause and the rollback is low risk, roll back the config change to the previous values. Ask for human approval before making that change.
4. Check the app's dependencies (databases, storage, APIs) for failures starting around 15:50 UTC, since a changed connection string or endpoint is a likely trigger.
5. After recovery, verify the Http5xx and Http2xx metrics return to the pre-15:50 baseline (about 0 5xx), and check that the critical alert clears.

**Tool calls**
1. `azure_appservice_webapp_get`
2. `azure_monitor_metrics_query`
3. `azure_group_resource_list`
4. `azure_monitor_activitylog_list`
5. `azure_monitor_activitylog_list`
6. `azure_resourcehealth_availability-status_get`
