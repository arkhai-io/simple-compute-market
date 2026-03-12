#!/bin/sh

# Start ZeroTier daemon in the background
echo "Starting ZeroTier daemon..."

zerotier-one -d
# Wait for the daemon to be ready (port file created)
for i in $(seq 1 10); do
  [ -f /var/lib/zerotier-one/zerotier-one.port ] && break
  sleep 1
done

if [ -z "${ONCHAIN_AGENT_ID:-}" ] || [ -z "${ZEROTIER_IP:-}" ]; then
  echo "Registering agent on-chain..."
  uv run python core/agent/scripts/register_onchain.py
else
  echo "Skipping on-chain registration (ONCHAIN_AGENT_ID and ZEROTIER_IP already set)."
fi

echo "Starting agent server..."
exec uv run uvicorn core.agent.app.server:app --host 0.0.0.0 --port "${PORT:-8080}"