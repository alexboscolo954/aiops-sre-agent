## shop-web (App Service, Basic SKU, shop-prod-rg) began returning 5xx at about 15:53Z, roughly 2 to 3 minutes after oncall@example.com wrote the site config (Microsoft.Web/sites/config/write at 15:50:54 to 15:50:56Z). By the last bucket, nearly all requests were 5xx (84 of 84), so the alert is real and the timing points to that config change. The logs don't show what changed, so the cause is not confirmed.

**Root cause** (medium confidence, `bad_config`): A site configuration change at about 15:50Z (app settings, startup command, or runtime setting) by oncall@example.com broke the app, and every request now fails with 5xx. The activity log shows the operation but not the new values, and no app or container logs were available to confirm the exact fault.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_appservice_webapp_get`: shop-web is Running and enabled, Basic SKU, centralus, hostname shop-web.azurewebsites.net, lastModifiedTimeUtc 2026-10-18T15:50:55Z.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write (Update web sites config) by oncall@example.com at 15:50:54 to 15:50:56Z, Succeeded, followed by a sites/write (Update website) at 15:50:55 to 15:50:56Z. Earlier publishxml action at 15:44:59Z. The result was truncated, so the changed values are not visible.
- `azure_monitor_metrics_query`: Requests and Http2xx were flat until 15:53Z. Http5xx went 0 to 61 in the 15:53 bucket and 84 in the 15:58 bucket, while Http2xx dropped to 3 and then 0. Requests were 20 and 110 earlier, and 64 and 84 after the change.

**Recommendations**
1. Review the most recent config change on shop-web (oncall@example.com, about 15:50Z) in the portal or with az webapp config show and az webapp config appsettings list, then compare it with the previous values. Look for changed app settings, startup command, runtime stack, or connection strings.
2. Check the app's Log stream or Kudu/diagnostic logs for the 15:53Z errors to confirm the failure (for example, a missing setting or a startup crash).
3. If the change is confirmed as the cause and it is low risk, revert it to the previous configuration. Revert needs human approval before it runs.
4. After the fix, confirm Http5xx returns to zero and check that the 5xx alert clears.

**Tool calls**
1. `azure_appservice_webapp_get`
2. `azure_monitor_activitylog_list`
3. `azure_monitor_metrics_query`
