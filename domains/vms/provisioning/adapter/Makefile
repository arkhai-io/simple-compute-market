DIST_DIR ?= ../../../../.dist
PYTHON_VERSION ?= 3.12

.PHONY: reinit test

reinit:
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-compute-provisioning --reinstall-package arkhai-compute-provisioning \
		--upgrade-package arkhai-compute-provisioning-service --reinstall-package arkhai-compute-provisioning-service \
		--upgrade-package arkhai-vms-provisioning-adapter --reinstall-package arkhai-vms-provisioning-adapter \
		--upgrade-package arkhai-vms-provisioning-operator-client --reinstall-package arkhai-vms-provisioning-operator-client \
		--upgrade-package arkhai-vms --reinstall-package arkhai-vms \
		--upgrade-package arkhai-bare-metal --reinstall-package arkhai-bare-metal \
		--upgrade-package arkhai-kit-resource-pools --reinstall-package arkhai-kit-resource-pools \
		--upgrade-package arkhai-kit-fulfillment --reinstall-package arkhai-kit-fulfillment

test: reinit
	uv run --find-links $(DIST_DIR) pytest ../../../../provisioning/compute/service/tests/unit/services/test_ansible_fulfillment_provider.py -q
