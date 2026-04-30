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

.PHONY: build build-images build-no-cache deploy deploy-seller-agent init reinit test test-unit test-integration

init: ## Resolve deps and create .venv. Run once after checkout or after changing pyproject.toml.
	uv sync --find-links $(DIST_DIR)

reinit: ## Force-reinstall internal wheels without bumping versions. Use after make dist-*.
	uv sync --find-links $(DIST_DIR) \
	--reinstall-package provisioning-service \
	--reinstall-package arkhai-storefront-client \
	--reinstall-package arkhai-registry-client

build: reinit build-images

build-images:
	docker build -f Dockerfile --build-arg INSTALL_RL_DEPS=false -t ${IMAGE_NAME}:${IMAGE_TAG} ..
	docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-$(GIT_SUFFIX)

build-no-cache: reinit ## Full Docker cache bust — use when .dist/ changes are not picked up by build-images.
	docker build --no-cache -f Dockerfile --build-arg INSTALL_RL_DEPS=false -t ${IMAGE_NAME}:${IMAGE_TAG} ..
	docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-$(GIT_SUFFIX)

test: test-unit test-integration ## Run all tests

test-unit: ## Run unit tests
	uv run --find-links $(DIST_DIR) pytest tests/unit/ -v

test-integration: ## Run integration tests (no real infrastructure required — event queue seam)
	ENABLE_EVENT_QUEUE=true \
	AGENT_WALLET_ADDRESS="" \
	uv run --find-links $(DIST_DIR) pytest tests/integration/ -v

deploy: deploy-seller-agent

# Buyers are pure HTTP clients (the `market` CLI / market_buyer
# library); they don't run a storefront. Use `make deploy-seller-agent`
# to bring up the seller; run `market buy ...` from the host or another
# container against `http://market-agent-sell:8001`.
deploy-seller-agent:
	docker run --rm -d --network market --name market-agent-sell -p 8001:8001 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	-e XDG_CONFIG_HOME=/etc \
	-v $(CURDIR)/config.bob.toml:/etc/arkhai/config.toml:ro \
	arkhai:storefront

stop:
	docker kill market-agent-sell