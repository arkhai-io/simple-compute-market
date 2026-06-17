REPO_ROOT := $(shell git rev-parse --show-toplevel)
DIST_DIR ?= $(abspath $(CURDIR)/../../../.dist)

.PHONY: build init reinit test smoke-test

init:
	uv venv --allow-existing --python 3.12
	uv sync --dev --python 3.12 --find-links $(DIST_DIR)

reinit:
	uv sync --dev --python 3.12 --find-links $(DIST_DIR) \
	--upgrade-package arkhai-vms-common \
	--reinstall-package arkhai-vms-common

test:
	uv run --find-links $(DIST_DIR) pytest tests -q

build: reinit
	uv run --no-sync pyinstaller --onefile --name market ./main.py

smoke-test:
	cd dist && ./market -v
