#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: run-vector-add.sh BUILD_DIRECTORY" >&2
  exit 64
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$1"
BINARY="$BUILD_DIR/scm-capacity-vector-add"
EXPECTED_OUTPUT="SCM_CUDA_VECTOR_ADD_OK elements=1024 checksum=1571328"

umask 077
mkdir -p "$BUILD_DIR"
nvcc --std=c++17 --optimize=2 "$SCRIPT_DIR/vector_add.cu" --output-file "$BINARY"
OUTPUT="$("$BINARY")"

if [[ "$OUTPUT" != "$EXPECTED_OUTPUT" ]]; then
  echo "SCM_CUDA_VECTOR_ADD_ERROR unexpected-output" >&2
  exit 1
fi

RESULT_SHA256="$(printf '%s\n' "$OUTPUT" | sha256sum | awk '{print $1}')"
printf 'SCM_CUDA_VECTOR_ADD_OK result_sha256=%s\n' "$RESULT_SHA256"
