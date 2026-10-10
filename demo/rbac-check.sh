#!/usr/bin/env bash
# Prove the shipped RBAC is least privilege by impersonating the agent's ServiceAccount.
set -euo pipefail
ctx=$1; actions=${2:-false}
sa=system:serviceaccount:aiops:aiops-agent
fail=0
check() {  # expected namespace verb resource [--subresource=x]
  local want=$1 ns=$2; shift 2
  got=$(kubectl --context "$ctx" auth can-i "$@" -n "$ns" --as "$sa" || true)
  if [[ "$got" == "$want" ]]; then echo "ok   $* -n $ns = $got"; else echo "FAIL $* -n $ns = $got (want $want)"; fail=1; fi
}
check yes demo list pods
check yes demo get pods --subresource=log
check yes demo list events
check yes demo get deployments.apps
check no  kube-system list pods
check no  demo get secrets
check no  demo list configmaps
check no  demo delete pods
check no  demo delete deployments.apps
check no  demo patch deployments.apps
if [[ "$actions" == true ]]; then
  check yes demo create pods --subresource=eviction
  check yes demo patch deployments.apps --subresource=scale
  check no  kube-system create pods --subresource=eviction
else
  check no  demo create pods --subresource=eviction
  check no  demo patch deployments.apps --subresource=scale
fi
exit $fail
