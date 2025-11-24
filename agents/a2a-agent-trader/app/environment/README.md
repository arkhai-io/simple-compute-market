# Market Environment

This directory contains the Market environment implementation for reinforcement learning.

## Files

- `market.py` - Python wrapper for the Market environment
- `market.c` - C implementation of the Market environment
- `market.h` - C header file with Market struct definitions
- `binding.c` - C binding that connects Python to the C implementation
- `market.ini` - Configuration file for training
- `default.ini` - Default training configuration

## Building the C Extension

The Market environment requires a C extension to be built. The binding uses pufferlib's build system template (`env_binding.h`).

### Prerequisites

1. **C Compiler**: `gcc` or `clang`
2. **Python development headers**: Usually `python3-dev` or `python3-devel`
3. **pufferlib**: Installed and accessible (for `env_binding.h`)

### Option 1: Build with Make (Recommended)

```bash
cd agents/a2a-agent-trader
make build-market-env
```

### Option 2: Build with uv directly

```bash
cd agents/a2a-agent-trader/app/environment
uv run python build_binding.py
```

### Option 3: Manual Build

If pufferlib is installed from source:

```bash
cd agents/a2a-agent-trader/app/environment

# Find and copy env_binding.h from pufferlib
python3 -c "import pufferlib; import os; print(os.path.dirname(pufferlib.__file__))"
# Copy env_binding.h to ../ (app/ directory)

# Build using setuptools
cd ../..  # Go to project root
uv run python -m setuptools build_ext --inplace --build-lib app/environment
```

### Installing pufferlib from Source (if needed)

If `env_binding.h` is not found, install pufferlib from source:

```bash
git clone https://github.com/pufferai/pufferlib
cd pufferlib
uv pip install -e .
```

This will make `env_binding.h` available in the pufferlib installation.

## Testing

After building, test the environment:

```bash
cd agents/a2a-agent-trader
make test-market-env
```

Or manually:

```bash
cd agents/a2a-agent-trader
uv run test_market_env.py
```

## Training

Train a model on the Market environment using pufferlib. **Note:** Since this is a local environment (not registered with pufferlib's ocean package), we use pufferlib's Python API directly.

### Basic Training

```bash
cd agents/a2a-agent-trader
make train-market-env
```

### Training with Custom Config and Device

```bash
# Use custom config file
make train-market-env CONFIG=app/environment/market.ini DEVICE=cuda

# Use CPU
make train-market-env DEVICE=cpu

# Use MPS (Apple Silicon)
make train-market-env DEVICE=mps
```

### Evaluation

Evaluate the environment (with or without a trained model):

```bash
# Evaluate with random actions (no model)
make eval-market-env

# Evaluate with specific model (when available)
make eval-market-env LOAD_MODEL_PATH=experiments/puffer_market/model.pt
```

### Hyperparameter Sweeps

**Note:** Sweeps require the environment to be registered with pufferlib's ocean package. For local environments, you may need to use the Python API directly or register the environment with pufferlib first.

```bash
# With Weights & Biases (if environment is registered)
make sweep-market-env LOGGER=wandb TAG=my_sweep

# With Neptune (if environment is registered)
make sweep-market-env LOGGER=neptune TAG=my_sweep
```

### Using Python API Directly

You can also use the Python scripts directly:

```bash
# Train
uv run python app/environment/train.py

# Evaluate
uv run python app/environment/eval.py
```

### Using pufferlib CLI (if environment is registered)

If you register the Market environment with pufferlib's ocean package, you can use the CLI:

```bash
# Train
uv run python -m pufferlib.pufferl train puffer_market --config app/environment/market.ini

# Evaluate
uv run python -m pufferlib.pufferl eval puffer_market --load-model-path latest

# Sweep
uv run python -m pufferlib.pufferl sweep puffer_market --wandb --tag my_sweep
```

See `market.ini` for training configuration options.

## Troubleshooting

### Error: "env_binding.h not found"

- Install pufferlib from source (see above)
- Or manually copy `env_binding.h` from pufferlib to `app/` directory

### Error: "gcc not found"

Install a C compiler:
- macOS: `xcode-select --install`
- Ubuntu/Debian: `sudo apt-get install build-essential`
- Fedora: `sudo dnf install gcc python3-devel`

### Error: "Python.h not found"

Install Python development headers:
- macOS: Usually included with Python
- Ubuntu/Debian: `sudo apt-get install python3-dev`
- Fedora: `sudo dnf install python3-devel`

### Import Error after build

Make sure the `.so` file is in the correct location:
- Should be: `app/environment/binding*.so`
- Or: `app/environment/binding.cpython-*.so`

Check with:
```bash
find . -name "binding*.so" -o -name "binding*.pyd"
```

