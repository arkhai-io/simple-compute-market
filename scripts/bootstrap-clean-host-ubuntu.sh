#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${SUDO_USER:-${USER:-ubuntu}}"
TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6 || true)"
TARGET_HOME="${TARGET_HOME:-${HOME:-/home/$TARGET_USER}}"
VALIDATION_COMMAND="${SCM_VALIDATION_COMMAND:-./scripts/issue-discovery strict}"
VALIDATION_SCRIPT="${SCM_VALIDATION_SCRIPT:-}"
CLEAN_ROOM_SEQUENCE="${SCM_CLEAN_ROOM_SEQUENCE:-}"
CLEAN_ROOM_SCRIPT_PATH="${SCM_CLEAN_ROOM_SCRIPT_PATH:-.scm-local/clean-room/run.sh}"
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

shell_quote() {
  printf '%q' "$1"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "missing required command: $1"
    return 1
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
    nodejs \
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
  require_command git
  require_command make
  require_command curl
  require_command jq
  require_command node
  require_command python3
  require_command uv
  require_command docker
  if [ "$SKIP_ZEROTIER" != "1" ]; then
    require_command zerotier-cli
  fi
  docker compose version
  if docker info >/dev/null 2>&1; then
    return
  fi
  if command -v sg >/dev/null 2>&1 && getent group docker >/dev/null 2>&1; then
    if sg docker -c 'docker info >/dev/null 2>&1'; then
      return
    fi
  fi
  log "docker daemon is not accessible to the current user"
  return 1
}

log_version_command() {
  label="$1"
  shift
  if "$@" >/tmp/scm-bootstrap-version.out 2>&1; then
    while IFS= read -r line; do
      log "$label: $line"
    done </tmp/scm-bootstrap-version.out
  else
    log "$label: unavailable"
  fi
  rm -f /tmp/scm-bootstrap-version.out
}

log_tool_versions() {
  log "tool versions"
  log_version_command git git --version
  log_version_command make make --version
  log_version_command curl curl --version
  log_version_command jq jq --version
  log_version_command node node --version
  log_version_command python3 python3 --version
  log_version_command uv uv --version
  log_version_command docker docker --version
  log_version_command docker-compose docker compose version
}

validation_command_text() {
  if [ -n "$VALIDATION_SCRIPT" ]; then
    printf 'bash %s' "$(shell_quote "$VALIDATION_SCRIPT")"
    return
  fi
  if [ -n "$CLEAN_ROOM_SEQUENCE" ]; then
    script_dir="$(dirname "$CLEAN_ROOM_SCRIPT_PATH")"
    printf 'mkdir -p %s && ./scripts/issue-discovery clean-room script %s > %s && bash %s' \
      "$(shell_quote "$script_dir")" \
      "$(shell_quote "$CLEAN_ROOM_SEQUENCE")" \
      "$(shell_quote "$CLEAN_ROOM_SCRIPT_PATH")" \
      "$(shell_quote "$CLEAN_ROOM_SCRIPT_PATH")"
    return
  fi
  printf '%s' "$VALIDATION_COMMAND"
}

run_validation() {
  if [ "$RUN_VALIDATION" != "1" ]; then
    log "validation disabled by SCM_RUN_VALIDATION=$RUN_VALIDATION"
    return
  fi

  command_text="$(validation_command_text)"
  log "running validation: $command_text"
  if [ "${EUID}" -eq 0 ] && id "$TARGET_USER" >/dev/null 2>&1; then
    sudo -iu "$TARGET_USER" bash -lc "cd '$REPO_ROOT' && export PATH=\"\$HOME/.local/bin:\$PATH\" && $command_text"
  else
    cd "$REPO_ROOT"
    export PATH="$HOME/.local/bin:$PATH"
    if docker info >/dev/null 2>&1; then
      bash -lc "$command_text"
    elif command -v sg >/dev/null 2>&1 && getent group docker >/dev/null 2>&1; then
      sg docker -c "cd '$REPO_ROOT' && export PATH=\"\$HOME/.local/bin:\$PATH\" && $command_text"
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
    log_tool_versions
    run_validation
    ;;
  *)
    echo "usage: $0 [check|run]" >&2
    exit 2
    ;;
esac
