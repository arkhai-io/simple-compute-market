#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
INSTALL_DIR="${MARKET_INSTALL_DIR:-$HOME/.market}"
BIN_DIR="$HOME/.local/bin"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12
UV_VERSION="0.8.13"
GCP_SA_KEY_URL="https://us-central1-ww-migration-arkhai.cloudfunctions.net/getServiceAccountKey"
DOCKER_IMAGE="us-east4-docker.pkg.dev/ww-migration-arkhai/a2a-agent/a2a-agent:v0.0.1"
GCP_DOCKER_REGISTRY="$(echo "$DOCKER_IMAGE" | cut -d'/' -f1)"

# ── Color helpers ──────────────────────────────────────────────
info()  { printf '\033[1;34m[info]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
ok()    { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

# ── Prerequisite checks ───────────────────────────────────────

check_command() {
    if ! command -v "$1" &>/dev/null; then
        error "'$1' is required but not found. Please install it and try again."
        exit 1
    fi
}

check_python_version() {
    local python_cmd=""
    if command -v python3 &>/dev/null; then
        python_cmd="python3"
    elif command -v python &>/dev/null; then
        python_cmd="python"
    else
        error "Python 3.12+ is required but neither 'python3' nor 'python' was found."
        exit 1
    fi

    local version
    version=$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [ "$major" -lt "$MIN_PYTHON_MAJOR" ] || { [ "$major" -eq "$MIN_PYTHON_MAJOR" ] && [ "$minor" -lt "$MIN_PYTHON_MINOR" ]; }; then
        error "Python >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} is required, but found $version."
        exit 1
    fi
}

detect_platform() {
    local os arch
    os="$(uname -s)"
    arch="$(uname -m)"

    case "$os" in
        Darwin) OS="macos" ;;
        Linux)  OS="linux" ;;
        *)
            error "Unsupported operating system: $os"
            exit 1
            ;;
    esac

    case "$arch" in
        x86_64|amd64)  ARCH="x86_64" ;;
        arm64|aarch64) ARCH="arm64" ;;
        *)
            error "Unsupported architecture: $arch"
            exit 1
            ;;
    esac
}

# ── Dependency resolution (gcloud & zerotier) ────────────────

# Known install locations to check when a command is not on PATH
GCLOUD_SEARCH_PATHS=(
    "$HOME/google-cloud-sdk/bin"
    "/usr/local/google-cloud-sdk/bin"
    "/opt/google-cloud-sdk/bin"
    "/snap/google-cloud-cli/current/bin"
)

ZEROTIER_SEARCH_PATHS=(
    "/usr/sbin"
    "/usr/local/bin"
    "/Library/Application Support/ZeroTier/One"
    "/opt/zerotier/bin"
)

# Try to find a command either on PATH or in known locations.
# If found off-PATH, exports the directory to PATH.
# Returns 0 if found, 1 if not.
resolve_command() {
    local cmd="$1"
    shift
    local search_paths=("$@")

    if command -v "$cmd" &>/dev/null; then
        return 0
    fi

    for dir in "${search_paths[@]}"; do
        if [ -x "$dir/$cmd" ]; then
            info "Found '$cmd' at $dir (adding to PATH)"
            export PATH="$dir:$PATH"
            return 0
        fi
    done

    return 1
}

install_gcloud() {
    info "Installing Google Cloud SDK..."

    curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts --install-dir="$HOME"

    export PATH="$HOME/google-cloud-sdk/bin:$PATH"

    if ! command -v gcloud &>/dev/null; then
        error "Google Cloud SDK installation failed. Please install manually."
        exit 1
    fi

    ok "Google Cloud SDK installed ($(gcloud --version 2>&1 | head -1))"
}

install_zerotier() {
    info "Installing ZeroTier..."
    curl -s https://install.zerotier.com | sudo bash
    if ! command -v zerotier-cli &>/dev/null; then
        error "ZeroTier installation failed. Please install manually."
        exit 1
    fi
    ok "ZeroTier installed"
}

check_and_install_dependencies() {
    local missing=()
    ZEROTIER_ALREADY_INSTALLED=true

    if ! resolve_command gcloud "${GCLOUD_SEARCH_PATHS[@]}"; then
        missing+=("Google Cloud SDK (gcloud)")
    else
        ok "gcloud found ($(command -v gcloud))"
    fi

    if ! resolve_command zerotier-cli "${ZEROTIER_SEARCH_PATHS[@]}"; then
        missing+=("ZeroTier (zerotier-cli)")
        ZEROTIER_ALREADY_INSTALLED=false
    else
        ok "zerotier-cli found ($(command -v zerotier-cli))"
    fi

    if [ ${#missing[@]} -eq 0 ]; then
        return
    fi

    echo ""
    warn "The following required dependencies are not found:"
    for dep in "${missing[@]}"; do
        echo "  - $dep"
    done
    echo ""

    printf '\033[1;34m[?]\033[0m Would you like to install them? [Y/n] '
    read -r answer </dev/tty
    case "$answer" in
        [nN]|[nN][oO])
            error "Cannot proceed without required dependencies."
            exit 1
            ;;
    esac
    echo ""

    for dep in "${missing[@]}"; do
        case "$dep" in
            *gcloud*)    install_gcloud ;;
            *zerotier*)  install_zerotier ;;
        esac
    done
}

# ── Install uv ────────────────────────────────────────────────

install_uv() {
    if command -v uv &>/dev/null; then
        return
    fi

    info "Installing uv v${UV_VERSION}..."
    local uv_installer
    uv_installer="$(mktemp)"
    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" -o "$uv_installer"
    bash "$uv_installer"
    rm -f "$uv_installer"

    # Source the env to make uv available in this session
    if [ -f "$HOME/.local/bin/env" ]; then
        # shellcheck disable=SC1091
        . "$HOME/.local/bin/env"
    elif [ -f "$HOME/.cargo/env" ]; then
        # shellcheck disable=SC1091
        . "$HOME/.cargo/env"
    fi

    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        error "uv installation failed. Please install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    ok "uv installed ($(uv --version))"
}

# ── Copy repo to install directory ────────────────────────────

install_repo() {
    local src_dir
    src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    info "Installing to $INSTALL_DIR..."

    # Back up existing .env files before overwriting
    local env_backup_dir=""
    if [ -d "$INSTALL_DIR" ]; then
        env_backup_dir="$(mktemp -d)"
        while IFS= read -r -d '' env_file; do
            local rel="${env_file#$INSTALL_DIR/}"
            local backup_path="$env_backup_dir/$rel"
            mkdir -p "$(dirname "$backup_path")"
            cp "$env_file" "$backup_path"
        done < <(find "$INSTALL_DIR" -name '.env' -print0 2>/dev/null || true)
    fi

    # Copy files to install directory
    mkdir -p "$INSTALL_DIR"
    rsync -a --delete \
        --exclude='.git' \
        --exclude='market-installer.sh' \
        "$src_dir/" "$INSTALL_DIR/"

    # Restore backed-up .env files
    if [ -n "$env_backup_dir" ] && [ -d "$env_backup_dir" ]; then
        while IFS= read -r -d '' env_file; do
            local rel="${env_file#$env_backup_dir/}"
            local target="$INSTALL_DIR/$rel"
            mkdir -p "$(dirname "$target")"
            cp "$env_file" "$target"
        done < <(find "$env_backup_dir" -name '.env' -print0 2>/dev/null || true)
        rm -rf "$env_backup_dir"
    fi
}

# ── Set up venv and install CLI ───────────────────────────────

install_cli() {
    local cli_dir="$INSTALL_DIR/cli"

    info "Setting up Python environment..."
    cd "$cli_dir"
    uv venv
    uv pip install -q -e .

    ok "CLI installed in $cli_dir/.venv"
}

# ── Create symlink and set up PATH ────────────────────────────

setup_path() {
    local market_bin="$INSTALL_DIR/cli/.venv/bin/market"

    mkdir -p "$BIN_DIR"

    # Create or update symlink
    if [ -L "$BIN_DIR/market" ] || [ -e "$BIN_DIR/market" ]; then
        rm -f "$BIN_DIR/market"
    fi
    ln -s "$market_bin" "$BIN_DIR/market"
    ok "Symlinked $BIN_DIR/market -> $market_bin"

    # Ensure BIN_DIR is on PATH for this session
    export PATH="$BIN_DIR:$PATH"

    # Add to shell RC if not already present
    local shell_name
    shell_name="$(basename "${SHELL:-/bin/bash}")"
    local rc_file=""
    local path_line="export PATH=\"$BIN_DIR:\$PATH\""

    case "$shell_name" in
        zsh)  rc_file="$HOME/.zshrc" ;;
        bash)
            if [ -f "$HOME/.bashrc" ]; then
                rc_file="$HOME/.bashrc"
            else
                rc_file="$HOME/.profile"
            fi
            ;;
        fish)
            rc_file="$HOME/.config/fish/config.fish"
            path_line="fish_add_path $BIN_DIR"
            ;;
        *)
            rc_file="$HOME/.profile"
            ;;
    esac

    if [ -n "$rc_file" ] && [ -f "$rc_file" ]; then
        if grep -qF "$BIN_DIR" "$rc_file" 2>/dev/null; then
            ok "$BIN_DIR is already in $rc_file"
            return
        fi
    fi

    if [ -n "$rc_file" ]; then
        echo "" >> "$rc_file"
        echo "# Added by Market CLI installer" >> "$rc_file"
        echo "$path_line" >> "$rc_file"
        warn "Added $BIN_DIR to PATH in $rc_file — restart your shell or run: source $rc_file"
    fi
}

# ── Verify installation ───────────────────────────────────────

verify() {
    if command -v market &>/dev/null && market --help &>/dev/null; then
        ok "Verification passed"
    else
        error "Verification failed: 'market --help' exited with an error"
        exit 1
    fi
}

# ── Main ───────────────────────────────────────────────────────

main() {
    echo ""
    echo "  ┌──────────────────────────────────┐"
    echo "  │      Market CLI Installer        │"
    echo "  └──────────────────────────────────┘"
    echo ""

    detect_platform
    check_command docker
    check_command make
    check_and_install_dependencies
    check_python_version
    install_uv
    install_repo
    install_cli
    setup_path
    verify

    echo ""
    ok "Market CLI installed successfully!"
    echo ""

    info "Running market install to set up service dependencies..."
    echo ""
    if [ "$ZEROTIER_ALREADY_INSTALLED" = true ]; then
        market install
    else
        market install --with-zerotier
    fi

    # ── Pull Docker image ──────────
    local gcp_sa_key_file
    gcp_sa_key_file="$(mktemp)"

    info "Pulling Agent Docker Image..."
    curl -sSfL "$GCP_SA_KEY_URL" -o "$gcp_sa_key_file"

    gcloud auth activate-service-account --key-file="$gcp_sa_key_file"
    gcloud auth configure-docker "$GCP_DOCKER_REGISTRY" --quiet

    docker pull "$DOCKER_IMAGE"

    info "Cleaning up..."
    local sa_email
    sa_email="$(python3 -c "import json; print(json.load(open('$gcp_sa_key_file'))['client_email'])")"
    gcloud auth revoke "$sa_email" --quiet 2>/dev/null || true
    rm -f "$gcp_sa_key_file"

    ok "Installation complete"

    echo ""
    info "Get started:"
    echo "    market --help              Show all commands"
    echo "    market config init agent   Configure the agent"
    echo ""
}

main "$@"
