CLUSTER := aiops
CTX     := kind-$(CLUSTER)

.PHONY: lint test cluster demo integration image deploy-smoke rbac-check down

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

test:
	uv run pytest --cov=aiops_agent --cov-report=term-missing

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

deploy-smoke: image ## real image + shipped manifests on kind
	kind load docker-image aiops-sre-agent:ci --name $(CLUSTER)
	./demo/deploy-smoke.sh $(CTX)
	./demo/rbac-check.sh $(CTX)
	kubectl kustomize deploy/actions | grep -q 'enable_actions: true'  # the overlay turns actions on
	kubectl --context $(CTX) apply -f deploy/actions/rbac-actions.yaml
	./demo/rbac-check.sh $(CTX) true

down:
	kind delete cluster --name $(CLUSTER)
