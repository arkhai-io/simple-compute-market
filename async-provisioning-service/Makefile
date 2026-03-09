.PHONY: help install serve worker clean docker-build docker-run docker-run-dev

.DEFAULT_GOAL := help

ENV_FILE ?= .env.local

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }
	uv sync --dev

serve: ## Start the API server
	PYTHONPATH=src uv run python -m async_provisioning_service.main

worker: ## Start the background worker
	PYTHONPATH=src uv run python -m async_provisioning_service.worker

clean: ## Remove generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov

# ── Docker ───────────────────────────────────────────────────────────

IMAGE_NAME ?= async-provisioning-service
IMAGE_TAG  ?= latest

docker-build: ## Build Docker image (from repo root)
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) -f Dockerfile ..

docker-run: ## Run with baked-in IaC
	docker run --rm --env-file $(ENV_FILE) -p 8081:8081 \
		--add-host=host.docker.internal:host-gateway \
		-e REDIS_URL=redis://host.docker.internal:6379/0 \
		-e DATABASE_URL=postgresql+psycopg2://postgres:postgres@host.docker.internal:5432/provisioning \
		$(IMAGE_NAME):$(IMAGE_TAG)

docker-run-dev: ## Run with host IaC + SSH keys mounted
	docker run --rm --env-file $(ENV_FILE) -p 8081:8081 \
		--add-host=host.docker.internal:host-gateway \
		-e REDIS_URL=redis://host.docker.internal:6379/0 \
		-v $$(cd .. && pwd)/compute-provisioning-iac:/app/compute-provisioning-iac \
		-v $$HOME/.ssh/id_ed25519:/home/appuser/.ssh/id_ed25519:ro \
		$(IMAGE_NAME):$(IMAGE_TAG)
