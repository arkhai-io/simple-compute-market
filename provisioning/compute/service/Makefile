# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../.python-version 2>/dev/null),$(error ../../../.python-version not found))

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
BARE_METAL_IAC_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../domains/bare_metal/provisioning/iac)

install: reinit ## Install service and development dependencies

reinit: ## Refresh local internal packages and adapters
	python3 ../../../scripts/uv_project.py reinit

serve: ## Start the compute provisioning API and in-process workers
	PROVISIONING_INVENTORY_PATH="$(IAC_DIR)/ansible/inventory/provisioning-hosts.ini" \
	PROVISIONING_PLAYBOOK_PATH="$(IAC_DIR)/ansible/playbooks/single-tenant/vm-operations.yaml" \
	PROVISIONING_BARE_METAL_PLAYBOOK_PATH="$(BARE_METAL_IAC_DIR)/ansible/playbooks/node-access.yaml" \
	PROVISIONING_MANAGEMENT_VARS_PATH="$(IAC_DIR)/ansible/inventory/management-vars.yaml" \
	uv run --find-links $(DIST_DIR) compute-provisioning-api

worker: ## Start the background-only worker role
	uv run --find-links $(DIST_DIR) compute-provisioning-worker

migrate: ## Apply ordered service-owned database migrations
	uv run --find-links $(DIST_DIR) compute-provisioning-migrate

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
