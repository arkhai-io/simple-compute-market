DIST_DIR ?= ../../.dist

.PHONY: build init reinit test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

reinit: ## Refresh the pinned same-version identity wheel during local iteration
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

test: reinit ## Run the test suite against freshly rebuilt internal wheels
	uv run --find-links $(DIST_DIR) pytest tests/unit -q
