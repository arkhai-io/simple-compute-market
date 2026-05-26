#!/bin/sh
# Container entrypoint for the storefront agent.
#
# Pattern: bring up the ZeroTier daemon, then exec whatever was passed
# as args. If no args, fall back to `market-storefront serve` — that's
# the one-shot docker-compose case.
#
# Registration is the server lifespan's job (agent.py:_ensure_agent_identity).
# It resolves the agent ID by checking, in order:
#   1. settings.onchain_agent_id  (pinned via TOML / helm values)
#   2. find_agent_id_by_owner    (look up an agent already owned by the wallet)
#   3. perform_registration       (mint a new agent — only if auto_register=true)
# So a separate `market-storefront register` step here is redundant; running
# it would burn gas and emit duplicate registry events if the lookup path is
# broken upstream.
#
# This split lets Helm run the same image with two different commands:
#   init container: ./entrypoint.sh market-storefront register --chain-id ...
#   main container: ./entrypoint.sh market-storefront serve
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

echo "Starting storefront server..."
exec market-storefront serve
