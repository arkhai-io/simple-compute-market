PYTHON      ?= python3

# Default profile if none supplied
ACTIVE_PROFILES ?= local
CONFIG_DIRECTORY ?= $(PWD)/config
MODULE ?= contracts

# Path to the monorepo .dist/ wheel directory, relative to integration-tests/.
# Used by uv when resolving pure-Python internal packages (arkhai-vms-buyer,
# arkhai-kit-policy, arkhai-vms-storefront, arkhai-vms-provisioning) that are distributed as wheels rather than editable
# source installs.  The Dockerfile passes --find-links /dist on the uv sync
# CLI instead; this variable is for local development only.
DIST_DIR ?= $(abspath $(CURDIR)/../.dist)

.PHONY: build venv test test-e2e

# -----------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------

init-venv:
	uv venv --allow-existing

init: init-venv
	uv sync --find-links $(DIST_DIR)

reinit: init-venv
	uv sync --find-links $(DIST_DIR) \
	--upgrade-package arkhai-core-registry-client \
	--upgrade-package arkhai-core-storefront-client \
	--upgrade-package arkhai-vms-provisioning \
	--upgrade-package arkhai-vms-storefront \
	--reinstall-package arkhai-core-registry-client \
	--reinstall-package arkhai-core-storefront-client \
	--reinstall-package arkhai-vms-provisioning \
	--reinstall-package arkhai-vms-storefront

# -----------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------

IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= integration-tests
GIT_SUFFIX := $(shell git rev-parse --short HEAD)
PYTHON_VERSION := 3.13

build: build-images

build-images: reinit
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
# Tests — buyer machine (in-network, realistic two-machine topology)
# -----------------------------------------------------------------------
# Runs the buyer-side e2e from a one-shot container attached to the seller's
# compose network, so discovery resolves the registry-advertised seller URL
# (bob-storefront:8001) and the `market` subprocess reaches it directly — no
# host port-forward or --seller override. Uses `docker run` (not `compose
# run`) so it works under daemonless podman, where the docker-compose
# provider can't reach a daemon.
#
# Prereqs: the stack is up (`docker compose up -d`) and the integration-tests
# image is rebuilt with the buyer wheel (`make build` at the repo root, then
# `make -C integration-tests build`).
#
# NETWORK defaults to the compose project's default network
# (<repo-dir>_default). Override if your project name differs.
NETWORK ?= simple-market-service_default
BUYER_MODULE ?= e2e_deal_buyer_cli or e2e_buy
E2E_MODULE ?= e2e_deal or e2e_deal_buyer_cli or e2e_buy or multi_registry \
              or e2e_compute_dynamic_listings or e2e_alkahest_escrow_codecs

test-buyer-machine:
	docker run --rm \
		--network=$(NETWORK) \
		-e ACTIVE_PROFILES=docker \
		-e CONFIG_DIRECTORY=/app/config \
		-v $(CURDIR)/tests:/app/tests:ro \
		-v $(CURDIR)/src:/app/src:ro \
		-v $(CURDIR)/config:/app/config:ro \
		-v $(CURDIR)/conftest.py:/app/conftest.py:ro \
		-v $(CURDIR)/pyproject.toml:/app/pyproject.toml:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		.venv/bin/pytest -m "$(BUYER_MODULE)" $(PYTEST_ARGS)

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
# Tests — full local e2e stack
# -----------------------------------------------------------------------
# Rebuilds the runtime + test images, starts a clean compose stack, then runs
# the buyer-machine scenarios from inside the compose network. This target is
# intentionally heavier than test-module: it verifies the deployed images and
# clears persisted compose state before each run.
test-e2e:
	cd .. && docker compose down -v --remove-orphans
	cd .. && $(MAKE) build-dev
	cd .. && docker compose up -d --wait
	$(MAKE) test-buyer-machine BUYER_MODULE="$(E2E_MODULE)"
