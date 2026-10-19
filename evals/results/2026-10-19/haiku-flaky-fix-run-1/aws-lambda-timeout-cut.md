## The checkout Lambda's error alarm fired because a deployer changed its timeout from 10s to 1s at 02:48:49Z. Duration had been about 1.2s before the change, so most invocations now time out. Errors went from 0 to about 18 per minute right after the change.

**Root cause** (high confidence, `bad_config`): UpdateFunctionConfiguration at 2026-10-19T02:48:49Z by user deployer set checkout's timeout to 1 second (request: timeout 1). The CreateFunction at 02:43:31Z had timeout 10 and memorySize 128. Before the change, Duration Maximum was about 1202ms with 0 errors. From 02:49 onward, Duration Maximum was capped at exactly 1000ms, which is the timeout, and Errors Sum ran at 17-18 per minute. Invocations that need more than 1s are being killed by the new timeout. The log group /aws/lambda/checkout has 0 stored bytes, so logs could not confirm the timeout message directly.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout/Function/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors is in ALARM: AWS/Lambda Errors Sum for FunctionName=checkout, threshold 0, 1 datapoint of 1.0 at 02:48.
- `aws_get_metric_data (Errors, Sum, 60s)`: Errors were 0 from 02:43 to 02:47, then 3 at 02:48, then 17-18 per minute from 02:49 through 02:58.
- `aws_get_metric_data (Duration, Maximum, 60s)`: Duration max was about 1202ms until 02:48, then exactly 1000.0ms from 02:49 onward, matching the new 1s timeout.
- `aws_lookup_events (resource checkout, 180 min)`: UpdateFunctionConfiguration20150331v2 at 02:48:49Z by deployer with request timeout=1 and environment={}, following CreateFunction at 02:43:31Z by deployer with timeout=10 and memorySize=128. No error on either call.
- `aws_describe_log_groups`: /aws/lambda/checkout exists but storedBytes is 0, so no runtime logs were available to read.

**Recommendations**
1. Restore the checkout function timeout to the previous value of 10s (update-function-configuration --timeout 10). This is low risk and needs human approval before it runs.
2. Confirm the timeout change was intended and find out who or what made it (the deployer identity at 02:48:49Z).
3. Check whether the update also cleared environment variables. The request sent environment={}, so compare the current environment with the one from the 02:43 CreateFunction call, and restore any missing variables.
4. After the revert, confirm Errors returns to 0 and Duration max falls back to about 1.2s. Then add a guard so timeout changes on checkout need review.

**Tool calls**
1. `aws_describe_alarms`
2. `aws_describe_log_groups`
3. `aws_lookup_events`
4. `aws_get_metric_data`
5. `aws_get_metric_data`
6. `aws_lookup_events`
