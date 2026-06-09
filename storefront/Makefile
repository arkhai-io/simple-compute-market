IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= storefront
GIT_SUFFIX := $(shell git rev-parse --short HEAD)

# Path to the monorepo .dist/ wheel directory, relative to storefront/.
# Used by uv when resolving pure-Python internal packages
# (market-policy, provisioning-service) that are
# distributed as wheels rather than editable source installs. The
# Dockerfile passes --find-links /dist on the uv sync CLI instead;
# this variable is for local development only.
DIST_DIR ?= $(abspath $(CURDIR)/../.dist)

.PHONY: build build-images build-no-cache deploy deploy-storefront init reinit test test-unit test-integration

init: ## Resolve deps and create .venv. Run once after checkout or after changing pyproject.toml.
	uv sync --find-links $(DIST_DIR)

reinit: ## Force-reinstall internal wheels without bumping versions. Use after make dist-*.
	uv sync --find-links $(DIST_DIR) \
	--upgrade-package provisioning-service \
	--upgrade-package arkhai-storefront-client \
	--upgrade-package arkhai-registry-client \
	--reinstall-package provisioning-service \
	--reinstall-package arkhai-storefront-client \
	--reinstall-package arkhai-registry-client

# build deliberately does NOT depend on reinit. reinit drives a host-side
# `uv sync` that resolves the [rl] extra (incl. torch) across whatever
# uv considers "supported platforms" for this project — on x86_64 Linux
# that decides no torch wheel exists and aborts, blocking the Docker
# build that doesn't need torch at all (INSTALL_RL_DEPS=false). The
# Docker build has its own self-contained `uv sync --find-links /dist`
# inside the builder stage; the host venv isn't on its critical path.
# Run `make reinit` explicitly when iterating on internal wheels in the
# local venv.
build: build-images

build-images:
	docker build --ulimit nofile=65536 -f Dockerfile --build-arg INSTALL_RL_DEPS=false -t ${IMAGE_NAME}:${IMAGE_TAG} ..
	docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-$(GIT_SUFFIX)

build-no-cache: ## Full Docker cache bust — use when .dist/ changes are not picked up by build-images.
	docker build --no-cache --ulimit nofile=65536 -f Dockerfile --build-arg INSTALL_RL_DEPS=false -t ${IMAGE_NAME}:${IMAGE_TAG} ..
	docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-$(GIT_SUFFIX)

test: reinit test-unit test-integration ## Run all tests

test-unit: ## Run unit tests
	uv run --find-links $(DIST_DIR) pytest tests/unit/ -v

test-integration: ## Run integration tests (no real infrastructure required — event queue seam)
	ENABLE_EVENT_QUEUE=true \
	AGENT_WALLET_ADDRESS="" \
	uv run --find-links $(DIST_DIR) pytest tests/integration/ -v

deploy: deploy-storefront

# Buyers are pure HTTP clients (the `market` CLI / domains.vms.buyer
# library); they don't run a storefront. Use `make deploy-storefront`
# to bring up the seller; run `market buy ...` from the host or another
# container against `http://bob-storefront:8001`.
## RESOURCES_CSV_FILE: host path to the compute resource inventory CSV.
## Bind-mounted read-only into the container so the storefront can seed
## its resources table on startup via seller.resources_csv_path in config.
## Defaults to the dev inventory shipped in the source tree.
RESOURCES_CSV_FILE ?= $(CURDIR)/src/market_storefront/data/kvm1-machine.csv

deploy-storefront:
	docker run --rm -d --name bob-storefront \
	--network market -p 8001:8001 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	-e XDG_CONFIG_HOME=/etc \
	-v $(CURDIR)/storefront.bob.toml:/etc/arkhai/storefront.toml:ro \
	-v $(RESOURCES_CSV_FILE):/app/resources.csv:ro \
	arkhai:storefront

deploy-dev:
	docker run --rm -it --name bob-storefront \
	--network market -p 8001:8001 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	-e XDG_CONFIG_HOME=/etc \
	-v $(CURDIR)/storefront.bob.toml:/etc/arkhai/storefront.toml:ro \
	-v $(RESOURCES_CSV_FILE):/app/resources.csv:ro \
	arkhai:storefront

stop:
	docker kill bob-storefront

status:
	curl -s -X GET http://localhost:8001/api/v1/system/status -H "X-Admin-Key: test-api-key" | jq .
