## The checkout Lambda times out on every call. At 02:48:49Z the deployer user ran UpdateFunctionConfiguration and cut its timeout from 10s to 1s. The function's inventory lookup alone takes about 1.2s, so no call can finish in time.

**Root cause** (high confidence, `bad_config`): The timeout setting on the checkout Lambda is too short. CloudTrail shows CreateFunction at 02:43:31Z with timeout 10. At 02:48:49Z the deployer user changed it to "timeout": 1 with UpdateFunctionConfiguration. Before the change, the function logged 'inventory lookup took 1.2s' on every call (02:43–02:46). Since the change, every REPORT line shows 'Duration: 1000.00 ms ... Status: timeout'. Max Memory Used is 37 MB of 128 MB, so memory isn't the cause and the code didn't change. The Errors alarm crossed its threshold in the 02:48 datapoint, which matches when the config changed.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors is in ALARM: AWS/Lambda Errors (FunctionName=checkout) Sum 1.0 at 02:48:00 > threshold 0, period 60s.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration by deployer on checkout set "timeout": 1. Earlier CreateFunction at 02:43:31Z had "timeout": 10, memorySize 128.
- `aws_query_logs`: /aws/lambda/checkout since about 02:49: every invocation REPORT shows 'Duration: 1000.00 ms Billed Duration: 1000 ms ... Max Memory Used: 37 MB Status: timeout'.
- `aws_query_logs`: Before the change (02:43:50–02:46:39) each invocation logged INFO 'inventory lookup took 1.2s', which is longer than the new 1s timeout.

**Recommendations**
1. Set the checkout timeout back to 10s, for example with aws lambda update-function-configuration --function-name checkout --timeout 10. This needs human approval because it changes the function.
2. Confirm recovery: the Errors metric for FunctionName=checkout should go to 0, and REPORT lines should show Status other than timeout with durations around 1.2s+.
3. Ask the deployer user, or whoever owns the pipeline that ran it, why the timeout was set to 1s. Fix the IaC or deploy config so the change isn't reapplied.
4. As follow-up, look into why the inventory lookup takes 1.2s. Consider adding a Duration alarm close to the configured timeout so this gets caught before calls start failing.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_lookup_events` {"resource_name": "checkout"}
3. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /ERROR|Error|Task timed out/ | sort @timestamp desc | limit 20"}
4. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "filter @type = \"REPORT\" | stats count(*) as n, avg(@duration) as avgDur, max(@duration) as maxDur by bin(1m) | sort @timestamp asc", "minutes": 30}
5. `read_more` {"result_id": "rb217fe", "start": 20000}
