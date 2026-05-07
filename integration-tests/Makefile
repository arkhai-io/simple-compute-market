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

reinit: init-venv
	uv sync --find-links $(DIST_DIR) \
	--reinstall-package arkhai-registry-client \
	--reinstall-package arkhai-storefront-client \
	--reinstall-package provisioning-service \
	--reinstall-package market-storefront

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
# E2E mock-provisioning targets retired with the buyer-storefront drop.
# The legacy targets (e2e-mock-happy / e2e-mock-failure) ran the
# now-deleted test_mock_provisioning.py against a stack that included a
# buyer-side storefront. After step 5b the buyer is a pure CLI client;
# the equivalent flow is exercised via market_buyer / `market buy` — see
# buyer/tests/test_buy_orchestrator.py for orchestrator coverage and
# (TODO) a future e2e target that drives `market buy` against a
# compose-launched seller.
# -----------------------------------------------------------------------
