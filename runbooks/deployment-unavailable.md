---
title: Deployment replicas unavailable
alerts: [KubeDeploymentReplicasMismatch, KubeDeploymentRolloutStuck, KubePodNotReady]
---
A deployment has fewer ready replicas than desired.

1. `list_deployments` then `list_pods` for the workload. Group pods by state:
   - `Pending`: scheduling. `get_events` shows `FailedScheduling` with the reason
     (insufficient cpu/memory, node selector, taints, PVC binding).
   - Running but not ready: the readiness probe fails. `describe_pod` shows the probe;
     logs show whether the app is slow to start or unhealthy.
   - Crash looping: use the pod-crashlooping runbook.
2. `describe_deployment`: conditions (`ProgressDeadlineExceeded`) and rollout history.
3. Insufficient resources is a capacity problem: scaling the deployment up makes it
   worse. Recommend fixing requests or adding nodes instead.
