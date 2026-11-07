export UV_PYTHON := $(or $(shell cat ../../../../.python-version 2>/dev/null),$(error ../../../../.python-version not found))
.PHONY: test

test:
	uv run pytest tests -q -m 'not native'
	@echo 'Native account/kernel checks omitted; run make test-bare-metal-iac-native at repository root.'

.PHONY: native-cleanup-gate
native-cleanup-gate:
	bash scripts/native_cleanup_gate.sh
