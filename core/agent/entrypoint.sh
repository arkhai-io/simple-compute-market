#!/bin/sh

# Start ZeroTier daemon in the background
echo "Starting ZeroTier daemon..."

zerotier-one -d
# Wait for the daemon to be ready (port file created)
for i in $(seq 1 10); do
  [ -f /var/lib/zerotier-one/zerotier-one.port ] && break
  sleep 1
done

echo "Registering agent on-chain..."
uv run python scripts/register_onchain.py
echo "Starting agent server..."
exec uv run uvicorn app.server:app --host 0.0.0.0 --port "${PORT:-8080}"
