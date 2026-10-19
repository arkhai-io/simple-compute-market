#!/usr/bin/env bash
# Create or update every out-of-band Secret the local two-release topology reads:
# release 1's (a deploy's and its Helm tests') and release 2's. Run by
# `make -C helm topology-secrets`, which passes each input below as the make
# variable of the same name; re-running it replaces each Secret's contents.
#
# DEVELOPMENT VALUES ONLY, never for a public network. Every key is derived from
# Foundry's published default mnemonic (`test test ... junk`) at the Anvil
# account index that values.yaml, local-values.yaml, and
# bare-metal-release-values.yaml pin the matching principal to, so anyone can
# reproduce them and none is secret. The one value not derived is provisioning's
# SSH key: mock provisioning never opens a connection, so it is the committed
# placeholder the bare-metal Compose lane mounts.
#
# Inputs:
#   NAMESPACE                          the namespace both releases run in
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
    DEV_ACCOUNT_BARE_METAL_PROVISIONING PROVISIONING_SSH_KEY_FILE

for tool in cast kubectl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: $tool is required (cast is Foundry's, which also provides Anvil)" >&2
        exit 1
    fi
done
if [ ! -r "$PROVISIONING_SSH_KEY_FILE" ]; then
    echo "ERROR: PROVISIONING_SSH_KEY_FILE ($PROVISIONING_SSH_KEY_FILE) is not a readable file" >&2
    exit 1
fi

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

echo "Development Secrets in namespace $NAMESPACE (never for a public network):"

# Release 1: the registry, Bob, and the provisioning service.
credential arkhai-registry-identity "$DEV_ACCOUNT_REGISTRY"
credential arkhai-bob-identity "$DEV_ACCOUNT_BOB"
credential arkhai-provisioning-identity "$DEV_ACCOUNT_PROVISIONING"

# Bob's secrets overlay: the wallet key Alkahest settles with. The same Secret's
# config-seller-secret.yml is the storefront smoke test's seller profile, which
# signs as Bob and as his administrator (both Bob's account). Values are quoted:
# TOML requires it, and YAML reads an unquoted 0x-prefixed value as an integer.
cat >"$work/bob.storefront.secrets.toml" <<EOF
[Wallet]
private_key = "$(key "$DEV_ACCOUNT_BOB")"
EOF
cat >"$work/config-seller-secret.yml" <<EOF
seller:
  private_key: "$(key "$DEV_ACCOUNT_BOB")"
  admin_credential: "$(key "$DEV_ACCOUNT_BOB")"
EOF
apply arkhai-bob-runtime \
    "storefront.secrets.toml=$work/bob.storefront.secrets.toml" \
    "config-seller-secret.yml=$work/config-seller-secret.yml"
echo "  arkhai-bob-runtime: [Wallet].private_key and the smoke seller profile, Anvil account $DEV_ACCOUNT_BOB"

# Provisioning's secrets profile: nothing mock provisioning needs. An empty
# inventory_ini seeds hosts from the image's inventory, as the Compose lane does.
cat >"$work/config-provisioning-secrets.yml" <<EOF
inventory_ini: ""
EOF
apply arkhai-provisioning-runtime "config-provisioning-secrets.yml=$work/config-provisioning-secrets.yml"
apply arkhai-provisioning-ssh "id_ed25519=$PROVISIONING_SSH_KEY_FILE"
echo "  arkhai-provisioning-runtime, arkhai-provisioning-ssh: mock provisioning's (no inventory; $PROVISIONING_SSH_KEY_FILE)"

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

# Release 2: the bare-metal storefront and its own provisioning service.
credential arkhai-bare-metal-storefront-identity "$DEV_ACCOUNT_BARE_METAL_STOREFRONT"
cat >"$work/bare-metal.storefront.secrets.toml" <<EOF
[Wallet]
private_key = "$(key "$DEV_ACCOUNT_BARE_METAL_STOREFRONT")"
EOF
apply arkhai-bare-metal-storefront-runtime "storefront.secrets.toml=$work/bare-metal.storefront.secrets.toml"
echo "  arkhai-bare-metal-storefront-runtime: [Wallet].private_key, Anvil account $DEV_ACCOUNT_BARE_METAL_STOREFRONT"
credential arkhai-bare-metal-provisioning-identity "$DEV_ACCOUNT_BARE_METAL_PROVISIONING"
