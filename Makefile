CLUSTER := aiops
CTX     := kind-$(CLUSTER)

.PHONY: lint test cluster demo integration down

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

integration: ## real MCP tools against the kind demo (never another context)
	AIOPS_KUBE_CONTEXT=$(CTX) AIOPS_NAMESPACES=demo uv run pytest -m integration -v

down:
	kind delete cluster --name $(CLUSTER)
