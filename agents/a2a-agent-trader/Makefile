# ==============================================================================
# Installation & Setup
# ==============================================================================

# Install dependencies using uv package manager
install:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }
	uv sync --dev

# ==============================================================================
# Agent Registration
# ==============================================================================

# Register agent on-chain (run this before starting the agent)
# Usage: make register-onchain [ENV_FILE=.env]
# This registers to the on-chain Registry separately from agent startup.
# The agent ID will be saved to .env as ONCHAIN_AGENT_ID
register-onchain:
	@echo "==============================================================================="
	@echo "| 🔗 Registering agent on-chain...                                            |"
	@echo "==============================================================================="
	@ENV_FILE="$(or $(ENV_FILE),.env)"; \
	ENV_FILE_ARG=""; \
	if [ -f "$$ENV_FILE" ]; then \
		ENV_FILE_ARG="--env-file $$ENV_FILE"; \
	fi; \
	uv run python scripts/register_onchain.py $$ENV_FILE_ARG

# ==============================================================================
# Playground Targets
# ==============================================================================

# Launch local dev playground
playground:
	@echo "==============================================================================="
	@echo "| 🚀 Starting your agent playground...                                        |"
	@echo "|                                                                             |"
	@echo "| 💡 Try asking: How many apples do you have?                                 |"
	@echo "|                                                                             |"
	@echo "| 🔍 IMPORTANT: Select the 'app' folder to interact with your agent.          |"
	@echo "==============================================================================="
	uv run adk web . --port 8501 --reload_agents

# Serve the A2A version of the app
# Usage: make serve-a2a [PORT=8000]

ENV_FILE ?= .env
ENV_ARG := $(if $(wildcard $(ENV_FILE)),--env-file $(ENV_FILE),)

# Load .env variables into Make if the file exists
ifneq (,$(wildcard $(ENV_FILE)))
  include $(ENV_FILE)
  export $(shell sed '/^\s*#/d;/^\s*$$/d;s/=.*//' $(ENV_FILE))
endif

serve-a2a:
	@bash -c 'set -e; \
	PORT="$(or $(PORT),8000)"; \
	ZT_NETWORK="$(ZEROTIER_NETWORK)"; \
	ENV_ARG="$(ENV_ARG)"; \
	if [ -n "$$ZT_NETWORK" ]; then \
		if ! command -v zerotier-cli >/dev/null 2>&1; then \
			echo "Error: ZeroTier CLI not found. Install with: cd infra && make install" >&2; \
			exit 1; \
		fi; \
		NODE_ID=$$(sudo zerotier-cli info | cut -d " " -f3); \
	fi; \
	echo "==============================================================================="; \
	echo "| 🚀 Starting A2A agent server...                                             |"; \
	echo "|                                                                             |"; \
	echo "| 🌐 Server will be available at: http://localhost:$$PORT                       |"; \
	echo "| 🤝 A2A protocol enabled for agent-to-agent communication                    |"; \
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
	GOOGLE_GENAI_USE_VERTEXAI=False uv run uvicorn app.server:app --host 0.0.0.0 --port $$PORT --reload $$ENV_ARG'


# ==============================================================================
# Backend Deployment Targets
# ==============================================================================

# Deploy the agent remotely
# Usage: make backend [IAP=true] [PORT=8080] - Set IAP=true to enable Identity-Aware Proxy, PORT to specify container port
backend:
	PROJECT_ID=$$(gcloud config get-value project) && \
	gcloud beta run deploy a2a-agent \
		--source . \
		--memory "4Gi" \
		--project $$PROJECT_ID \
		--region "asia-southeast1" \
		--no-allow-unauthenticated \
		--no-cpu-throttling \
		--labels "created-by=adk" \
		--set-env-vars \
		"COMMIT_SHA=$(shell git rev-parse HEAD)" \
		$(if $(IAP),--iap) \
		$(if $(PORT),--port=$(PORT))


# ==============================================================================
# Infrastructure Setup
# ==============================================================================

# Set up development environment resources using Terraform
setup-dev-env:
	PROJECT_ID=$$(gcloud config get-value project) && \
	(cd deployment/terraform/dev && terraform init && terraform apply --var-file vars/env.tfvars --var dev_project_id=$$PROJECT_ID --auto-approve)

# ==============================================================================
# Testing & Code Quality
# ==============================================================================

# Run unit and integration tests
test:
	uv run pytest tests/unit && uv run pytest tests/integration

# Run code quality checks (codespell, ruff, mypy)
lint:
	uv sync --dev --extra lint
	uv run codespell
	uv run ruff check . --diff
	uv run ruff format . --check --diff
	uv run mypy .

# ==============================================================================
# Local test chain helper
# ==============================================================================

# Spin up EnvTestManager once, print useful details, and hold the process open.
test-env:
	uv run python app/utils/test_env.py
# Market Environment Build Targets
# ==============================================================================

# Build the Market C extension binding
build-market-env:
	@echo "Building Market C extension..."
	@cd app/environment/seller && uv run python build_binding.py

# Check Market environment build dependencies
check-market-env:
	@echo "Checking Market environment build dependencies..."
	@which uv > /dev/null || (echo "ERROR: uv not found" && exit 1)
	@uv run python -c "import pufferlib" 2>/dev/null && echo "✓ pufferlib installed" || echo "⚠ pufferlib not found"
	@uv run python -c "from setuptools import setup" 2>/dev/null && echo "✓ setuptools available" || echo "⚠ setuptools not found"
	@which gcc > /dev/null && echo "✓ gcc compiler found" || (which clang > /dev/null && echo "✓ clang compiler found" || echo "⚠ C compiler not found")

# Clean Market environment build artifacts
clean-market-env:
	@echo "Cleaning Market environment build artifacts..."
	@cd app/environment/seller && rm -f *.so *.o binding.cpython-*.so
	@cd app/environment/seller && rm -rf build/ __pycache__/ *.egg-info/
	@rm -f app/env_binding.h

# Test Market environment
test-market-env: build-market-env
	@echo "Testing Market environment..."
	@uv run test_market_env.py

# Train Market environment model
# Usage: make train-market-env [CONFIG=app/environment/seller/market.ini] [DEVICE=cpu] [USE_WANDB=true] [WANDB_TAG=tag_name]
# Note: Uses Python API since puffer_market is a local environment
# For CLI usage, the environment needs to be registered with pufferlib's ocean package
train-market-env: build-market-env
	@echo "Training Market environment model..."
	@echo "Note: Using Python API for local environment"
	@echo "For CLI usage, register the environment with pufferlib's ocean package"
	@CONFIG_FILE=$${CONFIG:-app/environment/seller/market.ini}; \
	DEVICE=$${DEVICE:-cpu}; \
	USE_WANDB=$${USE_WANDB:-false}; \
	WANDB_TAG=$${WANDB_TAG:-}; \
	echo "Using config: $$CONFIG_FILE"; \
	echo "Using device: $$DEVICE"; \
	echo "Using wandb: $$USE_WANDB"; \
	[ -n "$$WANDB_TAG" ] && echo "Wandb tag: $$WANDB_TAG" || true; \
	PUFFERLIB_CONFIG=$$CONFIG_FILE \
	PUFFERLIB_DEVICE=$$DEVICE \
	USE_WANDB=$$USE_WANDB \
	WANDB_TAG=$$WANDB_TAG \
	uv run python app/environment/seller/train.py

# Evaluate Market environment (render with random agent)
# Usage: make eval-market-env [LOAD_MODEL_PATH=latest]
eval-market-env: build-market-env
	@echo "Evaluating Market environment..."
	@MODEL_PATH=$${LOAD_MODEL_PATH:-latest}; \
	LOAD_MODEL_PATH=$$MODEL_PATH \
	uv run python app/environment/seller/eval.py

# Run hyperparameter sweep for Market environment
# Usage: make sweep-market-env [LOGGER=wandb] [TAG=sweep_name] [CONFIG=app/environment/seller/market.ini]
# Examples:
#   make sweep-market-env LOGGER=wandb TAG=my_sweep
#   make sweep-market-env LOGGER=neptune TAG=my_sweep
# Note: Sweeps may require the environment to be registered with pufferlib
sweep-market-env: build-market-env
	@echo "Running hyperparameter sweep for Market environment..."
	@CONFIG_FILE=$${CONFIG:-app/environment/seller/market.ini}; \
	LOGGER=$${LOGGER:-wandb}; \
	TAG=$${TAG:-market_sweep}; \
	if [ "$$LOGGER" = "neptune" ]; then \
		uv run python -m pufferlib.pufferl sweep puffer_market \
			--config $$CONFIG_FILE \
			--neptune --tag $$TAG || \
		echo "Note: Sweep failed. You may need to register the environment with pufferlib."; \
	else \
		uv run python -m pufferlib.pufferl sweep puffer_market \
			--config $$CONFIG_FILE \
			--wandb --tag $$TAG || \
		echo "Note: Sweep failed. You may need to register the environment with pufferlib."; \
	fi

# Export model checkpoint to TorchScript
# Usage: make export-model [CHECKPOINT=path/to/model.pt] [OUTPUT=output.ts] [DEVICE=cpu] [SCRIPT=false]
# Examples:
#   make export-model  # Exports latest checkpoint
#   make export-model CHECKPOINT=experiments/123/model_000200.pt OUTPUT=model.ts
#   make export-model CHECKPOINT=experiments/123/model_000200.pt DEVICE=cuda
#   make export-model CHECKPOINT=experiments/123/model_000200.pt SCRIPT=true  # Use torch.jit.script
export-model: build-market-env
	@echo "Exporting model to TorchScript..."
	@CHECKPOINT=$${CHECKPOINT:-}; \
	OUTPUT=$${OUTPUT:-}; \
	DEVICE=$${DEVICE:-cpu}; \
	SCRIPT=$${SCRIPT:-false}; \
	if [ -n "$$CHECKPOINT" ]; then \
		CHECKPOINT_ARG="$$CHECKPOINT"; \
	else \
		CHECKPOINT_ARG=""; \
	fi; \
	if [ -n "$$OUTPUT" ]; then \
		OUTPUT_ARG="-o $$OUTPUT"; \
	else \
		OUTPUT_ARG=""; \
	fi; \
	if [ "$$SCRIPT" = "true" ]; then \
		SCRIPT_ARG="--script"; \
	else \
		SCRIPT_ARG=""; \
	fi; \
	uv run python app/environment/seller/export_model.py $$CHECKPOINT_ARG $$OUTPUT_ARG --device $$DEVICE $$SCRIPT_ARG

# Test TorchScript model inference
# Usage: make test-torchscript MODEL=<path_to_torchscript_model.ts>
test-torchscript:
	@if [ -z "$(MODEL)" ]; then \
		echo "Usage: make test-torchscript MODEL=<path_to_torchscript_model.ts>"; \
		exit 1; \
	fi
	@uv run python app/environment/seller/test_torchscript.py $(MODEL)
