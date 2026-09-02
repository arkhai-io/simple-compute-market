.PHONY: help install reinit serve worker migrate test test-unit test-integration clean build build-image deploy

.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

DIST_DIR ?= ../../../.dist
# Podman does not reliably invalidate a runtime-stage COPY when only the
# referenced builder stage changes. Include the wheel set in the runtime cache
# key so a rebuilt adapter/service can never be hidden by a stale final stage.
DIST_FINGERPRINT := $(shell find $(DIST_DIR) -maxdepth 1 -type f -name '*.whl' -exec cksum {} + 2>/dev/null | LC_ALL=C sort | cksum | awk '{print $$1}')
IAC_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../domains/vms/provisioning/iac)

install: ## Install service and development dependencies
	uv sync --dev --find-links $(DIST_DIR)

reinit: ## Refresh local internal packages and adapters
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-compute-provisioning --reinstall-package arkhai-compute-provisioning \
		--upgrade-package arkhai-compute-provisioning-service --reinstall-package arkhai-compute-provisioning-service \
		--upgrade-package arkhai-vms-provisioning-adapter --reinstall-package arkhai-vms-provisioning-adapter \
		--upgrade-package arkhai-vms-provisioning-operator-client --reinstall-package arkhai-vms-provisioning-operator-client \
		--upgrade-package arkhai-vms --reinstall-package arkhai-vms \
		--upgrade-package arkhai-bare-metal --reinstall-package arkhai-bare-metal \
		--upgrade-package arkhai-bare-metal-provisioning-adapter --reinstall-package arkhai-bare-metal-provisioning-adapter \
		--upgrade-package arkhai-kit-site --reinstall-package arkhai-kit-site \
		--upgrade-package arkhai-kit-resource-pools --reinstall-package arkhai-kit-resource-pools \
		--upgrade-package arkhai-kit-fulfillment --reinstall-package arkhai-kit-fulfillment \
		--upgrade-package arkhai-kit-site-client --reinstall-package arkhai-kit-site-client \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-core --reinstall-package arkhai-core \
		--upgrade-package arkhai-core-storefront-client --reinstall-package arkhai-core-storefront-client

serve: ## Start the compute provisioning API and in-process workers
	PROVISIONING_INVENTORY_PATH="$(IAC_DIR)/ansible/inventory/hosts" \
	PROVISIONING_PLAYBOOK_PATH="$(IAC_DIR)/ansible/playbooks/single-tenant/vm-operations.yaml" \
	PROVISIONING_MANAGEMENT_VARS_PATH="$(IAC_DIR)/ansible/inventory/management-vars.yaml" \
	ANSIBLE_CONFIG="$(IAC_DIR)/ansible/ansible.cfg" \
	uv run compute-provisioning-api

worker: ## Start the background-only worker role
	uv run compute-provisioning-worker

migrate: ## Apply ordered service-owned database migrations
	uv run compute-provisioning-migrate

test: reinit test-unit test-integration ## Run destination service tests

test-unit: ## Run unit tests
	ACTIVE_PROFILES=mock uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-integration: ## Run integration tests
	ACTIVE_PROFILES=mock uv run --find-links $(DIST_DIR) pytest tests/integration -q

clean: ## Remove generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov

IMAGE_NAME ?= arkhai
IMAGE_TAG ?= compute-provisioning
GIT_SUFFIX := $(shell git rev-parse --short HEAD)
APPUSER_UID ?= 1000
APPUSER_GID ?= 1000

build: build-image ## Build the compute provisioning image

build-image: ## Build the wheel-only destination image
	docker build \
		--ulimit nofile=65536 \
		--build-arg APPUSER_UID=$(APPUSER_UID) \
		--build-arg APPUSER_GID=$(APPUSER_GID) \
		--build-arg DIST_FINGERPRINT=$(DIST_FINGERPRINT) \
		-t $(IMAGE_NAME):$(IMAGE_TAG) \
		-f Dockerfile ../../..
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(IMAGE_TAG)-$(GIT_SUFFIX)

deploy: ## Run the destination image with mock provisioning
	docker run -d --rm --name compute-provisioning \
		-e ACTIVE_PROFILES=docker,mock \
		--network market -p 8081:8081 \
		$(IMAGE_NAME):$(IMAGE_TAG)
