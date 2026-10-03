DIST_DIR ?= ../../.dist
PYTHON ?= 3.12
.PHONY: build dist-core dist-identity dist-settlement-runtime reinit test test-unit check-vectors check-generated typecheck generate-models

build:
	uv build --wheel --out-dir $(DIST_DIR)

dist-core:
	mkdir -p $(DIST_DIR)
	uv build --no-sources --wheel --out-dir $(DIST_DIR) ../../core

dist-identity:
	mkdir -p $(DIST_DIR)
	uv build --no-sources --wheel --out-dir $(DIST_DIR) ../identity

dist-settlement-runtime: dist-core dist-identity
	mkdir -p $(DIST_DIR)
	uv build --no-sources --wheel --out-dir $(DIST_DIR) ../settlement-runtime

reinit: dist-core dist-identity dist-settlement-runtime
	uv sync --dev --python $(PYTHON) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core --reinstall-package arkhai-core \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-settlement-runtime --reinstall-package arkhai-kit-settlement-runtime

test: reinit typecheck check-vectors check-generated test-unit

test-unit:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) pytest tests -q
typecheck:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) mypy src examples/local_e2e.py

check-vectors:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) python scripts/check_vectors.py

check-generated:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) python scripts/generate_models.py --check

generate-models:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) python scripts/generate_models.py
