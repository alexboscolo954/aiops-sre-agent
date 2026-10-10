#!/usr/bin/env bash
# Prove the shipped RBAC is least privilege by impersonating the agent's ServiceAccount.
set -euo pipefail
ctx=$1; actions=${2:-false}
sa=system:serviceaccount:aiops:aiops-agent
fail=0
check() {  # expected verb resource namespace
  got=$(kubectl --context "$ctx" auth can-i "$2" "$3" -n "$4" --as "$sa" || true)
  if [[ "$got" == "$1" ]]; then echo "ok   $2 $3 -n $4 = $got"; else echo "FAIL $2 $3 -n $4 = $got (want $1)"; fail=1; fi
}
check yes list pods demo
check yes get pods/log demo
check yes list events demo
check yes get deployments.apps demo
check no  list pods kube-system
check no  get secrets demo
check no  list configmaps demo
check no  delete pods demo
check no  delete deployments.apps demo
if [[ "$actions" == true ]]; then
  check yes patch deployments.apps demo
  check yes patch deployments.apps/scale demo
  check no  patch deployments.apps kube-system
else
  check no  patch deployments.apps demo
fi
exit $fail
