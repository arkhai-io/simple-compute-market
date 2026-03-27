#!/usr/bin/env bash
set -euo pipefail

# ── Build tarball and upload to GCS for cURL installation ────
#
# Usage:
#   bash scripts/upload-gcs.sh
#
# Prerequisites:
#   - gcloud CLI authenticated with access to the bucket
#
# Uploads:
#   gs://ww-migration-arkhai-installer-files/install.sh                       (curl installer)
#   gs://ww-migration-arkhai-installer-files/releases/latest/market-cli.tar.gz (tarball)
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

GCS_BUCKET="ww-migration-arkhai-installer-files"
TARBALL_NAME="market-cli.tar.gz"

info()  { printf '\033[1;34m[upload]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[upload]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[upload]\033[0m %s\n' "$*" >&2; }

# ── Preflight checks ────────────────────────────────────────

if ! command -v gcloud &>/dev/null; then
    error "'gcloud' CLI is required. Install: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# ── Build tarball ────────────────────────────────────────────

TMPDIR_BUILD="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_BUILD"' EXIT

TARBALL="$TMPDIR_BUILD/$TARBALL_NAME"

info "Creating tarball from $REPO_ROOT..."

tar czf "$TARBALL" \
    -C "$(dirname "$REPO_ROOT")" \
    --exclude='.git' \
    --exclude='.github' \
    --exclude='mcp' \
    --exclude="$(basename "$REPO_ROOT")/scripts" \
    --exclude='tmp' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='.env' \
    --exclude='.env.tmp' \
    --exclude='*.egg-info' \
    --exclude='.claude' \
    --exclude='Dockerfile' \
    --exclude='docker-compose*.yml' \
    --exclude='market-installer.sh' \
    --exclude='.DS_Store' \
    "$(basename "$REPO_ROOT")"

TARBALL_SIZE=$(wc -c < "$TARBALL" | tr -d ' ')
ok "Tarball: $(( TARBALL_SIZE / 1024 )) KB"

# ── Generate checksum ───────────────────────────────────────

info "Generating checksum..."
cd "$TMPDIR_BUILD"
sha256sum "$TARBALL_NAME" > "${TARBALL_NAME}.sha256"
ok "Checksum generated"

# ── Upload to GCS ───────────────────────────────────────────

info "Uploading tarball to gs://${GCS_BUCKET}/releases/latest/${TARBALL_NAME}..."
gcloud storage cp "$TARBALL" "gs://${GCS_BUCKET}/releases/latest/${TARBALL_NAME}"

info "Uploading checksum to gs://${GCS_BUCKET}/releases/latest/${TARBALL_NAME}.sha256..."
gcloud storage cp "${TARBALL}.sha256" "gs://${GCS_BUCKET}/releases/latest/${TARBALL_NAME}.sha256"

info "Uploading installer script to gs://${GCS_BUCKET}/install.sh..."
gcloud storage cp "$SCRIPT_DIR/install-remote.sh" "gs://${GCS_BUCKET}/install.sh"

# ── Make objects publicly readable ──────────────────────────

info "Setting public read access..."
gcloud storage objects update "gs://${GCS_BUCKET}/releases/latest/${TARBALL_NAME}" --add-acl-grant=entity=allUsers,role=READER 2>/dev/null || \
    info "Skipped ACL update (bucket may use uniform access). Ensure bucket-level public access is configured."
gcloud storage objects update "gs://${GCS_BUCKET}/releases/latest/${TARBALL_NAME}.sha256" --add-acl-grant=entity=allUsers,role=READER 2>/dev/null || \
    info "Skipped ACL update (bucket may use uniform access). Ensure bucket-level public access is configured."
gcloud storage objects update "gs://${GCS_BUCKET}/install.sh" --add-acl-grant=entity=allUsers,role=READER 2>/dev/null || \
    info "Skipped ACL update (bucket may use uniform access). Ensure bucket-level public access is configured."

# ── Done ────────────────────────────────────────────────────

echo ""
ok "Upload complete!"
echo ""
info "Users can now install with:"
echo ""
echo "    curl -fsSL https://us-central1-ww-migration-arkhai.cloudfunctions.net/downloadMarketCli | bash"
echo ""
