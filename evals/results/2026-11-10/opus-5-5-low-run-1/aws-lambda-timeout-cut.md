## Since about 02:48 UTC, every checkout Lambda invocation has been timing out at 1000 ms. A config change by 'deployer' at 02:48:49 UTC lowered the function timeout from 10 s to 1 s.

**Root cause** (high confidence, `bad_config`): At 02:48:49Z the user 'deployer' ran UpdateFunctionConfiguration on checkout and set timeout=1. The function was created at 02:43:31Z with timeout=10. Every recent invocation since then ends with 'Duration: 1000.00 ms ... Status: timeout'. Max Memory Used is 37 MB of 128 MB, so memory is not the cause; the 1 s limit is shorter than the handler needs to finish.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_lookup_events`: UpdateFunctionConfiguration on checkout at 2026-10-19T02:48:49Z by deployer set timeout to 1. CreateFunction at 02:43:31Z had timeout 10.
- `aws_query_logs`: /aws/lambda/checkout: every REPORT line from 02:58 to 02:59 shows 'Duration: 1000.00 ms ... Max Memory Used: 37 MB, Status: timeout'.

**Recommendations**
1. Set the checkout timeout back to 10 s (aws lambda update-function-configuration --function-name checkout --timeout 10). This needs approval; I made no changes.
2. Check that the Errors metric drops and the checkout-errors alarm returns to OK.
3. Ask the deployer why the timeout was changed, and add a guard on timeout values in the deploy pipeline or IaC.

**Tool calls**
1. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Error|Task timed out/ | sort @timestamp desc | limit 20"}
2. `aws_lookup_events` {"resource_name": "checkout"}
