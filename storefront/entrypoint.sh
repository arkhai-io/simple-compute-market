#!/bin/sh
# Container entrypoint for the storefront agent.
#
# Reads configuration exclusively from $XDG_CONFIG_HOME/arkhai/config.toml
# (the mounted TOML). Steps:
#   1. Bring up ZeroTier if a network is configured in the TOML.
#   2. Run register_onchain.py to publish the agent's identity.
#   3. exec uvicorn.

set -eu

# Read a single TOML key via the config-loader's pure Python.
toml_get() {
  PYTHONPATH="/:/app:/app/src" uv run --no-project python -c "
from service.config_loader import load_user_config, get_dotted
v = get_dotted(load_user_config(), '$1')
print('' if v is None else v)
" 2>/dev/null || echo ""
}

ZEROTIER_NETWORK=$(toml_get seller.zerotier_network)
PORT=$(toml_get seller.port)
PORT="${PORT:-8001}"

if [ -n "${ZEROTIER_NETWORK}" ]; then
  echo "Starting ZeroTier daemon..."
  sudo zerotier-one -d
  for i in $(seq 1 10); do
    [ -f /var/lib/zerotier-one/zerotier-one.port ] && break
    sleep 1
  done
  echo "Joining ZeroTier network ${ZEROTIER_NETWORK}..."
  sudo zerotier-cli join "${ZEROTIER_NETWORK}" \
    || echo "Warning: zerotier-cli join failed (may already be joined)"
fi

echo "Registering agent on-chain..."
PYTHONPATH="/:/app:/app/src${PYTHONPATH:+:${PYTHONPATH}}" \
  uv run python storefront/scripts/register_onchain.py --no-update-env \
  || { echo "On-chain registration failed; aborting startup."; exit 1; }

echo "Starting storefront server on port ${PORT}..."
exec env PYTHONPATH="/:/app:/app/src${PYTHONPATH:+:${PYTHONPATH}}" \
  uv run uvicorn market_storefront.server:app \
  --host 0.0.0.0 --port "${PORT}"
