CLUSTER := squero
CTX     := kind-$(CLUSTER)
PG      := pgvector/pgvector:0.8.7-pg17-trixie

.PHONY: console-dev console-types console-check lint test db cluster demo lgtm lab lab-grafana integration image snapshots deploy-smoke hub-smoke rbac-check down

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

test: db
	uv run pytest --cov=squero --cov-report=term-missing

db: ## throwaway Postgres for the tests; each test gets its own database in it
	docker ps --format '{{.Names}}' | grep -qx squero-pg || docker run -d --rm --name squero-pg \
	  -e POSTGRES_PASSWORD=postgres -p 55432:5432 $(PG) >/dev/null
	until docker exec squero-pg pg_isready -h 127.0.0.1 -U postgres -q; do sleep 0.5; done

cluster:
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --config demo/kind.yaml

demo: ## broken workloads in namespaces demo and orders; checkout and inventory break via rollouts
	kubectl --context $(CTX) apply -f demo/apps.yaml
	kubectl --context $(CTX) -n demo rollout status deploy/checkout --timeout=5m
	kubectl --context $(CTX) -n demo set env deploy/checkout DATABASE_URL-
	kubectl --context $(CTX) -n orders rollout status deploy/inventory deploy/orders-api --timeout=5m
	kubectl --context $(CTX) -n orders set env deploy/inventory API_VERSION=v2
	./demo/wait-broken.sh $(CTX)
	./demo/gitops.sh $(CTX)

lgtm: ## Grafana LGTM + synthetic logs and traces (Grafana Scenarios; not in CI)
	kubectl --context $(CTX) apply -f demo/lgtm.yaml
	kubectl --context $(CTX) -n shop create configmap telemetry --from-file=demo/telemetry.py \
	  --dry-run=client -o yaml | kubectl --context $(CTX) apply -f -
	kubectl --context $(CTX) -n observability rollout status deploy/lgtm --timeout=10m
	kubectl --context $(CTX) -n shop rollout restart deploy/payments deploy/storefront
	kubectl --context $(CTX) -n shop rollout status deploy/payments deploy/storefront --timeout=5m

KPS := 92.11.0
METRICS_SERVER := 3.14.0
# LAB=small: the lab for a host with 4 CPUs (demo/lab/small). On another host:
#   make lab-remote LAB_HOST=<ssh name> LAB_ADDR=<its private address>
#   make lab LAB=small CLUSTER=lab KUBECONFIG=$(LAB_KUBECONFIG)
LAB := full
LAB_KUBECONFIG := $(HOME)/k8s_clusters/lab.yaml
LAB_CPUS := 2.5
LAB_MEMORY := 6g

lab: ## persistent optimizer lab: kube-prometheus-stack, metrics-server (the HPA's) + load generators in namespace lab. Its 30 days of history live in the kind node: `kind delete cluster` erases them
	for i in 1 2 3 4 5; do helm upgrade --install kps kube-prometheus-stack \
	  --repo https://prometheus-community.github.io/helm-charts --version $(KPS) \
	  --kube-context $(CTX) -n monitoring --create-namespace -f demo/lab/values.yaml \
	  --wait --timeout 15m && break; echo "retry $$i"; sleep 20; done
	helm upgrade --install metrics-server metrics-server \
	  --repo https://kubernetes-sigs.github.io/metrics-server/ --version $(METRICS_SERVER) \
	  --kube-context $(CTX) -n kube-system --set 'args={--kubelet-insecure-tls}' \
	  --wait --timeout 5m
	kubectl --context $(CTX) create namespace lab --dry-run=client -o yaml \
	  | kubectl --context $(CTX) apply -f -
	kubectl --context $(CTX) -n lab create configmap load --from-file=demo/lab/load.py \
	  --dry-run=client -o yaml | kubectl --context $(CTX) apply -f -
ifeq ($(LAB),small)
	kubectl kustomize --load-restrictor LoadRestrictionsNone demo/lab/small \
	  | kubectl --context $(CTX) apply -f -
else
	kubectl --context $(CTX) apply -f demo/lab/workloads.yaml
endif
	kubectl --context $(CTX) -n lab rollout status deploy/web deploy/api deploy/spiky deploy/idle --timeout=5m

lab-remote: ## a kind cluster `lab` on another host that never sleeps (ssh name LAB_HOST, with kind and Docker), its API server and Prometheus on LAB_ADDR only (the host's private address), its node capped at LAB_CPUS and LAB_MEMORY so the host's own services keep theirs; the kubeconfig lands in LAB_KUBECONFIG
	test -n "$(LAB_HOST)" && test -n "$(LAB_ADDR)"
	sed 's/LAB_ADDR/$(LAB_ADDR)/' demo/lab/kind-remote.yaml \
	  | ssh $(LAB_HOST) 'PATH=$$HOME/.local/bin:$$PATH kind create cluster --config -'
	ssh $(LAB_HOST) 'docker update --cpus $(LAB_CPUS) --memory $(LAB_MEMORY) --memory-swap $(LAB_MEMORY) --restart unless-stopped lab-control-plane'
	ssh $(LAB_HOST) 'PATH=$$HOME/.local/bin:$$PATH kind get kubeconfig --name lab' > $(LAB_KUBECONFIG)
	chmod 600 $(LAB_KUBECONFIG)

lab-grafana: ## the lab's Grafana on http://localhost:3000 (admin / lab-only)
	kubectl --context $(CTX) -n monitoring port-forward svc/kps-grafana 3000:80

integration: ## real MCP tools on the kind demo, as the demo Contracts (kind contexts only)
	uv run pytest -m integration -v

image:
	docker build -t squero:ci .

NODE := node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914
NPM := docker run --rm -v "$(CURDIR)/console:/w" -w /w $(NODE) npm

console-types: ## the console app's API types, from the Hub's OpenAPI (commit both)
	uv run python -c "from squero.webapp import openapi; print(openapi(), end='')" > console/openapi.json
	$(NPM) run -s types

console-check: ## the console app: install, types in sync, typecheck, lint, test, build
	$(NPM) ci --ignore-scripts --no-fund --no-audit
	$(MAKE) console-types
	git diff --exit-code console/openapi.json console/src/api-types.ts
	$(NPM) run -s typecheck
	$(NPM) run -s lint
	$(NPM) test
	$(NPM) run -s build

console-dev: ## Vite on 127.0.0.1:5173 against a local Hub (SQUERO_DEV_HUB, SQUERO_DEV_LOGIN)
	cd console && npm ci --no-fund --no-audit && npm run dev

snapshots: image ## vendors' tool schemas, from the pinned binaries in the image
	docker run --rm squero:ci integrations snapshot grafana --out - \
	  >src/squero/servers/snapshots/grafana.json.tmp
	mv src/squero/servers/snapshots/grafana.json.tmp src/squero/servers/snapshots/grafana.json
	docker run --rm squero:ci integrations snapshot azure --out - \
	  >src/squero/servers/snapshots/azure.json.tmp
	mv src/squero/servers/snapshots/azure.json.tmp src/squero/servers/snapshots/azure.json
	docker run --rm squero:ci integrations snapshot gcp --out - \
	  >src/squero/servers/snapshots/gcp.json.tmp
	mv src/squero/servers/snapshots/gcp.json.tmp src/squero/servers/snapshots/gcp.json

deploy-smoke: image ## real image + shipped manifests on kind
	kind load docker-image squero:ci --name $(CLUSTER)
	./demo/deploy-smoke.sh $(CTX)
	./demo/rbac-check.sh $(CTX)
	./demo/actuator-smoke.sh $(CTX)
	kubectl kustomize deploy/actions | grep -q 'enable_actions: true'  # the overlay turns actions on
	kubectl --context $(CTX) apply -f deploy/actions/rbac-actions.yaml
	./demo/rbac-check.sh $(CTX) true
	kubectl --context $(CTX) apply -f deploy/gitops/rbac-gitops.yaml
	./demo/rbac-check.sh $(CTX) true true

hub-smoke: image ## the Hub's compose stack: health, public boundary, backups, contracts updates
	./demo/hub-smoke.sh squero:ci

down:
	kind delete cluster --name $(CLUSTER)
	docker rm -f squero-pg >/dev/null 2>&1 || true
