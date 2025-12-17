# ==============================================================================
# Installation & Setup
# ==============================================================================

# Install dependencies using uv package manager
install:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }
	uv sync --dev

# ==============================================================================
# Server Targets
# ==============================================================================

# Serve the registry API server
# Usage: make serve [PORT=8080]

ENV_FILE := $(if $(wildcard .env.local),.env.local,$(if $(wildcard .env),.env,))
ENV_ARG := $(if $(ENV_FILE),--env-file $(ENV_FILE),)
ifneq (,$(ENV_FILE))
  include $(ENV_FILE)
  export $(shell sed '/^\s*#/d;/^\s*$$/d;s/=.*//' $(ENV_FILE))
endif

serve:
	@bash -c 'set -e; \
	PORT="$(or $(PORT),8080)"; \
	HOST="$(or $(HOST),0.0.0.0)"; \
	ZT_NETWORK="$(ZEROTIER_NETWORK)"; \
	ENV_ARG="$(ENV_ARG)"; \
	if [ -n "$$ZT_NETWORK" ]; then \
		if ! command -v zerotier-cli >/dev/null 2>&1; then \
			echo "Error: ZeroTier CLI not found. Install with: cd ../infra && make install" >&2; \
			exit 1; \
		fi; \
		NODE_ID=$$(sudo zerotier-cli info | cut -d " " -f3); \
	fi; \
	echo "==============================================================================="; \
	echo "| 🚀 Starting ERC-8004 Registry/Indexer server...                            |"; \
	echo "|                                                                             |"; \
	echo "| 🌐 Server will be available at: http://$$HOST:$$PORT                          |"; \
	if [ -n "$$ENV_ARG" ]; then \
		echo "| ✅ Loading environment from: $(ENV_FILE)                                           |"; \
	else \
		echo "| ⚠️  No .env file found - using environment variables or defaults            |"; \
	fi; \
	echo "|                                                                             |"; \
	if [ -n "$$ZT_NETWORK" ]; then \
		echo "| 🌐 ZeroTier network: $$ZT_NETWORK                                       |"; \
	else \
		echo "| ⚠️  ZEROTIER_NETWORK not set - skipping ZeroTier join                       |"; \
	fi; \
	echo "==============================================================================="; \
	if [ -n "$$ZT_NETWORK" ]; then \
		trap "echo Leaving ZeroTier network $$ZT_NETWORK; sudo zerotier-cli leave $$ZT_NETWORK" INT EXIT; \
		echo Connecting to ZeroTier network $$ZT_NETWORK; \
		echo ZeroTier node ID: $$NODE_ID; \
		sudo zerotier-cli join $$ZT_NETWORK; \
	fi; \
	uv run uvicorn src.main:app --host $$HOST --port $$PORT --reload $$ENV_ARG'

# ==============================================================================
# Database Management
# ==============================================================================

# Run database migrations
migrate:
	uv run alembic upgrade head

# Create a new migration
# Usage: make create-migration MESSAGE="description"
create-migration:
	@if [ -z "$(MESSAGE)" ]; then \
		echo "Usage: make create-migration MESSAGE=\"description\""; \
		exit 1; \
	fi
	uv run alembic revision --autogenerate -m "$(MESSAGE)"

# ==============================================================================
# Testing & Code Quality
# ==============================================================================

# Run tests
test:
	uv run pytest

# Run code quality checks
lint:
	uv run ruff check .
	uv run ruff format . --check
	uv run mypy src/

# Format code
format:
	uv run ruff format .
	uv run ruff check --fix .