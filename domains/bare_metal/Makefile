DIST_DIR ?= ../../.dist

.PHONY: build reinit test

build:
	uv build --wheel --out-dir $(DIST_DIR)

# Every internal wheel this project declares must be listed. A dependency
# omitted here keeps whatever version the venv already resolved, so tests can
# exercise a stale copy of a package the source tree has since changed.
reinit: ## Force-reinstall internal wheel dependencies. Run make dist from the monorepo root first.
	uv sync --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core            --reinstall-package arkhai-core \
		--upgrade-package arkhai-core-storefront --reinstall-package arkhai-core-storefront

test: reinit
	uv run --find-links $(DIST_DIR) pytest -q
