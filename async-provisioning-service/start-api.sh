#!/bin/sh
set -e

echo "Starting API server on ${HOST:-0.0.0.0}:${PORT:-8081}..."
exec uv run uvicorn async_provisioning_service.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8081}"