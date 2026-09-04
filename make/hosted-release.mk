# Which hosted settlement release this repository binds, and everything that
# follows from it. Included by every Makefile that verifies or installs the
# hosted client.
#
# No version is spelled here. Which release is bound follows from the version
# `kit/hosted-settlement/pyproject.toml` pins and whether `manifests/` holds a
# trust configuration signing it -- the relationship
# `scripts/select-hosted-client-channel.py` already owns. Naming a trust file
# per directory made that a third statement, and it was the one that named the
# previous release. A caller may still supply HOSTED_RELEASE_TRUST directly,
# and then everything below follows from that file instead.
#
# Each including Makefile sets HOSTED_REPO_ROOT -- the one fact only it knows --
# and HOSTED_RELEASE_DIR before including this file.

ifndef HOSTED_REPO_ROOT
$(error include hosted-release.mk only after setting HOSTED_REPO_ROOT)
endif

# `$(HOSTED_REPO_ROOT)/x` reads as `./x` from the root, which is the same path
# spelled differently. Keep one spelling so the commands built below are
# comparable across directories.
_hosted_path = $(patsubst ./%,%,$(HOSTED_REPO_ROOT)/$(1))

HOSTED_CHANNEL := $(shell uv run --no-project python \
	$(call _hosted_path,scripts/select-hosted-client-channel.py) 2>/dev/null)
_hosted_field = $(patsubst $(1)=%,%,$(filter $(1)=%,$(HOSTED_CHANNEL)))

_hosted_selected_trust := $(call _hosted_field,trust)
HOSTED_RELEASE_TRUST ?= $(if $(_hosted_selected_trust),$(call _hosted_path,$(_hosted_selected_trust)))
HOSTED_RELEASE_MANIFEST ?= $(HOSTED_RELEASE_DIR)/release-manifest.json

ifeq ($(HOSTED_RELEASE_TRUST),)

# The pinned version is not signed. There is no release to verify -- which is
# not the same as verifying the last signed release, a different release than
# the one this source consumes. That is what a hardcoded trust filename did.
#
# This states the situation and succeeds, because an unsigned pin is a state
# the design supports: the wheel comes from the producer's access-controlled
# index, or from a local build, while a capability runs ahead of a publish. A
# protected run binds a signed release by construction and so never lands here;
# if it did it would carry an empty `--trust` and fail closed in the verifier.
HOSTED_RELEASE_VERSION ?= $(call _hosted_field,version)
HOSTED_CLIENT_WHEEL ?= $(HOSTED_RELEASE_DIR)/$(call _hosted_field,wheel)
VERIFY_HOSTED_RELEASE = printf '%s\n' \
	'hosted client $(HOSTED_RELEASE_VERSION) is pinned and unsigned: no trust' \
	'configuration in manifests/ names it, so there is no release to verify' \
	'and the wheel is expected from the producer index or a local build.'

else

# Which release is bound is a choice, made once. What that release contains is
# not a choice -- it follows -- so the wheel name is derived from the version
# the trust config states rather than spelled out beside it, where it would have
# to be edited in step with it and would name the previous release when it was
# not. The verifier derives every artifact name from that same config.
HOSTED_RELEASE_CONTRACT := $(shell uv run --no-project python -c \
	"import json;d=json.load(open('$(HOSTED_RELEASE_TRUST)'));print(d['release_version'],d['schema_version'])" 2>/dev/null)
HOSTED_RELEASE_VERSION ?= $(word 1,$(HOSTED_RELEASE_CONTRACT))
HOSTED_CLIENT_WHEEL ?= $(HOSTED_RELEASE_DIR)/arkhai_hosted_settlement_client-$(HOSTED_RELEASE_VERSION)-py3-none-any.whl
VERIFY_HOSTED_RELEASE = uv run --no-project --with 'eth-account>=0.13,<0.14' \
	python $(call _hosted_path,scripts/verify-hosted-release.py) \
	--trust $(HOSTED_RELEASE_TRUST) \
	--manifest $(HOSTED_RELEASE_MANIFEST) \
	--wheel $(HOSTED_CLIENT_WHEEL)

endif
