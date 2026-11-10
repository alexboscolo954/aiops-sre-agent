## Every checkout Lambda invocation has been timing out since 02:48:49Z. At that moment the 'deployer' principal cut the function timeout from 10 s to 1 s, but the function normally takes about 1.2 s, so it now fails about 18 times a minute.

**Root cause** (high confidence, `bad_config`): CloudTrail shows UpdateFunctionConfiguration on checkout at 2026-10-19T02:48:49Z by 'deployer', setting "timeout": 1. The function was created at 02:43:31Z with timeout 10. Before the change, the maximum duration was about 1202 ms per minute (02:43 to 02:48), which is more than 1 s. After it, every invocation is cut off at 1000.00 ms with 'Status: timeout'. Memory is not the problem: 37 MB used of 128 MB. Errors were 0 until 02:48, then 3 in the 02:48 minute and 17 to 18 per minute from 02:49 on.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors is in ALARM on AWS/Lambda Errors (FunctionName=checkout), Sum > 0 over 60 s; the first breaching datapoint was 02:48:00.
- `aws_lookup_events`: UpdateFunctionConfiguration20150331v2 at 2026-10-19T02:48:49Z by user 'deployer' set checkout timeout to 1. CreateFunction at 02:43:31Z had set timeout 10 and memorySize 128.
- `aws_get_metric_data`: Errors per minute were 0 from 02:43 to 02:47, 3 at 02:48, then 17 to 18 every minute from 02:49 to 02:58.
- `aws_get_metric_data`: Maximum Duration was about 1202 ms per minute from 02:43 to 02:48 and has been capped at exactly 1000.0 ms since 02:49, the new 1 s timeout.
- `aws_query_logs`: /aws/lambda/checkout REPORT lines read 'Duration: 1000.00 ms ... Max Memory Used: 37 MB Status: timeout' for every invocation, 02:58 to 02:59.

**Recommendations**
1. Set the checkout timeout back to its previous value of 10 s, or to at least a few seconds above the observed ~1.2 s peak: aws lambda update-function-configuration --function-name checkout --timeout 10. This needs approval.
2. Check that the Errors metric returns to 0 and that REPORT lines no longer show 'Status: timeout'.
3. Ask whoever runs the 'deployer' pipeline or IaC why the timeout was set to 1, and fix the source (the template or deploy config) so the next deploy doesn't bring it back.
4. Add a check that rejects deploys whose Lambda timeout is below the function's observed p99 duration, and consider a Duration-near-timeout alarm.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_lookup_events` {"resource_name": "checkout"}
3. `aws_describe_log_groups` {"prefix": "/aws/lambda/checkout"}
4. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /(?i)(error|timed out|task)/ | sort @timestamp desc | limit 20", "minutes": 180}
5. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "minutes": 180, "period": 60}
6. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Duration", "dimensions": {"FunctionName": "checkout"}, "minutes": 180, "period": 60, "stat": "Maximum"}
