REPO_ROOT := $(shell git rev-parse --show-toplevel)

.PHONY: build

init:
	uv venv --allow-existing --python 3.12
	uv sync --python 3.12

build:
	uv run pyinstaller --onefile --name market ./main.py

smoke-test:
	cd dist && ./market -v