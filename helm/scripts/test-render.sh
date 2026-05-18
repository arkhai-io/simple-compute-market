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

STOREFRONT_PVC="$(extract_section   'storefront/templates/pvc\.yaml')"
REGISTRY_PVC="$(extract_section     'registry/templates/pvc\.yaml')"
PROVISIONING_PVC="$(extract_section 'provisioning/templates/pvc\.yaml')"
REGISTRY_DEPLOY="$(extract_section     'registry/templates/deployment\.yaml')"
PROVISIONING_DEPLOY="$(extract_section 'provisioning/templates/deployment\.yaml')"

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

# ============================================================================
# SQLite persistence — every SQLite-backed service has a PVC, mounts it,
# pins Recreate strategy, and sets fsGroup so the container user can write.
# ============================================================================

# --- PVCs render for all three services ---
[[ -n "$STOREFRONT_PVC"   ]] && pass "storefront PVC renders"   || fail "no storefront PVC"
[[ -n "$REGISTRY_PVC"     ]] && pass "registry PVC renders"     || fail "no registry PVC"
[[ -n "$PROVISIONING_PVC" ]] && pass "provisioning PVC renders" || fail "no provisioning PVC"

# --- helm.sh/resource-policy: keep protects state across `helm uninstall` ---
for name in STOREFRONT_PVC REGISTRY_PVC PROVISIONING_PVC; do
    body="${!name}"
    if grep -qF "helm.sh/resource-policy: keep" <<<"$body"; then
        pass "${name} carries resource-policy: keep"
    else
        fail "${name} missing resource-policy: keep (state would be reaped on helm uninstall)"
    fi
done

# --- Each PVC requests ReadWriteOnce ---
for name in STOREFRONT_PVC REGISTRY_PVC PROVISIONING_PVC; do
    body="${!name}"
    if grep -qE 'accessModes:\s*$' <<<"$body" && grep -qE '"ReadWriteOnce"|ReadWriteOnce' <<<"$body"; then
        pass "${name} requests ReadWriteOnce"
    else
        fail "${name} missing ReadWriteOnce access mode"
    fi
done

# --- Each Deployment uses Recreate strategy (rolling + RWO = deadlock) ---
for name in DEPLOYMENT REGISTRY_DEPLOY PROVISIONING_DEPLOY; do
    body="${!name}"
    if grep -qE "type:\s+Recreate" <<<"$body"; then
        pass "${name} uses Recreate strategy"
    else
        fail "${name} missing Recreate strategy"
    fi
done

# --- fsGroup: 1000 on pod spec — without it SQLite write fails on perms ---
for name in DEPLOYMENT REGISTRY_DEPLOY PROVISIONING_DEPLOY; do
    body="${!name}"
    if grep -qE "fsGroup:\s+1000" <<<"$body"; then
        pass "${name} sets fsGroup: 1000"
    else
        fail "${name} missing fsGroup: 1000"
    fi
done

# --- Deployments reference their PVC by claimName ---
grep -qE "claimName:\s+arkhai-test-storefront-bob-data"   <<<"$DEPLOYMENT"          && pass "storefront Deployment binds to its PVC"   || fail "storefront Deployment missing PVC claim"
grep -qE "claimName:\s+arkhai-test-registry-data"         <<<"$REGISTRY_DEPLOY"     && pass "registry Deployment binds to its PVC"     || fail "registry Deployment missing PVC claim"
grep -qE "claimName:\s+arkhai-test-provisioning-data"     <<<"$PROVISIONING_DEPLOY" && pass "provisioning Deployment binds to its PVC" || fail "provisioning Deployment missing PVC claim"

if [[ $errors -gt 0 ]]; then
    echo "$errors assertion(s) failed" >&2
    exit 1
fi
echo "All structural assertions passed."
