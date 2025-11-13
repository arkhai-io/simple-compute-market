# ==============================================================================
# Installation & Setup
# ==============================================================================

# Install dependencies using uv package manager
install:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }
	uv sync --dev

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
	@echo "==============================================================================="
	@echo "| 🚀 Starting A2A agent server...                                             |"
	@echo "|                                                                             |"
	@echo "| 🌐 Server will be available at: http://localhost:$(or $(PORT),8000)         |"
	@echo "| 📡 A2A protocol enabled for agent-to-agent communication                    |"
	@echo "|                                                                             |"
	@echo "| 💡 Try asking: How many apples do you have?                                 |"
	@echo "==============================================================================="
	GOOGLE_GENAI_USE_VERTEXAI=False uv run uvicorn app.server:app --host 0.0.0.0 --port $(or $(PORT),8000) --reload $(ENV_ARG)

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