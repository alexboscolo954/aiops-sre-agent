## The Lambda function checkout is timing out on every invocation. A deploy at 02:48:49Z cut its timeout from 10s to 1s, and the alarm fired at 02:48.

**Root cause** (high confidence, `bad_config`): CloudTrail shows UpdateFunctionConfiguration by 'deployer' at 02:48:49Z set timeout=1 and environment={}. The function was created at 02:43:31Z with timeout=10 and 128MB. Since then every invocation ends with 'Duration: 1000.00 ms ... Status: timeout'. Memory use is only 37MB of 128MB, so memory is not the limit. The 1s timeout is too short for the handler. The empty environment block may also have removed variables, but I saw no evidence of that in the logs I read.
**Severity:** critical  ·  **Affected:** lambda/function/checkout

**Evidence**
- `aws_describe_alarms`: Alarm checkout-errors is in ALARM. It watches AWS/Lambda Errors (Sum, 60s period) for FunctionName=checkout with threshold >0. The datapoint that crossed it was at 02:48.
- `aws_lookup_events`: At 02:48:49Z the deployer ran UpdateFunctionConfiguration with timeout=1 and environment={}. The earlier CreateFunction at 02:43:31Z had timeout=10 and memorySize=128.
- `aws_query_logs`: The checkout log group shows many invocations with 'Duration: 1000.00 ms ... Max Memory Used: 37 MB Status: timeout', one every few seconds up to 02:59:37.

**Recommendations**
1. Restore the checkout timeout to 10s or another value that fits the handler's real runtime, for example with aws lambda update-function-configuration --timeout 10.
2. Check whether the empty environment block in that update removed required environment variables, and restore them if it did.
3. Review the deployer pipeline or IaC so config updates cannot silently shrink the timeout or wipe the environment.
4. After the fix, confirm the Errors metric returns to 0 and the alarm clears.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_lookup_events` {"resource_name": "checkout", "minutes": 240}
3. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Error|error|Exception/ | sort @timestamp desc | limit 20"}
