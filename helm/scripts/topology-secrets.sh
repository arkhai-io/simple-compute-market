#!/usr/bin/env bash
# Create or update every out-of-band Secret and ConfigMap the local two-release
# topology reads: release 1's (a deploy's and its Helm tests') and release 2's.
# Run by `make -C helm topology-secrets`, which passes each input below as the
# make variable of the same name; re-running it replaces each one's contents.
#
# DEVELOPMENT VALUES ONLY, never for a public network. Every key is derived from
# Foundry's published default mnemonic (`test test ... junk`) at the Anvil
# account index that values.yaml, local-values.yaml, and
# bare-metal-release-values.yaml pin the matching principal to, so anyone can
# reproduce them and none is secret. The values not derived are committed:
# provisioning's SSH key, the placeholder the bare-metal Compose lane mounts,
# since mock provisioning never opens a connection; the payments lane double's
# lane CA and seller token, from its fixtures, which the storefronts' payments
# configuration in local-values.yaml and bare-metal-release-values.yaml trusts
# and authenticates with; and Bob's credential toward the double's pinned
# dispute authority, from his Compose secret overlay.
#
# Inputs:
#   NAMESPACE                          the namespace both releases run in, created
#                                      when absent
#   DEV_MNEMONIC                       the mnemonic the keys are derived from
#   DEV_ACCOUNT_PROVISIONING           release 1's provisioning signer (0)
#   DEV_ACCOUNT_BUYER                  the e2e-tests chart's buyer (1)
#   DEV_ACCOUNT_BOB                    Bob's principal, administrator, wallet (2)
#   DEV_ACCOUNT_REGISTRY               release 1's registry signer (3)
#   DEV_ACCOUNT_PROVISIONING_ADMIN     release 1's provisioning administrator (5)
#   DEV_ACCOUNT_BARE_METAL_STOREFRONT  release 2's storefront principal and wallet (8)
#   DEV_ACCOUNT_BARE_METAL_PROVISIONING release 2's provisioning signer (9)
#   PROVISIONING_SSH_KEY_FILE          the file both provisioning services mount
#                                      as their SSH key
#   PAYMENTS_LANE_CA_FILE              the payments lane double's committed lane
#                                      CA, the storefronts' CA bundle
#   PAYMENTS_LANE_ENV                  the double's lane_env.py, which prints its
#                                      seller token (`seller-token`)
#   BOB_COMPOSE_SECRETS_FILE           Bob's secret overlay in the Compose stacks,
#                                      whose [[DisputeCredential]] entries Bob's
#                                      runtime overlay takes
#   TEST_VOLUMES                       the PersistentVolumeClaims release 1's deal
#                                      test mounts (its buyer profile store)
#   TEST_VOLUME_SIZE                   the storage each requests
#
# A claim that already exists is left as it is: its size and access mode are
# immutable once bound, and its contents are the buyer's profiles.
set -euo pipefail

require() {
    local name
    for name in "$@"; do
        if [ -z "${!name:-}" ]; then
            echo "ERROR: $name is not set; pass it to make, e.g. make -C helm topology-secrets $name=..." >&2
            exit 1
        fi
    done
}

require NAMESPACE DEV_MNEMONIC DEV_ACCOUNT_PROVISIONING DEV_ACCOUNT_BUYER DEV_ACCOUNT_BOB \
    DEV_ACCOUNT_REGISTRY DEV_ACCOUNT_PROVISIONING_ADMIN DEV_ACCOUNT_BARE_METAL_STOREFRONT \
    DEV_ACCOUNT_BARE_METAL_PROVISIONING PROVISIONING_SSH_KEY_FILE PAYMENTS_LANE_CA_FILE \
    PAYMENTS_LANE_ENV BOB_COMPOSE_SECRETS_FILE TEST_VOLUMES TEST_VOLUME_SIZE

for tool in cast kubectl python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: $tool is required (cast is Foundry's, which also provides Anvil)" >&2
        exit 1
    fi
done
for file in PROVISIONING_SSH_KEY_FILE PAYMENTS_LANE_CA_FILE PAYMENTS_LANE_ENV BOB_COMPOSE_SECRETS_FILE; do
    if [ ! -r "${!file}" ]; then
        echo "ERROR: $file (${!file}) is not a readable file" >&2
        exit 1
    fi
done

key() {
    cast wallet private-key --mnemonic "$DEV_MNEMONIC" --mnemonic-index "$1"
}

address() {
    cast wallet address --private-key "$(key "$1")" | tr '[:upper:]' '[:lower:]'
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# apply <secret> <key>=<file>...: create the Secret, or replace its contents.
apply() {
    local name="$1"
    shift
    local sources=()
    local entry
    for entry in "$@"; do
        sources+=("--from-file=$entry")
    done
    kubectl create secret generic "$name" --namespace "$NAMESPACE" "${sources[@]}" \
        --dry-run=client --output yaml | kubectl apply --namespace "$NAMESPACE" --filename -
}

# credential <secret> <account>: a signer credential Secret, its key `credential`.
credential() {
    printf '%s' "$(key "$2")" >"$work/$1"
    apply "$1" "credential=$work/$1"
    echo "  $1: Anvil account $2 ($(address "$2"))"
}

# A change's validation namespace exists only once something creates it, and
# every Secret below is created in it.
if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    kubectl create namespace "$NAMESPACE"
fi

echo "Development Secrets in namespace $NAMESPACE (never for a public network):"

# Both releases' storefronts' payments key: the payments lane double's seller
# token, which each storefront's secrets overlay states as
# [Settlement.arkhai_payments].api_key. lane_env.py reads it from the double's
# committed account directory, so the overlays cannot drift from it. It is
# written into a TOML basic string, so a token needing escapes is refused.
payments_token="$(python3 -I "$PAYMENTS_LANE_ENV" seller-token | tr -d '\n')"
if [[ ! "$payments_token" =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
    echo "ERROR: $PAYMENTS_LANE_ENV seller-token printed no token a TOML string carries unescaped" >&2
    exit 1
fi

# Bob's credential toward the pinned dispute authority release 1's registry
# recommends, bound to the authority's identity: without one, servicing reports
# each of his payment deals repair_required. It is copied from his Compose secret
# overlay, which the VM lane runs with, so the two stacks hold one value. Each
# setting is rewritten as a TOML basic string; one that is not a string is
# refused, and so is a rewrite that does not read back as the file's entries,
# since a JSON escape is not always a TOML one.
bob_dispute_credentials="$(python3 -I - "$BOB_COMPOSE_SECRETS_FILE" <<'PY'
import json
import sys
import tomllib

path = sys.argv[1]
with open(path, "rb") as handle:
    entries = tomllib.load(handle).get("DisputeCredential", [])
if not entries:
    sys.exit(f"ERROR: {path} states no [[DisputeCredential]]")
lines = []
for entry in entries:
    lines += ["", "[[DisputeCredential]]"]
    for key, value in entry.items():
        if not isinstance(value, str):
            sys.exit(f"ERROR: {path}: a DisputeCredential's {key} is not a string")
        lines.append(f"{key} = {json.dumps(value)}")
text = "\n".join(lines)
try:
    rewritten = tomllib.loads(text).get("DisputeCredential")
except tomllib.TOMLDecodeError:
    rewritten = None
if rewritten != entries:
    sys.exit(f"ERROR: {path}: its [[DisputeCredential]] cannot be rewritten as TOML basic strings")
print(text)
PY
)"

# Release 1: the registry, Bob, and the provisioning service.
credential arkhai-registry-identity "$DEV_ACCOUNT_REGISTRY"
credential arkhai-bob-identity "$DEV_ACCOUNT_BOB"
credential arkhai-provisioning-identity "$DEV_ACCOUNT_PROVISIONING"

# Bob's secrets overlay: the wallet key Alkahest settles with, the payments key,
# and his dispute credential. The same Secret's config-seller-secret.yml is the storefront smoke test's
# seller profile, which signs as Bob and as his administrator (both Bob's
# account). Values are quoted: TOML requires it, and YAML reads an unquoted
# 0x-prefixed value as an integer.
cat >"$work/bob.storefront.secrets.toml" <<EOF
[Wallet]
private_key = "$(key "$DEV_ACCOUNT_BOB")"

[Settlement.arkhai_payments]
api_key = "$payments_token"
$bob_dispute_credentials
EOF
cat >"$work/config-seller-secret.yml" <<EOF
seller:
  private_key: "$(key "$DEV_ACCOUNT_BOB")"
  admin_credential: "$(key "$DEV_ACCOUNT_BOB")"
EOF
apply arkhai-bob-runtime \
    "storefront.secrets.toml=$work/bob.storefront.secrets.toml" \
    "config-seller-secret.yml=$work/config-seller-secret.yml"
echo "  arkhai-bob-runtime: [Wallet].private_key, Anvil account $DEV_ACCOUNT_BOB, [Settlement.arkhai_payments].api_key, the double's seller token, [[DisputeCredential]] from $BOB_COMPOSE_SECRETS_FILE, and the smoke seller profile"

# Provisioning's secrets profile: mock provisioning needs nothing from it, so it
# is an empty mapping. The chart mounts the profile whatever it holds, and the
# service refuses a retired setting it states, an empty one included; the
# scenarios register the hosts they need through the API.
cat >"$work/config-provisioning-secrets.yml" <<EOF
{}
EOF
apply arkhai-provisioning-runtime "config-provisioning-secrets.yml=$work/config-provisioning-secrets.yml"
apply arkhai-provisioning-ssh "id_ed25519=$PROVISIONING_SSH_KEY_FILE"
echo "  arkhai-provisioning-runtime, arkhai-provisioning-ssh: mock provisioning's (an empty profile; $PROVISIONING_SSH_KEY_FILE)"

# Release 1's Helm tests: the e2e-tests chart's deal test, whose
# config-e2e-secret.yml the registry smoke test also layers for the buyer's
# credential, and the buyer CLI's profile credential.
cat >"$work/config-e2e-secret.yml" <<EOF
buyer:
  marketplace_credential: "$(key "$DEV_ACCOUNT_BUYER")"
  private_key: "$(key "$DEV_ACCOUNT_BUYER")"
seller:
  private_key: "$(key "$DEV_ACCOUNT_BOB")"
  admin_credential: "$(key "$DEV_ACCOUNT_BOB")"
provisioning:
  admin_credential: "$(key "$DEV_ACCOUNT_PROVISIONING_ADMIN")"
  service_credential: "$(key "$DEV_ACCOUNT_PROVISIONING")"
  authority_identifier: "$(address "$DEV_ACCOUNT_PROVISIONING")"
EOF
apply arkhai-e2e-credentials "config-e2e-secret.yml=$work/config-e2e-secret.yml"
echo "  arkhai-e2e-credentials: buyer $DEV_ACCOUNT_BUYER, seller $DEV_ACCOUNT_BOB, provisioning admin $DEV_ACCOUNT_PROVISIONING_ADMIN and service $DEV_ACCOUNT_PROVISIONING"
credential arkhai-buyer-profile-credential "$DEV_ACCOUNT_BUYER"

# Both releases' storefronts' CA bundle, the double's committed lane CA, which
# local-values.yaml's double serves under.
kubectl create configmap payments-ca-bundle --namespace "$NAMESPACE" \
    "--from-file=ca-bundle.pem=$PAYMENTS_LANE_CA_FILE" \
    --dry-run=client --output yaml | kubectl apply --namespace "$NAMESPACE" --filename -
echo "  ConfigMap payments-ca-bundle: the payments lane double's lane CA ($PAYMENTS_LANE_CA_FILE)"

# Release 2: the bare-metal storefront and its own provisioning service.
credential arkhai-bare-metal-storefront-identity "$DEV_ACCOUNT_BARE_METAL_STOREFRONT"
cat >"$work/bare-metal.storefront.secrets.toml" <<EOF
[Wallet]
private_key = "$(key "$DEV_ACCOUNT_BARE_METAL_STOREFRONT")"

[Settlement.arkhai_payments]
api_key = "$payments_token"
EOF
apply arkhai-bare-metal-storefront-runtime "storefront.secrets.toml=$work/bare-metal.storefront.secrets.toml"
echo "  arkhai-bare-metal-storefront-runtime: [Wallet].private_key, Anvil account $DEV_ACCOUNT_BARE_METAL_STOREFRONT, and [Settlement.arkhai_payments].api_key, the double's seller token"
credential arkhai-bare-metal-provisioning-identity "$DEV_ACCOUNT_BARE_METAL_PROVISIONING"

# Release 1's deal test's buyer profile store, a volume no chart creates. The
# cluster's default storage class provisions it.
for claim in $TEST_VOLUMES; do
    if kubectl get pvc "$claim" --namespace "$NAMESPACE" >/dev/null 2>&1; then
        echo "  PersistentVolumeClaim $claim: exists, left as it is"
        continue
    fi
    kubectl apply --namespace "$NAMESPACE" --filename - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $claim
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: $TEST_VOLUME_SIZE
EOF
    echo "  PersistentVolumeClaim $claim: $TEST_VOLUME_SIZE, ReadWriteOnce"
done
