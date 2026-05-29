#!/usr/bin/env bash
set -euo pipefail

# ── Market CLI cURL Installer ────────────────────────────────
#
# Usage (latest):
#   curl -fsSL https://github.com/arkhai-io/simple-compute-market/releases/latest/download/install.sh | bash
#
# Usage (specific version):
#   curl -fsSL https://github.com/arkhai-io/simple-compute-market/releases/latest/download/install.sh | \
#     bash -s -- --version market-cli-v0.5.1
#
# Downloads the Market CLI tarball from the corresponding GitHub
# Release, extracts it, and runs the bundled install.sh.
# ─────────────────────────────────────────────────────────────

GITHUB_RELEASES_BASE="https://github.com/arkhai-io/simple-compute-market/releases"
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

# Compose the release base URL for a given version label.
# Empty / "latest" → /releases/latest/download
# Otherwise        → /releases/download/<tag>
release_url_for() {
    local version="$1"
    if [ -z "$version" ] || [ "$version" = "latest" ]; then
        echo "${GITHUB_RELEASES_BASE}/latest/download"
    else
        echo "${GITHUB_RELEASES_BASE}/download/${version}"
    fi
}

# ── Main ─────────────────────────────────────────────────────

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --version)
                if [ -z "${2:-}" ]; then
                    error "--version requires a value (e.g. --version market-cli-v0.5.1)"
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

    check_curl_or_wget

    TMPDIR_INSTALL="$(mktemp -d)"

    local base_url
    base_url="$(release_url_for "$CLI_VERSION")"

    local tarball_url="${base_url}/${TARBALL_NAME}"
    local tarball_path="${TMPDIR_INSTALL}/${TARBALL_NAME}"

    info "Downloading Market CLI (${version_label})..."
    if ! download "$tarball_url" "$tarball_path"; then
        error "Failed to download tarball from ${tarball_url}"
        error "Check that the URL is accessible and try again."
        exit 1
    fi

    local checksum_url="${base_url}/${TARBALL_NAME}.sha256"
    local checksum_path="${TMPDIR_INSTALL}/${TARBALL_NAME}.sha256"
    if download "$checksum_url" "$checksum_path"; then
        local expected_hash
        expected_hash="$(awk '{print $1}' "$checksum_path")"
        local actual_hash
        if command -v sha256sum &>/dev/null; then
            actual_hash="$(sha256sum "$tarball_path" | awk '{print $1}')"
        elif command -v shasum &>/dev/null; then
            actual_hash="$(shasum -a 256 "$tarball_path" | awk '{print $1}')"
        else
            warn "No sha256 tool found -- skipping verification"
            actual_hash="$expected_hash"
        fi
        if [ "$expected_hash" != "$actual_hash" ]; then
            error "Checksum verification failed! The download may be corrupted or tampered with."
            error "Expected: $expected_hash"
            error "Got:      $actual_hash"
            exit 1
        fi
    else
        warn "Checksum file not available -- skipping verification"
    fi

    tar xzf "$tarball_path" -C "$TMPDIR_INSTALL" --no-same-owner --no-same-permissions

    local extracted
    extracted="$(find "$TMPDIR_INSTALL" -mindepth 1 -maxdepth 1 -type d | head -1)"

    if [ -z "$extracted" ] || [ ! -f "$extracted/install.sh" ]; then
        error "Extraction failed or install.sh not found in archive."
        exit 1
    fi

    cd "$extracted"
    bash install.sh "$@"
}

main "$@"
