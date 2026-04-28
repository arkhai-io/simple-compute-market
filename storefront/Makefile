IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= storefront
GIT_SUFFIX := $(shell git rev-parse --short HEAD)

# Path to the monorepo .dist/ wheel directory, relative to storefront/.
# Used by uv when resolving pure-Python internal packages
# (market-service, market-policy, provisioning-service) that are
# distributed as wheels rather than editable source installs. The
# Dockerfile passes --find-links /dist on the uv sync CLI instead;
# this variable is for local development only.
DIST_DIR ?= $(abspath $(CURDIR)/../.dist)

.PHONY: build build-images deploy deploy-buyer-agent deploy-seller-agent init test test-unit test-integration

init: ## Resolve deps and create .venv. Run once after checkout or after changing pyproject.toml.
	uv sync --find-links $(DIST_DIR)

reinit: ## Force-reinstall internal wheels without bumping versions. Use after make dist-*.
	uv sync --find-links $(DIST_DIR) --reinstall-package provisioning-service --reinstall-package arkhai-storefront-client


build: build-images

build-images:
	docker build -f Dockerfile --build-arg INSTALL_RL_DEPS=false -t ${IMAGE_NAME}:${IMAGE_TAG} ..
	docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-$(GIT_SUFFIX)

test: test-unit test-integration ## Run all tests

test-unit: ## Run unit tests
	uv run --find-links $(DIST_DIR) pytest tests/unit/ -v

test-integration: ## Run integration tests (no real infrastructure required — event queue seam)
	ENABLE_EVENT_QUEUE=true \
	AGENT_WALLET_ADDRESS="" \
	uv run --find-links $(DIST_DIR) pytest tests/integration/ -v

deploy: deploy-buyer-agent deploy-seller-agent

# Todo, figure out what this volume was doing in the compose file: #      - zerotier-buy:/var/lib/zerotier-one
deploy-buyer-agent:
	docker run --rm -d --network market --name market-agent-buy -p 8000:8000 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	--env-file ./.env.alice.docker-compose --env-file ../shared-env/.env \
	arkhai:storefront

deploy-seller-agent:
	docker run --rm -d --network market --name market-agent-sell -p 8001:8001 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	--env-file ./.env.bob.docker-compose --env-file ../shared-env/.env \
	arkhai:storefront
