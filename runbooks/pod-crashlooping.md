---
title: Pod crash looping
alerts: [KubePodCrashLooping, KubeContainerWaiting]
---
A container keeps exiting and Kubernetes backs off restarting it.

1. `list_pods` in the namespace. Note restarts and the **last terminated reason**:
   - `OOMKilled` (exit 137): go to the oom-killed runbook.
   - `Error` (exit 1, 2...): the process itself failed. Continue here.
   - `Completed` (exit 0): the main process exits on its own; wrong command/args.
2. Read logs with `previous=true`. The current instance is often still starting;
   the crash is in the previous one. Look at the last 20 lines before the exit.
3. Common causes, in order of frequency:
   - Missing or wrong config: env var, ConfigMap key, Secret not mounted
     (`describe_pod` shows env var *names* and `envFrom` sources).
   - Dependency unreachable at startup (database, queue) with no retry.
   - Bad image or entrypoint after a rollout: check `describe_deployment`
     rollout history for a revision created shortly before the alert.
4. If a new revision caused it, the fix is a rollback of that revision; if config
   is missing, fix the config. A restart does not fix a crash loop: don't propose one.
