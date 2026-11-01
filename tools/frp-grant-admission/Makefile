# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

.PHONY: test test-frp

test: ## Run the unit and in-process integration tests; needs no network, and the real-frp tests skip without binaries
	uv run pytest tests -q

test-frp: ## Fetch and verify the frp pinned in frp-pins.toml, then run the real-frp tests; fails if any skips or none runs
	FRP_GATE=1 uv run pytest tests/frp -q -rs
