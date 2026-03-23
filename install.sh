#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
INSTALL_DIR="${MARKET_INSTALL_DIR:-$HOME/.market}"
BIN_DIR="$HOME/.local/bin"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12
UV_VERSION="0.8.13"

# ── System dependency mapping ─────────────────────────────────
# Format: "command:apt-package"
LINUX_SYSTEM_DEPS=(
    "curl:curl"
    "rsync:rsync"
    "git:git"
    "gcc:build-essential"
    "g++:build-essential"
    "python3.12:python3.12"
)
LINUX_PYTHON_DEV_PKGS=("python3.12-dev" "software-properties-common")

# ── Color helpers ──────────────────────────────────────────────
info()  { printf '\033[1;34m[info]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
ok()    { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }

# ── Prerequisite checks ───────────────────────────────────────

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

# ── Dependency detection & installation ───────────────────────

check_and_install_dependencies() {
    # ── Collect everything that's missing ──
    local display_items=()        # human-readable list for the prompt
    local missing_apt_cmds=()     # commands to verify after apt install
    local missing_apt_pkgs=()     # deduplicated apt packages
    local need_python312=false
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
                    # Deduplicate packages
                    local already=false
                    for p in "${missing_apt_pkgs[@]+"${missing_apt_pkgs[@]}"}"; do
                        [ "$p" = "$pkg" ] && already=true && break
                    done
                    if [ "$already" = false ]; then
                        missing_apt_pkgs+=("$pkg")
                        display_items+=("$pkg (apt)")
                    fi
                    [ "$cmd" = "python3.12" ] && need_python312=true
                fi
            done

            # Extra packages for python3.12
            if [ "$need_python312" = true ]; then
                for extra in "${LINUX_PYTHON_DEV_PKGS[@]}"; do
                    local already=false
                    for p in "${missing_apt_pkgs[@]+"${missing_apt_pkgs[@]}"}"; do
                        [ "$p" = "$extra" ] && already=true && break
                    done
                    if [ "$already" = false ]; then
                        missing_apt_pkgs+=("$extra")
                        display_items+=("$extra (apt)")
                    fi
                done
            fi
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
                info "You can install them with Homebrew, e.g.:"
                echo "    brew install ${mac_missing[*]}"
            else
                info "Install Homebrew (https://brew.sh) and then install the missing commands."
            fi
            exit 1
        fi
    fi

    # ── Nothing missing → done ──
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

    # ── Single prompt for everything ──
    echo ""
    warn "The following dependencies need to be installed:"
    for item in "${display_items[@]}"; do
        echo "  - $item"
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

    # ── Install system packages via apt ──
    if [ ${#missing_apt_pkgs[@]} -gt 0 ]; then
        info "Updating package lists..."
        sudo apt-get update -y

        if [ "$need_python312" = true ]; then
            if ! command -v add-apt-repository &>/dev/null; then
                info "Installing software-properties-common for PPA support..."
                sudo apt-get install -y software-properties-common
            fi
            info "Adding deadsnakes PPA for Python 3.12..."
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt-get update -y
        fi

        info "Installing packages: ${missing_apt_pkgs[*]}"
        sudo apt-get install -y "${missing_apt_pkgs[@]}"

        # Verify
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
    local core_dir="$INSTALL_DIR/core"
    local core_venv="$core_dir/.venv"

    info "Installing CLI into core venv..."
    uv --project "$core_dir" sync --no-dev -q

    ok "CLI installed into $core_venv"
}

# ── Create symlink and set up PATH ────────────────────────────

setup_path() {
    local market_bin="$INSTALL_DIR/core/.venv/bin/market"

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
    ok "Installation complete"

    echo ""
    info "Get started:"
    echo "    market --help              Show all commands"
    echo "    market install             Sync local agent/registry/contracts dependencies"
    echo "    market config init agent   Configure the agent"
    echo ""
}

main "$@"
