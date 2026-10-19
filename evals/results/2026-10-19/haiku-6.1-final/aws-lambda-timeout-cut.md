## The checkout Lambda is timing out on nearly every invocation since 02:48 UTC. A deployer's UpdateFunctionConfiguration at 02:48:49 cut the timeout from 10s to 1s, and every recent invocation reports Status: timeout at exactly 1000 ms. Restoring the timeout should stop the errors.

**Root cause** (high confidence, `bad_config`): A configuration change by user 'deployer' at 02:48:49 set the checkout Lambda timeout to 1 second (previously 10 seconds, per the CreateFunction at 02:43:31). Invocations exceed 1s and are killed. Max memory used is about 37 MB of 128 MB, so memory is not the cause.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout/function/checkout

**Evidence**
- `aws_describe_alarms`: Alarm checkout-errors is in ALARM: Errors Sum of 1.0 at 02:48 was greater than threshold 0.0.
- `aws_get_metric_data`: AWS/Lambda Errors Sum per 60s was 0 from 02:43 to 02:47, then 3 at 02:48 and 17-18 per minute from 02:49 through 02:58.
- `aws_lookup_events`: At 02:48:49Z, deployer ran UpdateFunctionConfiguration20150331v2 on checkout with request timeout: 1 and environment: {}. The earlier CreateFunction at 02:43:31Z had timeout 10, memorySize 128, python3.12.
- `aws_query_logs`: Over /aws/lambda/checkout, REPORT lines show Duration: 1000.00 ms and Status: timeout for the recent invocations, with Max Memory Used: 37 MB of 128 MB. No application ERROR or Traceback lines appeared in the results.

**Recommendations**
1. Confirm with the deployer whether the timeout change at 02:48:49Z was intentional. It is very likely accidental, since 1s is too short for this function's work.
2. Restore the timeout to the previous value of 10 seconds with aws lambda update-function-configuration --function-name checkout --timeout 10, or roll back the configuration change. This needs human approval because it changes a production resource.
3. After the change, watch the Errors metric and the checkout-errors alarm until they return to 0, and confirm REPORT lines show Status other than timeout.
4. Review the deploy pipeline or IaC that set timeout to 1, and add a guard or validation so a timeout drop like this is caught before it reaches production.

**Tool calls**
1. `aws_describe_alarms`
2. `aws_get_metric_data`
3. `aws_lookup_events`
4. `aws_describe_log_groups`
5. `aws_query_logs`
