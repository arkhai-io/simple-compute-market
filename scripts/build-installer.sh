#!/usr/bin/env bash
set -euo pipefail

# ── Build a self-extracting Market CLI installer ───────────────
#
# Usage:
#   bash scripts/build-installer.sh [output-path]
#
# Produces a single market-installer.sh that contains:
#   1. A shell header that extracts the embedded archive
#   2. A gzip-compressed tarball of the repo (minus .git, etc.)
#
# The user runs: bash market-installer.sh
# ───────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT="${1:-$REPO_ROOT/market-installer.sh}"

info()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[build]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[build]\033[0m %s\n' "$*" >&2; }

# ── Create tarball ─────────────────────────────────────────────

TMPDIR_BUILD="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_BUILD"' EXIT

TARBALL="$TMPDIR_BUILD/market-payload.tar.gz"

info "Creating tarball from $REPO_ROOT..."

tar czf "$TARBALL" \
    -C "$(dirname "$REPO_ROOT")" \
    --exclude='.git' \
    --exclude='.github' \
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
info "Tarball size: $(( TARBALL_SIZE / 1024 )) KB"

# ── Build self-extracting script ───────────────────────────────

info "Building self-extracting installer..."

cat > "$OUTPUT" << 'HEADER_EOF'
#!/usr/bin/env bash
set -euo pipefail

# ── Market CLI Self-Extracting Installer ───────────────────────
# This file contains an embedded tarball. It extracts to a
# temporary directory and runs install.sh from within.
# ───────────────────────────────────────────────────────────────

EXTRACT_DIR="$(mktemp -d)"
cleanup() { rm -rf "$EXTRACT_DIR"; }
trap cleanup EXIT

echo ""
echo "  Extracting Market CLI..."
echo ""

# Find where the archive starts (line after __ARCHIVE_BELOW__)
ARCHIVE_LINE=$(awk '/^__ARCHIVE_BELOW__$/ {print NR + 1; exit 0;}' "$0")

if [ -z "$ARCHIVE_LINE" ]; then
    echo "[error] Could not find archive marker in installer." >&2
    exit 1
fi

# Extract the embedded tarball
tail -n +"$ARCHIVE_LINE" "$0" | tar xz -C "$EXTRACT_DIR" 2>/dev/null

# Find the extracted directory (it's the repo basename)
EXTRACTED="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)"

if [ -z "$EXTRACTED" ] || [ ! -f "$EXTRACTED/install.sh" ]; then
    echo "[error] Extraction failed or install.sh not found." >&2
    exit 1
fi

# Run the installer
cd "$EXTRACTED"
bash install.sh "$@"

exit 0
__ARCHIVE_BELOW__
HEADER_EOF

# Append the tarball binary data
cat "$TARBALL" >> "$OUTPUT"
chmod +x "$OUTPUT"

FINAL_SIZE=$(wc -c < "$OUTPUT" | tr -d ' ')
ok "Built: $OUTPUT ($(( FINAL_SIZE / 1024 )) KB)"
ok "Users can install with: bash market-installer.sh"
