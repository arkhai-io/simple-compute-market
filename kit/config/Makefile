# Path to the monorepo .dist/ wheel directory, relative to kit/config/.
# Used by uv when resolving pure-Python internal packages distributed as wheels.
# The rule is: no [tool.uv.sources] path entries with ../ in this file; all
# cross-package internal dependencies resolve exclusively from .dist/ wheels
# via --find-links on the CLI.
DIST_DIR ?= ../../.dist

.PHONY: init reinit test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

# Reinstall the shared settlement contracts while iterating locally.
reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-settlement-runtime --reinstall-package arkhai-kit-settlement-runtime

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests/unit -q
