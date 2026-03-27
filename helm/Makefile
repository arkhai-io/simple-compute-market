# Makefile for arkhai-node-operator Helm chart

CHART_DIR    := .
RELEASE      := arkhai-node-operator
NAMESPACE    := default
VALUES       := values.yaml
SSH_KEY_FILE ?= $(HOME)/.ssh/id_ed25519

.PHONY: init template deploy test

## Update Helm dependencies declared in Chart.yaml
init:
	helm dependency update $(CHART_DIR)

## Render the full parent chart (and all enabled subcharts) to stdout
template:
	helm template $(RELEASE) $(CHART_DIR) \
		--namespace $(NAMESPACE) \
		--values $(VALUES)

## Render a single subchart in isolation.
## Requires MODULE=<subchart-name>, e.g. make template-module MODULE=test-env
template-module:
ifndef MODULE
	$(error MODULE is not set. Usage: make template-module MODULE=<subchart-name>)
endif
	helm template $(RELEASE)-$(MODULE) $(CHART_DIR)/charts/$(MODULE) \
		--namespace $(NAMESPACE) \
		--values $(CHART_DIR)/charts/$(MODULE)/values.yaml

## Install or upgrade the release in the target namespace
## SSH_KEY_FILE defaults to ~/.ssh/id_ed25519. Override with:
##   make deploy SSH_KEY_FILE=/path/to/other_key
deploy: init
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--values $(VALUES) \
		--set-file provisioning.sshKey.sshPrivateKey=$(SSH_KEY_FILE) \
		--wait

## Run helm tests against the deployed release
test:
	helm test $(RELEASE) \
		--namespace $(NAMESPACE) \
		--logs

## Run helm tests for a single subchart.
## Requires MODULE=<subchart-name>, e.g. make test-module MODULE=validate-contracts
## Valid values: validate-contracts, registry, agents, provisioning
##
## Test pod names per module:
##   validate-contracts → $(RELEASE)-validate-contracts-chain-environment-test
##   registry           → $(RELEASE)-registry-registry-environment-test
##   agents             → $(RELEASE)-agents-agents-environment-test
##   provisioning       → $(RELEASE)-provisioning-provisioning-environment-test
TEST_POD_SUFFIX_validate-contracts := chain-environment-test
TEST_POD_SUFFIX_registry           := registry-environment-test
TEST_POD_SUFFIX_agents             := agents-environment-test
TEST_POD_SUFFIX_provisioning       := provisioning-environment-test
 
test-module:
ifndef MODULE
	$(error MODULE is not set. Usage: make test-module MODULE=<subchart-name>)
endif
	helm test $(RELEASE) \
		--namespace $(NAMESPACE) \
		--logs \
		--filter name=$(RELEASE)-$(MODULE)-$(TEST_POD_SUFFIX_$(MODULE))

# PID file used by forward/unforward targets
FORWARD_PID_FILE := .port-forward.pids

## Forward all service ports to localhost in the background.
## PIDs are written to $(FORWARD_PID_FILE) so unforward can clean them up.
## Access services at:
##   Anvil RPC   http://localhost:8545
##   Registry    http://localhost:8080
##   Agent buy   http://localhost:8000
##   Agent sell  http://localhost:8001
##   Provisioning http://localhost:8081
##   Provisioning worker  http://localhost:8082
forward: unforward
	@echo "Starting port-forwards..."
	@kubectl port-forward --namespace $(NAMESPACE) \
		svc/$(RELEASE)-test-env 8545:8545 > /dev/null 2>&1 & echo $$! >> $(FORWARD_PID_FILE)
	@kubectl port-forward --namespace $(NAMESPACE) \
		svc/$(RELEASE)-registry 8080:8080 > /dev/null 2>&1 & echo $$! >> $(FORWARD_PID_FILE)
	@kubectl port-forward --namespace $(NAMESPACE) \
		svc/$(RELEASE)-agents-buyer 8000:8000 > /dev/null 2>&1 & echo $$! >> $(FORWARD_PID_FILE)
	@kubectl port-forward --namespace $(NAMESPACE) \
		svc/$(RELEASE)-agents-seller 8001:8001 > /dev/null 2>&1 & echo $$! >> $(FORWARD_PID_FILE)
	@kubectl port-forward --namespace $(NAMESPACE) \
		svc/$(RELEASE)-provisioning 8081:8081 > /dev/null 2>&1 & echo $$! >> $(FORWARD_PID_FILE)
	@kubectl port-forward --namespace $(NAMESPACE) \
		svc/$(RELEASE)-provisioning-worker 8082:8082 > /dev/null 2>&1 & echo $$! >> $(FORWARD_PID_FILE)
	@echo "  anvil    → http://localhost:8545"
	@echo "  registry → http://localhost:8080"
	@echo "  buy      → http://localhost:8000"
	@echo "  sell     → http://localhost:8001"
	@echo "  prov     → http://localhost:8081"
	@echo "  prov-wkr → http://localhost:8082"
	@echo "Run 'make unforward' to stop."

## Kill all port-forwards started by 'make forward'
unforward:
	@test -f $(FORWARD_PID_FILE) && cat $(FORWARD_PID_FILE) | xargs kill 2>/dev/null; rm -f $(FORWARD_PID_FILE); true