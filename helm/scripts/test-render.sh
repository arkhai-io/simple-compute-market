#!/usr/bin/env bash
# Structural identity/secret/optional-chain checks for the umbrella chart.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHART_DIR="$SCRIPT_DIR/.."
RELEASE="${RELEASE:-arkhai-test}"
"${PYTHON:-python3}" "$SCRIPT_DIR/check-settlement-schema-drift.py"

DEFAULT_RENDERED="$(mktemp)"
EVM_RENDERED="$(mktemp)"
OVERLAP_RENDERED="$(mktemp)"
trap 'rm -f "$DEFAULT_RENDERED" "$EVM_RENDERED" "$OVERLAP_RENDERED"' EXIT

helm template "$RELEASE" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" >"$DEFAULT_RENDERED" 2>/dev/null
helm template "$RELEASE-evm" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/eip191-evm-values.yaml" >"$EVM_RENDERED" 2>/dev/null
helm template "$RELEASE-overlap" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/identity-overlap-values.yaml" \
    --set-string 'storefront.agents[0].identity.servicePeers.provisioning_default.principals[0].scheme=ed25519' \
    --set-string 'storefront.agents[0].identity.servicePeers.provisioning_default.principals[0].identifier=xoImN8fTEOxXYnvgC6JZ0lN0n0qvZERwz_vlOjX3MkI' \
    --set-string 'storefront.agents[0].identity.administrators.operator.principals[0].scheme=ed25519' \
    --set-string 'storefront.agents[0].identity.administrators.operator.principals[0].identifier=5zTqbCtiV95yNV5HKqBaTEh-a0Y8Ap7TBt8vAbVja1g' \
    --set-string 'storefront.agents[0].config.registryAuthority.principals[0].scheme=ed25519' \
    --set-string 'storefront.agents[0].config.registryAuthority.principals[0].identifier=NLTZBDFWy23PC-sKKUm3VZyUDSvLbb6MU6mzAnjjp0Y' \
    --set-string 'storefront.agents[0].config.seller.provisioning.identity.principals[0].scheme=ed25519' \
    --set-string 'storefront.agents[0].config.seller.provisioning.identity.principals[0].identifier=xoImN8fTEOxXYnvgC6JZ0lN0n0qvZERwz_vlOjX3MkI' \
    --set-string 'storefront.agents[0].identity.servicePeers.provisioning_default.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].identity.servicePeers.provisioning_default.principals[1].identifier=0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266' \
    --set-string 'storefront.agents[0].identity.administrators.operator.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].identity.administrators.operator.principals[1].identifier=0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc' \
    --set-string 'storefront.agents[0].config.registryAuthority.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].config.registryAuthority.principals[1].identifier=0x90f79bf6eb2c4f870365e785982e1f101e93b906' \
    --set-string 'storefront.agents[0].config.seller.provisioning.identity.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].config.seller.provisioning.identity.principals[1].identifier=0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266' \
>"$OVERLAP_RENDERED" 2>/dev/null

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
EVM_CONFIGMAP="$(extract_section "$EVM_RENDERED" 'storefront/templates/configmap\.yaml')"
EVM_DEPLOYMENT="$(extract_section "$EVM_RENDERED" 'storefront/templates/deployment\.yaml')"
OVERLAP_CONFIGMAP="$(extract_section "$OVERLAP_RENDERED" 'storefront/templates/configmap\.yaml')"
OVERLAP_PROVISIONING_CONFIGMAP="$(extract_section "$OVERLAP_RENDERED" 'provisioning/templates/configmap\.yaml')"

expect_present "$DEFAULT_CONFIGMAP" 'storefront\.toml:' "storefront ConfigMap renders"
expect_present "$DEFAULT_DEPLOYMENT" 'mountPath: +/etc/arkhai/storefront\.toml' "storefront mounts public config"
expect_present "$DEFAULT_DEPLOYMENT" 'name: +ARKHAI_IDENTITY_CREDENTIAL' "signer credential uses environment injection"
expect_present "$DEFAULT_DEPLOYMENT" 'name: +\"?arkhai-bob-identity\"?' "signer credential references a Secret"
expect_present "$DEFAULT_CONFIGMAP" 'priority = \[\]' "new defaults have empty settlement priority"
expect_absent "$DEFAULT_CONFIGMAP" '\[Settlement\.alkahest\]' "new defaults install no mechanism subsection"
expect_absent "$DEFAULT_RENDERED" 'private_key|privateKey|request_credential' "default manifests contain no signing key fields"
expect_absent "$DEFAULT_RENDERED" 'admin_api_key|adminApiKey|X-Admin-Key' "default manifests contain no legacy administrator shared secret"


expect_present "$EVM_CONFIGMAP" 'scheme = \"eip191\"' "EVM profile renders explicit EIP-191 scheme"
expect_present "$EVM_CONFIGMAP" '\[Settlement\.alkahest\]' "EVM profile renders canonical Alkahest mechanism"
expect_present "$EVM_CONFIGMAP" 'priority = \["alkahest\.v1"\]' "EVM profile selects only Alkahest"
expect_present "$EVM_CONFIGMAP" '\[Chains\.anvil\]' "EVM profile renders explicit chain"
expect_present "$OVERLAP_CONFIGMAP" 'principals = \[\{ scheme = \"ed25519\"[^]]+\}, \{ scheme = \"eip191\"' "overlap profile renders ordered two-principal storefront trust"
expect_present "$OVERLAP_PROVISIONING_CONFIGMAP" 'identifier: +0x9965507d1a55bcc2695c58ba16fb37d819b0a4dc' "overlap profile renders second provisioning administrator principal"
expect_present "$EVM_CONFIGMAP" 'chain_id = 31337' "EVM profile renders explicit chain ID"
expect_present "$EVM_DEPLOYMENT" 'wait-for-rpc' "EVM profile retains chain readiness"
expect_present "$EVM_DEPLOYMENT" 'name: +\"?evm-bob-marketplace-identity\"?' "EVM marketplace signer is Secret-referenced"
expect_present "$EVM_DEPLOYMENT" 'secretName: +\"?evm-bob-runtime\"?' "EVM wallet overlay is Secret-referenced"
expect_absent "$EVM_RENDERED" 'private_key|privateKey|request_credential|sshPrivateKey|golden_root_ssh_password|frp_dashboard_password' "EVM manifests reference secrets without embedding keys"

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
    "$CHART_DIR/fixtures/eip191-evm-values.yaml" \
    "Alkahest without wallet Secret fails schema/render" \
    --set-string 'storefront.agents[0].secret.secretName='



if [[ $errors -gt 0 ]]; then
    echo "$errors assertion(s) failed" >&2
    exit 1
fi
echo "All structural identity assertions passed."
