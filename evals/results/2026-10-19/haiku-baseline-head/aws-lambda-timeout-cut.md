## The checkout Lambda's timeout was cut from 10s to 1s at 02:48:49Z by user deployer, and every invocation since has ended with Status: timeout at exactly 1000 ms. The Errors alarm is a direct result of that change, not a code bug.

**Root cause** (high confidence, `bad_config`): A CloudTrail UpdateFunctionConfiguration call at 02:48:49Z set checkout's timeout to 1 second (the function was created with 10s at 02:43:31Z). Invocations take longer than 1s, so Lambda kills them. Errors jumped from 0 to about 18 per minute right after the change. Max memory used is 37 MB of 128 MB, which rules out memory pressure.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout (us-east-1)

**Evidence**
- `aws_lookup_events`: 2026-10-19T02:48:49Z UpdateFunctionConfiguration20150331v2 by user deployer on checkout, request body: timeout=1, environment={}.
- `aws_lookup_events`: 2026-10-19T02:43:31Z CreateFunction20150331 on checkout with timeout=10, memorySize=128, runtime python3.12.
- `aws_get_metric_data`: AWS/Lambda Errors Sum per 60s: 0 through 02:47, 3 at 02:48, then 17-18 per minute from 02:49 through 02:58 (still firing).
- `aws_describe_alarms`: checkout-errors is in ALARM: 1 datapoint 1.0 at 02:48 crossed threshold 0.0 (GreaterThanThreshold).
- `aws_query_logs (/aws/lambda/checkout)`: REPORT lines show Duration: 1000.00 ms, Billed Duration: 1000 ms, Max Memory Used: 37 MB, Status: timeout, repeated across many requests from 02:58 to 02:59. No ERROR or Traceback lines, so the code itself is not throwing.

**Recommendations**
1. Restore the checkout function timeout to its previous value of 10s (or the value the team intends). This is a config change, so get human approval before running it, e.g. aws lambda update-function-configuration --function-name checkout --timeout 10.
2. Confirm with the deployer who made the 02:48:49Z change and why, and add guardrails so timeout changes need review.
3. After the fix, watch the checkout-errors alarm and the Lambda Errors and Duration metrics to confirm recovery. If p99 duration sits near 10s, consider raising the timeout further.
4. Check downstream checkout callers for failed or retried orders during 02:48-03:00Z and replay them if needed.

**Tool calls**
1. `aws_describe_alarms`
2. `aws_get_metric_data`
3. `aws_lookup_events`
4. `aws_describe_log_groups`
5. `aws_query_logs`
