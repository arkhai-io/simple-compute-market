.PHONY: help install serve worker clean

.DEFAULT_GOAL := help

ENV_FILE ?= .env.local

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }
	uv sync --dev

serve: ## Start the API server
	PYTHONPATH=src uv run python -m async_provisioning_service.main

worker: ## Start the background worker
	PYTHONPATH=src uv run python -m async_provisioning_service.worker

clean: ## Remove generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov
