## Lambda function "checkout" started timing out on every invocation at 02:48 UTC, right after a configuration update at 02:48:49 set its timeout to 1 second (the function was created at 02:43 with a 10-second timeout). Errors are counted as timeouts, so the alarm is tripped by the config change, not by a code fault.

**Root cause** (high confidence, `bad_config`): An UpdateFunctionConfiguration call by user "deployer" at 2026-10-19T02:48:49Z set checkout's timeout to 1 second (request: {"timeout": 1}). Before that, the function ran with a 10s timeout (CreateFunction at 02:43:31) and its max Duration was about 1202 ms, so it was already running past 1s on some invocations. After the change, every invocation is reported as "Status: timeout" at Duration 1000.00 ms with only 37 MB of 128 MB used, and the Errors metric went from 0 to 17-18 per minute from 02:48 onward. The timeout of 1s is below the function's normal execution time, so it is the deciding factor. Logs contain only START/END/REPORT lines, so there is no application error message; the failure is a timeout, not a crash.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors is in ALARM: Errors Sum > 0 on AWS/Lambda FunctionName=checkout, 1 datapoint at 02:48 UTC.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration20150331v2 by user 'deployer' on 'checkout', request {"timeout": 1, "environment": {}}. Earlier, 02:43:31Z CreateFunction with timeout 10, memorySize 128.
- `aws_get_metric_data`: Errors Sum per minute: 0 from 02:43 to 02:47, then 3 at 02:48, then 17-18 each minute from 02:49 to 02:58.
- `aws_get_metric_data`: Duration Maximum: about 1202 ms from 02:43 to 02:48, then exactly 1000 ms from 02:49 onward (capped by the new 1s timeout).
- `aws_query_logs`: Recent REPORT lines for /aws/lambda/checkout: 'Duration: 1000.00 ms ... Max Memory Used: 37 MB ... Status: timeout'. No application ERROR or Exception lines in the 180-minute window.

**Recommendations**
1. Restore the checkout function timeout to its previous value (10s, as created at 02:43) or to a value above its p99 duration, e.g. aws lambda update-function-configuration --function-name checkout --timeout 10. Get approval before making this change.
2. Confirm with the 'deployer' who ran the 02:48:49Z change and why the timeout was set to 1s, and add a guard so timeouts below the observed duration are not applied.
3. Check downstream checkout flows for failed or stuck orders from 02:48 onward, and retry any that timed out.
4. After the fix, confirm that Errors returns to 0 and Duration falls below the timeout.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_describe_log_groups` {"prefix": "/aws/lambda/checkout"}
3. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Exception|Task timed out|error/ | sort @timestamp desc | limit 20", "minutes": 180}
4. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "minutes": 180, "period": 60}
5. `aws_lookup_events` {"resource_name": "checkout", "minutes": 360}
6. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Duration", "dimensions": {"FunctionName": "checkout"}, "minutes": 180, "period": 60, "stat": "Maximum"}
7. `TriageReport` {"summary": "Lambda function \"checkout\" started timing out on every invocation at 02:48 UTC, right after a configuration update at 02:48:49 set its timeout to 1 second (the function was created at 02:43 with a 10-second timeout). Errors are counted as timeouts, so the alarm is tripped by the confi
8. `TriageReport` {"summary": "Lambda function \"checkout\" started timing out on every invocation at 02:48 UTC, right after a configuration update at 02:48:49 set its timeout to 1 second (the function was created at 02:43 with a 10-second timeout). Errors are counted as timeouts, so the alarm is tripped by the confi
