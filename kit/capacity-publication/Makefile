DIST_DIR ?= ../../.dist

.PHONY: init test build

init:
	uv sync

test:
	uv run pytest

build:
	uv build --wheel --out-dir $(DIST_DIR)
