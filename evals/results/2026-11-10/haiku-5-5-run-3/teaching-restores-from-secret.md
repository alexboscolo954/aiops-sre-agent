## The checkout pod is crash looping because revision 2 of the checkout deployment (rolled out about 48s before triage) removed the DATABASE_URL env var from the app container. The app exits at startup with "FATAL: required env var DATABASE_URL is not set". Separately, the reports pod is OOMKilled at a 64Mi limit while loading 200MB of rows; that is a different problem and not part of this alert's cause.

**Root cause** (high confidence, `bad_config`): Checkout revision 2 (ReplicaSet checkout-869fc5bcc6, created 36s before triage) dropped DATABASE_URL from the app container's env. Revision 1 (checkout-67d9799c78) had env DATABASE_URL and is now scaled to 0. The current container's log shows "FATAL: required env var DATABASE_URL is not set", and the pod's last termination is Error with exit code 1. The env list on revision 2 is empty, with no env_from. Per the Operator's teaching, the fix is to restore DATABASE_URL from secret checkout-db and redeploy, not to roll back.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: demo checkout revision 2 rollout 48s ago: env_removed app: [DATABASE_URL]
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps 0/1 ready, restarts 3, last terminated Error exit code 1
- `kubernetes_describe_deployment`: checkout revision 2 config app env: [] env_from: []; revision 1 config app env: [DATABASE_URL]; Available=False MinimumReplicasUnavailable
- `runbooks_read_runbook`: pod-crashlooping runbook: Error exit means the process failed; check config and the rollout history for a recent revision
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f is OOMKilled (exit 137), restarts 3
- `kubernetes_pod_logs`: reports pod previous log: 'building monthly report: loading 200MB of rows'

**Recommendations**
1. Restore DATABASE_URL on the checkout deployment's app container from secret checkout-db (secretKeyRef), then redeploy. Do not roll back the checkout deployment, per the Operator's teaching.
2. Confirm checkout-869fc5bcc6-db5ps becomes Ready and the restart count stops rising.
3. Separately: reports is OOMKilled with a 64Mi limit while loading 200MB of rows. Raise its memory limit above observed peak (the oom-killed runbook suggests peak plus 25%), or reduce the batch size. This is a separate cause from the checkout alert.
4. Separately: frontend pod is in ErrImagePull because the image tag nginx:1.99.99-does-not-exist does not exist. Correct the tag to a valid image.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
6. `incidents_search` {"keywords": "checkout DATABASE_URL crash loop"}
7. `runbooks_read_runbook` {"name": "pod-crashlooping"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
9. `TriageReport` {"summary": "The checkout pod is crash looping because revision 2 of the checkout deployment (rolled out ~48s before triage) removed the DATABASE_URL env var from the app container. The app exits at startup with \"FATAL: required env var DATABASE_URL is not set\". Separately, the reports pod is OOMK
10. `TriageReport` {"summary": "The checkout pod is crash looping because revision 2 of the checkout deployment (rolled out about 48s before triage) removed the DATABASE_URL env var from the app container. The app exits at startup with \"FATAL: required env var DATABASE_URL is not set\". Separately, the reports pod is
