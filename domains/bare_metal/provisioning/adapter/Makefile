DIST_DIR ?= ../../../../.dist
PYTHON_VERSION ?= 3.12

.PHONY: reinit test

# --find-links resolves the internal packages from built wheels rather than
# from PyPI. Without it uv re-resolves the published releases, which lag this
# checkout, and the suite fails on imports that exist only in the local tree.
reinit:
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-bare-metal --reinstall-package arkhai-bare-metal \
		--upgrade-package arkhai-compute-provisioning --reinstall-package arkhai-compute-provisioning \
		--upgrade-package arkhai-compute-provisioning-service --reinstall-package arkhai-compute-provisioning-service \
		--upgrade-package arkhai-vms-provisioning-adapter --reinstall-package arkhai-vms-provisioning-adapter \
		--upgrade-package arkhai-vms-provisioning-operator-client --reinstall-package arkhai-vms-provisioning-operator-client \
		--upgrade-package arkhai-kit-fulfillment --reinstall-package arkhai-kit-fulfillment \
		--upgrade-package arkhai-kit-resource-pools --reinstall-package arkhai-kit-resource-pools

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests/ -q
