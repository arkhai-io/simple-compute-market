#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INVENTORY="${INVENTORY:-$ROOT_DIR/ansible/inventory/hosts}"
KVM_HOST="${KVM_HOST:-}"
VM_NAME="${VM_NAME:-iac-acceptance-$(date -u +%Y%m%d%H%M%S)}"
VM_IMAGE_TYPE="${VM_IMAGE_TYPE:-scratch}"
EXTRA_VARS_FILE="${EXTRA_VARS_FILE:-}"
RUN_HOST_KIT=1
KEEP_VM=0
VM_CREATED=0
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
Usage: ./scripts/run_acceptance_validation.sh --kvm-host <inventory-alias> [options] [-- <extra ansible args>]

Runs the heavier IaC acceptance path against a real KVM host. This script is
intentionally operator-run and not part of the default CI path.

Options:
  --kvm-host <alias>         Required inventory alias from [kvm_hosts]
  --inventory <path>         Inventory file to use (default: ansible/inventory/hosts)
  --vm-name <name>           Acceptance VM name (default: iac-acceptance-<timestamp>)
  --vm-image-type <type>     VM image type to validate (default: scratch)
  --extra-vars-file <path>   Optional extra vars file passed as @file
  --skip-host-kit            Skip ansible/playbooks/host-kit/vm-setup.yaml
  --keep-vm                  Keep the acceptance VM after vm_action=create and vm_action=check
  -h, --help                 Show this help

The acceptance flow runs:
  1. ansible/playbooks/host-kit/vm-setup.yaml
  2. ansible/playbooks/single-tenant/vm-operations.yaml with vm_action=create
  3. ansible/playbooks/single-tenant/vm-operations.yaml with vm_action=check
  4. ansible/playbooks/single-tenant/vm-operations.yaml with vm_action=destroy
  5. ansible/playbooks/single-tenant/vm-operations.yaml with vm_action=undefine
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kvm-host)
      KVM_HOST="${2:?missing value for --kvm-host}"
      shift 2
      ;;
    --inventory)
      INVENTORY="${2:?missing value for --inventory}"
      shift 2
      ;;
    --vm-name)
      VM_NAME="${2:?missing value for --vm-name}"
      shift 2
      ;;
    --vm-image-type)
      VM_IMAGE_TYPE="${2:?missing value for --vm-image-type}"
      shift 2
      ;;
    --extra-vars-file)
      EXTRA_VARS_FILE="${2:?missing value for --extra-vars-file}"
      shift 2
      ;;
    --skip-host-kit)
      RUN_HOST_KIT=0
      shift
      ;;
    --keep-vm)
      KEEP_VM=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS=("$@")
      break
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$KVM_HOST" ]]; then
  echo "KVM_HOST is required." >&2
  usage >&2
  exit 2
fi

if [[ ! -f "$INVENTORY" ]]; then
  echo "Inventory file not found: $INVENTORY" >&2
  exit 2
fi

if [[ -n "$EXTRA_VARS_FILE" && ! -f "$EXTRA_VARS_FILE" ]]; then
  echo "Extra vars file not found: $EXTRA_VARS_FILE" >&2
  exit 2
fi

PLAYBOOK_ARGS=(-i "$INVENTORY" --limit "$KVM_HOST")
if [[ -n "$EXTRA_VARS_FILE" ]]; then
  PLAYBOOK_ARGS+=(--extra-vars "@$EXTRA_VARS_FILE")
fi

run_playbook() {
  local playbook="$1"
  shift
  echo "[run] ansible-playbook ${PLAYBOOK_ARGS[*]} $playbook $* ${EXTRA_ARGS[*]}"
  ansible-playbook "${PLAYBOOK_ARGS[@]}" "$playbook" "$@" "${EXTRA_ARGS[@]}"
}

run_vm_action() {
  local action="$1"
  run_playbook \
    ansible/playbooks/single-tenant/vm-operations.yaml \
    -e "target_host=${KVM_HOST}" \
    -e "vm_name=${VM_NAME}" \
    -e "vm_image_type=${VM_IMAGE_TYPE}" \
    -e "vm_action=${action}"
}

cleanup() {
  if [[ "$KEEP_VM" -eq 1 || "$VM_CREATED" -eq 0 ]]; then
    return
  fi

  set +e
  echo "[cleanup] best-effort teardown for ${VM_NAME} on ${KVM_HOST}"
  run_vm_action destroy
  run_vm_action undefine
}

trap cleanup EXIT

if [[ "$RUN_HOST_KIT" -eq 1 ]]; then
  run_playbook ansible/playbooks/host-kit/vm-setup.yaml
fi

run_vm_action create
VM_CREATED=1
run_vm_action check

if [[ "$KEEP_VM" -eq 1 ]]; then
  trap - EXIT
  echo "[ok] acceptance VM retained after vm_action=create and vm_action=check"
  exit 0
fi

run_vm_action destroy
run_vm_action undefine
VM_CREATED=0
trap - EXIT

echo "[ok] acceptance validation completed successfully"
