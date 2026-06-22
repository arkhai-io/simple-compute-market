# Path to the monorepo .dist/ wheel directory, relative to core/buyer/.
# Used by uv when resolving pure-Python internal packages distributed as wheels
# (arkhai-core, arkhai-kit-alkahest, arkhai-kit-config, arkhai-kit-policy).
# The rule is: no [tool.uv.sources] path entries with ../ in this file; all
# cross-package internal dependencies resolve exclusively from .dist/ wheels
# via --find-links on the CLI.
DIST_DIR ?= $(abspath $(CURDIR)/../../.dist)

.PHONY: init reinit test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

# Reinstall all internal wheel dependencies when iterating on kit packages.
# Run make dist-core / dist-alkahest / dist-config / dist-policy from the
# monorepo root first to ensure .dist/ has fresh wheels.
reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core         --reinstall-package arkhai-core \
		--upgrade-package arkhai-kit-alkahest --reinstall-package arkhai-kit-alkahest \
		--upgrade-package arkhai-kit-config   --reinstall-package arkhai-kit-config \
		--upgrade-package arkhai-kit-policy   --reinstall-package arkhai-kit-policy

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests/unit -q
