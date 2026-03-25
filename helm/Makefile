# Makefile for arkhai-node-operator Helm chart
#
# Usage:
#   make template                    # Template the full parent chart
#   make template-module MODULE=test-env  # Template a single subchart
#   make deploy                      # Install or upgrade the release
#   make test                        # Run helm tests against the release

CHART_DIR   := .
RELEASE     := arkhai-node-operator
NAMESPACE   := default
VALUES      := values.yaml

.PHONY: dep template template-module deploy test

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
deploy: init
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--values $(VALUES) \
		--wait

## Run helm tests against the deployed release
test:
	helm test $(RELEASE) \
		--namespace $(NAMESPACE) \
		--logs