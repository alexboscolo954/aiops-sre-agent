## The Lambda function `checkout` has timed out on every invocation since 02:48Z. A config update at 02:48:49Z cut its timeout from 10s to 1s.

**Root cause** (high confidence, `bad_config`): CloudTrail shows `UpdateFunctionConfiguration` by `deployer` at 02:48:49Z set `timeout` to 1 second. The function was created at 02:43:31Z with a 10s timeout. Every invocation since then ends with `Duration: 1000.00 ms ... Status: timeout`. Memory use is only 37 MB of 128 MB, so memory is not the cause. Errors were 0 per minute until 02:47 and have been about 18 per minute since 02:49. The same update also sent `environment: {}`, which may have wiped environment variables. The function was created with an empty environment too, so there is no sign anything was lost. The 1s timeout is the confirmed cause.
**Severity:** critical  ·  **Affected:** lambda/function/checkout

**Evidence**
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration by deployer set timeout=1 and environment={}. The earlier CreateFunction at 02:43:31Z had timeout=10 and memorySize=128.
- `aws_query_logs`: Every recent invocation in /aws/lambda/checkout reports 'Duration: 1000.00 ms ... Max Memory Used: 37 MB Status: timeout'.
- `aws_get_metric_data`: AWS/Lambda Errors for checkout was 0 through 02:47Z, then 3 at 02:48Z and about 18 per minute from 02:49Z onward.
- `aws_describe_alarms`: Alarm checkout-errors is in ALARM: Errors Sum > 0 over a 60s period, with the first datapoint at 02:48Z.

**Recommendations**
1. Restore the checkout function timeout to its previous value of 10s, for example with `aws lambda update-function-configuration --function-name checkout --timeout 10`.
2. Check that the function's environment variables and config are as intended, since the update also sent an empty `environment`.
3. Find out why the deployer pipeline set timeout=1, and add validation or a review step for Lambda config changes.
4. After the fix, confirm the Errors metric returns to 0 and the alarm clears.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_lookup_events` {"resource_name": "checkout", "minutes": 240}
3. `aws_describe_log_groups` {"prefix": "/aws/lambda/checkout"}
4. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | sort @timestamp desc | limit 20", "minutes": 240}
5. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "minutes": 120, "period": 60}
