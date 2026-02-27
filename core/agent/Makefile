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
# Usage: make register [ENV_FILE=.env]
# This registers to the on-chain Registry separately from agent startup.
# The agent ID will be saved to .env as ONCHAIN_AGENT_ID
register:
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
	uv run python scripts/extract_anvil_addresses.py --output app/data/alkahest_anvil_addresses.json
	uv run python app/utils/test_env.py
# ==============================================================================
# Arkhai Training Environment Targets
# ==============================================================================

# Train Arkhai model using upstream puffer CLI.
# Usage: make train-arkhai [DEVICE=cpu] [TOTAL_TIMESTEPS=10000000] [WANDB=true] [TAG=exp_name] [ARGS="..."]
train-arkhai:
	@echo "Training Arkhai model via puffer..."
	@DEVICE=$${DEVICE:-cpu}; \
	TOTAL_TIMESTEPS=$${TOTAL_TIMESTEPS:-10000000}; \
	WANDB_FLAG=""; \
	TAG_FLAG=""; \
	ARGS="$${ARGS:-}"; \
	if [ "$${WANDB:-false}" = "true" ]; then WANDB_FLAG="--wandb"; fi; \
	if [ -n "$${TAG:-}" ]; then TAG_FLAG="--tag $${TAG}"; fi; \
	echo "Device: $$DEVICE"; \
	echo "Total timesteps: $$TOTAL_TIMESTEPS"; \
	[ -n "$$ARGS" ] && echo "Extra args: $$ARGS" || true; \
	uv run puffer train puffer_arkhai \
		--train.device $$DEVICE \
		--train.total-timesteps $$TOTAL_TIMESTEPS \
		$$WANDB_FLAG $$TAG_FLAG $$ARGS

# Evaluate Arkhai policy with upstream puffer CLI.
# Usage: make eval-arkhai [MODEL=latest] [DEVICE=cpu] [ARGS="..."]
eval-arkhai:
	@echo "Evaluating Arkhai model via puffer..."
	@MODEL=$${MODEL:-latest}; \
	DEVICE=$${DEVICE:-cpu}; \
	ARGS="$${ARGS:-}"; \
	echo "Model: $$MODEL"; \
	echo "Device: $$DEVICE"; \
	[ -n "$$ARGS" ] && echo "Extra args: $$ARGS" || true; \
	uv run puffer eval puffer_arkhai \
		--load-model-path $$MODEL \
		--train.device $$DEVICE \
		$$ARGS

# Backward-compatible alias for previous target name.
eval-arkhai-seller: eval-arkhai

# Export model weights in puffer's native format.
# Usage: make export-arkhai-weights [MODEL=latest]
export-arkhai-weights:
	@echo "Exporting Arkhai weights via puffer..."
	@MODEL=$${MODEL:-latest}; \
	echo "Model: $$MODEL"; \
	uv run puffer export puffer_arkhai --load-model-path $$MODEL

# Backward-compatible alias for previous target name.
export-arkhai-model: export-arkhai-weights

# Test Arkhai environment integration
# Usage: make test-arkhai-env
test-arkhai-env:
	@echo "Testing Arkhai environment..."
	@uv run python -c "\
	from pufferlib.ocean.arkhai.arkhai import Arkhai; \
	import numpy as np; \
	env = Arkhai(num_envs=2, seed=42, node_types=3, ai_sellers=1, ai_buyers=0, scripted_sellers=0, scripted_buyers=3, \
	    episode_length=100, request_timeout=5, \
	    job_gpu_0_nodes=10, job_gpu_0_nodes_dr=0.2, job_gpu_1_nodes=10, job_gpu_1_nodes_dr=0.2, job_gpu_2_nodes=10, job_gpu_2_nodes_dr=0.2, \
	    job_duration=10, job_duration_dr=0.2, job_tb_usage=0.2, job_tb_usage_dr=0.2, job_efficiency=0.8, job_efficiency_dr=0.2, \
	    scripted_buy_price=0.9, scripted_buy_price_dr=0.2, scripted_sell_price=0.9, scripted_sell_price_dr=0.2, \
	    reward_scale=0.0001, tb_price=0.03, gpu_0_price=5.31, gpu_0_kw=6.5, gpu_1_price=15.92, gpu_1_kw=10.0, gpu_2_price=0.37, gpu_2_kw=1.0, \
	    energy_demand_base=1500.0, kwh_price_base=0.02, kwh_price_sensitivity=0.0000001, kwh_demand_threshold=1400, \
	    a1=-374, b1=-387, a2=-4.6, b2=-17.1, a3=3.2, b3=18.9, randomize_offset=1, preset=0, \
	    cluster_gpu_0_capacity=100, cluster_gpu_0_capacity_dr=0.2, cluster_gpu_1_capacity=100, cluster_gpu_1_capacity_dr=0.2, \
	    cluster_gpu_2_capacity=100, cluster_gpu_2_capacity_dr=0.2, cluster_tb_capacity=100, cluster_tb_capacity_dr=0.2, \
	    cluster_kwh_capacity=100, cluster_kwh_capacity_dr=0.2, cluster_kw_generation=10, cluster_kw_generation_dr=0.2); \
	obs, info = env.reset(); \
	print(f'✓ Environment created: {env.num_agents} agents'); \
	print(f'✓ Observation shape: {obs.shape}'); \
	print(f'✓ Observation space: {env.single_observation_space}'); \
	print(f'✓ Action space: {env.single_action_space}'); \
	actions = np.array([[4, 0]] * env.num_agents); \
	obs, reward, done, trunc, info = env.step(actions); \
	print(f'✓ Step completed: obs={obs.shape}, reward={reward.shape}'); \
	print('✓ Arkhai environment integration test passed'); \
	"
