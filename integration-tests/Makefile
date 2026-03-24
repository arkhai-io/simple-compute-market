# Makefile — arkhai-e2e-tests
# -----------------------------------------------------------------------
# Targets are designed to work both locally and inside CI pipelines.
# Set CONFIG_DIRECTORY and ACTIVE_PROFILES before running test targets,
# or rely on the .env file for local development.
# -----------------------------------------------------------------------

PYTHON      ?= python3

# Default profile if none supplied
ACTIVE_PROFILES ?= local
CONFIG_DIRECTORY ?= $(PWD)/config
MODULE ?= contracts

.PHONY: build venv test

# -----------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------

init-venv:
	uv venv --allow-existing

init: init-venv
	uv sync

# -----------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------

IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= provisioning
GIT_SUFFIX := $(shell git rev-parse --short HEAD)
PYTHON_VERSION := 3.13

build: build-images

build-images:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) -f Dockerfile .
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
# Tests — docker
# -----------------------------------------------------------------------

test-docker:
	docker run --rm -it --network market --name integration-tests $(IMAGE_NAME):$(IMAGE_TAG)