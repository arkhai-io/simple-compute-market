IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= storefront
GIT_SUFFIX := $(shell git rev-parse --short HEAD)

# Path to the monorepo .dist/ wheel directory, relative to domains/vms/storefront/.
# Used by uv when resolving pure-Python internal packages
# (arkhai-kit-policy, arkhai-compute-provisioning) that are
# distributed as wheels rather than editable source installs. The
# Dockerfile passes --find-links /dist on the uv sync CLI instead;
# this variable is for local development only.
DIST_DIR ?= ../../../.dist
# Podman may reuse cross-stage layers after an internal wheel changes. Make the
# wheel set an explicit cache key for both image stages.
DIST_FINGERPRINT := $(shell find $(DIST_DIR) -maxdepth 1 -type f -name '*.whl' -exec cksum {} + 2>/dev/null | LC_ALL=C sort | cksum | awk '{print $$1}')
HOSTED_RELEASE_TRUST ?= ../../../manifests/hosted-settlement-v0.1.0-trust.json
HOSTED_RELEASE_MANIFEST ?= $(DIST_DIR)/release-manifest.json
HOSTED_CLIENT_WHEEL ?= $(DIST_DIR)/arkhai_hosted_settlement_client-0.1.0-py3-none-any.whl
VERIFY_HOSTED_RELEASE = uv run --no-project --with 'eth-account>=0.13,<0.14' \
	python ../../../scripts/verify-hosted-release.py \
	--trust $(HOSTED_RELEASE_TRUST) \
	--manifest $(HOSTED_RELEASE_MANIFEST) \
	--wheel $(HOSTED_CLIENT_WHEEL)

.PHONY: build build-images build-no-cache deploy deploy-storefront init reinit test test-unit test-integration verify-hosted-release

verify-hosted-release:
	$(VERIFY_HOSTED_RELEASE)

init: verify-hosted-release ## Resolve deps from verified wheels and create .venv.
	uv sync --find-links $(DIST_DIR)

reinit: verify-hosted-release ## Force-reinstall verified internal wheels.
	uv sync --find-links $(DIST_DIR) \
	--upgrade-package arkhai-core                    --reinstall-package arkhai-core \
	--upgrade-package arkhai-core-storefront         --reinstall-package arkhai-core-storefront \
	--upgrade-package arkhai-vms-storefront       --reinstall-package arkhai-vms-storefront \
	--upgrade-package arkhai-bare-metal             --reinstall-package arkhai-bare-metal \
	--upgrade-package arkhai-kit-identity            --reinstall-package arkhai-kit-identity \
	--upgrade-package arkhai-kit-alkahest            --reinstall-package arkhai-kit-alkahest \
	--upgrade-package arkhai-kit-config              --reinstall-package arkhai-kit-config \
	--upgrade-package arkhai-kit-policy              --reinstall-package arkhai-kit-policy \
	--upgrade-package arkhai-kit-settlement-runtime  --reinstall-package arkhai-kit-settlement-runtime \
	--upgrade-package arkhai-hosted-settlement-client --reinstall-package arkhai-hosted-settlement-client \
	--upgrade-package arkhai-kit-hosted-settlement     --reinstall-package arkhai-kit-hosted-settlement \
	--upgrade-package arkhai-kit-site                --reinstall-package arkhai-kit-site \
	--upgrade-package arkhai-kit-resource-pools       --reinstall-package arkhai-kit-resource-pools \
	--upgrade-package arkhai-kit-fulfillment         --reinstall-package arkhai-kit-fulfillment \
	--upgrade-package arkhai-vms              --reinstall-package arkhai-vms \
	--upgrade-package arkhai-compute-provisioning --reinstall-package arkhai-compute-provisioning \
	--upgrade-package arkhai-core-storefront-client  --reinstall-package arkhai-core-storefront-client \
	--upgrade-package arkhai-kit-site-client         --reinstall-package arkhai-kit-site-client \
	--upgrade-package arkhai-core-registry-client    --reinstall-package arkhai-core-registry-client

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
	docker build --ulimit nofile=65536 -f Dockerfile --build-arg INSTALL_RL_DEPS=false --build-arg DIST_FINGERPRINT=$(DIST_FINGERPRINT) -t ${IMAGE_NAME}:${IMAGE_TAG} ../../..
	docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-$(GIT_SUFFIX)

build-no-cache: ## Full Docker cache bust — use when .dist/ changes are not picked up by build-images.
	docker build --no-cache --ulimit nofile=65536 -f Dockerfile --build-arg INSTALL_RL_DEPS=false --build-arg DIST_FINGERPRINT=$(DIST_FINGERPRINT) -t ${IMAGE_NAME}:${IMAGE_TAG} ../../..
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
