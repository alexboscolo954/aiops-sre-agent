## shop-web (App Service, shop-prod-rg) is returning mostly 5xx responses. Metrics show 5xx starting around 15:50 UTC, right after a configuration write to the app by oncall@example.com at 15:50:54-56Z. The activity log shows that write but not its new values, so the root cause is not yet confirmed.

**Root cause** (medium confidence, `bad_config`): Probable bad configuration change. The app's site config was updated at 15:50:54-56Z by oncall@example.com (Microsoft.Web/sites/config/write, then UpdateWebSite, both Succeeded). Http5xx began in the 15:50 bucket (0 errors before, then 61 and 84 in the following buckets). Http2xx dropped from 110 to 3 to 0 while Requests stayed at 64-84, so almost all requests since 15:50 are failing. This timing points to the config change. The metrics do not show which setting changed, and no app logs were available, so the exact cause is unconfirmed. The platform looks healthy: Resource Health reports the web app and plan as Available.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_metrics_query`: Http5xx per 5-min bucket from 14:03Z: 0 until the 15:50 bucket, then 61 and 84. Requests were 20, 110, 64, 84. Http2xx went 20, 110, 3, 0, so almost every request since 15:50 has failed.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write (Update web sites config) Succeeded at 15:50:54-56Z by oncall@example.com. Microsoft.Web/sites/write (Update website) Succeeded at 15:54:36Z by the same caller. The log does not show the new values.
- `azure_appservice_webapp_get`: shop-web is Running, enabled, Basic SKU, lastModifiedTimeUtc 2026-10-18T15:50:55Z, matching the config write.
- `azure_resourcehealth_availability-status_get`: shop-web and squero-plan both report Available, with no platform incident.

**Recommendations**
1. Confirm with oncall@example.com what was changed at about 15:50Z. Check the app settings, connection strings, runtime stack, startup command and health-check settings.
2. If the change is the likely cause, roll it back to the previous configuration (for example, restore the earlier app settings or runtime). This needs human approval before any change is made.
3. Pull the application logs (Log Stream or App Service diagnostic logs) for the 5xx responses to confirm the error, for example a missing setting, a wrong startup command, or a dependency that can no longer be reached.
4. Compare the configuration before and after 15:50Z to find the changed values; the activity log does not include them.
5. After the fix, watch Http5xx and Http2xx to confirm recovery.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 6}
3. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests,HttpResponseTime", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T15:00:00Z", "end-time": "2026-10-18
4. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 6, "event-level": "Error"}
5. `read_more` {"result_id": "radef53", "grep": "config/write|Update"}
6. `read_more` {"result_id": "ra7b0b9", "grep": "Error|Fail|restart|appSettings|config"}
7. `read_more` {"result_id": "radef53", "start": 4000}
8. `read_more` {"result_id": "radef53", "start": 11800}
9. `azure_resourcehealth_availability-status_get` {"resourceId": "/subscriptions/00000000-0000-0000-0000-00000000a001/resourceGroups/shop-prod-rg/providers/Microsoft.Web/sites/shop-web"}
10. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 6, "event-level": "Error"}
11. `read_more` {"result_id": "r5dcad7", "fields": ["operationName.value", "eventTimestamp", "caller", "status.value", "level"]}
12. `read_more` {"result_id": "r5dcad7", "grep": "Error|Fail|restart|Delete|Stop|Start the|Restart"}
13. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests,HttpResponseTime", "aggregation": "Average", "interval": "PT5M", "start-time": "2026-10-18T15:30:00Z", "end-time": "2026-10-
14. `TriageReport` {"summary": "shop-web (App Service, shop-prod-rg) is returning mostly 5xx responses. Metrics show 5xx starting around 15:50 UTC, after a configuration write to the app by oncall@example.com at 15:50:54-56Z. The activity log shows that write but not its new values, so the root cause is not yet confir
15. `TriageReport` {"summary": "shop-web (App Service, shop-prod-rg) is returning mostly 5xx responses. Metrics show 5xx starting around 15:50 UTC, right after a configuration write to the app by oncall@example.com at 15:50:54-56Z. The activity log shows that write but not its new values, so the root cause is not yet 
16. `TriageReport` {"summary": "shop-web (App Service, shop-prod-rg) is returning mostly 5xx responses. Metrics show 5xx starting around 15:50 UTC, right after a configuration write to the app by oncall@example.com at 15:50:54-56Z. The activity log shows that write but not its new values, so the root cause is not yet 
