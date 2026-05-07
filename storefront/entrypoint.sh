#!/bin/sh
# Container entrypoint for the storefront agent.
#
# Pattern: bring up the ZeroTier daemon, then exec whatever was passed
# as args. If no args, fall back to the default sequence (register +
# serve) — that's the one-shot docker-compose case.
#
# This split lets Helm run the same image with two different commands:
#   init container: ./entrypoint.sh market-storefront register --chain-id ...
#   main container: ./entrypoint.sh market-storefront serve
# without re-registering on every pod start.
#
# The ZeroTier daemon is the one piece that can't move into the CLI:
# it's a side-process that has to keep running alongside `serve` (and
# is needed by `register` too, when seller.zerotier_network is set).
#
# The `market-storefront` console script is installed into
# /app/.venv/bin/ by `uv sync` in the builder stage and is on PATH
# (see Dockerfile: ENV PATH="/app/.venv/bin:$PATH").

set -eu

echo "Starting ZeroTier daemon (fail-soft)..."
sudo zerotier-one -d || echo "ZeroTier daemon could not start (no caps?). Continuing."
for i in $(seq 1 10); do
  [ -f /var/lib/zerotier-one/zerotier-one.port ] && break
  sleep 1
done

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

echo "Registering agent on-chain..."
market-storefront register

echo "Starting storefront server..."
exec market-storefront serve
