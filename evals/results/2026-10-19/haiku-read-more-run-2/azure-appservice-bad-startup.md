## shop-web started returning 5xx at about 15:53 UTC, right after a configuration write to the app (Microsoft.Web/sites/config/write at 15:50:54 to 15:50:56, caller oncall@example.com). By the last bucket, 5xx made up all 84 of 84 requests, and 2xx had dropped to zero. The config values changed are not visible in the activity log, so the exact cause inside the config is not confirmed.

**Root cause** (medium confidence, `bad_config`): A configuration change to the shop-web site was saved at 15:50:54 to 15:50:56 UTC by oncall@example.com. Traffic was healthy before it: the 15:43 and 15:48 buckets had 110 requests with 2xx responses and no 5xx. The 15:53 bucket returned 61 5xx against 3 2xx out of 64 requests, and the 15:58 bucket returned 84 5xx and 0 2xx. A full site update (Microsoft.Web/sites/write) followed at 15:54:36 and did not restore service. The activity log shows operation names and callers only, not the changed values, so the specific bad setting cannot be identified from these tools. The timing strongly points to the config write, but it is an inference, so confidence is medium.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_activitylog_list`: Microsoft.Web/sites/config/write ('Update web sites config', config/web) at 2026-10-18T15:50:54 to 15:50:56Z, status Succeeded, caller oncall@example.com. Then UpdateWebSite Started at 15:50:55 and Succeeded at 15:50:56. Microsoft.Web/sites/write ('Update website') at 15:54:36Z, Succeeded, same caller.
- `azure_monitor_metrics_query`: Http5xx and Requests at PT5M from 14:03Z. Buckets 14:03 to 15:48 show Requests 0 until 15:43, then 20 and 110 requests, all 2xx (Http2xx 20 and 110). The 15:53 bucket shows Requests 64, Http2xx 3, Http5xx 61. The 15:58 bucket shows Requests 84, Http2xx 0, Http5xx 84.
- `azure_appservice_webapp_get`: shop-web is Running and enabled, kind app,linux, Basic SKU, in shop-prod-rg (centralus). lastModifiedTimeUtc is 2026-10-18T15:50:55.88Z, which matches the config write.

**Recommendations**
1. Compare the current shop-web configuration (app settings, connection strings, startup command, runtime stack, and the site's configuration) with the version before 15:50 UTC. The Azure portal's activity log entry 'Update web sites config' at 15:50:54 may show the change details.
2. Check the App Service log stream or Application Insights for the exception or stack trace behind the 5xx responses, starting at about 15:53 UTC, to confirm which setting is failing.
3. Confirm with oncall@example.com whether the 15:50 config change and the 15:54 site update were intended. If the bad setting is confirmed, revert it to the previous values. This is a change and needs human approval before it is made.
4. After the revert, confirm that Http5xx drops and Http2xx returns to the roughly 110 requests per 5 minutes seen before 15:50.

**Tool calls**
1. `azure_group_resource_list`
2. `azure_appservice_webapp_get`
3. `azure_monitor_activitylog_list`
4. `azure_monitor_metrics_query`
5. `read_more`
6. `read_more`
