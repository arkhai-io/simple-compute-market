DIST_DIR ?= ../../.dist
PYTHON ?= 3.12

.PHONY: build dist-identity reinit test check-vectors check-generated typecheck generate-models

build:
	uv build --wheel --out-dir $(DIST_DIR)

dist-identity:
	mkdir -p $(DIST_DIR)
	uv build --no-sources --wheel --out-dir $(DIST_DIR) ../identity

reinit: dist-identity
	uv sync --dev --python $(PYTHON) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity

test: reinit typecheck check-vectors check-generated

typecheck:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) mypy src examples/local_e2e.py

check-vectors:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) python scripts/check_vectors.py

check-generated:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) python scripts/generate_models.py --check

generate-models:
	uv run --python $(PYTHON) --find-links $(DIST_DIR) python scripts/generate_models.py
