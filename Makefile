#Basic flow: build (optional), init (downloads if not built), run 
#Build should construct all deployment and runtime arifacts locally.
build: build-cli

build-cli: init-prerequisites init-dependencies
	cd cli && make build

#Init should complete all deployment times set up steps required prior to your standalone run statements
#The less of these the better but sometimes you get things like helm repo add or terraform init that can't be avoided.
init: init-cli init-images

init-prerequisites:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }

init-dependencies: init-zero-tier init-agent init-registry init-cli

#requires sudo
init-zero-tier:
	cd infra && make install

#In this branch the erc-8004-contracts folder is a submodule that isn't downloaded. I'm fine with inter-repo composition but the lower level things should be put into an artifactory and downloaded by whatever comes next.
#As a result while I have Anvil set up, I can't npm install and deploy the contracts.
init-contracts:
	npm install ./erc-8004-contracts

init-registry:
	cd erc-8004-registry-py && uv sync

init-agent:
	cd agent && make init

# Initializing the cli should be as simple as downloading a standalone exe. This shouldn't need pip, uv, or even python.
init-cli:
	echo "NYI"

# This will eventually download the docker images
init-images:
	echo "NYI"

#Ideally a helm chart eventually replaces 3 different docker run statements so all you have to do is edit a values file, init a helm+docker repo, and helm install
deploy: deploy-test-env deploy-registry deploy-agent

#This currently eats the window to run the web service, we should replace the test-env target with a docker run command so we can run a single init command when we can.
deploy-test-env:
	cd agent && make test-env

#Again this eats the window. Same suggestions as test-env apply here.
deploy-registry:
	cd erc-8004-registry-py && make serve

#Again this eats the window. Same suggestions as test-env apply here.
deploy-agent:
	cd agent && make serve-a2a

#We're also going to want some targets built to idempotently smoke test a deployment