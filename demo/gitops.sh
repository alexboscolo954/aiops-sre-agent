#!/usr/bin/env bash
# STAND-INS, not ArgoCD or Flux: their CRDs' group/version/plural with any fields
# allowed, and objects whose status is written here, so recent_changes and the RBAC
# overlay run against the real API without the controllers. Times are relative to
# now. orders' objects are demo-shop's; bank-ledger is demo-bank's, in the same
# shared namespaces.
set -euo pipefail
ctx=$1
k() { kubectl --context "$ctx" "$@"; }
ago() { date -u -d "-$1 minutes" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-"$1"M +%Y-%m-%dT%H:%M:%SZ; }
crd() {  # group version kind plural
  k apply -f - <<YAML
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: {name: $4.$1}
spec:
  group: $1
  scope: Namespaced
  names: {kind: $3, plural: $4, singular: $(tr '[:upper:]' '[:lower:]' <<<"$3")}
  versions:
    - name: $2
      served: true
      storage: true
      schema: {openAPIV3Schema: {type: object, x-kubernetes-preserve-unknown-fields: true}}
YAML
}
crd argoproj.io v1alpha1 Application applications
crd kustomize.toolkit.fluxcd.io v1 Kustomization kustomizations
crd helm.toolkit.fluxcd.io v2 HelmRelease helmreleases
k wait --for=condition=Established crd --all --timeout=60s >/dev/null
for ns in argocd flux-system; do k create namespace $ns --dry-run=client -o yaml | k apply -f -; done
k apply -f - <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: orders, namespace: argocd}
spec:
  destination: {server: https://kubernetes.default.svc, namespace: orders}
status:
  resources:
    - {kind: Deployment, namespace: orders, name: inventory}
    - {kind: Deployment, namespace: orders, name: orders-api}
  history:
    - {id: 1, revision: 1b2c3d4, deployedAt: "$(ago 45)", source: {repoURL: "https://git.example/shop/deploy", path: orders}}
    - {id: 2, revision: 9e8f7a6, deployedAt: "$(ago 4)", source: {repoURL: "https://git.example/shop/deploy", path: orders}}
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: bank-ledger, namespace: argocd}
spec:
  destination: {server: https://kubernetes.default.svc, namespace: bank}
status:
  history:
    - {id: 1, revision: bank001, deployedAt: "$(ago 3)", source: {repoURL: "https://git.example/bank/deploy", path: ledger}}
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata: {name: orders, namespace: flux-system}
spec: {targetNamespace: orders}
status:
  inventory: {entries: [{id: orders_inventory_apps_Deployment, v: v1}]}
  history:
    - {firstReconciled: "$(ago 4)", lastReconciledStatus: ReconciliationSucceeded, metadata: {revision: "main@sha1:9e8f7a6"}}
    - {firstReconciled: "$(ago 45)", lastReconciledStatus: ReconciliationSucceeded, metadata: {revision: "main@sha1:1b2c3d4"}}
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata: {name: bank-ledger, namespace: flux-system}
spec: {targetNamespace: bank}
status:
  history:
    - {version: 1, action: install, status: deployed, chartName: ledger, chartVersion: 2.0.0, namespace: bank, lastDeployed: "$(ago 2)"}
YAML
echo "ok: GitOps stand-ins in argocd and flux-system"
