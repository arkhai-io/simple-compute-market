DIST_DIR ?= ../../../.dist

.PHONY: init reinit test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

# Reinstall arkhai-apitokens-middleware when iterating on it.
# Run make dist-apitokens-middleware from the monorepo root first.
reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
		--upgrade-package arkhai-apitokens-middleware --reinstall-package arkhai-apitokens-middleware

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests -q
