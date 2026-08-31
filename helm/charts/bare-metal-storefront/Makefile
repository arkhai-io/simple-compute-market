CHART_DIR := .
RELEASE ?= bare-metal-storefront
NAMESPACE ?= default
VALUES ?= examples/production-values.yaml
PYTHON ?= python3

.PHONY: template test-render deploy test stop

template:
	helm template $(RELEASE) $(CHART_DIR) --namespace $(NAMESPACE) --values $(VALUES)

test-render:
	$(PYTHON) tests/test_render.py

deploy:
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
		--namespace $(NAMESPACE) --create-namespace --values $(VALUES) --wait

test:
	helm test $(RELEASE) --namespace $(NAMESPACE) --logs

stop:
	helm uninstall $(RELEASE) --namespace $(NAMESPACE)
