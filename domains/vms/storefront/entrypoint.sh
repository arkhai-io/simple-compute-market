#!/bin/sh
# Container entrypoint for the storefront agent.
#
# Pattern: bring up the ZeroTier daemon, then exec whatever was passed
# as args. If no args, fall back to `market-storefront serve`.
#
# Helm's storefront container runs `./entrypoint.sh market-storefront serve`;
# Compose runs `./entrypoint.sh sh -c "market-storefront-migrate && exec
# market-storefront serve"`. The chart's migration init container runs
# `market-storefront-migrate` without this script, since migrating needs no
# network.
#
# The ZeroTier daemon is the one piece that can't move into the CLI:
# it's a side-process that has to keep running alongside `serve`.
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

echo "Starting storefront server..."
exec market-storefront serve
