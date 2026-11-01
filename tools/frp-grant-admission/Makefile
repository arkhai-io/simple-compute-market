# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

.PHONY: test

test: ## Run the unit and in-process integration tests; needs no network and no frp binaries
	uv run pytest tests -q
