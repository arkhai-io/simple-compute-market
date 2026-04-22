# ==============================================================================
# Installation & Setup
# ==============================================================================

# Install dependencies using uv package manager
install:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }
	uv --project .. sync --dev

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
	PYTHONPATH="$(PYTHONPATH)" uv --project .. run python scripts/register_onchain.py $$ENV_FILE_ARG

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
	uv --project .. run adk web . --port 8501 --reload_agents

# Serve the A2A version of the app
# Usage: make serve-a2a [PORT=8000]

ENV_FILE ?= .env
ENV_ARG := $(if $(wildcard $(ENV_FILE)),--env-file $(ENV_FILE),)
PYTHONPATH := ../..$(if $(PYTHONPATH),:$(PYTHONPATH))

# Load .env variables into Make if the file exists
ifneq (,$(wildcard $(ENV_FILE)))
  include $(ENV_FILE)
  export $(shell sed '/^\s*#/d;/^\s*$$/d;s/=.*//' $(ENV_FILE))
endif

serve-a2a:
	@bash -c 'set -e; \
	trap "stty echo" EXIT; \
	PORT="$(or $(PORT),8000)"; \
	ZT_NETWORK="$(ZEROTIER_NETWORK)"; \
	ENV_ARG="$(ENV_ARG)"; \
	export PYTHONPATH="$(PYTHONPATH)"; \
	if [ -n "$$ZT_NETWORK" ]; then \
		if ! command -v zerotier-cli >/dev/null 2>&1; then \
			echo "Error: ZeroTier CLI not found. Install with: cd infra && make install" >&2; \
			exit 1; \
		fi; \
		sudo -v || { echo "Error: sudo authentication failed" >&2; exit 1; }; \
		( while true; do sleep 300; sudo -n -v 2>/dev/null || true; done ) & \
		SUDO_KEEPALIVE=$$!; \
		trap "kill $$SUDO_KEEPALIVE 2>/dev/null; stty echo" EXIT; \
		if ! NODE_ID=$$(sudo -n zerotier-cli info 2>/dev/null | cut -d " " -f3) || [ -z "$$NODE_ID" ]; then \
			echo "Error: sudo access required for zerotier-cli. Run: sudo zerotier-cli info" >&2; \
			exit 1; \
		fi; \
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
		trap "kill $$SUDO_KEEPALIVE 2>/dev/null; stty echo; echo Leaving ZeroTier network $$ZT_NETWORK; sudo -n zerotier-cli leave $$ZT_NETWORK" INT EXIT; \
		echo Connecting to ZeroTier network $$ZT_NETWORK; \
		echo ZeroTier node ID: $$NODE_ID; \
		sudo -n zerotier-cli join $$ZT_NETWORK; \
	fi; \
	uv --project .. run uvicorn core.agent.app.server:app --host 0.0.0.0 --port $$PORT --reload $$ENV_ARG'


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

# Import resources from CSV into Agent DB.
# Usage: make import-resources CSV=path/to/resources.csv [ENV_FILE=.env] [DB_PATH=/tmp/agent.db] [DRY_RUN=true]
import-resources:
	@bash -c 'set -e; \
	if [ -z "$$CSV" ]; then \
		echo "ERROR: CSV is required. Usage: make import-resources CSV=path/to/resources.csv [ENV_FILE=.env] [DB_PATH=...] [DRY_RUN=true]" >&2; \
		exit 1; \
	fi; \
	ENV_FILE="$${ENV_FILE:-.env}"; \
	DB_ARG=""; \
	DRY_ARG=""; \
	if [ -n "$$DB_PATH" ]; then DB_ARG="--db-path $$DB_PATH"; fi; \
	if [ "$${DRY_RUN:-false}" = "true" ]; then DRY_ARG="--dry-run"; fi; \
	uv --project .. run python scripts/import_resources_csv.py --csv "$$CSV" --env-file "$$ENV_FILE" $$DB_ARG $$DRY_ARG'

# Run unit and integration tests
test:
	uv --project .. run pytest tests/unit && uv --project .. run pytest tests/integration

# Run code quality checks (codespell, ruff, mypy)
lint:
	uv --project .. sync --dev --extra lint
	uv --project .. run codespell
	uv --project .. run ruff check . --diff
	uv --project .. run ruff format . --check --diff
	uv --project .. run mypy .

# ==============================================================================
# Local test chain helper
# ==============================================================================

# Spin up EnvTestManager once, print useful details, and hold the process open.
test-env:
	uv --project .. run python scripts/extract_anvil_addresses.py --output app/data/alkahest_anvil_addresses.json
	uv --project .. run python -m app.utils.test_env
# ==============================================================================
# GPU Installation (for training)
# ==============================================================================

# Install PyTorch with CUDA support for GPU training.
# Default install uses CPU-only torch. Run this after `make install` for GPU.
install-gpu:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	uv --project .. sync --dev
	uv pip install torch --reinstall-package torch --index-url https://download.pytorch.org/whl/cu128

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
	uv --project .. run puffer train puffer_arkhai \
		--train.device $$DEVICE \
		--train.total-timesteps $$TOTAL_TIMESTEPS \
		$$WANDB_FLAG $$TAG_FLAG $$ARGS

# Patch pufferlib's eval loop to guard driver.render() with a render_mode check.
# Re-run after every `uv sync`.
patch-puffer-eval:
	uv --project .. run python scripts/patch_puffer_eval.py

# Evaluate Arkhai policy with upstream puffer CLI.
# Usage: make eval-arkhai [MODEL=latest] [DEVICE=cpu] [ARGS="--render-mode None"]
eval-arkhai:
	@echo "Evaluating Arkhai model via puffer..."
	@MODEL=$${MODEL:-latest}; \
	DEVICE=$${DEVICE:-cpu}; \
	ARGS="$${ARGS:-}"; \
	echo "Model: $$MODEL"; \
	echo "Device: $$DEVICE"; \
	[ -n "$$ARGS" ] && echo "Extra args: $$ARGS" || true; \
	$(MAKE) patch-puffer-eval; \
	uv --project .. run puffer eval puffer_arkhai \
		--load-model-path $$MODEL \
		--train.device $$DEVICE \
		$$ARGS

# Export model weights in puffer's native format.
# Usage: make export-arkhai-weights [MODEL=latest]
export-arkhai-weights:
	@echo "Exporting Arkhai weights via puffer..."
	@MODEL=$${MODEL:-latest}; \
	echo "Model: $$MODEL"; \
	uv --project .. run puffer export puffer_arkhai --load-model-path $$MODEL

# ==============================================================================
# Arkhai Buyer Training
# ==============================================================================

# Train Arkhai BUYER model. Buyer learns against 3 scripted sellers.
# Usage: make train-arkhai-buyer [DEVICE=cpu] [TOTAL_TIMESTEPS=100000000] [WANDB=true] [TAG=exp_name]
train-arkhai-buyer:
	@echo "Training Arkhai BUYER model via puffer..."
	@DEVICE=$${DEVICE:-cpu}; \
	TOTAL_TIMESTEPS=$${TOTAL_TIMESTEPS:-100000000}; \
	WANDB_FLAG=""; \
	TAG_FLAG=""; \
	ARGS="$${ARGS:-}"; \
	if [ "$${WANDB:-false}" = "true" ]; then WANDB_FLAG="--wandb"; fi; \
	if [ -n "$${TAG:-}" ]; then TAG_FLAG="--tag $${TAG}"; fi; \
	echo "Device: $$DEVICE"; \
	echo "Total timesteps: $$TOTAL_TIMESTEPS"; \
	[ -n "$$ARGS" ] && echo "Extra args: $$ARGS" || true; \
	uv --project .. run puffer train puffer_arkhai \
		--train.device $$DEVICE \
		--train.total-timesteps $$TOTAL_TIMESTEPS \
		--env.ai-sellers 0 \
		--env.ai-buyers 1 \
		--env.scripted-sellers 3 \
		--env.scripted-buyers 0 \
		$$WANDB_FLAG $$TAG_FLAG $$ARGS

# Evaluate Arkhai BUYER policy.
eval-arkhai-buyer:
	@echo "Evaluating Arkhai BUYER model via puffer..."
	@MODEL=$${MODEL:-latest}; \
	DEVICE=$${DEVICE:-cpu}; \
	ARGS="$${ARGS:-}"; \
	echo "Model: $$MODEL"; \
	echo "Device: $$DEVICE"; \
	[ -n "$$ARGS" ] && echo "Extra args: $$ARGS" || true; \
	$(MAKE) patch-puffer-eval; \
	uv --project .. run puffer eval puffer_arkhai \
		--load-model-path $$MODEL \
		--train.device $$DEVICE \
		--env.ai-sellers 0 \
		--env.ai-buyers 1 \
		--env.scripted-sellers 3 \
		--env.scripted-buyers 0 \
		$$ARGS

# ==============================================================================
# Arkhai Bilateral Training (Experimental)
# ==============================================================================

# Train both AI seller and AI buyer simultaneously.
train-arkhai-bilateral:
	@echo "Training Arkhai BILATERAL model via puffer (experimental)..."
	@DEVICE=$${DEVICE:-cpu}; \
	TOTAL_TIMESTEPS=$${TOTAL_TIMESTEPS:-100000000}; \
	WANDB_FLAG=""; \
	TAG_FLAG=""; \
	ARGS="$${ARGS:-}"; \
	if [ "$${WANDB:-false}" = "true" ]; then WANDB_FLAG="--wandb"; fi; \
	if [ -n "$${TAG:-}" ]; then TAG_FLAG="--tag $${TAG}"; fi; \
	echo "Device: $$DEVICE"; \
	echo "Total timesteps: $$TOTAL_TIMESTEPS"; \
	[ -n "$$ARGS" ] && echo "Extra args: $$ARGS" || true; \
	uv --project .. run puffer train puffer_arkhai \
		--train.device $$DEVICE \
		--train.total-timesteps $$TOTAL_TIMESTEPS \
		--env.ai-sellers 1 \
		--env.ai-buyers 1 \
		--env.scripted-sellers 0 \
		--env.scripted-buyers 0 \
		$$WANDB_FLAG $$TAG_FLAG $$ARGS

# ==============================================================================
# Model Release & Download
# ==============================================================================

REPO ?= arkhai-io/simple-market-service

# Download trained models from a GitHub release.
# Usage: make download-models [VERSION=model-v0.1.0]
download-models:
	@VERSION=$${VERSION:-latest}; \
	echo "Downloading models (version: $$VERSION)..."; \
	bash scripts/download_models.sh $$VERSION

# Create a GitHub release with trained model artifacts.
# Usage: make release-models VERSION=model-v0.1.0 [MODELS_DIR=path/to/models]
MODELS_DIR ?= ../../domain/compute/agent/app/policy/models
release-models:
	@if [ -z "$${VERSION:-}" ]; then echo "ERROR: VERSION is required. Usage: make release-models VERSION=model-v0.1.0"; exit 1; fi; \
	MODELS_DIR="$(MODELS_DIR)"; \
	ASSETS=""; \
	if [ -f "$$MODELS_DIR/arkhai_negotiator_seller.pt" ]; then ASSETS="$$ASSETS $$MODELS_DIR/arkhai_negotiator_seller.pt"; fi; \
	if [ -f "$$MODELS_DIR/arkhai_negotiator_buyer.pt" ]; then ASSETS="$$ASSETS $$MODELS_DIR/arkhai_negotiator_buyer.pt"; fi; \
	if [ -z "$$ASSETS" ]; then echo "ERROR: No .pt model files found in $$MODELS_DIR"; exit 1; fi; \
	echo "Creating release $$VERSION with:$$ASSETS"; \
	git tag "$$VERSION" || true; \
	git push origin "$$VERSION" || true; \
	NOTES="Model Release $$VERSION"; \
	NOTES="$$NOTES\n\nPufferLib commit: ef59f84c"; \
	NOTES="$$NOTES\nEnvironment: puffer_arkhai (node_types=3, episode_length=100, bilateral)"; \
	NOTES="$$NOTES\n\nArtifacts:"; \
	if [ -f "$$MODELS_DIR/arkhai_negotiator_seller.pt" ]; then NOTES="$$NOTES\n- arkhai_negotiator_seller.pt: Bilateral negotiation seller (10M steps)"; fi; \
	if [ -f "$$MODELS_DIR/arkhai_negotiator_buyer.pt" ]; then NOTES="$$NOTES\n- arkhai_negotiator_buyer.pt: Bilateral negotiation buyer (10M steps)"; fi; \
	gh release create "$$VERSION" \
		--repo $(REPO) \
		--title "Model Release $$VERSION" \
		--notes "$$(printf "$$NOTES")" \
		$$ASSETS; \
	echo "Release $$VERSION created successfully."

# ==============================================================================
# Test Arkhai environment integration
# ==============================================================================

# Test Arkhai environment integration
# Usage: make test-arkhai-env
test-arkhai-env:
	@echo "Testing Arkhai environment..."
	@uv --project .. run python -c "\
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
