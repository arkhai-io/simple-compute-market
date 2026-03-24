# Makefile — arkhai-e2e-tests
# -----------------------------------------------------------------------
# Targets are designed to work both locally and inside CI pipelines.
# Set CONFIG_DIRECTORY and ACTIVE_PROFILES before running test targets,
# or rely on the .env file for local development.
# -----------------------------------------------------------------------

PYTHON      ?= python3
ARKHAI_TEST := .venv/bin/arkhai-test

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