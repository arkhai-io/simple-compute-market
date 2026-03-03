#!/usr/bin/env bash
# Download trained model artifacts from the latest (or specified) GitHub Release.
# Usage:
#   ./scripts/download_models.sh                    # latest release
#   ./scripts/download_models.sh model-v0.2.0       # specific version
#
# Requires: gh CLI (authenticated) OR curl with GITHUB_TOKEN

set -euo pipefail

REPO="arkhai-io/simple-market-service"
VERSION="${1:-latest}"
DEST_DIR="${2:-../../agent/app/policies/models}"

mkdir -p "$DEST_DIR"

download_asset() {
    local asset_name="$1"
    local dest_path="${DEST_DIR}/${asset_name}"

    echo "Downloading ${asset_name} from release ${VERSION}..."

    if command -v gh &>/dev/null; then
        if [ "$VERSION" = "latest" ]; then
            gh release download --repo "$REPO" --pattern "$asset_name" --dir "$DEST_DIR" --clobber 2>/dev/null
        else
            gh release download "$VERSION" --repo "$REPO" --pattern "$asset_name" --dir "$DEST_DIR" --clobber 2>/dev/null
        fi
    elif [ -n "${GITHUB_TOKEN:-}" ]; then
        local release_url
        if [ "$VERSION" = "latest" ]; then
            release_url="https://api.github.com/repos/${REPO}/releases/latest"
        else
            release_url="https://api.github.com/repos/${REPO}/releases/tags/${VERSION}"
        fi
        local asset_url
        asset_url=$(curl -sH "Authorization: token ${GITHUB_TOKEN}" "$release_url" \
            | python3 -c "
import sys, json
assets = json.load(sys.stdin).get('assets', [])
url = next((a['url'] for a in assets if a['name'] == '${asset_name}'), '')
print(url)
")
        if [ -z "$asset_url" ]; then
            echo "  WARNING: Asset ${asset_name} not found in release ${VERSION}"
            return 1
        fi
        curl -sL -H "Authorization: token ${GITHUB_TOKEN}" -H "Accept: application/octet-stream" \
            "$asset_url" -o "$dest_path"
    else
        echo "  ERROR: Neither 'gh' CLI nor GITHUB_TOKEN available"
        return 1
    fi

    if [ -f "$dest_path" ]; then
        echo "  -> Saved to ${dest_path} ($(du -h "$dest_path" | cut -f1))"
    else
        echo "  WARNING: Failed to download ${asset_name}"
        return 1
    fi
}

# Download both models; failures are non-fatal (graceful degradation at runtime)
download_asset "arkhai_seller.pt" || echo "  (seller model not available; will use fallback policy at runtime)"
download_asset "arkhai_buyer.pt" || echo "  (buyer model not available; will use fallback policy at runtime)"

echo "Done. Models available in ${DEST_DIR}/"
