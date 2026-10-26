#!/usr/bin/env bash
# Run the real image on kind with the shipped manifests: pod starts under the
# hardened securityContext, health and auth behave, a webhook is accepted.
set -euo pipefail
ctx=$1
k() { kubectl --context "$ctx" "$@"; }
k create namespace aiops --dry-run=client -o yaml | k apply -f -
k apply -f demo/postgres.yaml
k -n aiops rollout status deploy/aiops-postgres --timeout=3m
k -n aiops create secret generic aiops-secrets \
  --from-literal=AIOPS_APPROVER_TOKEN=smoke-approver --from-literal=AIOPS_MODEL_API_KEY=not-a-real-key \
  --from-literal=AIOPS_DATABASE_URL=postgresql://postgres:smoke@aiops-postgres.aiops:5432/postgres \
  --dry-run=client -o yaml | k apply -f -
# The shipped Contract has no webhook token: add one, as an Operator would.
new=$(uv run aiops contracts new-token 2>/dev/null)
token=$(sed -n 1p <<<"$new" | awk '{print $NF}')
work=$(mktemp -d); cp -R deploy/base "$work/base"
sed -n 2p <<<"$new" | sed 's/^contract.yaml: *//' >> "$work/base/contract.yaml"
kubectl kustomize "$work/base" \
  | sed 's#ghcr.io/alexboscolo954/aiops-sre-agent:0.13.0#aiops-sre-agent:ci#' \
  | k apply -f -
k -n aiops rollout status deploy/aiops-agent --timeout=3m
# kubectl itself, not the k() wrapper: $! must be kubectl's pid for the trap to stop it.
kubectl --context "$ctx" -n aiops port-forward svc/aiops-agent 18080:8080 >/dev/null 2>&1 & pf=$!
trap 'kill $pf' EXIT; sleep 3
curl -sf localhost:18080/healthz
url=localhost:18080/contracts/in-cluster/alertmanager
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST $url \
  -H 'Authorization: Bearer wrong' -H 'Content-Type: application/json' -d @examples/alert-crashloop.json)
[[ $code == 401 ]] || { echo "expected 401, got $code"; exit 1; }
curl -sf -X POST $url -H "Authorization: Bearer $token" \
  -H 'Content-Type: application/json' -d @examples/alert-crashloop.json
curl -sf localhost:18080/metrics | grep -q aiops_triages_total
echo; echo "deploy smoke ok"
