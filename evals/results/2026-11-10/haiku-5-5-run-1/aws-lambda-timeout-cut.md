## The checkout Lambda began timing out at 02:48 UTC on 2026-10-19, right after a configuration change by user "deployer" set its timeout to 1 second. Every invocation since then hits the 1000 ms limit (Status: timeout), producing about 18 errors per minute. This is a self-inflicted config regression, not a code fault.

**Root cause** (high confidence, `bad_config`): At 02:48:49Z, CloudTrail shows UpdateFunctionConfiguration20150331v2 on "checkout" by user "deployer" with request timeout: 1. The function was created at 02:43:31 with timeout 10 s. Before the change, Duration max was about 1202 ms, so the handler normally runs longer than 1 s. Once the timeout dropped to 1 s, Logs show REPORT lines with "Duration: 1000.00 ms ... Status: timeout" for every invocation, with Max Memory Used 37 MB (so this is not memory). Errors went from 0 to 3 at 02:48 and to about 18 per minute from 02:49 onward, matching the timeout change.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors alarm in ALARM: Errors Sum > 0 on FunctionName=checkout, 1 datapoint at 02:48 UTC.
- `aws_get_metric_data`: AWS/Lambda Errors per 60s: 0 until 02:47, then 3 at 02:48, 18 at 02:49, and about 17-18 per minute through 02:58.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration20150331v2 by user 'deployer' on checkout, request {"timeout": 1, "environment": {}}. Prior CreateFunction at 02:43:31 used timeout 10 and memorySize 128.
- `aws_get_metric_data`: AWS/Lambda Duration Maximum: about 1202 ms per minute from 02:43 to 02:48, then exactly 1000.0 ms from 02:49 onward, which is the 1 s cap.
- `aws_query_logs`: /aws/lambda/checkout REPORT lines: 'Duration: 1000.00 ms ... Max Memory Used: 37 MB ... Status: timeout' for repeated invocations at 02:58-02:59. No application ERROR or Exception lines were returned; the failures are timeouts, not code exceptions.

**Recommendations**
1. Confirm with the deployer who changed the timeout to 1 s at 02:48:49Z, and whether it was intended. Use the deployer's change record to verify.
2. Restore the timeout to the previous value of 10 s (the value from CreateFunction) with: aws lambda update-function-configuration --function-name checkout --timeout 10. Set it to a value above the observed p-max duration of about 1.2 s. This needs human approval before anyone runs it.
3. After the change, watch the Errors metric and the checkout-errors alarm return to OK, and confirm Duration returns to about 1.2 s.
4. Add a guard for accidental timeout changes, such as a config-drift alert or a deployment check that rejects timeouts under the observed p99 duration.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_describe_log_groups` {"prefix": "/aws/lambda/checkout"}
3. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Exception|Task timed out|error/ | sort @timestamp desc | limit 20", "minutes": 180}
4. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "minutes": 180, "period": 60}
5. `aws_lookup_events` {"resource_name": "checkout", "minutes": 360}
6. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Duration", "dimensions": {"FunctionName": "checkout"}, "minutes": 180, "period": 60, "stat": "Average"}
7. `TriageReport` {"summary": "The checkout Lambda began timing out at 02:48 UTC on 2026-10-19, right after a configuration change by user \"deployer\" set its timeout to 1 second. Every invocation since then hits the 1000 ms limit (Status: timeout), producing about 18 errors per minute. This is a self-inflicted conf
