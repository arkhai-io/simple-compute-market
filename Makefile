GIT_SUFFIX := $(shell git rev-parse --short HEAD)
FOUNDRY_VERSION := v1.5.1

.PHONY: build build-runtime-images

#Basic flow: build (optional), init (downloads if not built), run
#Build should construct all deployment and runtime arifacts locally.
# build-test-env must run after build-market-contract-deployer (uses the image).
# build-runtime-images parallelizes the three independent service images.
build: build-cli build-market-contract-deployer build-test-env build-runtime-images

build-runtime-images:
	$(MAKE) -j3 build-registry build-core build-provisioning

build-cli: init-prerequisites init-dependencies
	cd cli && make build

build-market-contract-deployer:
	cd market-contract-deployer && make build

#The anvil rpc url is hard coded inside of deploy_alkhahest.py. Don't change the network name or anvil container name.
#Yes it's weird running containers to build a container but the --init <genesis.json> way of initializing anvil looks tedious
build-anvil-state:
	-docker network create anvil
	-mkdir shared-env
	docker run -d --rm --network anvil --name anvil -p 8545:8545 -e ANVIL_IP_ADDR=0.0.0.0 -v ./test-env/state:/state --user root --entrypoint anvil ghcr.io/foundry-rs/foundry:${FOUNDRY_VERSION} --dump-state /state/state.json
	docker run --rm --network anvil --name market-contracts-deploy -e ENV_FILE=/app/shared-env/.env -v ./shared-env:/app/shared-env/ arkhai:contract-deployer
	echo "Todo: add a step here to verify contract deployment"
	docker stop anvil
	-docker network rm anvil

build-test-env: build-anvil-state
	cd test-env && make build

build-registry:
	cd erc-8004-registry-py && make build

build-core:
	cd core && make build

build-provisioning:
	cd async-provisioning-service && make build

#Init should complete all deployment times set up steps required prior to your standalone run statements
#The less of these the better but sometimes you get things like helm repo add or terraform init that can't be avoided.
init: init-submodules init-cli init-images

init-prerequisites:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }

init-submodules:
	GIT_TRACE=1 GIT_CURL_TRACE=1 git submodule update --init

init-dependencies: init-zero-tier init-cli

#requires sudo
init-zero-tier:
	cd infra && make install

# Initializing the cli should be as simple as downloading a standalone exe. This shouldn't need pip, uv, or even python.
init-cli:
	echo "NYI"

# This will eventually download the docker images
init-images:
	echo "NYI"

deploy-compose:
	docker compose up
	docker compose ps

#Ideally a helm chart eventually replaces the different docker run statements so all you have to do is edit a values file, init a helm+docker repo, and helm install
deploy: deploy-test-env deploy-registry deploy-agents deploy-provisioning

#docker run -it --rm -v ./test-env/state:/state arkhai:test-env-$(GIT_SUFFIX) anvil --load-state /state/state.json
deploy-test-env:
	cd test-env && make deploy

deploy-registry:
	cd erc-8004-registry-py && make deploy

deploy-agents:
	cd core && make deploy

deploy-provisioning:
	cd async-provisioning-service && make deploy

#We're also going to want some targets built to idempotently smoke test a deployment
stop-compose:
	docker compose down
	docker compose rm