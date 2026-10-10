#!/usr/bin/env bash
# Run the real image on kind with the shipped manifests: pod starts under the
# hardened securityContext, health and auth behave, a webhook is accepted.
set -euo pipefail
ctx=$1
k() { kubectl --context "$ctx" "$@"; }
k create namespace aiops --dry-run=client -o yaml | k apply -f -
k -n aiops create secret generic aiops-secrets \
  --from-literal=AIOPS_WEBHOOK_TOKEN=smoke-token --from-literal=AIOPS_APPROVER_TOKEN=smoke-approver --from-literal=AIOPS_MODEL_API_KEY=not-a-real-key \
  --dry-run=client -o yaml | k apply -f -
kubectl kustomize deploy/base \
  | sed 's#ghcr.io/alexboscolo954/aiops-sre-agent:0.1.0#aiops-sre-agent:ci#' \
  | k apply -f -
k -n aiops rollout status deploy/aiops-agent --timeout=3m
k -n aiops port-forward svc/aiops-agent 18080:8080 >/dev/null & pf=$!
trap 'kill $pf' EXIT; sleep 3
curl -sf localhost:18080/healthz
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:18080/alertmanager \
  -H 'Authorization: Bearer wrong' -H 'Content-Type: application/json' -d @examples/alert-crashloop.json)
[[ $code == 401 ]] || { echo "expected 401, got $code"; exit 1; }
curl -sf -X POST localhost:18080/alertmanager -H 'Authorization: Bearer smoke-token' \
  -H 'Content-Type: application/json' -d @examples/alert-crashloop.json
curl -sf localhost:18080/metrics | grep -q aiops_triages_total
echo; echo "deploy smoke ok"
