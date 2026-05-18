#!/usr/bin/env bash
# Repeatable structural check for the rendered umbrella chart.
#
# Asserts the invariants that the storefront config-split refactor
# depends on — without these holding, non-sensitive config changes
# would still trigger Secret rotations and sensitive values could leak
# into a ConfigMap. The CI check is stable across cosmetic chart edits
# (no byte-level snapshots) and targeted at the structural pieces only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHART_DIR="$SCRIPT_DIR/.."
RELEASE="${RELEASE:-arkhai-test}"

RENDERED="$(mktemp)"
trap 'rm -f "$RENDERED"' EXIT

helm template "$RELEASE" "$CHART_DIR" \
    --values "$CHART_DIR/values.yaml" >"$RENDERED" 2>/dev/null

errors=0
fail() {
    echo "FAIL  $*" >&2
    errors=$((errors + 1))
}
pass() {
    echo "ok    $*"
}

# Slice one rendered document out of the combined stream. Helm emits
# `# Source: <chart>/templates/<file>` before each doc; we capture from
# that header until the next Source comment.
extract_section() {
    local pattern="$1"
    awk -v pat="$pattern" '
        /^# Source: / { in_section = ($0 ~ pat) }
        in_section { print }
    ' "$RENDERED"
}

CONFIGMAP="$(extract_section 'storefront/templates/configmap\.yaml')"
SECRET="$(extract_section 'storefront/templates/secrets\.yaml')"
DEPLOYMENT="$(extract_section 'storefront/templates/deployment\.yaml')"

# --- Per-agent objects all render ---
[[ -n "$CONFIGMAP"  ]] && pass "storefront ConfigMap renders"   || fail "no storefront ConfigMap"
[[ -n "$SECRET"     ]] && pass "storefront Secret renders"      || fail "no storefront Secret"
[[ -n "$DEPLOYMENT" ]] && pass "storefront Deployment renders"  || fail "no storefront Deployment"

# --- Key layout matches what the runtime loader expects ---
grep -qF "config.toml:"         <<<"$CONFIGMAP" && pass "ConfigMap exposes config.toml key"        || fail "ConfigMap missing config.toml key"
grep -qF "config.secrets.toml:" <<<"$SECRET"    && pass "Secret exposes config.secrets.toml key"  || fail "Secret missing config.secrets.toml key"
grep -qE "config-[a-z]+-secret\.yml:" <<<"$SECRET" && pass "Secret retains smoke-test profile yml" || fail "Secret missing config-<component>-secret.yml (smoke-test pod depends on it)"

# --- Deployment mounts both files at /etc/arkhai/ ---
grep -qE "mountPath: +/etc/arkhai/config\.toml"         <<<"$DEPLOYMENT" && pass "Deployment mounts config.toml at /etc/arkhai/"         || fail "Deployment missing config.toml mount"
grep -qE "mountPath: +/etc/arkhai/config\.secrets\.toml" <<<"$DEPLOYMENT" && pass "Deployment mounts config.secrets.toml at /etc/arkhai/" || fail "Deployment missing config.secrets.toml mount"

# --- Independent checksums for rollout isolation ---
grep -qF "checksum/config:"  <<<"$DEPLOYMENT" && pass "checksum/config annotation present"  || fail "missing checksum/config"
grep -qF "checksum/secrets:" <<<"$DEPLOYMENT" && pass "checksum/secrets annotation present" || fail "missing checksum/secrets"

# --- No sensitive leak: private_key must not appear in the ConfigMap ---
if grep -qF "private_key" <<<"$CONFIGMAP"; then
    fail "private_key leaks into ConfigMap-rendered config.toml"
else
    pass "no private_key in ConfigMap config.toml"
fi

# --- Sensitive presence: private_key must appear in the Secret ---
grep -qF "private_key" <<<"$SECRET" && pass "private_key present in Secret config.secrets.toml" || fail "private_key missing from Secret"

if [[ $errors -gt 0 ]]; then
    echo "$errors assertion(s) failed" >&2
    exit 1
fi
echo "All structural assertions passed."
