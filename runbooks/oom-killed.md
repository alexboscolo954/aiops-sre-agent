---
title: Container OOM killed
alerts: [KubeContainerOOMKilled, ContainerOOMKilled, KubePodCrashLooping]
---
The kernel killed the container for exceeding its memory limit (exit code 137,
reason `OOMKilled` in the container's last state).

1. Confirm: `list_pods` shows `last_terminated: OOMKilled`, exit code 137.
2. Compare the memory **limit** (`describe_pod`) with real usage. With Prometheus:
   `max by (pod) (container_memory_working_set_bytes{namespace="<ns>", container!=""})`
   over the last hours (`query_range`). Steady growth until the kill points to a leak;
   a flat line just under the limit means the limit is too small.
3. Runtime-specific: JVMs size the heap from the container limit; a heap set with
   `-Xmx` above the limit gets OOM killed. Node.js needs `--max-old-space-size`.
4. Fix: raise the limit (and request) to observed peak plus 25%, or fix the leak.
   Restarting only buys time until the next kill.
