## shop-web began returning 5xx right after a site config write by oncall@example.com at 15:50 UTC. Almost all traffic fails now, but the platform reports the app and plan as healthy, so this looks like an application-level failure caused by the config change.

**Root cause** (medium confidence, `bad_config`): The Microsoft.Web/sites/config/write (Update web sites config) at 15:50:54-15:50:56Z, followed by an UpdateWebSite at 15:50:55Z, preceded the failures. The 5xx count went from 0 to 61 in the 15:53 bucket and 84 in the 15:58 bucket. Over the same two buckets, 2xx fell from 110 to 3 and then 0. Before the change, traffic was healthy: 20 and 110 requests with zero 5xx. A later site write at 15:54:36Z by the same caller did not fix it. The activity log shows the operation but not the new values, so which setting was changed (for example startup command, runtime stack or app settings) is inferred, not seen. Resource Health shows the app and plan as Available, which rules out a platform or plan outage.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_activitylog_list`: Config write (Microsoft.Web/sites/config/write) and UpdateWebSite on shop-web at 15:50:54-15:50:56Z by oncall@example.com, and another sites/write at 15:54:36Z. This is the only change shortly before the onset.
- `azure_monitor_metrics_query`: 5-minute buckets: Http5xx was 0 up to the 15:48 bucket, then 61 (15:53) and 84 (15:58). Http2xx went 110 -> 3 -> 0 over the same buckets, so nearly all requests fail.
- `azure_resourcehealth_availability-status_get`: shop-web and squero-plan are both Available ('The Web app is running normally'), so this is not a platform outage.
- `azure_appservice_webapp_get`: The app is Running on a Basic SKU, with lastModifiedTimeUtc 2026-10-18T15:50:55Z, which matches the config change.

**Recommendations**
1. Compare the current shop-web site config and app settings with the previous known-good state (startup command, runtime stack, app settings, connection strings). Revert the 15:50 change, or confirm it with oncall@example.com.
2. Check App Service logs (Log stream, Kudu, container logs) for startup or runtime errors after 15:50Z to identify the failing setting.
3. If the cause is not obvious, roll back the config now to restore service, then watch Http5xx and Http2xx until 2xx recovers.
4. Add a config-change gate or slot-based deployment (stage in a slot, then swap) for production App Service changes.

**Tool calls**
1. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
2. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24, "top": 30}
3. `azure_group_resource_list` {"resource-group": "shop-prod-rg"}
4. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-namespace": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "aggregation": "Total", "interval": "PT5M", "start-time": "2026-10-18T15:20:00Z"}
5. `azure_resourcehealth_availability-status_get` {"resourceId": "/subscriptions/00000000-0000-0000-0000-00000000a001/resourceGroups/shop-prod-rg/providers/Microsoft.Web/sites/shop-web"}
6. `read_more` {"result_id": "rb67ac5", "grep": "restart|appsettings|slotsswap|stop", "fields": "operationName.value,eventTimestamp,caller"} (error)
