#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
make dist
make -C domains/bare_metal/storefront reinit
cd domains/bare_metal/storefront
uv run --no-sync pytest tests/test_http_introductions.py -k survives_contact_disable -q
