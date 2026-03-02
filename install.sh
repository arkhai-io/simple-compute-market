#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
INSTALL_DIR="${MARKET_INSTALL_DIR:-$HOME/.market}"
BIN_DIR="${MARKET_BIN_DIR:-$HOME/.local/bin}"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10
UV_VERSION="0.8.13"

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
        error "Python 3.10+ is required but neither 'python3' nor 'python' was found."
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

    ok "Python $version found ($python_cmd)"
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

    ok "Platform: $OS/$ARCH"
}

# ── Install uv ────────────────────────────────────────────────

install_uv() {
    if command -v uv &>/dev/null; then
        ok "uv is already installed ($(uv --version))"
        return
    fi

    info "Installing uv v${UV_VERSION}..."
    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh

    # Source the env to make uv available in this session
    if [ -f "$HOME/.local/bin/env" ]; then
        # shellcheck disable=SC1091
        . "$HOME/.local/bin/env"
    elif [ -f "$HOME/.cargo/env" ]; then
        # shellcheck disable=SC1091
        . "$HOME/.cargo/env"
    fi

    # Add to PATH directly as fallback
    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        error "uv installation failed. Please install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    ok "uv installed ($(uv --version))"
}

# ── Copy files to install directory ────────────────────────────

copy_to_install_dir() {
    local source_dir
    source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [ "$source_dir" = "$INSTALL_DIR" ]; then
        ok "Already running from install directory"
        return
    fi

    info "Installing to $INSTALL_DIR..."
    mkdir -p "$INSTALL_DIR"

    # Preserve existing .env files
    local env_backup_dir
    env_backup_dir="$(mktemp -d)"
    local env_files_found=false

    while IFS= read -r -d '' env_file; do
        env_files_found=true
        local rel_path="${env_file#"$INSTALL_DIR"/}"
        local backup_path="$env_backup_dir/$rel_path"
        mkdir -p "$(dirname "$backup_path")"
        cp "$env_file" "$backup_path"
    done < <(find "$INSTALL_DIR" -name ".env" -type f -print0 2>/dev/null || true)

    # Copy source files (rsync if available, otherwise cp)
    if command -v rsync &>/dev/null; then
        rsync -a --delete \
            --exclude='.git' \
            --exclude='.github' \
            --exclude='__pycache__' \
            --exclude='.venv' \
            --exclude='node_modules' \
            --exclude='.env' \
            --exclude='.env.tmp' \
            --exclude='*.egg-info' \
            --exclude='.claude' \
            "$source_dir/" "$INSTALL_DIR/"
    else
        rm -rf "${INSTALL_DIR:?}/"*
        cp -R "$source_dir/." "$INSTALL_DIR/"
    fi

    # Restore .env files
    if [ "$env_files_found" = true ]; then
        while IFS= read -r -d '' env_file; do
            local rel_path="${env_file#"$env_backup_dir"/}"
            local target_path="$INSTALL_DIR/$rel_path"
            mkdir -p "$(dirname "$target_path")"
            cp "$env_file" "$target_path"
        done < <(find "$env_backup_dir" -name ".env" -type f -print0 2>/dev/null || true)
        info "Preserved existing .env files"
    fi

    rm -rf "$env_backup_dir"
    ok "Files installed to $INSTALL_DIR"
}

# ── Set up CLI virtual environment ─────────────────────────────

setup_cli() {
    info "Setting up Market CLI..."
    cd "$INSTALL_DIR/cli"

    uv venv --quiet
    uv pip install -e . --quiet

    ok "Market CLI installed"
}

# ── Set up PATH ────────────────────────────────────────────────

setup_path() {
    local market_bin="$INSTALL_DIR/cli/.venv/bin/market"

    if [ ! -f "$market_bin" ]; then
        error "market binary not found at $market_bin"
        exit 1
    fi

    mkdir -p "$BIN_DIR"
    ln -sf "$market_bin" "$BIN_DIR/market"
    ok "Symlinked market → $BIN_DIR/market"

    # Check if BIN_DIR is already in PATH (resolve $HOME in both)
    local resolved_bin_dir="${BIN_DIR/#\$HOME/$HOME}"
    if echo "$PATH" | tr ':' '\n' | grep -qxF "$resolved_bin_dir"; then
        ok "$BIN_DIR is already in PATH"
        return
    fi

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
        # Check if the rc file already references this directory (handles $HOME, ~, or absolute paths)
        if grep -qF "$BIN_DIR" "$rc_file" 2>/dev/null || grep -qF "$resolved_bin_dir" "$rc_file" 2>/dev/null; then
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
    local market_bin="$BIN_DIR/market"

    if [ ! -L "$market_bin" ] && [ ! -f "$market_bin" ]; then
        error "Verification failed: market not found at $market_bin"
        exit 1
    fi

    if "$market_bin" --help &>/dev/null; then
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
    echo "  │      Market CLI Installer         │"
    echo "  └──────────────────────────────────┘"
    echo ""

    detect_platform
    check_command make
    check_python_version
    install_uv
    copy_to_install_dir
    setup_cli
    setup_path
    verify

    echo ""
    ok "Market CLI installed successfully!"
    echo ""
    info "Get started:"
    echo "    market --help              Show all commands"
    echo "    market install             Install service dependencies"
    echo "    market config init agent   Configure the agent"
    echo ""
}

main "$@"
