DIST_DIR ?= ../../../.dist

.PHONY: init reinit test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

# Reinstall arkhai-apicredits-middleware when iterating on it.
# Run make dist-apicredits-middleware from the monorepo root first.
reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
		--upgrade-package arkhai-apicredits-middleware --reinstall-package arkhai-apicredits-middleware

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests -q
