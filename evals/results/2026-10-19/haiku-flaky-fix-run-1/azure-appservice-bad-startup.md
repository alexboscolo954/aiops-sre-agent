## shop-web (shop-prod-rg, Basic plan) went from almost all 2xx to almost all 5xx starting around 15:53 UTC on 2026-10-18. About 2 to 3 minutes earlier, oncall@example.com wrote the web app's site config (Microsoft.Web/sites/config/write at 15:50:55 and 15:50:56), so the config change is the leading suspect. The platform health check reports the app as Available, so the 5xx errors come from the app's responses, not an outage of the platform.

**Root cause** (medium confidence, `bad_config`): A site configuration write by oncall@example.com at 15:50:55 to 15:50:56 UTC precedes the 5xx onset. Metrics show 2xx falling from 110 in the 15:48 to 15:53 bucket to 3 in the 15:53 to 15:58 bucket, and 0 in the last bucket, while Http5xx rose to 61 and then 84 with total requests staying at 64 and 84. The app's startup or request handling is failing after that change. The activity log shows only that a config write happened, not which settings changed, and the app's own logs were not available to this investigation, so the specific faulty setting (for example an app setting, startup command, or connection string) is not confirmed.
**Severity:** critical  ·  **Affected:** shop-prod-rg/App Service/shop-web

**Evidence**
- `azure_appservice_webapp_get`: shop-web is Running and enabled, Linux, centralus, Basic SKU, host shop-web.azurewebsites.net, lastModifiedTimeUtc 2026-10-18T15:50:55Z.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write (Update web sites config, Succeeded) by oncall@example.com at 15:50:56Z, with a Started entry at 15:50:54Z; site write (Update website) at 15:54:36Z by the same caller. The list was truncated, so later entries were not seen.
- `azure_monitor_metrics_query`: Http5xx is zero until the 15:48 to 15:53 bucket, then 61 in the 15:53 to 15:58 bucket and 84 in the last bucket. Http2xx goes 110, then 3, then 0 over the same buckets, while Requests stays at 64 and 84 (the requests are still arriving, but they are failing).
- `azure_resourcehealth_availability-status_get`: The Web app is Available ("The Web app is running normally", causeType Transient, occurred 15:51:21Z). The App Service plan is also Available, so the platform is not reporting an outage.

**Recommendations**
1. Compare the current site config (app settings, connection strings, startup command, runtime stack) against the previous version and find the setting written by oncall@example.com at 15:50 UTC. Pull the full activity log for the window (the list above was truncated) and the change details if they are available.
2. Pull the App Service HTTP and application logs for shop-web since 15:50 UTC to see the actual error (for example a startup failure, missing setting, or failed dependency connection).
3. If the config change is confirmed as the cause and the fix is clear, revert that setting, or roll back the config to its pre-15:50 state. This needs human approval before it is applied.
4. Once the 5xx count drops, confirm recovery on the Http5xx and Http2xx metrics, and record the change as the incident cause.

**Tool calls**
1. `azure_appservice_webapp_get`
2. `azure_monitor_activitylog_list`
3. `azure_monitor_metrics_query`
4. `azure_resourcehealth_availability-status_get`
