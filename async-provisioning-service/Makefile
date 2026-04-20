.PHONY: help install serve worker clean build build-images deploy deploy-redis deploy-provisioning deploy-worker docker-run-dev

.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }
	uv sync --dev

serve: ## Start the API server locally
	PYTHONPATH=src uv run python -m async_provisioning_service.main

worker: ## Start the background worker locally
	PYTHONPATH=src uv run python -m async_provisioning_service.worker

clean: ## Remove generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov

# ── Docker ───────────────────────────────────────────────────────────

IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= provisioning
GIT_SUFFIX := $(shell git rev-parse --short HEAD)
ENV_FILE   ?= .env.docker-compose

build: build-images

build-images:
	docker build \
		--build-arg ENTRYPOINT_SCRIPT=start-api.sh \
		-t $(IMAGE_NAME):$(IMAGE_TAG)-api \
		-f Dockerfile ..
	docker tag $(IMAGE_NAME):$(IMAGE_TAG)-api $(IMAGE_NAME):$(IMAGE_TAG)-api-$(GIT_SUFFIX)
	docker build \
		--build-arg ENTRYPOINT_SCRIPT=start-worker.sh \
		-t $(IMAGE_NAME):$(IMAGE_TAG)-worker \
		-f Dockerfile ..
	docker tag $(IMAGE_NAME):$(IMAGE_TAG)-worker $(IMAGE_NAME):$(IMAGE_TAG)-worker-$(GIT_SUFFIX)

deploy: deploy-redis deploy-provisioning deploy-worker ## Deploy redis, API, and worker containers

deploy-redis:
	docker run -d --rm --name redis \
	--network market -p 6379:6379 \
	--health-cmd "redis-cli ping" --health-interval 10s --health-timeout 3s --health-retries 3 \
	redis:7-alpine

deploy-provisioning:
	docker run -d --rm --name provisioning \
	--env-file $(ENV_FILE) \
	--network market -p 8081:8081 \
	$(IMAGE_NAME):$(IMAGE_TAG)-api

deploy-worker:
	docker run -d --rm --name provisioning-worker \
	--env-file $(ENV_FILE) \
	--network market -p 8082:8082 \
	$(IMAGE_NAME):$(IMAGE_TAG)-worker

docker-run-dev: ## Run API + worker with host IaC + SSH keys mounted
	docker run --rm --env-file $(ENV_FILE) -p 8081:8081 \
	--add-host=host.docker.internal:host-gateway \
	-e REDIS_URL=redis://host.docker.internal:6379/0 \
	-v "$$(cd .. && pwd)/compute-provisioning-iac:/app/compute-provisioning-iac" \
	$(IMAGE_NAME):$(IMAGE_TAG)-api &
	docker run --rm --env-file $(ENV_FILE) \
	--add-host=host.docker.internal:host-gateway \
	-e REDIS_URL=redis://host.docker.internal:6379/0 \
	-v "$$(cd .. && pwd)/compute-provisioning-iac:/app/compute-provisioning-iac" \
	-v "$$HOME/.ssh/id_ed25519:/home/appuser/.ssh/id_ed25519:ro" \
	$(IMAGE_NAME):$(IMAGE_TAG)-worker
