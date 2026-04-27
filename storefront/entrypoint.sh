#!/bin/sh

# Start ZeroTier daemon in the background
echo "Starting ZeroTier daemon..."

sudo zerotier-one -d
# Wait for the daemon to be ready (port file created)
for i in $(seq 1 10); do
  [ -f /var/lib/zerotier-one/zerotier-one.port ] && break
  sleep 1
done

# Always join the ZeroTier network if configured, regardless of registration state
if [ -n "${ZEROTIER_NETWORK:-}" ]; then
  echo "Joining ZeroTier network ${ZEROTIER_NETWORK}..."
  sudo zerotier-cli join "${ZEROTIER_NETWORK}" || echo "Warning: zerotier-cli join failed (may already be joined)"
fi

if [ -z "${ONCHAIN_AGENT_ID:-}" ] || [ -z "${ZEROTIER_IP:-}" ]; then
  echo "Registering agent on-chain..."
  # Resolve env file to absolute path so POSIX sh (dash) can source it
  echo "ZeroTier Env file:"${ENV_FILE}
  case "${ENV_FILE:-.env}" in
    /*) _env_file="${ENV_FILE:-.env}" ;;
    *)  _env_file="$(pwd)/${ENV_FILE:-.env}" ;;
  esac
  # Ensure the file exists so register_onchain.py can write ONCHAIN_AGENT_ID back to it
  touch "${_env_file}"
  PYTHONPATH="/:/app:/app/src${PYTHONPATH:+:${PYTHONPATH}}" uv run python scripts/register_onchain.py --env_file="${_env_file}"
  # Reload env file so ONCHAIN_AGENT_ID written by registration is visible to the server
  set -a
  . "${_env_file}"
  set +a
else
  echo "Skipping on-chain registration (ONCHAIN_AGENT_ID and ZEROTIER_IP already set)."
fi

echo "Starting storefront server..."
exec env PYTHONPATH="/:/app:/app/src${PYTHONPATH:+:${PYTHONPATH}}" uv run uvicorn market_storefront.server:app --host 0.0.0.0 --port "${PORT:-8080}"