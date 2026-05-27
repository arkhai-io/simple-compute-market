#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${SUDO_USER:-${USER:-ubuntu}}"
TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6 || true)"
TARGET_HOME="${TARGET_HOME:-${HOME:-/home/$TARGET_USER}}"
VALIDATION_COMMAND="${SCM_VALIDATION_COMMAND:-./scripts/issue-discovery strict}"
RUN_VALIDATION="${SCM_RUN_VALIDATION:-1}"
SKIP_ZEROTIER="${SCM_BOOTSTRAP_SKIP_ZEROTIER:-0}"
export PATH="$TARGET_HOME/.local/bin:$PATH"

log() {
  printf '[bootstrap-clean-host] %s\n' "$*"
}

need_sudo() {
  if [ "${EUID}" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

check_ubuntu() {
  if [ ! -r /etc/os-release ]; then
    log "missing /etc/os-release"
    return 1
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ]; then
    log "expected Ubuntu, found ${PRETTY_NAME:-unknown}"
    return 1
  fi
}

install_base_packages() {
  log "installing base packages"
  need_sudo apt-get update --allow-releaseinfo-change
  need_sudo apt-get install -y \
    ca-certificates \
    curl \
    git \
    gnupg \
    jq \
    make \
    python3 \
    sudo \
    tar \
    unzip
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "docker and compose plugin already installed"
  else
    log "installing docker engine and compose plugin"
    need_sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | need_sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
    need_sudo chmod a+r /etc/apt/keyrings/docker.gpg
    # shellcheck disable=SC1091
    . /etc/os-release
    arch="$(dpkg --print-architecture)"
    codename="${VERSION_CODENAME}"
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
      "$arch" "$codename" \
      | need_sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    need_sudo apt-get update --allow-releaseinfo-change
    need_sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi

  need_sudo systemctl enable --now docker
  if id "$TARGET_USER" >/dev/null 2>&1; then
    need_sudo usermod -aG docker "$TARGET_USER"
  fi
}

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    log "uv already installed"
    return
  fi
  log "installing uv"
  if [ "${EUID}" -eq 0 ]; then
    sudo -u "$TARGET_USER" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
}

install_zerotier() {
  if [ "$SKIP_ZEROTIER" = "1" ]; then
    log "skipping zerotier install"
    return
  fi
  if command -v zerotier-cli >/dev/null 2>&1; then
    log "zerotier already installed"
    return
  fi
  log "installing zerotier"
  need_sudo apt-get update --allow-releaseinfo-change
  curl -fsSL https://install.zerotier.com | need_sudo bash
}

check_tools() {
  check_ubuntu
  command -v git
  command -v make
  command -v curl
  command -v jq
  command -v python3
  command -v uv
  command -v docker
  docker compose version
}

run_validation() {
  if [ "$RUN_VALIDATION" != "1" ]; then
    log "validation disabled by SCM_RUN_VALIDATION=$RUN_VALIDATION"
    return
  fi

  log "running validation: $VALIDATION_COMMAND"
  if [ "${EUID}" -eq 0 ] && id "$TARGET_USER" >/dev/null 2>&1; then
    sudo -iu "$TARGET_USER" bash -lc "cd '$REPO_ROOT' && export PATH=\"\$HOME/.local/bin:\$PATH\" && $VALIDATION_COMMAND"
  else
    cd "$REPO_ROOT"
    export PATH="$HOME/.local/bin:$PATH"
    if docker info >/dev/null 2>&1; then
      bash -lc "$VALIDATION_COMMAND"
    elif command -v sg >/dev/null 2>&1 && getent group docker >/dev/null 2>&1; then
      sg docker -c "cd '$REPO_ROOT' && export PATH=\"\$HOME/.local/bin:\$PATH\" && $VALIDATION_COMMAND"
    else
      log "docker is not accessible to the current user; rerun after starting a new docker-group session"
      return 1
    fi
  fi
}

case "$MODE" in
  check)
    check_tools
    ;;
  run)
    check_ubuntu
    install_base_packages
    install_docker
    install_uv
    install_zerotier
    check_tools
    run_validation
    ;;
  *)
    echo "usage: $0 [check|run]" >&2
    exit 2
    ;;
esac
