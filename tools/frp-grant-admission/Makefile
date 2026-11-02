# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

# The floor run's environment, apart from the project's: building it never touches the
# committed uv.lock or .venv. It is named .venv, as every environment here is, so the
# repository's scans skip the third-party code installed in it.
FLOOR_ENV := .floor/.venv

.PHONY: build test test-frp test-floor

build: ## Build the plugin's wheel into dist/
	uv build --wheel --out-dir dist

test: ## Run the unit and in-process integration tests; needs no network, and the real-frp tests skip without binaries
	uv run pytest tests -q

test-frp: ## Fetch and verify the frp pinned in frp-pins.toml, then run the real-frp tests; fails if any skips or none runs
	FRP_GATE=1 uv run pytest tests/frp -q -rs

# pyproject.toml's runtime dependencies, read as direct requirements, so lowest-direct
# resolution installs each at its declared floor; tests.floor fails the run unless it
# did.
test-floor: ## Run the unit tests, the vector included, with PyJWT and cryptography at their declared floors; needs the network
	uv venv --clear $(FLOOR_ENV)
	uv pip install --python $(FLOOR_ENV) --resolution lowest-direct -r pyproject.toml --group dev
	uv pip install --python $(FLOOR_ENV) --no-deps -e .
	$(FLOOR_ENV)/bin/python -m tests.floor
	$(FLOOR_ENV)/bin/python -m pytest tests/unit -q
