REPO_ROOT := $(shell git rev-parse --show-toplevel)

.PHONY: build

init:
	uv venv --allow-existing
	uv sync --python 3.10

build:
	uv run pyinstaller --onefile --name market ./main.py

smoke-test:
	cd dist && ./market -v