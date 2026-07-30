#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

exec "$ROOT_DIR/scripts/issue-discovery" capacity action-capture \
  "$@" \
  --expected-action-kind seller-service-start
