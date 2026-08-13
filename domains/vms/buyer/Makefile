REPO_ROOT := $(shell git rev-parse --show-toplevel)
DIST_DIR ?= ../../../.dist

.PHONY: build init reinit test smoke-test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

# This project ships its own modules into its venv (a force-include wheel), so a
# source edit is invisible until the wheel is replaced -- and uv will not replace
# a wheel whose version has not changed. Reinstalling itself is what makes
# `make test` test the working tree rather than whatever was installed first.
reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
	--upgrade-package arkhai-core         --reinstall-package arkhai-core \
	--upgrade-package arkhai-core-buyer   --reinstall-package arkhai-core-buyer \
	--upgrade-package arkhai-kit-alkahest --reinstall-package arkhai-kit-alkahest \
	--upgrade-package arkhai-kit-config   --reinstall-package arkhai-kit-config \
	--upgrade-package arkhai-kit-policy   --reinstall-package arkhai-kit-policy \
	--upgrade-package arkhai-vms   --reinstall-package arkhai-vms \
		--upgrade-package arkhai-vms-buyer --reinstall-package arkhai-vms-buyer

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests -q

build: reinit
	uv run --no-sync pyinstaller --onefile --name market ./main.py

smoke-test:
	cd dist && ./market -v
