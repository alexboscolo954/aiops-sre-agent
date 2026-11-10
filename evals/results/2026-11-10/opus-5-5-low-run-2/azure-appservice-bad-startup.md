## shop-web (shop-prod-rg) went from all 2xx to almost all 5xx starting in the 15:53Z bucket on 2026-10-18. That is about 2 minutes after oncall@example.com wrote the site's web config at 15:50:56Z. The activity log names the operation but not what changed, so the exact setting still has to be found.

**Root cause** (medium confidence, `bad_config`): A config change most likely broke the app. Two changes came just before the 5xx started. At 15:50:54–15:50:56Z oncall@example.com made a Microsoft.Web/sites/config/write on shop-web/config/web, and that triggered an UpdateWebSite. At 15:54:36Z the same user made a Microsoft.Web/sites/write. Traffic was healthy before: 110 requests and 110 2xx in the 15:48 bucket. From the 15:53 bucket it fell to 3 2xx and 61 5xx out of 64, then 0 2xx and 84 5xx out of 84. The site still reports Running and enabled. It is a Linux app on the Basic SKU, last modified at 15:50:55Z. This points to a bad web config setting, such as the startup command, stack or runtime version, or the health check path, rather than a platform outage. The new values are not in the activity log, so I can't name the exact setting. I also didn't check Resource Health or the app's logs, so a platform-side cause is not ruled out. Confidence is medium.
**Severity:** critical  ·  **Affected:** shop-prod-rg/Microsoft.Web/sites/shop-web

**Evidence**
- `azure_monitor_metrics_query`: Http2xx was 20 and 110 in the buckets before 15:53Z, with no 5xx. Then Http5xx was 61 of 64 requests and 84 of 84 requests.
- `azure_monitor_activitylog_list`: oncall@example.com made a Microsoft.Web/sites/config/write (web config) at 15:50:54–15:50:56Z, followed by UpdateWebSite. The same user made a Microsoft.Web/sites/write at 15:54:36Z and fetched the publishing profile at 15:44:59Z.
- `azure_appservice_webapp_get`: shop-web is Running and enabled, kind app,linux, Basic SKU, lastModifiedTimeUtc 2026-10-18T15:50:55Z.

**Recommendations**
1. Ask oncall@example.com what they changed in the web config at 15:50Z and in the site update at 15:54Z. Compare the current site config with the last known-good one, for example by checking the deployment slot or config history in the portal.
2. Read the App Service log stream or the Docker/container logs for shop-web after 15:51Z. Look for startup or runtime errors.
3. Roll back the config change once someone approves, for example by restoring the previous startup command or runtime settings. Then check that the Http5xx metric goes back to 0.
4. Check Resource Health for shop-web to rule out a platform problem.
5. If the publishing profile fetched at 15:44Z was used for a code deploy, check the deployment history too.

**Tool calls**
1. `azure_monitor_activitylog_list` {"resource-name": "shop-web", "resource-group": "shop-prod-rg", "hours": 24}
2. `azure_appservice_webapp_get` {"app": "shop-web", "resource-group": "shop-prod-rg"}
3. `azure_monitor_metrics_query` {"resource": "shop-web", "resource-group": "shop-prod-rg", "resource-type": "Microsoft.Web/sites", "metric-names": "Http5xx,Requests", "metric-namespace": "Microsoft.Web/sites", "start-time": "2026-10-18T15:00:00Z", "interval": "PT5M", "aggregation": "Total"}
