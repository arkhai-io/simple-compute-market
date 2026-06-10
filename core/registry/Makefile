GIT_SUFFIX := $(shell git rev-parse --short HEAD)
PYTHON_VERSION := 3.13

# Path to the monorepo .dist/ wheel directory, relative to core/registry/.
# Used by uv when resolving pure-Python internal packages distributed as wheels
# (arkhai-core-registry-client).  The Dockerfile passes --find-links /dist on the
# uv sync CLI instead; this variable is for local development only.
DIST_DIR ?= $(abspath $(CURDIR)/../../.dist)

# ==============================================================================
# Installation & Setup
# ==============================================================================

init: init-uv
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR)

reinit:
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR) --reinstall-package arkhai-core-registry-client

init-uv:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }

build: reinit build-images

build-images:
	docker build --ulimit nofile=65536:65536 -f Dockerfile -t arkhai:registry ../..
	docker tag arkhai:registry arkhai:registry-$(GIT_SUFFIX)

deploy:
	docker run --rm -d --network market --name registry --env-file ./.env.docker-compose --env-file ../../shared-env/.env -p 8080:8080 arkhai:registry

smoke:
	curl localhost:8080/health

# ==============================================================================
# Server Targets
# ==============================================================================

# Serve the registry API server
# Usage: make serve [PORT=8080]

ENV_FILE := $(if $(wildcard .env.local),.env.local,$(if $(wildcard .env),.env,))
ENV_ARG := $(if $(ENV_FILE),--env-file $(ENV_FILE),)
# Hoisted into a variable: macOS-shipped GNU Make 3.81 mis-parses
# ``$$`` inside single quotes inside ``$(shell ...)`` and refuses the
# whole Makefile with "unterminated call to function `shell'". Also
# uses POSIX [[:space:]] instead of GNU sed's \s for BSD-sed compat.
ENV_SED_PROG := /^[[:space:]]*\#/d;/^[[:space:]]*$$/d;s/=.*//
ifneq (,$(ENV_FILE))
  include $(ENV_FILE)
  export $(shell sed '$(ENV_SED_PROG)' $(ENV_FILE))
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
	echo "| 🚀 Starting Registry/Indexer server...                                     |"; \
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
test: reinit test-unit test-integration

test-unit:
	uv run pytest tests/unit/ -v

test-integration:
	uv run pytest tests/integration/ -v

# Run code quality checks
lint:
	uv run ruff check .
	uv run ruff format . --check
	uv run mypy src/

# Format code
format:
	uv run ruff format .
	uv run ruff check --fix .
