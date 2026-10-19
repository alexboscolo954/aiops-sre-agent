## shop-web (shop-prod-rg, Basic SKU) is returning mostly 5xx: Http5xx went from 0 to 61 and then 84 per 5-minute bucket starting around 15:53 UTC, while successful responses fell to 3 and then 0. The onset follows a configuration write to the shop-web site and web config by oncall@example.com at 15:50:54-15:50:56 UTC, so that change is the leading suspect. Resource Health still reports the app as Available, so the failure is at the application layer.

**Root cause** (medium confidence, `bad_config`): The site configuration write (Microsoft.Web/sites/config/write on config/web, plus a site Update) at about 15:50:55 UTC by oncall@example.com is the likely trigger. Requests began returning 5xx within about 3-5 minutes of it, and 2xx traffic dropped to near zero in the same window. The activity log shows the operation name only, not the values changed, so the specific bad setting (app settings, startup command, runtime stack, or similar) is unconfirmed. Application logs and the config diff were not available to this investigation.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_appservice_webapp_get`: shop-web is Running and enabled, Basic SKU, centralus, lastModifiedTimeUtc 2026-10-18T15:50:55.88Z.
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write (Update web sites config, config/web) by oncall@example.com, Succeeded at 15:50:56Z; Microsoft.Web/sites/write (Update website) by the same caller at 15:54:36Z. The list was truncated, so earlier or later events may be missing.
- `azure_monitor_metrics_query`: Http5xx per 5-min bucket from 15:43: 0, 0, 61 (15:53), 84 (15:58). Http2xx: 20, 110, 3 (15:53), 0 (15:58). Requests: 20, 110, 64, 84. Errors dominate after the 15:50 config change.
- `azure_resourcehealth_availability-status_get`: shop-web availabilityState Available, 'The Web app is running normally.' Platform health is not the cause, so the failure is likely in the app or its config.

**Recommendations**
1. Compare the current site config and app settings with the last known-good values (for example the previous deployment slot or an exported config). Identify what oncall@example.com changed at about 15:50 UTC.
2. Check the application log stream or Kudu/diagnostic logs for shop-web and the stack-specific startup errors (HTTP 500/503 details) from 15:50 UTC onward.
3. If the cause is confirmed as the 15:50 change, roll back that setting or swap back to the previous slot. This is a state-changing action and needs human approval before it is run.
4. Confirm recovery by watching Http5xx and Http2xx for the next few 5-minute buckets. Also check the activity log for any further changes after 15:54, since the list was truncated.

**Tool calls**
1. `azure_appservice_webapp_get`
2. `azure_monitor_activitylog_list`
3. `azure_resourcehealth_availability-status_get`
4. `azure_monitor_metrics_query`
