.PHONY: help install serve test test-unit test-integration clean build build-image deploy docker-run-dev

.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }
	uv sync --dev

# ── Paths ─────────────────────────────────────────────────────────────────────
# Absolute path to compute-provisioning-iac, resolved from this Makefile's
# directory regardless of where make is invoked from.
IAC_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../compute-provisioning-iac)

# ── Local dev ─────────────────────────────────────────────────────────────────

serve: ## Start the unified API + job processing server locally
	PYTHONPATH=src \
	PROVISIONING_INVENTORY_PATH="$(IAC_DIR)/ansible/inventory/hosts" \
	PROVISIONING_PLAYBOOK_PATH="$(IAC_DIR)/ansible/playbooks/single-tenant/vm-operations.yaml" \
	PROVISIONING_MANAGEMENT_VARS_PATH="$(IAC_DIR)/ansible/inventory/management-vars.yaml" \
	ANSIBLE_CONFIG="$(IAC_DIR)/ansible/ansible.cfg" \
	uv run uvicorn main:app --host 0.0.0.0 --port 8081 --reload

# ── Tests ─────────────────────────────────────────────────────────────────────

test: test-unit test-integration ## Run all tests

test-unit: ## Run unit tests
	PYTHONPATH=src uv run pytest src/tests/unit/ -v

test-integration: ## Run integration tests (no real Ansible or DB required — mocked at boundary)
	PYTHONPATH=src uv run pytest src/tests/integration/ -v

clean: ## Remove generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov

# ── Docker ────────────────────────────────────────────────────────────────────

IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= provisioning
GIT_SUFFIX := $(shell git rev-parse --short HEAD)
SSH_KEY    ?= $(HOME)/.ssh/id_ed25519
ENV_FILE   ?= .env.docker-compose

build: build-image ## Build the provisioning service image

build-image: ## Build a single unified image
	docker build \
		-t $(IMAGE_NAME):$(IMAGE_TAG) \
		-f Dockerfile ..
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(IMAGE_TAG)-$(GIT_SUFFIX)

deploy: deploy-provisioning ## Deploy the provisioning service container

deploy-provisioning: ## Run the provisioning container (mock provisioning)
	docker run -d --rm --name provisioning \
	-e ACTIVE_PROFILES=docker,mock \
	--network market -p 8081:8081 \
	-v "$(SSH_KEY):/home/appuser/.ssh/id_ed25519:ro" \
	$(IMAGE_NAME):$(IMAGE_TAG)

docker-run-dev: ## Run the service with host IaC + SSH key mounted (local dev)
	docker run --rm \
	-e ACTIVE_PROFILES=docker,mock \
	--network market -p 8081:8081 \
	-v "$(IAC_DIR):/opt/compute-provisioning-iac" \
	-v "$(SSH_KEY):/home/appuser/.ssh/id_ed25519:ro" \
	$(IMAGE_NAME):$(IMAGE_TAG)