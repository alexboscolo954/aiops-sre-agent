#!/usr/bin/env bash
# Wait until each demo workload shows its failure, so tests and demos are deterministic.
set -euo pipefail
ctx=$1
k() { kubectl --context "$ctx" -n demo "$@"; }
until_true() {  # description, command
  for _ in $(seq 60); do eval "$2" >/dev/null 2>&1 && { echo "ok: $1"; return; }; sleep 5; done
  echo "timeout: $1"; k get pods -o wide; exit 1
}
until_true "checkout crash looping" \
  "k get pods -l app=checkout -o jsonpath='{.items[*].status.containerStatuses[0].restartCount}' | tr ' ' '\n' | awk '\$1>=2{f=1} END{exit !f}'"
until_true "reports OOM killed" \
  "k get pods -l app=reports -o jsonpath='{.items[0].status.containerStatuses[0].lastState.terminated.reason}' | grep -q OOMKilled"
until_true "frontend image pull failing" \
  "k get pods -l app=frontend -o jsonpath='{.items[0].status.containerStatuses[0].state.waiting.reason}' | grep -Eq 'ImagePullBackOff|ErrImagePull'"
