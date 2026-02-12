# ==============================================================================
# Async Provisioning Service Makefile
# ==============================================================================

.PHONY: help install dev serve worker test clean db-init db-reset check-redis

# Default target
.DEFAULT_GOAL := help

# Environment file
ENV_FILE ?= .env.local

# ==============================================================================
# Help
# ==============================================================================

help: ## Show this help message
	@echo "==============================================================================="
	@echo "| Async Provisioning Service - Available Commands                            |"
	@echo "==============================================================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo "==============================================================================="

# ==============================================================================
# Installation & Setup
# ==============================================================================

install: ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $$HOME/.local/bin/env; }
	uv sync --dev

check-redis: ## Check if Redis is running
	@echo "Checking Redis connection..."
	@redis-cli ping > /dev/null 2>&1 || { echo "❌ Redis is not running. Start it with: redis-server"; exit 1; }
	@echo "✅ Redis is running"

# ==============================================================================
# Database Management
# ==============================================================================

db-init: ## Initialize database (create tables)
	@echo "==============================================================================="
	@echo "| Initializing database...                                                    |"
	@echo "==============================================================================="
	PYTHONPATH=src uv run python -c "from async_provisioning_service.db.database import init_db; init_db()"
	@echo "✅ Database initialized"

db-reset: ## Reset database (WARNING: Deletes all data)
	@echo "⚠️  WARNING: This will delete all data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -f provisioning.db; \
		echo "✅ Database deleted"; \
		$(MAKE) db-init; \
	else \
		echo "Cancelled"; \
	fi

# ==============================================================================
# Development
# ==============================================================================

dev: check-redis db-init ## Setup development environment
	@echo "==============================================================================="
	@echo "| Development environment ready!                                              |"
	@echo "|                                                                             |"
	@echo "| Next steps:                                                                 |"
	@echo "|   1. make serve    - Start API server                                      |"
	@echo "|   2. make worker   - Start background worker (in another terminal)         |"
	@echo "==============================================================================="

serve: check-redis ## Start the provisioning service API server
	@echo "==============================================================================="
	@echo "| 🚀 Starting Async Provisioning Service API...                               |"
	@echo "|                                                                             |"
	@echo "| API URL: http://localhost:8081                                              |"
	@echo "| Docs:    http://localhost:8081/docs                                         |"
	@echo "==============================================================================="
	@if [ -f "$(ENV_FILE)" ]; then \
		echo "Loading configuration from $(ENV_FILE)"; \
		PYTHONPATH=src uv run python -m async_provisioning_service.main; \
	else \
		echo "⚠️  $(ENV_FILE) not found, using defaults"; \
		PYTHONPATH=src uv run python -m async_provisioning_service.main; \
	fi

worker: check-redis ## Start the background worker
	@echo "==============================================================================="
	@echo "| 🔧 Starting Provisioning Worker...                                          |"
	@echo "|                                                                             |"
	@echo "| Worker will process jobs from Redis queue                                   |"
	@echo "==============================================================================="
	@if [ -f "$(ENV_FILE)" ]; then \
		echo "Loading configuration from $(ENV_FILE)"; \
		PYTHONPATH=src uv run python -m async_provisioning_service.worker; \
	else \
		echo "⚠️  $(ENV_FILE) not found, using defaults"; \
		PYTHONPATH=src uv run python -m async_provisioning_service.worker; \
	fi

# ==============================================================================
# Testing
# ==============================================================================

test: ## Run tests
	@echo "==============================================================================="
	@echo "| Running tests...                                                            |"
	@echo "==============================================================================="
	PYTHONPATH=src uv run pytest tests/ -v

test-cov: ## Run tests with coverage
	PYTHONPATH=src uv run pytest tests/ --cov=async_provisioning_service --cov-report=html --cov-report=term
	@echo "📊 Coverage report: htmlcov/index.html"

test-integration: check-redis ## Run integration tests (requires Redis)
	PYTHONPATH=src uv run pytest tests/integration/ -v

# ==============================================================================
# Service Management
# ==============================================================================

start-all: ## Start both API and worker (in background)
	@echo "Starting API server in background..."
	@$(MAKE) serve > logs/api.log 2>&1 &
	@echo "Starting worker in background..."
	@$(MAKE) worker > logs/worker.log 2>&1 &
	@echo "✅ Services started. Check logs/api.log and logs/worker.log"

stop-all: ## Stop all background services
	@echo "Stopping services..."
	@pkill -f "async_provisioning_service.main" || true
	@pkill -f "async_provisioning_service.worker" || true
	@echo "✅ Services stopped"

status: ## Check service status
	@echo "API Server:"
	@pgrep -f "async_provisioning_service.main" > /dev/null && echo "  ✅ Running" || echo "  ❌ Not running"
	@echo "Worker:"
	@pgrep -f "async_provisioning_service.worker" > /dev/null && echo "  ✅ Running" || echo "  ❌ Not running"
	@echo "Redis:"
	@redis-cli ping > /dev/null 2>&1 && echo "  ✅ Running" || echo "  ❌ Not running"

logs: ## Show logs directory
	@mkdir -p logs
	@echo "Logs directory: logs/"
	@ls -lh logs/ 2>/dev/null || echo "No logs yet"

# ==============================================================================
# Utilities
# ==============================================================================

health: ## Check API health endpoint
	@curl -s http://localhost:8081/health | python -m json.tool || echo "❌ Service not responding"

queue-status: check-redis ## Check Redis queue status
	@echo "Queue: provisioning_jobs"
	@echo "  Length: $$(redis-cli LLEN provisioning_jobs)"
	@echo ""
	@echo "Recent jobs:"
	@redis-cli LRANGE provisioning_jobs 0 4 | head -5

queue-clear: check-redis ## Clear Redis queue (WARNING: Deletes all queued jobs)
	@echo "⚠️  WARNING: This will delete all queued jobs!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		redis-cli DEL provisioning_jobs; \
		echo "✅ Queue cleared"; \
	else \
		echo "Cancelled"; \
	fi

db-query: ## Query database (interactive)
	@if [ -f "provisioning.db" ]; then \
		sqlite3 provisioning.db; \
	else \
		echo "❌ Database not found. Run 'make db-init' first"; \
	fi

db-show-jobs: ## Show all provisioning jobs
	@if [ -f "provisioning.db" ]; then \
		sqlite3 provisioning.db "SELECT job_id, status, created_at FROM provisioning_jobs ORDER BY created_at DESC LIMIT 10;"; \
	else \
		echo "❌ Database not found. Run 'make db-init' first"; \
	fi

# ==============================================================================
# Cleanup
# ==============================================================================

clean: ## Clean up generated files
	@echo "Cleaning up..."
	rm -rf __pycache__ .pytest_cache .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "✅ Cleaned"

clean-all: clean ## Clean everything including database and logs
	@echo "⚠️  This will delete database and logs!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -f provisioning.db; \
		rm -rf logs/; \
		echo "✅ Everything cleaned"; \
	else \
		echo "Cancelled"; \
	fi

# ==============================================================================
# Quick Start
# ==============================================================================

quickstart: install dev ## Quick start: Install, setup, and show next steps
	@echo ""
	@echo "==============================================================================="
	@echo "| 🎉 Quick start complete!                                                    |"
	@echo "|                                                                             |"
	@echo "| To start the service:                                                       |"
	@echo "|   Terminal 1: make serve                                                    |"
	@echo "|   Terminal 2: make worker                                                   |"
	@echo "|                                                                             |"
	@echo "| Or run both in background:                                                  |"
	@echo "|   make start-all                                                            |"
	@echo "==============================================================================="

# ==============================================================================
# Configuration
# ==============================================================================

config: ## Show current configuration
	@echo "==============================================================================="
	@echo "| Current Configuration                                                       |"
	@echo "==============================================================================="
	@if [ -f "$(ENV_FILE)" ]; then \
		cat $(ENV_FILE); \
	else \
		echo "⚠️  $(ENV_FILE) not found"; \
	fi

config-sample: ## Create .env.local from .env.sample
	@if [ ! -f ".env.local" ]; then \
		cp .env.sample .env.local; \
		echo "✅ Created .env.local from .env.sample"; \
		echo "⚠️  Please edit .env.local with your configuration"; \
	else \
		echo "⚠️  .env.local already exists"; \
	fi
