---
title: Image pull failure
alerts: [KubePodNotReady, KubeContainerWaiting, KubeDeploymentRolloutStuck]
---
Pods stay in `ImagePullBackOff` / `ErrImagePull`.

1. `describe_pod`: the events say why. Typical messages:
   - `manifest unknown` / `not found`: the tag does not exist (typo, CI never pushed it).
   - `unauthorized` / `denied`: missing or expired imagePullSecret, or registry permissions.
   - `i/o timeout` / `TLS`: node cannot reach the registry (egress, proxy, DNS).
2. Check `describe_deployment` rollout history: a new revision with a new image tag
   right before the alert is the usual trigger.
3. Fix the tag or the pull secret, or roll back. The old ReplicaSet keeps serving
   during a stuck rollout, so impact is often limited: say so in the report.
