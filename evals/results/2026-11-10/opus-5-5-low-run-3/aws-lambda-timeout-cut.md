## Every invocation of the Lambda function checkout is timing out at exactly 1000 ms. At 02:48:49Z 'deployer' changed the function's timeout from 10s to 1s, and the timeouts in the logs follow that change.

**Root cause** (high confidence, `bad_config`): At 2026-10-19T02:48:49Z the user 'deployer' ran UpdateFunctionConfiguration on checkout and set timeout to 1 (second). When the function was created at 02:43:31Z the timeout was 10s. The REPORT lines from 02:58–02:59 show 'Duration: 1000.00 ms ... Status: timeout' on every request. Memory use is only 37 MB of 128 MB, so the cause is not memory. The handler needs more than 1s, so every request hits the limit and fails.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration by deployer on checkout set timeout to 1; the earlier CreateFunction at 02:43:31Z had timeout 10, memorySize 128.
- `aws_query_logs`: In /aws/lambda/checkout, every REPORT line from 02:58 to 02:59 shows 'Duration: 1000.00 ms, Billed 1000 ms, Max Memory Used: 37 MB, Status: timeout'.

**Recommendations**
1. Set the checkout function's timeout back to 10s (aws lambda update-function-configuration --function-name checkout --timeout 10). This change needs human approval.
2. Check that the Errors metric and the checkout-errors alarm go back to OK, and that new REPORT lines show normal durations without Status: timeout.
3. Ask the deployer why the timeout was set to 1s, and fix the infrastructure-as-code or deploy config so the change isn't applied again.
4. Consider adding a check on timeout values to deploy review or CI.

**Tool calls**
1. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Task timed out|Exception/ | sort @timestamp desc | limit 20"}
2. `aws_lookup_events` {"resource_name": "checkout"}
