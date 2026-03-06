#!/usr/bin/env bash
set -euo pipefail

# ── Market CLI cURL Installer ────────────────────────────────
#
# Usage:
#   curl -sL https://storage.googleapis.com/ww-migration-arkhai-installer-files/install.sh -o install.sh
#   bash install.sh
#
# This script downloads the latest Market CLI tarball from GCS,
# extracts it, and runs the bundled install.sh.
# ─────────────────────────────────────────────────────────────

GCS_BUCKET="ww-migration-arkhai-installer-files"
GCS_BASE_URL="https://storage.googleapis.com/${GCS_BUCKET}"
TARBALL_NAME="market-cli.tar.gz"
CLI_VERSION=""

# ── Color helpers ────────────────────────────────────────────
info()  { printf '\033[1;34m[info]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
ok()    { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

# ── Cleanup on exit ──────────────────────────────────────────
TMPDIR_INSTALL=""
cleanup() {
    if [ -n "$TMPDIR_INSTALL" ] && [ -d "$TMPDIR_INSTALL" ]; then
        rm -rf "$TMPDIR_INSTALL"
    fi
}
trap cleanup EXIT

# ── Check for required tools ─────────────────────────────────
check_curl_or_wget() {
    if command -v curl &>/dev/null; then
        DOWNLOADER="curl"
    elif command -v wget &>/dev/null; then
        DOWNLOADER="wget"
    else
        error "Either 'curl' or 'wget' is required. Please install one and try again."
        exit 1
    fi
}

download() {
    local url="$1"
    local dest="$2"

    if [ "$DOWNLOADER" = "curl" ]; then
        curl -fsSL "$url" -o "$dest"
    else
        wget -q "$url" -O "$dest"
    fi
}

# ── Main ─────────────────────────────────────────────────────

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --version)
                if [ -z "${2:-}" ]; then
                    error "--version requires a value (e.g. --version market-cli-v1.0.0)"
                    exit 1
                fi
                CLI_VERSION="$2"
                shift 2
                ;;
            *)
                shift
                ;;
        esac
    done
}

main() {
    parse_args "$@"

    local version_label="latest"
    if [ -n "$CLI_VERSION" ]; then
        version_label="$CLI_VERSION"
    fi

    echo ""
    echo "  ┌──────────────────────────────────┐"
    echo "  │   Market CLI Remote Installer     │"
    echo "  │   Version: $(printf '%-23s' "$version_label")│"
    echo "  └──────────────────────────────────┘"
    echo ""

    check_curl_or_wget

    # Create temp directory for download and extraction
    TMPDIR_INSTALL="$(mktemp -d)"

    local tarball_url
    if [ -n "$CLI_VERSION" ]; then
        tarball_url="${GCS_BASE_URL}/releases/${CLI_VERSION}/${TARBALL_NAME}"
    else
        tarball_url="${GCS_BASE_URL}/releases/latest/${TARBALL_NAME}"
    fi
    local tarball_path="${TMPDIR_INSTALL}/${TARBALL_NAME}"

    info "Downloading Market CLI from ${tarball_url}..."
    if ! download "$tarball_url" "$tarball_path"; then
        error "Failed to download tarball from ${tarball_url}"
        error "Check that the URL is accessible and try again."
        exit 1
    fi
    ok "Download complete"

    info "Verifying checksum..."
    local checksum_url="${tarball_url}.sha256"
    local checksum_path="${TMPDIR_INSTALL}/checksum.sha256"
    if download "$checksum_url" "$checksum_path"; then
        cd "$TMPDIR_INSTALL"
        if ! sha256sum -c "$checksum_path" 2>/dev/null && ! shasum -a 256 -c "$checksum_path" 2>/dev/null; then
            error "Checksum verification failed! The download may be corrupted or tampered with."
            exit 1
        fi
        ok "Checksum verified"
    else
        warn "Checksum file not available — skipping verification"
    fi

    info "Extracting..."
    tar xzf "$tarball_path" -C "$TMPDIR_INSTALL" --no-same-owner --no-same-permissions

    # Find the extracted directory
    local extracted
    extracted="$(find "$TMPDIR_INSTALL" -mindepth 1 -maxdepth 1 -type d | head -1)"

    if [ -z "$extracted" ] || [ ! -f "$extracted/install.sh" ]; then
        error "Extraction failed or install.sh not found in archive."
        exit 1
    fi
    ok "Extracted to ${extracted}"

    # Run the bundled installer
    info "Running installer..."
    cd "$extracted"
    bash install.sh "$@"
}

main "$@"
