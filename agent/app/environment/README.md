# Market Environment

This directory contains Market environment implementations for reinforcement learning. The directory is organized by environment type to allow for multiple environment variants.

## Directory Structure

- `seller/` - Seller-side market environment
  - `market.py` - Python wrapper for the Market environment
  - `market.c` - C implementation of the Market environment
  - `market.h` - C header file with Market struct definitions
  - `binding.c` - C binding that connects Python to the C implementation
  - `market.ini` - Configuration file for training
  - `default.ini` - Default training configuration
  - `train.py` - Training script
  - `eval.py` - Evaluation script
  - `build_binding.py` - Build script for C extension

Future environments (e.g., `buyer/`) can be added as separate subdirectories following the same structure.

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
cd agents/a2a-agent-trader/app/environment/seller
uv run python build_binding.py
```

### Option 3: Manual Build

If pufferlib is installed from source:

```bash
cd agents/a2a-agent-trader/app/environment/seller

# Find and copy env_binding.h from pufferlib
python3 -c "import pufferlib; import os; print(os.path.dirname(pufferlib.__file__))"
# Copy env_binding.h to ../ (app/environment/ directory)

# Build using setuptools
cd ../..  # Go to project root
uv run python -m setuptools build_ext --inplace --build-lib app/environment/seller
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

**Note:** The test script imports from `environment.seller.market`, but you can also import directly from `app.environment` which will automatically use the seller environment.

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
make train-market-env CONFIG=app/environment/seller/market.ini DEVICE=cuda

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
uv run python app/environment/seller/train.py

# Evaluate
uv run python app/environment/seller/eval.py
```

### Using pufferlib CLI (if environment is registered)

If you register the Market environment with pufferlib's ocean package, you can use the CLI:

```bash
# Train
uv run python -m pufferlib.pufferl train puffer_market --config app/environment/seller/market.ini

# Evaluate
uv run python -m pufferlib.pufferl eval puffer_market --load-model-path latest

# Sweep
uv run python -m pufferlib.pufferl sweep puffer_market --wandb --tag my_sweep
```

See `seller/market.ini` for training configuration options.

## Model Export

Export trained model checkpoints to TorchScript format for deployment or inference in other environments.

### Export with Make

```bash
# Export latest checkpoint (auto-detects from experiments/)
make export-model

# Export specific checkpoint
make export-model CHECKPOINT=experiments/176397814556/model_000200.pt

# Export with custom output path
make export-model CHECKPOINT=experiments/176397814556/model_000200.pt OUTPUT=my_model.ts

# Export using CUDA (faster if available)
make export-model CHECKPOINT=experiments/176397814556/model_000200.pt DEVICE=cuda

# Use torch.jit.script instead of trace (better for models with control flow)
make export-model CHECKPOINT=experiments/176397814556/model_000200.pt SCRIPT=true
```

### Export with Python Script

```bash
# Export latest checkpoint
uv run python app/environment/seller/export_model.py

# Export specific checkpoint
uv run python app/environment/seller/export_model.py experiments/176397814556/model_000200.pt

# Export with custom output path
uv run python app/environment/seller/export_model.py experiments/176397814556/model_000200.pt -o my_model.ts

# Export with custom observation shape (if different from default)
uv run python app/environment/seller/export_model.py experiments/176397814556/model_000200.pt --obs-shape 14

# Use torch.jit.script method
uv run python app/environment/seller/export_model.py experiments/176397814556/model_000200.pt --script
```

### Using Exported TorchScript Models

```python
import torch

# Load the exported model
model = torch.jit.load("my_model.ts")
model.eval()

# Create input (observation shape: 14 features)
observation = torch.zeros((1, 14), dtype=torch.float32)

# Run inference
with torch.no_grad():
    output = model(observation)
    # output contains logits for action space MultiDiscrete([9, 2])
```

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
- Should be: `app/environment/seller/binding*.so`
- Or: `app/environment/seller/binding.cpython-*.so`

Check with:
```bash
find . -name "binding*.so" -o -name "binding*.pyd"
```

