PYTHON      ?= python3

# Default profile if none supplied
ACTIVE_PROFILES ?= local
CONFIG_DIRECTORY ?= $(PWD)/config
MODULE ?= contracts

# Path to the monorepo .dist/ wheel directory, relative to integration-tests/.
# Used by uv when resolving pure-Python internal packages (market-service,
# provisioning-service) that are distributed as wheels rather than editable
# source installs.  The Dockerfile passes --find-links /dist on the uv sync
# CLI instead; this variable is for local development only.
DIST_DIR ?= $(abspath $(CURDIR)/../.dist)

.PHONY: build venv test

# -----------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------

init-venv:
	uv venv --allow-existing

init: init-venv
	uv sync --find-links $(DIST_DIR)

# -----------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------

IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= integration-tests
GIT_SUFFIX := $(shell git rev-parse --short HEAD)
PYTHON_VERSION := 3.13

build: build-images

build-images:
	cd .. && docker build -t $(IMAGE_NAME):$(IMAGE_TAG) -f integration-tests/Dockerfile .
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(IMAGE_TAG)-$(GIT_SUFFIX)

# -----------------------------------------------------------------------
# Tests — local
# -----------------------------------------------------------------------

test:
	ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
	CONFIG_DIRECTORY=$(CONFIG_DIRECTORY) \
	.venv/bin/pytest $(PYTEST_ARGS)

test-module:
	ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
	CONFIG_DIRECTORY=$(CONFIG_DIRECTORY) \
	.venv/bin/pytest -m $(MODULE) $(PYTEST_ARGS)

test-container-module:
	docker run --rm -it \
		--network=market \
		-e ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
		-e CONFIG_DIRECTORY=/app/config \
		-v $(CONFIG_DIRECTORY):/app/config:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		.venv/bin/pytest -m $(MODULE) $(PYTEST_ARGS)

# -----------------------------------------------------------------------
# Tests — CI (HTML report, no colour, exit-on-first-fail)
# -----------------------------------------------------------------------

test-ci:
	ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
	CONFIG_DIRECTORY=$(CONFIG_DIRECTORY) \
	.venv/bin/pytest \
		--html=pytest-report.html \
		--self-contained-html \
		--no-header \
		-p no:cacheprovider \
		$(PYTEST_ARGS)

# -----------------------------------------------------------------------
# E2E Mock Provisioning Tests
# -----------------------------------------------------------------------
# These targets manage the full docker-compose lifecycle + pytest run.
# Usage:
#   make e2e-mock-happy          # happy path only
#   make e2e-mock-failure        # failure path only
# -----------------------------------------------------------------------

REPO_ROOT       := $(shell git -C .. rev-parse --show-toplevel)
COMPOSE         := docker compose -f "$(REPO_ROOT)/docker-compose.yml"
E2E_PROFILE     ?= local,e2e-mock

e2e-clean-dbs:
	rm -f "$(REPO_ROOT)/core/agent/app/data/buy-agent/agent.db" "$(REPO_ROOT)/core/agent/app/data/sell-agent/agent.db"

e2e-wait-ready:
	@echo "Waiting for registry healthcheck..."
	@for i in $$(seq 1 30); do curl -sf http://localhost:8080/health >/dev/null 2>&1 && break; sleep 2; done
	@echo "Waiting for buyer agent HTTP..."
	@for i in $$(seq 1 30); do curl -sf http://localhost:8000/.well-known/agent.json >/dev/null 2>&1 && break; sleep 2; done
	@echo "Waiting for seller agent HTTP..."
	@for i in $$(seq 1 30); do curl -sf http://localhost:8001/.well-known/agent.json >/dev/null 2>&1 && break; sleep 2; done
	@echo "Waiting for agents to register on-chain (~25s)..."
	@for i in $$(seq 1 45); do \
		COUNT=$$(curl -sf http://localhost:8080/agents 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('items',[])))" 2>/dev/null || echo 0); \
		[ "$$COUNT" -ge 2 ] && break; \
		sleep 2; \
	done
	@echo "All services ready."

e2e-mock-happy: e2e-clean-dbs
	$(COMPOSE) down -v
	PROVISIONING_MODE=mock $(COMPOSE) up -d
	$(MAKE) e2e-wait-ready
	ACTIVE_PROFILES=$(E2E_PROFILE) uv run pytest -m mock_provisioning_happy -v --tb=long

e2e-mock-failure: e2e-clean-dbs
	$(COMPOSE) down -v
	PROVISIONING_MODE=mock MOCK_PROVISIONING_SUCCESS=false $(COMPOSE) up -d
	$(MAKE) e2e-wait-ready
	ACTIVE_PROFILES=$(E2E_PROFILE) uv run pytest -m mock_provisioning_failure -v --tb=long
