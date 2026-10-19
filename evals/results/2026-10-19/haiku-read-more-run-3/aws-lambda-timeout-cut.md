## The checkout Lambda began timing out at 02:48 UTC, about a minute after the deployer changed its timeout from 10s to 1s. Every invocation now hits the 1000 ms limit and reports Status: timeout, so the Errors alarm fires at about 18 errors per minute. Restoring the timeout to 10s is the first step.

**Root cause** (high confidence, `bad_config`): A CloudTrail UpdateFunctionConfiguration event at 2026-10-19T02:48:49Z by user 'deployer' set checkout's timeout to 1 second. The function was created at 02:43:31Z with timeout 10. Logs show every invocation has Duration 1000.00 ms and Status: timeout, while Max Memory Used is only 37 MB of 128 MB, so memory is not the cause. Error counts go from 0 at 02:47 to 3 at 02:48 and about 18 per minute from 02:49 onward, which matches the config change. The same update request also set environment to {}, which may have cleared the function's environment variables; this was not verified.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors is in ALARM: AWS/Lambda Errors, Sum over 60s, FunctionName=checkout, threshold > 0, last datapoint 1.0 at 02:48.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration20150331v2 by user deployer on checkout, request {"timeout": 1, "environment": {}}. Earlier, 02:43:31Z CreateFunction20150331 with timeout 10, memorySize 128, python3.12.
- `aws_query_logs`: /aws/lambda/checkout REPORT lines show Duration: 1000.00 ms, Billed Duration 1000 ms, Memory Size 128 MB, Max Memory Used 37 MB, Status: timeout. Repeated for every request in the sampled window (about 02:58 to 02:59). The result was truncated, so the full error population was not checked.
- `aws_get_metric_data`: AWS/Lambda Errors Sum per 60s for checkout: 0 through 02:47, then 3 at 02:48, then 18, 18, 18, 17, 18, 18, 18, 18, 17 from 02:49 to 02:58.

**Recommendations**
1. Restore the checkout function timeout to at least 10 seconds, the value it was created with. Changing this needs human approval. Confirm the change with the deployer and the team that owns checkout before applying it.
2. Check whether the environment variables were removed by the 02:48:49 update, since the request set environment to {}. If they were, restore them from the previous configuration or from the source of truth.
3. Watch the checkout-errors alarm and the Lambda Errors metric for a few minutes after the fix to confirm the errors stop.
4. Find out why the deployer sent a 1-second timeout, and add a guard (for example a CI or IaC check, or a timeout minimum) so a timeout this low is not applied again.
5. Check downstream checkout callers for failed or retried orders from 02:48 onward, since about 18 invocations per minute failed.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM", "prefix": "checkout", "region": "us-east-1"}
2. `aws_lookup_events` {"minutes": 180, "resource_name": "checkout", "event_name": null, "region": "us-east-1"}
3. `aws_describe_log_groups` {"prefix": "/aws/lambda/checkout", "region": "us-east-1"}
4. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /Task timed out|ERROR|Error/ | sort @timestamp desc | limit 20", "minutes": 180, "region": "us-east-1"}
5. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "stat": "Sum", "period": 60, "minutes": 180, "region": "us-east-1"}
