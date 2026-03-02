#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
BIN_DIR="${MARKET_BIN_DIR:-$HOME/.local/bin}"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10
UV_VERSION="0.8.13"
PACKAGE_NAME="market-cli"

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

    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        error "uv installation failed. Please install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    ok "uv installed ($(uv --version))"
}

# ── Install market-cli from PyPI ───────────────────────────────

install_market_cli() {
    info "Installing $PACKAGE_NAME from PyPI..."
    uv tool install "$PACKAGE_NAME" --force
    ok "$PACKAGE_NAME installed"
}

# ── Set up PATH ────────────────────────────────────────────────

setup_path() {
    # uv tool install puts binaries in ~/.local/bin by default
    local market_bin
    market_bin="$(uv tool dir --bin 2>/dev/null || echo "$BIN_DIR")"

    if ! command -v market &>/dev/null; then
        # Check if market exists in the uv tool bin directory
        if [ -f "$market_bin/market" ]; then
            export PATH="$market_bin:$PATH"
        fi
    fi

    if command -v market &>/dev/null; then
        ok "market is on PATH"
        return
    fi

    # If still not found, try to add the bin dir to shell RC
    local resolved_bin_dir="${market_bin}"
    local shell_name
    shell_name="$(basename "${SHELL:-/bin/bash}")"
    local rc_file=""
    local path_line="export PATH=\"$resolved_bin_dir:\$PATH\""

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
            path_line="fish_add_path $resolved_bin_dir"
            ;;
        *)
            rc_file="$HOME/.profile"
            ;;
    esac

    if [ -n "$rc_file" ] && [ -f "$rc_file" ]; then
        if grep -qF "$resolved_bin_dir" "$rc_file" 2>/dev/null; then
            ok "$resolved_bin_dir is already in $rc_file"
            return
        fi
    fi

    if [ -n "$rc_file" ]; then
        echo "" >> "$rc_file"
        echo "# Added by Market CLI installer" >> "$rc_file"
        echo "$path_line" >> "$rc_file"
        warn "Added $resolved_bin_dir to PATH in $rc_file — restart your shell or run: source $rc_file"
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
    echo "  │      Market CLI Installer         │"
    echo "  └──────────────────────────────────┘"
    echo ""

    detect_platform
    check_command make
    check_python_version
    install_uv
    install_market_cli
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
