#!/bin/sh
set -eu

mkdir -p /app/shared-env

# Replay the Alkahest + EAS deployment transactions onto the running RPC.
# After Phase 4 of the pluggable-identity refactor this is the only contract
# suite the deployer ships — ERC-8004 contracts were removed along with the
# rest of the ERC-8004 code paths.
python3 /app/deploy_alkahest.py
