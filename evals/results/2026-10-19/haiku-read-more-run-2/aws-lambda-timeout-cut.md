## The checkout Lambda is timing out on nearly every invocation because its timeout was cut to 1 second at 02:48:49Z, about a minute before the errors started. Its previous value was 10 seconds, and the function runs at about 1000 ms each time, so the fix is to restore the timeout.

**Root cause** (high confidence, `bad_config`): A CloudTrail UpdateFunctionConfiguration event by user 'deployer' at 02:48:49Z set checkout's timeout to 1 second (request: {"functionName": "checkout", "timeout": 1, "environment": {}}). The function was created at 02:43:31Z with timeout 10. Every invocation after the change reports Duration 1000.00 ms with Status: timeout, and Max Memory Used is only 37 MB of 128 MB, so memory is not the cause. Errors went from 0 before 02:48 to 17-18 per minute from 02:49 onward, which matches the timing of the config change.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout/function

**Evidence**
- `aws_describe_alarms`: Alarm checkout-errors is in ALARM: 1 datapoint of 1.0 at 02:48 was greater than threshold 0.0 (AWS/Lambda Errors, FunctionName=checkout).
- `aws_get_metric_data`: AWS/Lambda Errors Sum per 60s: 0 from 02:43 to 02:47, then 3 at 02:48, then 17-18 per minute from 02:49 through 02:58.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration20150331v2 by user 'deployer' on checkout with request timeout: 1. Earlier, at 02:43:31Z, CreateFunction20150331 by 'deployer' had timeout: 10, memorySize: 128, python3.12.
- `aws_query_logs`: /aws/lambda/checkout logs show repeated REPORT lines with Duration: 1000.00 ms, Billed Duration 1000 ms, Memory Size 128 MB, Max Memory Used 37 MB, Status: timeout (for example at 02:59:37 and 02:58:57). The logs contain no ERROR lines, so the failures are timeouts, not application exceptions.

**Recommendations**
1. Restore the checkout Lambda timeout to its previous value of 10 seconds (or whatever the intended value is). This needs human approval because it is a configuration change: aws lambda update-function-configuration --function-name checkout --timeout 10.
2. Confirm the 1-second timeout was an accident by checking with whoever ran the 'deployer' change at 02:48:49Z. Also check whether the environment was intentionally cleared in the same request (environment: {}).
3. After the fix, watch the checkout-errors alarm and the Errors and Duration metrics until they return to zero, and confirm the logs show Status: success.
4. Add a guard, such as a CloudWatch alarm on Lambda timeouts or a change review for timeout values below the function's normal duration, so a timeout this low cannot be applied without review.

**Tool calls**
1. `aws_describe_alarms`
2. `aws_get_metric_data`
3. `aws_lookup_events`
4. `aws_describe_log_groups`
5. `aws_query_logs`
