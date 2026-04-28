#!/bin/sh
# Container entrypoint for the storefront agent.
#
# Three linear steps, no shell-side config inspection:
#   1. Bring up the ZeroTier daemon (fail-soft — caps may not be granted).
#   2. Run register_onchain.py to publish the agent's identity.
#   3. exec the storefront server, which reads its own config from the
#      mounted TOML at $XDG_CONFIG_HOME/arkhai/config.toml.
#
# The agent itself decides whether to actually `zerotier-cli join` based
# on its TOML (seller.zerotier_network); the daemon idles when no
# network is requested.

set -eu

echo "Starting ZeroTier daemon (fail-soft)..."
sudo zerotier-one -d || echo "ZeroTier daemon could not start (no caps?). Continuing."
for i in $(seq 1 10); do
  [ -f /var/lib/zerotier-one/zerotier-one.port ] && break
  sleep 1
done

echo "Registering agent on-chain..."
PYTHONPATH="/:/app:/app/src${PYTHONPATH:+:${PYTHONPATH}}" \
  uv run python scripts/register_onchain.py --no-update-env \
  || { echo "On-chain registration failed; aborting startup."; exit 1; }

echo "Starting storefront server..."
exec env PYTHONPATH="/:/app:/app/src${PYTHONPATH:+:${PYTHONPATH}}" \
  uv run python -m market_storefront.server
