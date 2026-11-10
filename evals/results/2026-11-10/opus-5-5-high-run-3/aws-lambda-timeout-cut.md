## The checkout Lambda has been timing out on every invocation (about 18 errors/min) since 02:48 UTC. At 02:48:49 'deployer' cut the function timeout from 10s to 1s, but the handler's inventory lookup alone takes about 1.2s.

**Root cause** (high confidence, `bad_config`): CloudTrail shows UpdateFunctionConfiguration on checkout by 'deployer' at 2026-10-19T02:48:49Z setting timeout=1. The function was created at 02:43:31 with timeout=10. Before the change, the function logged 'inventory lookup took 1.2s' on every request, which already exceeds the new 1s limit. Since then every REPORT line shows 'Duration: 1000.00 ms ... Status: timeout' with only 37 MB of the 128 MB memory used, so memory is not the issue. The Errors metric was 0/min from 02:43 to 02:47, 3 in the 02:48 minute (when the change landed), then 17–18/min through 02:58. There was no code deploy, only this config change.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors in ALARM: AWS/Lambda Errors Sum (60s) for FunctionName=checkout above the 0 threshold, first datapoint at 02:48.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration20150331v2 on checkout by deployer with {"timeout": 1}. The earlier CreateFunction at 02:43:31Z had timeout 10 and memorySize 128.
- `aws_get_metric_data`: Errors per minute: 0 from 02:43–02:47, 3 at 02:48, then 18,18,18,18,17,18,18,18,18,17 through 02:58.
- `aws_query_logs`: /aws/lambda/checkout: before the change, every request logged 'inventory lookup took 1.2s'. After it, every REPORT line reads 'Duration: 1000.00 ms ... Max Memory Used: 37 MB Status: timeout'.

**Recommendations**
1. Set the checkout timeout back to 10s, the value it was created with (e.g. aws lambda update-function-configuration --function-name checkout --timeout 10). This needs human approval.
2. Confirm that Errors returns to 0 and REPORT lines no longer show 'Status: timeout'.
3. Ask the deployer, or whoever owns the pipeline or IaC, why the timeout was set to 1s, and fix the source config so the next deploy doesn't bring it back.
4. If a shorter timeout is really wanted, first cut the inventory lookup latency (about 1.2s) and leave headroom above p99 duration. Consider adding a Duration p99 alarm close to the timeout.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_lookup_events` {"resource_name": "checkout"}
3. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Task timed out|Error|REPORT/ | sort @timestamp desc | limit 30", "minutes": 180}
4. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "minutes": 60, "period": 60}
5. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /REPORT/ and @message not like /Status: timeout/ | sort @timestamp desc | limit 20", "minutes": 180}
6. `read_more` {"result_id": "rf72c35", "grep": "02:4"}
