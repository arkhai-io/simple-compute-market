DIST_DIR ?= ../../.dist
PYTHON_VERSION ?= 3.13

.PHONY: build init reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: ## Create or update the environment from repository-built wheels
	uv venv --allow-existing --python $(PYTHON_VERSION)
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR)

reinit: ## Reinstall internal kit dependencies from the shared wheel directory
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-site \
		--upgrade-package arkhai-kit-resource-pools \
		--upgrade-package arkhai-kit-identity \
		--reinstall-package arkhai-kit-site \
		--reinstall-package arkhai-kit-resource-pools \
		--reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-capability-shape --reinstall-package arkhai-kit-capability-shape

test: reinit ## Run the test suite against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q
