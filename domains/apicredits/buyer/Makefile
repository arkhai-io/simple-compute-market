DIST_DIR ?= ../../../.dist

.PHONY: init reinit test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

# Reinstall all internal wheel dependencies when iterating on kit or core packages.
# Run the relevant dist-* targets from the monorepo root first.
reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
		--reinstall-package arkhai-apicredits-buyer \
		--upgrade-package arkhai-core              --reinstall-package arkhai-core \
		--upgrade-package arkhai-apicredits-domain --reinstall-package arkhai-apicredits-domain \
		--upgrade-package arkhai-core-buyer        --reinstall-package arkhai-core-buyer \
		--upgrade-package arkhai-core-registry-client --reinstall-package arkhai-core-registry-client \
		--upgrade-package arkhai-kit-alkahest      --reinstall-package arkhai-kit-alkahest \
		--upgrade-package arkhai-kit-config        --reinstall-package arkhai-kit-config \
		--upgrade-package arkhai-kit-identity      --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-policy        --reinstall-package arkhai-kit-policy \
		--upgrade-package arkhai-kit-settlement-runtime --reinstall-package arkhai-kit-settlement-runtime

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests -q
