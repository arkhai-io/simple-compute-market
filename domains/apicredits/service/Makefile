# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../.python-version 2>/dev/null),$(error ../../../.python-version not found))

.PHONY: help install reinit test serve build clean

.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

DIST_DIR ?= ../../../.dist

install: reinit ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }

reinit: ## Sync this environment, refreshing the internal wheels its lock installs. Run make dist first.
	python3 ../../../scripts/uv_project.py reinit

test: reinit ## Run the test suite
	uv run --find-links $(DIST_DIR) pytest tests -q

serve: ## Run the service locally (reload)
	uv run --find-links $(DIST_DIR) python -m apicredits_service.main

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

clean: ## Remove build artifacts
	rm -rf build dist *.egg-info
