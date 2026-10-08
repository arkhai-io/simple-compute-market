# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../.python-version 2>/dev/null),$(error ../../../.python-version not found))

.PHONY: help init reinit build test clean

.DEFAULT_GOAL := help

DIST_DIR ?= ../../../.dist

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

init: reinit ## Install dependencies from public indexes and internal wheels
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }

reinit: ## Upgrade and reinstall changed internal wheel dependencies
	python3 ../../../scripts/uv_project.py reinit

test: reinit ## Run the storefront package tests
	uv run --find-links $(DIST_DIR) pytest tests -q

build: ## Build the wheel into the shared .dist directory
	uv build --wheel --out-dir $(DIST_DIR)

clean: ## Remove build artifacts
	rm -rf build dist *.egg-info
