## The checkout Lambda times out on every invocation. A deploy at 02:48:49Z cut its timeout from 10s to 1s. Errors have run at about 18 per minute since then.

**Root cause** (high confidence, `bad_config`): UpdateFunctionConfiguration by 'deployer' at 02:48:49Z set timeout=1s, down from 10s at creation. It also sent an empty environment, which may have removed environment variables, though the logs don't show this. Every invocation now hits the 1s limit (Duration: 1000.00 ms, Status: timeout), and max memory used is only 37 MB of 128 MB, so memory is not the cause. Errors were 0 until 02:47 and then rose to about 18 per minute from 02:49.
**Severity:** critical  ·  **Affected:** lambda/function/checkout

**Evidence**
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration by deployer with timeout=1 and environment={}. The earlier CreateFunction at 02:43:31Z had timeout=10.
- `aws_query_logs`: Every recent invocation reports Duration: 1000.00 ms, Status: timeout, Max Memory Used: 37 MB of 128 MB.
- `aws_get_metric_data`: Errors per minute were 0 until 02:47, then 3 at 02:48, then about 17-18 per minute from 02:49 through 02:58.
- `aws_describe_alarms`: Alarm checkout-errors is in ALARM state: AWS/Lambda Errors Sum > 0 for FunctionName=checkout, first datapoint at 02:48.

**Recommendations**
1. Restore the checkout timeout to 10s (or the correct value) with update-function-configuration.
2. Check whether the empty environment {} wiped required environment variables, and restore them if so.
3. Find out why the deployer pipeline set timeout=1 and fix it. Add validation or review for Lambda config changes.
4. After the fix, confirm that Errors returns to 0 and the alarm clears.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_describe_log_groups` {"prefix": "/aws/lambda/checkout"}
3. `aws_lookup_events` {"resource_name": "checkout"}
4. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | sort @timestamp desc | limit 20"}
5. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "period": 60, "minutes": 60}
