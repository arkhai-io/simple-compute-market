DIST_DIR ?= ../../../.dist

.PHONY: init reinit test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

# Reinstall all internal wheel dependencies when iterating on kit or core packages.
# Run the relevant dist-* targets from the monorepo root first.
# This project ships its own modules into its venv (a force-include wheel), so a
# source edit is invisible until the wheel is replaced -- and uv will not replace
# a wheel whose version has not changed. Reinstalling itself is what makes
# `make test` test the working tree rather than whatever was installed first.
reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core              --reinstall-package arkhai-core \
		--upgrade-package arkhai-apicredits-domain --reinstall-package arkhai-apicredits-domain \
		--upgrade-package arkhai-core-buyer        --reinstall-package arkhai-core-buyer \
		--upgrade-package arkhai-kit-alkahest      --reinstall-package arkhai-kit-alkahest \
		--upgrade-package arkhai-kit-config        --reinstall-package arkhai-kit-config \
		--upgrade-package arkhai-kit-policy        --reinstall-package arkhai-kit-policy \
		--upgrade-package arkhai-apicredits-buyer --reinstall-package arkhai-apicredits-buyer

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests -q
