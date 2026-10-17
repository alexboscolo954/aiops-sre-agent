CLUSTER := aiops
CTX     := kind-$(CLUSTER)
PG      := postgres:17.10

.PHONY: lint test db cluster demo integration image snapshots deploy-smoke hub-smoke rbac-check down

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

test: db
	uv run pytest --cov=aiops_agent --cov-report=term-missing

db: ## throwaway Postgres for the tests; each test gets its own database in it
	docker ps --format '{{.Names}}' | grep -qx aiops-pg || docker run -d --rm --name aiops-pg \
	  -e POSTGRES_PASSWORD=postgres -p 55432:5432 $(PG) >/dev/null
	until docker exec aiops-pg pg_isready -h 127.0.0.1 -U postgres -q; do sleep 0.5; done

cluster:
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --config demo/kind.yaml

demo: ## broken workloads in namespace demo; checkout breaks via a rollout
	kubectl --context $(CTX) apply -f demo/apps.yaml
	kubectl --context $(CTX) -n demo rollout status deploy/checkout --timeout=5m
	kubectl --context $(CTX) -n demo set env deploy/checkout DATABASE_URL-
	./demo/wait-broken.sh $(CTX)

integration: ## real MCP tools on the kind demo, as the demo Contracts (kind contexts only)
	uv run pytest -m integration -v

image:
	docker build -t aiops-sre-agent:ci .

snapshots: image ## vendors' tool schemas, from the pinned binaries in the image
	docker run --rm aiops-sre-agent:ci integrations snapshot grafana --out - \
	  >src/aiops_agent/servers/snapshots/grafana.json.tmp
	mv src/aiops_agent/servers/snapshots/grafana.json.tmp src/aiops_agent/servers/snapshots/grafana.json

deploy-smoke: image ## real image + shipped manifests on kind
	kind load docker-image aiops-sre-agent:ci --name $(CLUSTER)
	./demo/deploy-smoke.sh $(CTX)
	./demo/rbac-check.sh $(CTX)
	kubectl kustomize deploy/actions | grep -q 'enable_actions: true'  # the overlay turns actions on
	kubectl --context $(CTX) apply -f deploy/actions/rbac-actions.yaml
	./demo/rbac-check.sh $(CTX) true

hub-smoke: image ## the Hub's compose stack: health, public boundary, backups, contracts updates
	./demo/hub-smoke.sh aiops-sre-agent:ci

down:
	kind delete cluster --name $(CLUSTER)
	docker rm -f aiops-pg >/dev/null 2>&1 || true
