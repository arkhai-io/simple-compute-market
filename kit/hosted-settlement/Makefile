# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist
HOSTED_REPO_ROOT := ../..
HOSTED_RELEASE_DIR ?= $(DIST_DIR)
include $(HOSTED_REPO_ROOT)/make/hosted-release.mk

.PHONY: build init reinit test verify-hosted-release

verify-hosted-release:
	$(VERIFY_HOSTED_RELEASE)

# The hosted client is an ordinary external dependency, resolved from an index
# like any other. Verification of the producer's signed release is a
# publication-time concern and gates nothing here: a signed release describes a
# deployed authority, and nothing below deploys one.
build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: reinit ## Create or update the environment

reinit: ## Reinstall the local package environment
	python3 ../../scripts/uv_project.py reinit

test: reinit ## Run the focused unit suite
	uv run pytest tests/unit -q
