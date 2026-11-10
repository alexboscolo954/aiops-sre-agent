## The checkout Lambda is failing on every call because its timeout dropped from 10s to 1s at 02:48:49Z. Its inventory lookup alone takes about 1.2s, so since then each invocation has hit the 1000 ms limit and ended with Status: timeout, and the Errors alarm fired.

**Root cause** (high confidence, `bad_config`): At 2026-10-19T02:48:49Z, user 'deployer' ran UpdateFunctionConfiguration on checkout and set timeout=1 second. When the function was created at 02:43:31Z the timeout was 10 seconds. Function logs from before the change show 'inventory lookup took 1.2s' on every request, which is longer than the new 1s limit. Since the change, every REPORT line shows 'Duration: 1000.00 ms ... Status: timeout' with only 37 MB of 128 MB memory used, so this is not a memory problem or a code crash. The alarm (Errors Sum > 0 over 60s) crossed its threshold in the 02:48 datapoint, the same minute as the change. The update also sent an empty environment ({}); the create request was empty too, so that is probably not a change, but it's worth confirming.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors is in ALARM on AWS/Lambda Errors (FunctionName=checkout), Sum > 0 over a 60s period; the threshold was crossed in the 02:48:00 datapoint.
- `aws_lookup_events`: UpdateFunctionConfiguration by 'deployer' at 2026-10-19T02:48:49Z set timeout to 1 (environment {}). CreateFunction at 02:43:31Z had set timeout to 10 and memorySize to 128.
- `aws_query_logs`: /aws/lambda/checkout: from 02:58 to 02:59 every REPORT line reads 'Duration: 1000.00 ms Billed Duration: 1000 ms Memory Size: 128 MB Max Memory Used: 37 MB Status: timeout'. Log lines from 02:45 to 02:48:47, before the change, read 'inventory lookup took 1.2s'.

**Recommendations**
1. Set the checkout timeout back to 10 seconds (or at least comfortably above the ~1.2s inventory lookup plus the rest of the handler), e.g. aws lambda update-function-configuration --function-name checkout --timeout 10. This needs human approval; I didn't change anything.
2. Check that the Errors metric returns to 0 and that REPORT lines no longer show Status: timeout.
3. Ask the 'deployer' owner, or check the IaC/pipeline config, why the timeout became 1s, and fix it at the source so the next deploy doesn't undo the repair.
4. Confirm that the empty environment in the update didn't remove any environment variables the function needs.
5. Look into the 1.2s inventory lookup latency, and consider a timeout or duration alarm with headroom so this kind of misconfiguration is caught before it causes errors.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_lookup_events` {"resource_name": "checkout"}
3. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /(?i)error|exception|timed out/ | sort @timestamp desc | limit 20"}
4. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "filter @type = \"REPORT\" | stats count(*) as n, avg(@duration) as avgDur, max(@duration) as maxDur by bin(1m) | sort bin(1m) asc", "minutes": 30}
5. `read_more` {"result_id": "r304a2d", "grep": "02:4"}
