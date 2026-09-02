#!/usr/bin/env bash
# Structural identity/secret/optional-chain checks for the umbrella chart.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHART_DIR="$SCRIPT_DIR/.."
RELEASE="${RELEASE:-arkhai-test}"
"${PYTHON:-python3}" "$SCRIPT_DIR/check-settlement-schema-drift.py"

DEFAULT_RENDERED="$(mktemp)"
FIAT_RENDERED="$(mktemp)"
EVM_RENDERED="$(mktemp)"
DUAL_RENDERED="$(mktemp)"
OVERLAP_RENDERED="$(mktemp)"
TWO_REGISTRIES_RENDERED="$(mktemp)"
trap 'rm -f "$DEFAULT_RENDERED" "$FIAT_RENDERED" "$EVM_RENDERED" "$DUAL_RENDERED" "$OVERLAP_RENDERED" "$TWO_REGISTRIES_RENDERED"' EXIT

helm template "$RELEASE" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" >"$DEFAULT_RENDERED" 2>/dev/null
helm template "$RELEASE-fiat" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" >"$FIAT_RENDERED" 2>/dev/null
helm template "$RELEASE-evm" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/eip191-evm-values.yaml" >"$EVM_RENDERED" 2>/dev/null
helm template "$RELEASE-dual" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/eip191-evm-values.yaml" \
    --set-json 'storefront.agents[0].config.settlement.priority=["fiat.stripe.v1","alkahest.v1"]' \
    --set 'storefront.agents[0].config.settlement.stripe.enabled=true' \
    --set-string 'storefront.agents[0].config.settlement.stripe.base_url=https://hosted-settlement.example.test' \
    --set-string 'storefront.agents[0].config.settlement.stripe.authority_id=hosted-authority' \
    --set-string 'storefront.agents[0].config.settlement.stripe.environment=test' \
    --set-string 'storefront.agents[0].config.settlement.stripe.account_ref=account-protected' \
    --set-string 'storefront.agents[0].config.settlement.stripe.currency=usd' \
    --set-string 'storefront.agents[0].config.settlement.stripe.country=US' \
    --set-string 'storefront.agents[0].config.settlement.stripe.condition_profile=vm-fulfillment' \
    --set-json 'storefront.agents[0].config.settlement.stripe.condition_profiles={"vm-fulfillment":{"condition_id":"vm-fulfillment","evaluator":{"kind":"builtin.v1","version":"trivial.v1","resolver_id":"vm-portable","params":{"kind":"trivial"}},"demand":{"encoding":"application/jcs+json","value":{}}}}' \
    --set-json 'storefront.agents[0].config.settlement.stripe.resolvers={"vm-portable":{"chain_name":"fiat.stripe.v1","evidence_mode":"portable-remote.v1"}}' \
    --set-json 'storefront.agents[0].config.pricing={"default_min_price":"1","default_token_address":"","default_max_duration_seconds":0,"settlements":[{"mechanism":"alkahest.v1","asset":"0x0000000000000000000000000000000000000001","rate":"1","per":"hour","mechanism_input":{"chain":"anvil"}},{"mechanism":"fiat.stripe.v1","asset":"usd","rate":"100","per":"hour","mechanism_input":{"funding_profile":"card.v1","interaction":"interactive","funds_flow":"separate_charges_transfers"}}]}' \
    --set-string 'storefront.agents[0].config.settlement.stripe.expected_manifest_digest=sha256:4859b12cb8703a3c1db85c9636be903f493ae9a9ad1795ffb18a8f801a843a7e' \
    --set-string 'storefront.agents[0].config.settlement.stripe.expected_api_version=0.2.1' \
    --set 'storefront.agents[0].config.settlement.stripe.expected_schema_version=5' \
    --set-json 'storefront.agents[0].config.settlement.stripe.authority.principals=[{"scheme":"eip191","identifier":"0x1c5a77d9fa7ef466951b2f01f724bca3a5820b63"}]' \
    --set-json 'storefront.agents[0].config.settlement.stripe.required_capabilities=["scheme-tagged-identities.v1","account-owner-admission.v1","account-owner-rotation.v1","account-owner-retirement.v1","signer-injected-client.v1","provider-neutral-seller-onboarding.v1","conditional-escrow.v2","stripe-connect-separate-charges-transfers.v2","portable-attestation.v1","eas-arbiter.v1","payer-profile.v1","funding-authorization.v1","funding-profile.card.v1","funding-profile.us_bank_transfer.v1","funding-profile.us_ach_debit.v1","normalized-funding-reversal.v1","operator-recovery-redaction.v1"]' >"$DUAL_RENDERED" 2>/dev/null
helm template "$RELEASE-overlap" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    --values "$CHART_DIR/fixtures/identity-overlap-values.yaml" \
    --set-string 'storefront.agents[0].identity.servicePeers.provisioning_default.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].identity.servicePeers.provisioning_default.principals[1].identifier=0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266' \
    --set-string 'storefront.agents[0].identity.administrators.operator.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].identity.administrators.operator.principals[1].identifier=0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc' \
    --set-string 'storefront.agents[0].config.registryAuthority.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].config.registryAuthority.principals[1].identifier=0x90f79bf6eb2c4f870365e785982e1f101e93b906' \
    --set-string 'storefront.agents[0].config.seller.provisioning.identity.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].config.seller.provisioning.identity.principals[1].identifier=0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266' \
    --set-string 'storefront.agents[0].config.settlement.stripe.authority.principals[1].scheme=eip191' \
    --set-string 'storefront.agents[0].config.settlement.stripe.authority.principals[1].identifier=0x1c5a77d9fa7ef466951b2f01f724bca3a5820b63' >"$OVERLAP_RENDERED" 2>/dev/null
helm template "$RELEASE-registries" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" \
    --values "$CHART_DIR/fixtures/two-registries-values.yaml" >"$TWO_REGISTRIES_RENDERED" 2>/dev/null

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
TWO_REGISTRIES_COMPUTE="$(extract_section "$TWO_REGISTRIES_RENDERED" 'charts/registry/templates/deployment\.yaml')"
TWO_REGISTRIES_CREDITS="$(extract_section "$TWO_REGISTRIES_RENDERED" 'charts/api-credits-registry/templates/deployment\.yaml')"
FIAT_CONFIGMAP="$(extract_section "$FIAT_RENDERED" 'storefront/templates/configmap\.yaml')"
FIAT_DEPLOYMENT="$(extract_section "$FIAT_RENDERED" 'storefront/templates/deployment\.yaml')"
FIAT_REGISTRY="$(extract_section "$FIAT_RENDERED" 'registry/templates/deployment\.yaml')"
EVM_CONFIGMAP="$(extract_section "$EVM_RENDERED" 'storefront/templates/configmap\.yaml')"
EVM_DEPLOYMENT="$(extract_section "$EVM_RENDERED" 'storefront/templates/deployment\.yaml')"
DUAL_CONFIGMAP="$(extract_section "$DUAL_RENDERED" 'storefront/templates/configmap\.yaml')"
PROVISIONING_CONFIGMAP="$(extract_section "$FIAT_RENDERED" 'provisioning/templates/configmap\.yaml')"
PROVISIONING_DEPLOYMENT="$(extract_section "$FIAT_RENDERED" 'provisioning/templates/deployment\.yaml')"
OVERLAP_CONFIGMAP="$(extract_section "$OVERLAP_RENDERED" 'storefront/templates/configmap\.yaml')"
OVERLAP_PROVISIONING_CONFIGMAP="$(extract_section "$OVERLAP_RENDERED" 'provisioning/templates/configmap\.yaml')"

expect_present "$DEFAULT_CONFIGMAP" 'storefront\.toml:' "storefront ConfigMap renders"
expect_present "$DEFAULT_DEPLOYMENT" 'mountPath: +/etc/arkhai/storefront\.toml' "storefront mounts public config"
expect_present "$DEFAULT_DEPLOYMENT" 'name: +ARKHAI_IDENTITY_CREDENTIAL' "signer credential uses environment injection"
expect_present "$DEFAULT_DEPLOYMENT" 'name: +\"?arkhai-bob-identity\"?' "signer credential references a Secret"
expect_present "$DEFAULT_CONFIGMAP" 'priority = \[\]' "new defaults have empty settlement priority"
expect_absent "$DEFAULT_CONFIGMAP" '\[Settlement\.(stripe|alkahest)\]' "new defaults install no mechanism subsection"
expect_absent "$DEFAULT_RENDERED" 'private_key|privateKey|request_credential' "default manifests contain no signing key fields"
expect_absent "$DEFAULT_RENDERED" 'admin_api_key|adminApiKey|X-Admin-Key' "default manifests contain no legacy administrator shared secret"
expect_present "$DEFAULT_REGISTRY" 'name: +REGISTRY_DESCRIPTOR_BASE_URL' "registry renders its public descriptor URL"
expect_present "$DEFAULT_REGISTRY" 'value: +"?Local VM Compute Registry"?' "registry renders its descriptor display name"
expect_present "$DEFAULT_REGISTRY" 'value: +"?Arkhai local development"?' "registry renders its operator identity"
expect_absent "$DEFAULT_REGISTRY" 'REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER' "public registry omits an acquisition pointer"
expect_present "$DEFAULT_REGISTRY" 'value: +"?/app/filter-spec\.yaml"?' "default registry selects the compute filter specification"
expect_absent "$DEFAULT_RENDERED" 'api-credits-registry' "default render omits the API-credits registry"

expect_present "$CHART_DIR/../core/registry/filter-spec.yaml" 'id: +vms\.compute' "compute filter specification declares vms.compute"
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

expect_present "$FIAT_CONFIGMAP" 'scheme = \"ed25519\"' "fiat profile renders Ed25519 scheme"
expect_present "$FIAT_CONFIGMAP" 'identifier = \"0EqyMnQrtKs6E2i9RhXk5tAiSrcaAWuvhSCjMsl3hzc\"' "fiat profile renders the configured public storefront principal"
expect_present "$FIAT_CONFIGMAP" '\[Settlement\]' "fiat profile renders canonical Settlement root"
expect_present "$FIAT_CONFIGMAP" 'priority = \["fiat\.stripe\.v1"\]' "fiat profile selects only Stripe"
expect_present "$FIAT_CONFIGMAP" '\[Settlement\.stripe\]' "fiat profile renders Stripe subsection"
expect_present "$FIAT_CONFIGMAP" 'expected_schema_version = 5' "fiat profile pins hosted schema 5"
expect_present "$FIAT_CONFIGMAP" 'scheme-tagged-identities\.v1' "fiat profile pins scheme-tagged hosted identity"
expect_present "$FIAT_CONFIGMAP" 'signer-injected-client\.v1' "fiat profile pins signer-injected hosted client"
expect_present "$FIAT_CONFIGMAP" 'account-owner-retirement\.v1' "fiat profile pins owner retirement"
expect_present "$FIAT_CONFIGMAP" 'funding-profile\.card\.v1' "fiat profile pins card funding capability"
expect_present "$FIAT_CONFIGMAP" 'funding-profile\.us_bank_transfer\.v1' "fiat profile pins push-transfer funding capability"
expect_present "$FIAT_CONFIGMAP" 'funding-profile\.us_ach_debit\.v1' "fiat profile pins ACH funding capability"
expect_present "$FIAT_CONFIGMAP" 'country = "US"' "fiat profile pins US country policy"
expect_present "$FIAT_CONFIGMAP" '\[pricing\]' "fiat profile renders ordered public pricing"
expect_present "$FIAT_CONFIGMAP" '"funding_profile" = "card\.v1".*"funding_profile" = "us_bank_transfer\.v1".*"funding_profile" = "us_ach_debit\.v1"' "fiat profile preserves three distinct funding clauses"
expect_present "$FIAT_CONFIGMAP" 'account_ref = "account-protected"' "fiat profile renders the authority account reference"
expect_present "$FIAT_CONFIGMAP" 'condition_profile = "vm-fulfillment"' "fiat profile selects an explicit condition profile"
expect_present "$FIAT_CONFIGMAP" '\[Settlement\.stripe\.condition_profiles\."vm-fulfillment"\]' "fiat profile renders condition details"
expect_present "$FIAT_CONFIGMAP" '\[Settlement\.stripe\.resolvers\."vm-portable"\]' "fiat profile renders resolver mapping"
expect_present "$FIAT_DEPLOYMENT" 'name: +\"?fiat-bob-marketplace-identity\"?' "fiat signer comes from a Secret reference"
expect_absent "$FIAT_CONFIGMAP" '\[Wallet\]|\[Chains\.|rpc_url|(^|[[:space:]])(provider|webhook|database|migration)[[:space:]]*=' "fiat storefront config omits EVM and authority-provider configuration"
expect_absent "$FIAT_CONFIGMAP" 'hostedSettlement|hosted_settlement|settlement\.hosted' "fiat storefront config rejects legacy hierarchy"
expect_absent "$FIAT_DEPLOYMENT" 'wait-for-rpc|CHAIN_ID|RPC_URL' "fiat storefront pod omits chain readiness"
expect_absent "$FIAT_DEPLOYMENT" 'STOREFRONT_SETTLEMENT__HOSTED|HOSTED_SETTLEMENT' "fiat storefront pod emits no legacy settlement environment"
expect_absent "$FIAT_REGISTRY" 'CHAIN_ID|RPC_URL' "fiat registry pod omits chain configuration"
expect_present "$FIAT_REGISTRY" 'name: +REGISTRY_AUTHORITY_SCHEME' "fiat registry renders its public signer scheme"
expect_present "$FIAT_REGISTRY" 'value: +\"?NLTZBDFWy23PC-sKKUm3VZyUDSvLbb6MU6mzAnjjp0Y\"?' "fiat registry renders its public authority"
expect_present "$FIAT_REGISTRY" 'secretName: +\"?fiat-registry-identity\"?' "fiat registry signer credential is Secret-referenced"
expect_absent "$FIAT_RENDERED" 'private_key|privateKey|request_credential|STRIPE_[A-Z_]*KEY' "fiat manifests contain no private or provider credentials"
expect_absent "$FIAT_RENDERED" 'checkout\.stripe\.com|client_secret|payer_profile_ref|instrument_ref|payment_method|mandate|bank_instructions' "fiat manifests contain no payer, instrument, action, or bank material"
expect_present "$PROVISIONING_CONFIGMAP" 'scheme: +ed25519' "fiat provisioning renders Ed25519 public principals"
expect_present "$PROVISIONING_CONFIGMAP" 'identifier: +xoImN8fTEOxXYnvgC6JZ0lN0n0qvZERwz_vlOjX3MkI' "fiat provisioning renders its public service identity"
expect_absent "$FIAT_RENDERED" 'admin_api_key|adminApiKey|X-Admin-Key' "fiat manifests contain no legacy administrator shared secret"
expect_present "$PROVISIONING_CONFIGMAP" 'identifier: +0EqyMnQrtKs6E2i9RhXk5tAiSrcaAWuvhSCjMsl3hzc' "fiat provisioning pins the trusted storefront principal"
expect_present "$PROVISIONING_CONFIGMAP" 'identifier: +5zTqbCtiV95yNV5HKqBaTEh-a0Y8Ap7TBt8vAbVja1g' "fiat provisioning pins a distinct administrator principal"
expect_present "$PROVISIONING_DEPLOYMENT" 'name: +ARKHAI_IDENTITY_CREDENTIAL' "fiat provisioning injects its signer credential"
expect_present "$PROVISIONING_DEPLOYMENT" 'name: +\"?fiat-provisioning-identity\"?' "fiat provisioning signer is Secret-referenced"
expect_present "$FIAT_CONFIGMAP" '\[Identity\.service_peers\.provisioning_default\]' "fiat storefront renders provisioning service-peer trust"
expect_present "$FIAT_CONFIGMAP" 'site_id = \"default\"' "fiat storefront binds provisioning callbacks to the default site"
expect_present "$FIAT_CONFIGMAP" '\[provisioning\.identity\]' "fiat storefront pins provisioning response authority"
expect_present "$FIAT_CONFIGMAP" 'identifier = \"xoImN8fTEOxXYnvgC6JZ0lN0n0qvZERwz_vlOjX3MkI\"' "fiat storefront trusts the provisioning principal"
expect_present "$FIAT_CONFIGMAP" '\[Identity\.administrators\.operator\]' "fiat storefront renders explicit administrator trust"
expect_present "$FIAT_CONFIGMAP" 'principals = \[\{ scheme = \"ed25519\", identifier = \"5zTqbCtiV95yNV5HKqBaTEh-a0Y8Ap7TBt8vAbVja1g\" \}\]' "fiat storefront administrator is principal-bound and distinct from its service signer"
expect_present "$FIAT_CONFIGMAP" '\[registry\.authorities\.\"http://arkhai-test-fiat-registry:8080\"\]' "fiat storefront pins registry response authority by URL"
expect_present "$FIAT_CONFIGMAP" 'authority = \"registry-a\"' "fiat storefront pins the stable registry authority id separately from its URL"
expect_present "$FIAT_CONFIGMAP" 'identifier = \"NLTZBDFWy23PC-sKKUm3VZyUDSvLbb6MU6mzAnjjp0Y\"' "fiat storefront trusts the registry service principal"
expect_present "$FIAT_RENDERED" 'image: +[^[:space:]]+@sha256:1111111111111111111111111111111111111111111111111111111111111111' "fiat registry image is digest-pinned"
expect_present "$FIAT_RENDERED" 'image: +[^[:space:]]+@sha256:2222222222222222222222222222222222222222222222222222222222222222' "fiat provisioning image is digest-pinned"
expect_present "$FIAT_RENDERED" 'image: +[^[:space:]]+@sha256:3333333333333333333333333333333333333333333333333333333333333333' "fiat storefront image is digest-pinned"
expect_present "$FIAT_RENDERED" 'image: +[^[:space:]]+@sha256:4444444444444444444444444444444444444444444444444444444444444444' "fiat smoke images are digest-pinned"
expect_absent "$FIAT_RENDERED" 'kind: +Secret|sshPrivateKey|golden_root_ssh_password|frp_dashboard_password' "fiat chart renders only pre-existing Secret references"

expect_present "$EVM_CONFIGMAP" 'scheme = \"eip191\"' "EVM profile renders explicit EIP-191 scheme"
expect_present "$EVM_CONFIGMAP" '\[Settlement\.alkahest\]' "EVM profile renders canonical Alkahest mechanism"
expect_present "$EVM_CONFIGMAP" 'priority = \["alkahest\.v1"\]' "EVM profile selects only Alkahest"
expect_present "$EVM_CONFIGMAP" '\[Chains\.anvil\]' "EVM profile renders explicit chain"
expect_present "$DUAL_CONFIGMAP" 'priority = \["fiat\.stripe\.v1", "alkahest\.v1"\]' "dual profile preserves canonical priority"
expect_present "$DUAL_CONFIGMAP" '\[Settlement\.stripe\]' "dual profile renders Stripe"
expect_present "$DUAL_CONFIGMAP" '\[Settlement\.alkahest\]' "dual profile renders Alkahest"
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
expect_render_failure \
    "$CHART_DIR/fixtures/invalid-hosted-identity-v1-values.yaml" \
    "schema 3 hosted authority fails schema/render"
expect_render_failure \
    "$CHART_DIR/fixtures/invalid-missing-hosted-capability-values.yaml" \
    "missing hosted identity capability fails schema/render"
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "legacy hosted values fail schema/render" \
    --set 'storefront.agents[0].config.hostedSettlement.enabled=true'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "provider fields fail marketplace schema/render" \
    --set-string 'storefront.agents[0].config.settlement.stripe.webhook_secret=forbidden'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "buyer off-session policy fails storefront role schema/render" \
    --set 'storefront.agents[0].config.settlement.stripe.off_session_policy.enabled=false'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "image and config schema mismatch fails render" \
    --set 'storefront.image.settlementConfigSchemaVersion=2'
expect_override_failure \
    "$CHART_DIR/fixtures/eip191-evm-values.yaml" \
    "Alkahest without wallet Secret fails schema/render" \
    --set-string 'storefront.agents[0].secret.secretName='
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "key-gated registry without an acquisition pointer fails render" \
    --set 'registry.config.requireReadApiKey=true'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "public registry with an acquisition pointer fails render" \
    --set-string 'registry.descriptor.accessAcquisitionPointer=https://registry.example/access'

expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "missing seller account binding fails schema/render" \
    --set-string 'storefront.agents[0].config.settlement.stripe.account_ref='
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "condition resolver mismatch fails schema/render" \
    --set-string 'storefront.agents[0].config.settlement.stripe.condition_profile=missing'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "invalid funding profile fails schema/render" \
    --set-string 'storefront.agents[0].config.pricing.settlements[0].mechanism_input.funding_profile=card'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "push bank transfer saved-instrument clause fails schema/render" \
    --set-string 'storefront.agents[0].config.pricing.settlements[1].mechanism_input.interaction=saved_instrument'
expect_override_failure \
    "$CHART_DIR/fixtures/fiat-ed25519-values.yaml" \
    "enabled Stripe without publication pricing fails schema/render" \
    --set-json 'storefront.agents[0].config.pricing=null'
if [[ $errors -gt 0 ]]; then
    echo "$errors assertion(s) failed" >&2
    exit 1
fi
echo "All structural identity assertions passed."
