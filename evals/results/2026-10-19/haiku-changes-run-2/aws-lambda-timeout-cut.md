## The checkout Lambda's Errors alarm fired because a deployer lowered the function timeout from 10s to 1s at 02:48:49Z. Errors went from 0 to about 18 per minute right after, and max Duration pinned at exactly 1000ms, which is consistent with invocations timing out. Lambda logs are empty, so the timeout is inferred from metrics and config rather than confirmed in logs.

**Root cause** (medium confidence, `bad_config`): A config change via UpdateFunctionConfiguration at 02:48:49Z set the checkout Lambda timeout to 1 second (previously 10 seconds, per the CreateFunction call at 02:43:31Z). Checkout invocations that need more than 1s now time out, producing errors. Duration plateaus at 1000ms, matching the new limit. The same call also set environment to an empty map, which could be a second cause if the function relied on environment variables.
**Severity:** critical  ·  **Affected:** checkout/Function/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors is in ALARM: AWS/Lambda Errors Sum for FunctionName=checkout > 0, triggered at 02:48 UTC.
- `aws_get_metric_data (Errors, Sum/60s)`: Errors were 0 from 02:43 to 02:47, then 3 at 02:48, then 17-18 per minute from 02:49 through 02:58 (still ongoing).
- `aws_get_metric_data (Duration, Maximum/60s)`: Max Duration was about 1202ms before 02:48 and was capped at exactly 1000ms from 02:49 onward, matching the new 1s timeout.
- `aws_lookup_events`: 2026-10-19T02:48:49Z UpdateFunctionConfiguration20150331v2 by user deployer on checkout: request sets "timeout": 1 and "environment": {}. The prior CreateFunction at 02:43:31Z had timeout 10 and memorySize 128.
- `aws_describe_log_groups / aws_query_logs`: Log group /aws/lambda/checkout exists but has 0 stored bytes, so no error messages could be read to confirm the timeout cause.

**Recommendations**
1. Confirm the cause: check the function's Timeout in the Lambda console, or check with the deployer whether 1s was intentional.
2. Restore the timeout to 10s (the previous value) with aws lambda update-function-configuration --function-name checkout --timeout 10. This is a config change, so it needs human approval before running.
3. Check whether the environment variables cleared by the 02:48:49Z update (environment: {}) need to be restored, and restore them from the previous config or deployment source if so.
4. Confirm errors fall toward zero in the Errors and Duration metrics after the fix, and that the alarm clears.
5. Find out why the function has no logs (0 stored bytes), and check the log group and IAM role aiops-checkout-role so future errors can be diagnosed from logs.
6. Review the deployer's change process so that timeout or environment changes to critical functions go through review.

**Tool calls**
1. `aws_describe_alarms`
2. `aws_describe_log_groups`
3. `aws_lookup_events`
4. `aws_get_metric_data`
5. `aws_get_metric_data`
