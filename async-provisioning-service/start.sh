#!/bin/sh
set -e

# Start the background worker
uv run python -m async_provisioning_service.worker &
WORKER_PID=$!

# Start the API server
uv run uvicorn async_provisioning_service.main:app --host 0.0.0.0 --port 8081 &
SERVER_PID=$!

# If either process exits, shut down the other
trap "kill $WORKER_PID $SERVER_PID 2>/dev/null; exit 1" INT TERM

while kill -0 $WORKER_PID 2>/dev/null && kill -0 $SERVER_PID 2>/dev/null; do
    sleep 1
done

kill $WORKER_PID $SERVER_PID 2>/dev/null
exit 1
