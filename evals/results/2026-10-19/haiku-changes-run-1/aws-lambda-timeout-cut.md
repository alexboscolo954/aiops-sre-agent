## The checkout Lambda is timing out on nearly every invocation. About a minute before the errors began, someone (user deployer) changed its timeout from 10s to 1s. Every logged invocation since then reports Duration 1000 ms with Status: timeout. Restoring the 10s timeout is the likely fix.

**Root cause** (high confidence, `bad_config`): A configuration change at 02:48:49Z (UpdateFunctionConfiguration by deployer) set the checkout function timeout to 1 second, down from the 10 second timeout set at creation. Invocations that need more than 1s are killed, so the Errors metric jumps from 0 to about 18 per minute right after the change.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout/Function/checkout

**Evidence**
- `aws_describe_alarms`: Alarm checkout-errors is in ALARM: AWS/Lambda Errors Sum for FunctionName=checkout, threshold >0, 1 datapoint at 02:48 UTC.
- `aws_get_metric_data (AWS/Lambda Errors, Sum, 60s)`: Errors were 0 from 02:43 to 02:47, then 3 at 02:48 and 17-18 per minute from 02:49 through 02:58, so errors began at the time of the config change.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration20150331v2 on checkout by user deployer, request: timeout 1. The function was created at 02:43:31Z with timeout 10, memorySize 128, python3.12.
- `aws_query_logs (/aws/lambda/checkout)`: REPORT lines show Duration: 1000.00 ms, Status: timeout, Max Memory Used 37 MB of 128 MB. Repeated across the window, so these are timeouts, not out-of-memory or code exceptions. The logs contain no application ERROR lines.

**Recommendations**
1. Confirm with the deployer whether the timeout 1 was intentional. It is most likely a mistake or a bad value.
2. Restore the timeout to 10 seconds (the previous value), either with the AWS console/CLI or by rolling back the deployment that made the change. This needs human approval because it changes a live function.
3. After the change, watch the checkout Errors metric and the REPORT Status lines to confirm the timeouts stop and the alarm clears.
4. Review the change process so timeout and other limits can't be lowered to 1s without a review. Check whether the update also dropped environment variables: the logged request shows environment {}, which may be partial.

**Tool calls**
1. `aws_describe_alarms`
2. `aws_get_metric_data`
3. `aws_lookup_events`
4. `aws_describe_log_groups`
5. `aws_query_logs`
