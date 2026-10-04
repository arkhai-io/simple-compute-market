#!/usr/bin/env bash
# Structural identity/secret/optional-chain checks for the umbrella chart.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHART_DIR="$SCRIPT_DIR/.."
RELEASE="${RELEASE:-arkhai-test}"

DEFAULT_RENDERED="$(mktemp)"
FIAT_RENDERED="$(mktemp)"
EVM_RENDERED="$(mktemp)"
OVERLAP_RENDERED="$(mktemp)"
TWO_REGISTRIES_RENDERED="$(mktemp)"
BARE_METAL_RENDERED="$(mktemp)"
trap 'rm -f "$DEFAULT_RENDERED" "$FIAT_RENDERED" "$EVM_RENDERED" "$OVERLAP_RENDERED" "$TWO_REGISTRIES_RENDERED" "$BARE_METAL_RENDERED"' EXIT

helm template "$RELEASE" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" >"$DEFAULT_RENDERED" 2>/dev/null
helm template "$RELEASE-fiat" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" >"$FIAT_RENDERED" 2>/dev/null
helm template "$RELEASE-evm" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/eip191-evm-values.yaml" >"$EVM_RENDERED" 2>/dev/null
helm template "$RELEASE-overlap" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    --values "$CHART_DIR/fixtures/identity-overlap-values.yaml" \
    --set-string 'storefront.agents[0].config.Identity.service_peers.provisioning_default.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].config.Identity.service_peers.provisioning_default.principals[1].identifier=0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266' \
    --set-string 'storefront.agents[0].config.Identity.administrators.operator.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].config.Identity.administrators.operator.principals[1].identifier=0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc' \
    --set-string 'storefront.agents[0].internalRegistryTrust.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].internalRegistryTrust.principals[1].identifier=0x90f79bf6eb2c4f870365e785982e1f101e93b906' \
    --set-string 'storefront.agents[0].config.provisioning.identity.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].config.provisioning.identity.principals[1].identifier=0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266' >"$OVERLAP_RENDERED" 2>/dev/null
helm template "$RELEASE-registries" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/two-registries-values.yaml" >"$TWO_REGISTRIES_RENDERED" 2>/dev/null
helm template "$RELEASE-bare-metal" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --set 'bare-metal-storefront.enabled=true' >"$BARE_METAL_RENDERED" 2>/dev/null

errors=0
fail() {
    echo "FAIL  $*" >&2
    errors=$((errors + 1))
}
pass() {
    echo "ok    $*"
}

extract_section() {
    local rendered="$1"
    local pattern="$2"
    awk -v pat="$pattern" '
        /^# Source: / { in_section = ($0 ~ pat) }
        in_section { print }
    ' "$rendered"
}

expect_present() {
    local body="$1"
    local pattern="$2"
    local label="$3"
    if [[ -f "$body" ]]; then
        grep -qE "$pattern" "$body" && pass "$label" || fail "$label"
    else
        grep -qE "$pattern" <<<"$body" && pass "$label" || fail "$label"
    fi
}

expect_absent() {
    local body="$1"
    local pattern="$2"
    local label="$3"
    if [[ -f "$body" ]]; then
        if grep -qE "$pattern" "$body"; then
            fail "$label"
        else
            pass "$label"
        fi
    elif grep -qE "$pattern" <<<"$body"; then
        fail "$label"
    else
        pass "$label"
    fi
}

expect_render_failure() {
    local fixture="$1"
    local label="$2"
    if helm template "$RELEASE-invalid" "$CHART_DIR" \
        --values "$CHART_DIR/values.yaml" \
        --values "$fixture" >/dev/null 2>&1; then
        fail "$label"
    else
        pass "$label"
    fi
}

expect_override_failure() {
    local base_fixture="$1"
    local label="$2"
    shift 2
    if helm template "$RELEASE-invalid" "$CHART_DIR" \
        --values "$CHART_DIR/values.yaml" \
        --values "$base_fixture" "$@" >/dev/null 2>&1; then
        fail "$label"
    else
        pass "$label"
    fi
}

DEFAULT_CONFIGMAP="$(extract_section "$DEFAULT_RENDERED" 'storefront/templates/configmap\.yaml')"
DEFAULT_DEPLOYMENT="$(extract_section "$DEFAULT_RENDERED" 'storefront/templates/deployment\.yaml')"
DEFAULT_REGISTRY="$(extract_section "$DEFAULT_RENDERED" 'registry/templates/deployment\.yaml')"
DEFAULT_PROVISIONING_CONFIGMAP="$(extract_section "$DEFAULT_RENDERED" 'provisioning/templates/configmap\.yaml')"
DEFAULT_TEST_CONFIG="$(extract_section "$DEFAULT_RENDERED" 'templates/tests/test-config\.yaml')"
TWO_REGISTRIES_COMPUTE="$(extract_section "$TWO_REGISTRIES_RENDERED" 'charts/registry/templates/deployment\.yaml')"
TWO_REGISTRIES_CREDITS="$(extract_section "$TWO_REGISTRIES_RENDERED" 'charts/api-credits-registry/templates/deployment\.yaml')"
FIAT_DEPLOYMENT="$(extract_section "$FIAT_RENDERED" 'storefront/templates/deployment\.yaml')"
FIAT_REGISTRY="$(extract_section "$FIAT_RENDERED" 'registry/templates/deployment\.yaml')"
EVM_DEPLOYMENT="$(extract_section "$EVM_RENDERED" 'storefront/templates/deployment\.yaml')"
PROVISIONING_CONFIGMAP="$(extract_section "$FIAT_RENDERED" 'provisioning/templates/configmap\.yaml')"
PROVISIONING_DEPLOYMENT="$(extract_section "$FIAT_RENDERED" 'provisioning/templates/deployment\.yaml')"
OVERLAP_PROVISIONING_CONFIGMAP="$(extract_section "$OVERLAP_RENDERED" 'provisioning/templates/configmap\.yaml')"

expect_present "$DEFAULT_CONFIGMAP" 'storefront\.json:' "storefront ConfigMap renders"
expect_present "$DEFAULT_DEPLOYMENT" 'mountPath: +/etc/arkhai/storefront\.json$' "storefront mounts public config"
expect_present "$DEFAULT_DEPLOYMENT" 'name: +ARKHAI_IDENTITY_CREDENTIAL' "signer credential uses environment injection"
expect_present "$DEFAULT_DEPLOYMENT" 'name: +\"?arkhai-bob-identity\"?' "signer credential references a Secret"
expect_absent "$DEFAULT_RENDERED" 'private_key|privateKey|request_credential' "default manifests contain no signing key fields"
expect_absent "$DEFAULT_RENDERED" 'admin_api_key|adminApiKey|X-Admin-Key' "default manifests contain no legacy administrator shared secret"
expect_absent "$DEFAULT_RENDERED" 'charts/bare-metal-storefront/' "default render omits the dedicated bare-metal storefront"
expect_present "$BARE_METAL_RENDERED" 'charts/bare-metal-storefront/templates/deployment\.yaml' "dedicated bare-metal storefront can be enabled explicitly"
expect_present "$DEFAULT_REGISTRY" 'name: +REGISTRY_DESCRIPTOR_BASE_URL' "registry renders its public descriptor URL"
expect_present "$DEFAULT_REGISTRY" 'value: +"?Local VM Compute Registry"?' "registry renders its descriptor display name"
expect_present "$DEFAULT_REGISTRY" 'value: +"?Arkhai local development"?' "registry renders its operator identity"
expect_absent "$DEFAULT_REGISTRY" 'REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER' "public registry omits an acquisition pointer"
expect_present "$DEFAULT_REGISTRY" 'value: +"?/app/filter-spec\.yaml"?' "default registry selects the compute filter specification"
expect_absent "$DEFAULT_RENDERED" 'api-credits-registry' "default render omits the API-credits registry"
expect_present "$DEFAULT_PROVISIONING_CONFIGMAP" '"identifier": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"' "provisioning keeps EIP-191 identifiers as strings"
expect_present "$DEFAULT_TEST_CONFIG" '"identifier": "0x90f79bf6eb2c4f870365e785982e1f101e93b906"' "smoke-test profile keeps EIP-191 identifiers as strings"

expect_present "$CHART_DIR/../core/registry/filter-spec.yaml" 'id: +compute\.market' "compute filter specification declares compute.market"
expect_present "$CHART_DIR/../domains/apicredits/registry/filter-spec.yaml" 'id: +api_credits' "API-credits filter specification declares api_credits"
expect_present "$TWO_REGISTRIES_COMPUTE" 'name: +'"$RELEASE"'-registries-registry' "dual render names the compute workload independently"
expect_present "$TWO_REGISTRIES_COMPUTE" 'value: +"?/app/filter-spec\.yaml"?' "dual render selects the compute filter specification"
expect_present "$TWO_REGISTRIES_COMPUTE" 'secretName: +"?arkhai-registry-identity"?' "dual render keeps the compute signer Secret"
expect_present "$TWO_REGISTRIES_CREDITS" 'name: +'"$RELEASE"'-registries-api-credits-registry' "dual render names the API-credits workload independently"
expect_present "$TWO_REGISTRIES_CREDITS" 'value: +"?/app/filter-spec-apicredits\.yaml"?' "dual render selects the API-credits filter specification"
expect_present "$TWO_REGISTRIES_CREDITS" 'value: +"?https://credits\.example\.test"?' "dual render gives API credits its own descriptor URL"
expect_present "$TWO_REGISTRIES_CREDITS" 'secretName: +"?credits-registry-identity"?' "dual render gives API credits its own signer Secret"
expect_present "$TWO_REGISTRIES_RENDERED" 'name: +'"$RELEASE"'-registries-registry-data' "dual render keeps an independent compute PVC"
expect_present "$TWO_REGISTRIES_RENDERED" 'name: +'"$RELEASE"'-registries-api-credits-registry-data' "dual render creates an independent API-credits PVC"
expect_present "$TWO_REGISTRIES_RENDERED" 'name: +'"$RELEASE"'-registries-registry' "dual render keeps an independent compute Service"
expect_present "$TWO_REGISTRIES_RENDERED" 'name: +'"$RELEASE"'-registries-api-credits-registry' "dual render creates an independent API-credits Service"

expect_present "$FIAT_DEPLOYMENT" 'name: +\"?fiat-bob-marketplace-identity\"?' "fiat signer comes from a Secret reference"
expect_absent "$FIAT_DEPLOYMENT" 'wait-for-rpc|CHAIN_ID|RPC_URL' "fiat storefront pod omits chain readiness"
expect_absent "$FIAT_DEPLOYMENT" 'STOREFRONT_SETTLEMENT__HOSTED|HOSTED_SETTLEMENT' "fiat storefront pod emits no legacy settlement environment"
expect_absent "$FIAT_REGISTRY" 'CHAIN_ID|RPC_URL' "fiat registry pod omits chain configuration"
expect_present "$FIAT_REGISTRY" 'name: +REGISTRY_AUTHORITY_SCHEME' "fiat registry renders its public signer scheme"
expect_present "$FIAT_REGISTRY" 'value: +\"?NLTZBDFWy23PC-sKKUm3VZyUDSvLbb6MU6mzAnjjp0Y\"?' "fiat registry renders its public authority"
expect_present "$FIAT_REGISTRY" 'secretName: +\"?fiat-registry-identity\"?' "fiat registry signer credential is Secret-referenced"
expect_absent "$FIAT_RENDERED" 'private_key|privateKey|request_credential|STRIPE_[A-Z_]*KEY' "fiat manifests contain no private or provider credentials"
expect_absent "$FIAT_RENDERED" 'checkout\.stripe\.com|client_secret|payer_profile_ref|instrument_ref|payment_method|mandate|bank_instructions' "fiat manifests contain no payer, instrument, action, or bank material"
expect_present "$PROVISIONING_CONFIGMAP" '"scheme": "ed25519"' "fiat provisioning renders Ed25519 public principals"
expect_present "$PROVISIONING_CONFIGMAP" '"identifier": "xoImN8fTEOxXYnvgC6JZ0lN0n0qvZERwz_vlOjX3MkI"' "fiat provisioning renders its public service identity"
expect_absent "$PROVISIONING_CONFIGMAP" '"principal":' "provisioning renders the service identity at the runtime config path"
expect_absent "$PROVISIONING_CONFIGMAP" '"principals":' "provisioning renders singular bootstrap trust identities at their runtime config paths"
expect_absent "$FIAT_RENDERED" 'admin_api_key|adminApiKey|X-Admin-Key' "fiat manifests contain no legacy administrator shared secret"
expect_present "$PROVISIONING_CONFIGMAP" '"identifier": "0EqyMnQrtKs6E2i9RhXk5tAiSrcaAWuvhSCjMsl3hzc"' "fiat provisioning pins the trusted storefront principal"
expect_present "$PROVISIONING_CONFIGMAP" '"identifier": "5zTqbCtiV95yNV5HKqBaTEh-a0Y8Ap7TBt8vAbVja1g"' "fiat provisioning pins a distinct administrator principal"
expect_present "$PROVISIONING_DEPLOYMENT" 'name: +ARKHAI_IDENTITY_CREDENTIAL' "fiat provisioning injects its signer credential"
expect_present "$PROVISIONING_DEPLOYMENT" 'name: +\"?fiat-provisioning-identity\"?' "fiat provisioning signer is Secret-referenced"
expect_present "$FIAT_RENDERED" 'image: +[^[:space:]]+@sha256:1111111111111111111111111111111111111111111111111111111111111111' "fiat registry image is digest-pinned"
expect_present "$FIAT_RENDERED" 'image: +[^[:space:]]+@sha256:2222222222222222222222222222222222222222222222222222222222222222' "fiat provisioning image is digest-pinned"
expect_present "$FIAT_RENDERED" 'image: +[^[:space:]]+@sha256:3333333333333333333333333333333333333333333333333333333333333333' "fiat storefront image is digest-pinned"
expect_present "$FIAT_RENDERED" 'image: +[^[:space:]]+@sha256:4444444444444444444444444444444444444444444444444444444444444444' "fiat smoke images are digest-pinned"
expect_absent "$FIAT_RENDERED" 'kind: +Secret|sshPrivateKey|golden_root_ssh_password|relay_token' "fiat chart renders only pre-existing Secret references"

expect_absent "$OVERLAP_PROVISIONING_CONFIGMAP" '^[[:space:]]+principals:' "overlap profile keeps provisioning bootstrap identities singular"
expect_present "$EVM_DEPLOYMENT" 'wait-for-rpc' "EVM profile retains chain readiness"
expect_present "$EVM_DEPLOYMENT" 'name: +\"?evm-bob-marketplace-identity\"?' "EVM marketplace signer is Secret-referenced"
expect_present "$EVM_DEPLOYMENT" 'secretName: +\"?evm-bob-runtime\"?' "EVM wallet overlay is Secret-referenced"
expect_absent "$EVM_RENDERED" 'private_key|privateKey|request_credential|sshPrivateKey|golden_root_ssh_password|relay_token' "EVM manifests reference secrets without embedding keys"

expect_render_failure \
    "$CHART_DIR/fixtures/invalid-missing-identity-secret-values.yaml" \
    "missing identity Secret reference fails schema/render"
expect_render_failure \
    "$CHART_DIR/fixtures/invalid-missing-registry-identity-secret-values.yaml" \
    "missing registry signer Secret reference fails schema/render"
expect_render_failure \
    "$CHART_DIR/fixtures/invalid-registry-authority-mismatch-values.yaml" \
    "mismatched active registry authority fails render"
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "legacy hosted values fail schema/render" \
    --set 'storefront.agents[0].config.hostedSettlement.enabled=true'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "provider fields fail the generated storefront schema" \
    --set-string 'storefront.agents[0].config.Settlement.stripe.webhook_secret=forbidden'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "buyer off-session policy fails the generated storefront schema" \
    --set 'storefront.agents[0].config.Settlement.stripe.off_session_policy.enabled=false'
expect_override_failure \
    "$CHART_DIR/fixtures/eip191-evm-values.yaml" \
    "a wallet key in pass-through config fails the generated storefront schema" \
    --set-string 'storefront.agents[0].config.Wallet.private_key=0xforbidden'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "key-gated registry without an acquisition pointer fails render" \
    --set 'registry.config.requireReadApiKey=true'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "public registry with an acquisition pointer fails render" \
    --set-string 'registry.descriptor.accessAcquisitionPointer=https://registry.example/access'
# Each chart's own render tests (docs/development/TESTING.md, "Chart Render
# Tests"), so this one target runs every render check. The storefront chart's
# tests also load a rendered document with the storefront's own loader when its
# environment exists (make init-storefront); without it they say so and skip.
STOREFRONT_ENV_PYTHON="$CHART_DIR/../domains/vms/storefront/.venv/bin/python"
if [[ -z "${STOREFRONT_PYTHON:-}" && -x "$STOREFRONT_ENV_PYTHON" ]]; then
    export STOREFRONT_PYTHON="$STOREFRONT_ENV_PYTHON"
fi
for chart_test in "$CHART_DIR"/charts/*/tests/test_render.py; do
    if ! "${PYTHON:-python3}" "$chart_test"; then
        echo "FAIL: $chart_test" >&2
        errors=$((errors + 1))
    fi
done
if [[ $errors -gt 0 ]]; then
    echo "$errors assertion(s) failed" >&2
    exit 1
fi
echo "All structural identity assertions passed."
