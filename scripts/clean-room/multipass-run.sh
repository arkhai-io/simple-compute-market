#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="${SCM_MULTIPASS_NAME:-scm-issue-discovery-$(date -u +%Y%m%d%H%M%S)}"
IMAGE="${SCM_MULTIPASS_IMAGE:-22.04}"
CPUS="${SCM_MULTIPASS_CPUS:-4}"
MEMORY="${SCM_MULTIPASS_MEMORY:-8G}"
DISK="${SCM_MULTIPASS_DISK:-40G}"
KEEP_VM="${KEEP_VM:-0}"
SEQUENCE="${SCM_CLEAN_ROOM_SEQUENCE:-local-vm}"
ARTIFACT_DEST="${SCM_MULTIPASS_ARTIFACT_DEST:-$ROOT_DIR/.scm-local/clean-room-runs/$NAME}"
TRANSFER_DIR="${SCM_MULTIPASS_TRANSFER_DIR:-$ROOT_DIR/scm-clean-room-transfer}"
DRY_RUN=0

log() {
  printf '[multipass-clean-room] %s\n' "$*"
}

usage() {
  cat <<'USAGE'
usage: scripts/clean-room/multipass-run.sh [--dry-run]

Environment:
  SCM_MULTIPASS_NAME           VM name. Defaults to scm-issue-discovery-<utc timestamp>.
  SCM_MULTIPASS_IMAGE          Multipass image. Defaults to 22.04.
  SCM_MULTIPASS_CPUS           VM CPU count. Defaults to 4.
  SCM_MULTIPASS_MEMORY         VM memory. Defaults to 8G.
  SCM_MULTIPASS_DISK           VM disk. Defaults to 40G.
  SCM_CLEAN_ROOM_SEQUENCE      issue-discovery clean-room sequence. Defaults to local-vm.
  SCM_MULTIPASS_ARTIFACT_DEST  Host artifact destination.
  SCM_MULTIPASS_TRANSFER_DIR   Host git bundle staging directory.
  KEEP_VM                      Keep the VM instead of deleting it.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done

cleanup() {
  if [ "$KEEP_VM" = "1" ]; then
    log "keeping VM $NAME"
    return
  fi
  if multipass info "$NAME" >/dev/null 2>&1; then
    log "deleting VM $NAME"
    multipass delete "$NAME" --purge >/dev/null 2>&1 || true
  fi
}

require_git_repo() {
  if ! git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "not inside a git repository"
    exit 1
  fi
}

create_bundle() {
  local bundle="$1"
  local branch
  branch="$(git -C "$ROOT_DIR" branch --show-current)"
  if ! git -C "$ROOT_DIR" diff --quiet || ! git -C "$ROOT_DIR" diff --cached --quiet; then
    log "warning: uncommitted tracked changes are not included in the clean-room bundle"
  fi
  if [ -n "$(git -C "$ROOT_DIR" ls-files --others --exclude-standard)" ]; then
    log "warning: untracked files are not included in the clean-room bundle"
  fi
  if [ -n "$branch" ]; then
    git -C "$ROOT_DIR" bundle create "$bundle" "$branch" >/dev/null
  else
    git -C "$ROOT_DIR" bundle create "$bundle" HEAD >/dev/null
  fi
}

fetch_artifacts() {
  mkdir -p "$ARTIFACT_DEST"
  if multipass exec "$NAME" -- test -d /home/ubuntu/simple-compute-market/.scm-local; then
    log "fetching artifacts to $ARTIFACT_DEST"
    multipass transfer --recursive \
      "$NAME:/home/ubuntu/simple-compute-market/.scm-local" \
      "$ARTIFACT_DEST/" || true
  else
    log "no clean-room artifacts found in VM"
  fi
}

dry_run() {
  log "dry run only; multipass will not be invoked"
  log "would launch VM $NAME ($IMAGE, cpus=$CPUS, memory=$MEMORY, disk=$DISK)"
  log "would stage git bundle under $TRANSFER_DIR"
  log "would transfer current git branch as a bundle"
  log "would run bootstrap with SCM_CLEAN_ROOM_SEQUENCE=$SEQUENCE"
  log "would fetch artifacts to $ARTIFACT_DEST"
  if [ "$KEEP_VM" = "1" ]; then
    log "would keep VM $NAME"
  else
    log "would delete VM $NAME"
  fi
  "$ROOT_DIR/scripts/issue-discovery" clean-room plan "$SEQUENCE"
}

if [ "$DRY_RUN" = "1" ]; then
  dry_run
  exit 0
fi

command -v multipass >/dev/null 2>&1 || {
  echo "multipass is required" >&2
  exit 127
}

require_git_repo

mkdir -p "$TRANSFER_DIR"
bundle="$(mktemp -p "$TRANSFER_DIR" scm-issue-discovery.XXXXXX.bundle)"
rm -f "$bundle"
trap 'rm -f "$bundle"; cleanup' EXIT
create_bundle "$bundle"

log "launching VM $NAME ($IMAGE, cpus=$CPUS, memory=$MEMORY, disk=$DISK)"
multipass launch "$IMAGE" --name "$NAME" --cpus "$CPUS" --memory "$MEMORY" --disk "$DISK"

log "installing git before clone"
multipass exec "$NAME" -- sudo apt-get update --allow-releaseinfo-change
multipass exec "$NAME" -- sudo apt-get install -y git

log "transferring git bundle"
multipass transfer "$bundle" "$NAME:/tmp/simple-compute-market.bundle"

log "cloning bundle"
multipass exec "$NAME" -- bash -lc '
  set -euo pipefail
  rm -rf /home/ubuntu/simple-compute-market
  git clone /tmp/simple-compute-market.bundle /home/ubuntu/simple-compute-market
  sudo chown -R ubuntu:ubuntu /home/ubuntu/simple-compute-market
'

log "running bootstrap and validation"
set +e
multipass exec "$NAME" -- sudo env \
  "SCM_CLEAN_ROOM_SEQUENCE=$SEQUENCE" \
  /home/ubuntu/simple-compute-market/scripts/bootstrap-clean-host-ubuntu.sh run
rc=$?
set -e

fetch_artifacts
exit "$rc"
