#!/bin/sh

# Start ZeroTier daemon in the background
echo "Starting ZeroTier daemon..."

if [ -n "${ZEROTIER_NETWORK:-}" ]; then
  sudo zerotier-one -d
  # Wait for the daemon to be ready (port file created)
  for i in $(seq 1 10); do
    [ -f /var/lib/zerotier-one/zerotier-one.port ] && break
    sleep 1
  done

  echo "Joining ZeroTier network ${ZEROTIER_NETWORK}..."
  sudo zerotier-cli join "${ZEROTIER_NETWORK}" || echo "Warning: zerotier-cli join failed (may already be joined)"
fi

# Resolve env file to absolute path and preload it so persisted host-local
# values drive the registration decision on container restarts.
case "${ENV_FILE:-.env}" in
  /*) _env_file="${ENV_FILE:-.env}" ;;
  *)  _env_file="$(pwd)/${ENV_FILE:-.env}" ;;
esac
if [ -f "${_env_file}" ]; then
  set -a
  . "${_env_file}"
  set +a
fi

needs_registration=false
if [ -z "${ONCHAIN_AGENT_ID:-}" ]; then
  needs_registration=true
else
  case "${ONCHAIN_AGENT_ID:-}" in
    eip155:*) ;;
    *)
      needs_registration=true
      ;;
  esac
fi
if [ -n "${ZEROTIER_NETWORK:-}" ] && [ -z "${ZEROTIER_IP:-}" ]; then
  needs_registration=true
fi

if [ "${needs_registration}" = "true" ]; then
  echo "Registering agent on-chain..."
  echo "ZeroTier Env file:"${ENV_FILE}
  # Ensure the file exists so register_onchain.py can write ONCHAIN_AGENT_ID back to it
  touch "${_env_file}"
  PYTHONPATH="/:/app:/app/core/agent${PYTHONPATH:+:${PYTHONPATH}}" uv run python core/agent/scripts/register_onchain.py --env_file="${_env_file}"
  # Reload env file so ONCHAIN_AGENT_ID written by registration is visible to the server
  set -a
  . "${_env_file}"
  set +a
else
  echo "Skipping on-chain registration (required identity fields already set)."
fi

echo "Starting agent server..."
exec env PYTHONPATH="/:/app:/app/core/agent${PYTHONPATH:+:${PYTHONPATH}}" /app/.venv/bin/uvicorn core.agent.app.server:app --host 0.0.0.0 --port "${PORT:-8080}"
