## Lambda checkout is failing every invocation with a timeout. At 2026-10-19T02:48:49Z the 'deployer' user changed its timeout from 10s to 1s, but the inventory lookup inside each invocation takes about 1.2s, so every call now times out at 1000 ms.

**Root cause** (high confidence, `bad_config`): CloudTrail shows UpdateFunctionConfiguration on checkout at 02:48:49Z by 'deployer', setting timeout to 1. The function was created at 02:43:31Z with a 10s timeout. Up to 02:48:47 the logs show steady INFO lines saying 'inventory lookup took 1.2s', which is longer than the new 1s limit. Since 02:48:49 every REPORT line reads 'Duration: 1000.00 ms ... Status: timeout'. Memory is fine (37 MB used of 128 MB). The Errors alarm (Sum > 0, 60s period) crossed its threshold on the 02:48 datapoint, the same minute as the change.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors in ALARM: AWS/Lambda Errors for FunctionName=checkout, value 1.0 at 19/10/26 02:48:00, threshold > 0, period 60s
- `aws_lookup_events`: UpdateFunctionConfiguration20150331v2 on checkout at 2026-10-19T02:48:49Z by deployer with timeout: 1. CreateFunction at 02:43:31Z had timeout: 10, memorySize 128
- `aws_query_logs`: /aws/lambda/checkout from 02:48:49 on: every REPORT shows 'Duration: 1000.00 ms Billed Duration: 1000 ms ... Max Memory Used: 37 MB Status: timeout'
- `aws_query_logs`: /aws/lambda/checkout from 02:45 to 02:48:47: repeated INFO 'inventory lookup took 1.2s', which takes longer than the new 1s timeout

**Recommendations**
1. Put the checkout timeout back to its earlier 10s (aws lambda update-function-configuration --function-name checkout --timeout 10), or at least well above the ~1.2s inventory lookup.
2. Check that checkout-errors returns to OK and that REPORT lines no longer show Status: timeout.
3. Ask the deployer, or whatever pipeline uses that identity, why the timeout was set to 1 and fix the source (IaC/pipeline config) so the next deploy doesn't bring it back.
4. Consider an alarm on Duration near the timeout, and look at why the inventory lookup takes 1.2s.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_lookup_events` {"resource_name": "checkout"}
3. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Error|Task timed out|errorMessage/ | sort @timestamp desc | limit 20"}
4. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /REPORT/ | sort @timestamp asc | limit 15"}
5. `read_more` {"result_id": "r72fc83", "grep": "02:4"}
