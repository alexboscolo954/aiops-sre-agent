## The checkout Lambda is timing out on every invocation. At 02:48:49Z the user 'deployer' cut its timeout from 10 s to 1 s, but the handler normally takes about 1.2 s. Since then it has logged about 18 errors a minute, all ending in 'Status: timeout' at exactly 1000 ms.

**Root cause** (high confidence, `bad_config`): At 2026-10-19T02:48:49Z, 'deployer' ran UpdateFunctionConfiguration on checkout and set timeout to 1 second. The function was created at 02:43:31Z with timeout 10. Before the change, max Duration was about 1202 ms each minute (02:43–02:48). That is longer than the new 1000 ms limit, so every invocation is cut off. Memory is not the cause: max memory used is 37 MB of 128 MB. Errors were 0 per minute from 02:43 to 02:47, 3 at 02:48, then 17–18 every minute after. Max duration is pinned at exactly 1000.0 ms. Note: the alarm's first breaching datapoint is labeled 02:48:00, about 49 s before the change event. Those 3 early errors are unexplained; possible causes are bucket/timestamp skew or a few errors that came before the change.
**Severity:** critical  ·  **Affected:** aws/lambda/checkout

**Evidence**
- `aws_describe_alarms`: checkout-errors in ALARM: AWS/Lambda Errors Sum for FunctionName=checkout was 1.0 at 02:48, over the threshold of 0.
- `aws_lookup_events`: 02:48:49Z UpdateFunctionConfiguration on checkout by 'deployer' set timeout to 1. CreateFunction at 02:43:31Z had set timeout to 10 and memorySize to 128.
- `aws_get_metric_data`: Errors per minute: 0 from 02:43–02:47, 3 at 02:48, then 17–18 every minute through 02:58.
- `aws_get_metric_data`: Max Duration: about 1202 ms every minute from 02:43–02:48, then exactly 1000.0 ms from 02:49 on (cut off by the timeout).
- `aws_query_logs`: /aws/lambda/checkout REPORT lines: 'Duration: 1000.00 ms ... Max Memory Used: 37 MB Status: timeout' on every invocation from 02:58–02:59.

**Recommendations**
1. Set the checkout timeout back to 10 s, or at least well above the ~1.2 s normal run time, e.g. `aws lambda update-function-configuration --function-name checkout --timeout 10`. This needs a human to approve and run it.
2. Watch the Errors metric go back to 0 and Duration return to about 1.2 s. Then confirm the checkout-errors alarm returns to OK.
3. Ask the 'deployer' identity or pipeline owner why timeout was set to 1, and fix the source (IaC or deploy config) so the next deploy doesn't bring it back.
4. Add a guard in the deploy process: the timeout must exceed p99 duration plus headroom. Also look into why checkout takes ~1.2 s per call if a shorter timeout is wanted.

**Tool calls**
1. `aws_describe_alarms` {"state": "ALARM"}
2. `aws_lookup_events` {"resource_name": "checkout"}
3. `aws_describe_log_groups` {"prefix": "/aws/lambda/checkout"}
4. `aws_query_logs` {"log_groups": ["/aws/lambda/checkout"], "query": "fields @timestamp, @message | filter @message like /(?i)error|timed out|exception|task/ | sort @timestamp desc | limit 30", "minutes": 120}
5. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Errors", "dimensions": {"FunctionName": "checkout"}, "period": 60, "minutes": 30}
6. `aws_get_metric_data` {"namespace": "AWS/Lambda", "metric_name": "Duration", "dimensions": {"FunctionName": "checkout"}, "period": 60, "minutes": 30, "stat": "Maximum"}
