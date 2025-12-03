#!/bin/bash
# Build script for Market C extension binding

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Building Market C extension binding..."
echo "======================================"

# Check if pufferlib is installed and try to find env_binding.h
PUFFERLIB_PATH=$(python3 -c "import pufferlib; import os; print(os.path.dirname(pufferlib.__file__))" 2>/dev/null || echo "")

if [ -n "$PUFFERLIB_PATH" ]; then
    echo "Found pufferlib at: $PUFFERLIB_PATH"
    
    # Look for env_binding.h in common locations
    ENV_BINDING_H=""
    for path in "$PUFFERLIB_PATH/ocean/env_binding.h" \
                "$PUFFERLIB_PATH/../ocean/env_binding.h" \
                "$(python3 -m site --user-site)/pufferlib/ocean/env_binding.h"; do
        if [ -f "$path" ]; then
            ENV_BINDING_H="$path"
            echo "Found env_binding.h at: $ENV_BINDING_H"
            break
        fi
    done
    
    if [ -z "$ENV_BINDING_H" ]; then
        echo "WARNING: env_binding.h not found. You may need to install pufferlib from source."
        echo "Trying to build without it..."
    fi
else
    echo "WARNING: pufferlib not found. Trying to build anyway..."
fi

# Try building with setuptools
echo ""
echo "Attempting to build with setuptools..."
python3 setup_binding.py build_ext --inplace

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Build successful!"
    echo "The binding module should now be available."
else
    echo ""
    echo "✗ Build failed. You may need to:"
    echo "  1. Install pufferlib from source to get env_binding.h"
    echo "  2. Install build dependencies: python3-dev, gcc"
    echo "  3. Check the error messages above"
    exit 1
fi

