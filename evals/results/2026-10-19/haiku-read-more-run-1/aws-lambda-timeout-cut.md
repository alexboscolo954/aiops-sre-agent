## The checkout Lambda's error alarm fired because a configuration update at 02:48:49Z cut its timeout from 10s to 1s. Its Max Duration has been pinned at exactly 1000ms since, while it previously ran at about 1200ms, so invocations are most likely timing out, with about 18 errors per minute since 02:49.

**Root cause** (high confidence, `bad_config`): CloudTrail shows UpdateFunctionConfiguration20150331v2 by user deployer at 2026-10-19T02:48:49Z on checkout with "timeout": 1. The function was created at 02:43:31Z with timeout 10. Duration Maximum was about 1202ms for every minute from 02:43 to 02:48, then flat at 1000ms from 02:49 onward, which is the new 1s limit. Errors were 0 before 02:48 and 17-18 per minute from 02:49 to 02:58. Errors and the timeout change start in the same minute. The same update also sent "environment": {}, which may have cleared environment variables, but that is not confirmed. Lambda logs are empty (storedBytes 0), so the error type is not directly confirmed.
**Severity:** critical  ·  **Affected:** lambda/aws/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors is in ALARM: AWS/Lambda Errors Sum for FunctionName=checkout, threshold >0, 1 datapoint of 1.0 at 02:48 UTC.
- `aws_lookup_events`: UpdateFunctionConfiguration20150331v2 by deployer at 2026-10-19T02:48:49Z on checkout, request timeout=1 and environment={}. Earlier CreateFunction at 02:43:31Z had timeout=10, memorySize=128, python3.12.
- `aws_get_metric_data`: AWS/Lambda Errors Sum per 60s for checkout: 0 from 02:43 to 02:47, 3 at 02:48, then 17-18 per minute from 02:49 to 02:58.
- `aws_get_metric_data`: AWS/Lambda Duration Maximum per 60s for checkout: about 1202ms from 02:43 to 02:48, then exactly 1000.0ms from 02:49 to 02:58, matching the new 1s timeout.
- `aws_describe_log_groups`: /aws/lambda/checkout exists but storedBytes is 0, so no invocation logs were available to read the exact error.

**Recommendations**
1. Confirm the cause by checking the latest checkout error from the function's logs or X-Ray traces. Logs are empty here, so use another logging source if one exists. Expect 'Task timed out after 1.00 seconds'.
2. Roll back the timeout to 10s, the value before the change at 02:48:49Z. This needs human approval because it is a configuration change. Run aws lambda update-function-configuration --function-name checkout --timeout 10.
3. Check whether the environment was wiped by the same update. The request sent environment={}. If so, restore the previous environment variables, and confirm the checkout role and dependencies still work.
4. Ask the deployer who made the 02:48:49Z change why the timeout was set to 1s, and add a guard in the deploy pipeline for timeout values below the observed p99 duration (about 1.2s).
5. After the rollback, confirm Errors returns to 0 and the alarm clears.

**Tool calls**
1. `aws_describe_alarms`
2. `aws_describe_log_groups`
3. `aws_lookup_events`
4. `aws_get_metric_data`
5. `aws_get_metric_data`
