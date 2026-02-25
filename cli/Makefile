REPO_ROOT := $(shell git rev-parse --show-toplevel)

init:
	uv venv --allow-existing
	uv pip install -e .
	uv pip install pyinstaller

# Requires foreign python projects dependencies have already been initialized
# Also we need to work on lean dependencies here because while this built the resuling cli is 700MB
build:
	uv run pyinstaller --onefile \
	--name market \
	--add-data "${REPO_ROOT}/agent:agent" \
	--add-data "${REPO_ROOT}/erc-8004-contracts:erc-8004-contracts" \
	--add-data "${REPO_ROOT}/erc-8004-registry-py:erc-8004-registry-py" \
	--add-data "${REPO_ROOT}/infra:infra" \
	./market/cli.py