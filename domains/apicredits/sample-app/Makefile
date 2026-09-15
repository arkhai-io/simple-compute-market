DIST_DIR ?= ../../../.dist

.PHONY: init reinit test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

# Reinstall arkhai-apicredits-middleware when iterating on it.
# Run make dist-apicredits-middleware from the monorepo root first.
#
# arkhai-kit-identity is refreshed alongside it because the app requires
# the middleware's `signed` extra, which resolves to that wheel out of
# $(DIST_DIR). Upgrading only the middleware would re-resolve the extra
# against whatever identity wheel is already pinned in uv.lock, so
# iterating on kit/identity would silently test a stale copy.
reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
		--upgrade-package arkhai-apicredits-middleware --reinstall-package arkhai-apicredits-middleware \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests -q
