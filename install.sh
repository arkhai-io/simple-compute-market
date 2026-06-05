#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
INSTALL_DIR="${MARKET_INSTALL_DIR:-$HOME/.market}"
BIN_DIR="$HOME/.local/bin"
UV_VERSION="0.8.13"
ASSUME_YES=false

# ── System dependency mapping ─────────────────────────────────
# Format: "command:apt-package"
LINUX_SYSTEM_DEPS=(
    "curl:curl"
    "rsync:rsync"
    "git:git"
    "gcc:build-essential"
    "g++:build-essential"
    "make:build-essential"
    "jq:jq"
)

# ── Color helpers ──────────────────────────────────────────────
info()  { printf '\033[1;34m[info]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
ok()    { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

# ── Prerequisite checks ───────────────────────────────────────
#
# Note: there is no system-Python version gate. `uv sync` (install_cli)
# provisions a managed CPython matching the buyer's requires-python
# (>=3.12), downloading it if absent. Gating on the system `python3`
# wrongly rejected macOS, which ships only python3 (3.9).

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --yes|-y)
                ASSUME_YES=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
}

assume_yes_enabled() {
    case "${MARKET_INSTALL_ASSUME_YES:-}" in
        1|true|TRUE|yes|YES|y|Y) return 0 ;;
    esac
    [ "$ASSUME_YES" = true ]
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

# ── Dependency detection & installation ───────────────────────

check_and_install_dependencies() {
    local display_items=()        # human-readable list for the prompt
    local missing_apt_cmds=()     # commands to verify after apt install
    local missing_apt_pkgs=()     # deduplicated apt packages
    local has_apt=false

    # -- System packages (Linux only) --
    if [ "$OS" = "linux" ]; then
        if command -v apt-get &>/dev/null; then
            has_apt=true
        else
            warn "apt-get not found -- cannot auto-install system packages on this distro."
        fi

        if [ "$has_apt" = true ]; then
            for entry in "${LINUX_SYSTEM_DEPS[@]}"; do
                local cmd="${entry%%:*}"
                local pkg="${entry##*:}"

                if ! command -v "$cmd" &>/dev/null; then
                    missing_apt_cmds+=("$cmd")
                    local already=false
                    for p in "${missing_apt_pkgs[@]+"${missing_apt_pkgs[@]}"}"; do
                        [ "$p" = "$pkg" ] && already=true && break
                    done
                    if [ "$already" = false ]; then
                        missing_apt_pkgs+=("$pkg")
                        display_items+=("$pkg (apt)")
                    fi
                fi
            done
        fi

    elif [ "$OS" = "macos" ]; then
        local mac_missing=()
        for entry in "${LINUX_SYSTEM_DEPS[@]}"; do
            local cmd="${entry%%:*}"
            if ! command -v "$cmd" &>/dev/null; then
                mac_missing+=("$cmd")
            fi
        done

        if [ ${#mac_missing[@]} -gt 0 ]; then
            echo ""
            error "The following required commands are missing:"
            for cmd in "${mac_missing[@]}"; do
                echo "  - $cmd"
            done
            echo ""
            if command -v brew &>/dev/null; then
                info "Install with Homebrew:"
                echo "    brew install ${mac_missing[*]}"
            else
                info "Install Homebrew (https://brew.sh) and then install the missing commands."
            fi
            exit 1
        fi
    fi

    if [ ${#display_items[@]} -eq 0 ]; then
        ok "All dependencies are present."
        return
    fi

    # ── Sudo check (Linux, before prompting) ──
    if [ "$OS" = "linux" ] && [ ${#missing_apt_pkgs[@]} -gt 0 ]; then
        if ! command -v sudo &>/dev/null; then
            if [ "$(id -u)" -ne 0 ]; then
                error "'sudo' is not installed and you are not root."
                error "Please run this script as root or install sudo first: apt-get install sudo"
                exit 1
            fi
            sudo() { "$@"; }
        fi
    fi

    echo ""
    warn "The following dependencies need to be installed:"
    for item in "${display_items[@]}"; do
        echo "  - $item"
    done
    echo ""

    if assume_yes_enabled; then
        info "Installing missing dependencies because --yes/-y or MARKET_INSTALL_ASSUME_YES is set."
    elif [ -e /dev/tty ] && [ -r /dev/tty ]; then
        printf '\033[1;34m[?]\033[0m Would you like to install them? [Y/n] '
        read -r answer </dev/tty
        case "$answer" in
            [nN]|[nN][oO])
                error "Cannot proceed without required dependencies."
                exit 1
                ;;
        esac
    else
        error "Cannot prompt for dependency installation because no TTY is available."
        error "Install the missing packages above, or rerun with MARKET_INSTALL_ASSUME_YES=1 to allow apt installation."
        exit 1
    fi
    echo ""

    if [ ${#missing_apt_pkgs[@]} -gt 0 ]; then
        info "Updating package lists..."
        sudo apt-get update -y

        info "Installing packages: ${missing_apt_pkgs[*]}"
        sudo apt-get install -y "${missing_apt_pkgs[@]}"

        local still_missing=()
        for cmd in "${missing_apt_cmds[@]}"; do
            if ! command -v "$cmd" &>/dev/null; then
                still_missing+=("$cmd")
            fi
        done
        if [ ${#still_missing[@]} -gt 0 ]; then
            error "The following commands are still not available after installation: ${still_missing[*]}"
            exit 1
        fi
        ok "System packages installed successfully."
    fi
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

    mkdir -p "$INSTALL_DIR"
    rsync -a --delete \
        --exclude='.git' \
        --exclude='market-installer.sh' \
        "$src_dir/" "$INSTALL_DIR/"

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
    local buyer_dir="$INSTALL_DIR/buyer"
    local buyer_venv="$buyer_dir/.venv"

    info "Installing buyer CLI into venv..."
    uv --project "$buyer_dir" sync --no-dev -q

    ok "Buyer CLI installed into $buyer_venv"
}

# ── Create symlink and set up PATH ────────────────────────────

setup_path() {
    local market_bin="$INSTALL_DIR/buyer/.venv/bin/market"

    mkdir -p "$BIN_DIR"

    if [ -L "$BIN_DIR/market" ] || [ -e "$BIN_DIR/market" ]; then
        rm -f "$BIN_DIR/market"
    fi
    ln -s "$market_bin" "$BIN_DIR/market"
    ok "Symlinked $BIN_DIR/market -> $market_bin"

    export PATH="$BIN_DIR:$PATH"

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
        warn "Added $BIN_DIR to PATH in $rc_file -- restart your shell or run: source $rc_file"
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

    parse_args "$@"
    detect_platform
    check_and_install_dependencies
    install_uv
    install_repo
    install_cli
    setup_path
    verify

    echo ""
    ok "Market CLI installed successfully!"
    echo ""
    info "Get started:"
    echo "    market --help              Show all commands"
    echo "    market config init-user    Scaffold ~/.config/arkhai/buyer.toml"
    echo ""
}

main "$@"
