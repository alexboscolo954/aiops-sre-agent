## The checkout Lambda is failing because its timeout was cut from 10 s to 1 s at 02:48:49Z by an UpdateFunctionConfiguration call from user deployer. Invocations now hit the 1000 ms limit and report Status: timeout, and Errors went from 0 to about 18 per minute right after the change.

**Root cause** (high confidence, `bad_config`): A configuration change at 02:48:49Z (UpdateFunctionConfiguration, user deployer) set checkout's timeout to 1 second. CreateFunction at 02:43:31Z had timeout 10. Every REPORT line since then shows Duration: 1000.00 ms and Status: timeout, while Max Memory Used is only 37 MB of 128 MB, so memory is not the cause. The Errors metric was 0 until 02:47 and rose to 18 per minute from 02:49, which matches the change time. The 1 s limit is too short for normal execution, although the logs don't show a per-request normal duration to prove how long the handler actually needs.
**Severity:** critical  ·  **Affected:** checkout/Function/checkout

**Evidence**
- `aws_describe_alarms`: Alarm checkout-errors is in ALARM: Errors Sum > 0 on FunctionName=checkout, updated at 02:48 (1 datapoint, 1.0).
- `aws_get_metric_data`: AWS/Lambda Errors Sum per 60s: 0 through 02:47, then 3 at 02:48, then 17-18 per minute from 02:49 through 02:58, still firing.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration20150331v2 by deployer on checkout, request sets "timeout": 1. Earlier, 02:43:31Z CreateFunction had "timeout": 10, memorySize 128.
- `aws_query_logs`: /aws/lambda/checkout REPORT lines show Duration: 1000.00 ms, Billed Duration 1000 ms, Memory Size 128 MB, Max Memory Used 37 MB, Status: timeout, repeated for every request from 02:58 to 02:59.
- `aws_describe_log_groups`: Log group /aws/lambda/checkout exists, storedBytes 0 (only the group's name and size were returned; no application error lines were found).

**Recommendations**
1. Restore the checkout Lambda timeout to 10 s (the value set at creation) with UpdateFunctionConfiguration. This needs human approval before it is run.
2. Confirm the errors stop: Errors should drop to 0 and the checkout-errors alarm should return to OK within a few minutes of the change.
3. Ask deployer why the timeout was lowered to 1 s and whether the change went through review. Check whether other settings were changed in the same call, since the logged request only shows timeout and an empty environment.
4. If a lower timeout is actually wanted, measure real p99 duration first and set the timeout above it, not at 1 s.
5. Add a guardrail or alert on Lambda Duration approaching Timeout, and review who can call UpdateFunctionConfiguration on checkout.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM", "prefix": "checkout", "region": null}
2. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "stat": "Sum", "period": 300, "minutes": 120, "region": null}
3. `aws_lookup_events` {"minutes": 180, "resource_name": "checkout", "event_name": null, "region": null}
4. `aws_describe_log_groups` {"prefix": "/aws/lambda/checkout", "region": null}
5. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /Task timed out|ERROR|Timeout/ | sort @timestamp desc | limit 20", "minutes": 120, "region": null}
