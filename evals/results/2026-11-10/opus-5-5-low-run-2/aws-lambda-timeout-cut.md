## Every checkout Lambda invocation is timing out at exactly 1000 ms. At 02:48:49Z the deployer changed the function's timeout from 10 s to 1 s, and the timeouts started after that change.

**Root cause** (high confidence, `bad_config`): At 2026-10-19T02:48:49Z the deployer ran UpdateFunctionConfiguration on checkout and set timeout=1 second. The function was created at 02:43:31Z with timeout=10. Since the change, each invocation in the logs ends with 'Duration: 1000.00 ms ... Status: timeout'. Memory use is only 37 of 128 MB, so memory isn't the problem: the handler just needs more than 1 s and gets killed at the new limit.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_lookup_events`: UpdateFunctionConfiguration on checkout by deployer at 02:48:49Z set timeout 1. CreateFunction at 02:43:31Z had timeout 10, memorySize 128.
- `aws_query_logs`: Every recent REPORT line in the /aws/lambda/checkout logs (02:58–02:59) shows 'Duration: 1000.00 ms ... Max Memory Used: 37 MB Status: timeout'.

**Recommendations**
1. Set the checkout Lambda timeout back to 10 s, e.g. aws lambda update-function-configuration --function-name checkout --timeout 10.
2. Check that the Errors metric and the checkout-errors alarm go back to OK.
3. Ask the deployer why the timeout was set to 1 s, and fix the IaC or deploy config so the change doesn't come back.
4. Add a review or guardrail for timeout changes and an alarm on Duration nearing the timeout.

**Tool calls**
1. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Task timed out|Exception/ | sort @timestamp desc | limit 20"}
2. `aws_lookup_events` {"resource_name": "checkout"}
