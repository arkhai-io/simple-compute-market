# Arkhai Training (Library-First)

This project uses `ArkhaiPufferEnv` via `pufferlib` directly. Training produces `.pt` checkpoint files that are released as GitHub Release assets and downloaded at deployment time.

Training pulls in pufferlib's C-backed env + trainer (heavy build, Python 3.12 only). **Inference does not** — the storefront and buyer load the trained `.pt` files into a small inline `ArkhaiInferencePolicy` (see `domains/vms/negotiation/rl/arkhai_common.py`) with just `torch` as a dep. The two paths are explicitly separate extras so a seller / buyer install doesn't drag in pufferlib.

## Install

```bash
# Training (this folder + market-policy train/eval CLI)
cd kit/policy && uv pip install -e ".[training]"

# Inference only (storefront / buyer at runtime)
cd storefront && uv pip install -e ".[rl]"   # torch only, no pufferlib
cd buyer     && uv pip install -e ".[rl]"
```

On macOS with uv-managed Python the pufferlib C extension build can pick up stale Xcode SDK paths from the Python sysconfig. If linking fails with `library 'c++' not found` or references to a non-existent `Xcode_15.2.app`, override the sysroot:

```bash
LDCXXSHARED="clang++ -bundle -undefined dynamic_lookup -arch arm64 \
    -mmacosx-version-min=11.0 -isysroot $(xcrun --sdk macosx --show-sdk-path)" \
  uv pip install -e ".[training]"
```

## Source of Truth

- Environment and training contracts come from upstream `pufferlib`.
- Local scripts in this folder are intentionally minimal.
- Training and evaluation run through `puffer` CLI commands via Makefile targets.
- Training configs live in `agent/app/arkhai_training/config/`.
- Sweep-tuned PPO hyperparameters are from upstream ArkhaiPufferEnv (100M timesteps).

## Prerequisites

**Hardware:** GPU recommended. Training runs at ~300K SPS on RTX A5000 (~5 min for 100M steps).

**WandB setup** (optional, for tracking training metrics):

```bash
# Install is automatic (transitive dep from pufferlib)
# Login with your API key from https://wandb.ai/authorize
cd agent
uv run wandb login
```

## Training Commands

Run from `/agent`:

```bash
# ──────────────────────────────────────────────
# Seller training
# ──────────────────────────────────────────────

# Smoke test (CPU, quick validation)
make train-arkhai DEVICE=cpu TOTAL_TIMESTEPS=1000000

# Production seller (GPU, 100M steps, WandB logging)
make train-arkhai DEVICE=cuda TOTAL_TIMESTEPS=100000000 WANDB=true TAG=seller_prod_v1

# With explicit overrides
make train-arkhai DEVICE=cuda TOTAL_TIMESTEPS=100000000 WANDB=true TAG=seller_v1 \
  ARGS="--vec.num-envs 1 --env.num-envs 64 --train.batch-size 16384 --train.minibatch-size 2048"

# ──────────────────────────────────────────────
# Buyer training
# ──────────────────────────────────────────────

# Production buyer (GPU, 100M steps, WandB logging)
make train-arkhai-buyer DEVICE=cuda TOTAL_TIMESTEPS=100000000 WANDB=true TAG=buyer_prod_v1

# ──────────────────────────────────────────────
# Bilateral training (experimental)
# ──────────────────────────────────────────────

# Both AI seller and AI buyer train simultaneously
make train-arkhai-bilateral DEVICE=cuda TOTAL_TIMESTEPS=100000000 WANDB=true TAG=bilateral_v1
```

## Evaluation

```bash
# Evaluate latest checkpoint
make eval-arkhai

# Evaluate specific checkpoint
make eval-arkhai MODEL=experiments/puffer_arkhai_*/model_puffer_arkhai_000001.pt

# Evaluate buyer
make eval-arkhai-buyer MODEL=experiments/puffer_arkhai_*/model_puffer_arkhai_000001.pt

# Export puffer-native weights binary
make export-arkhai-weights MODEL=latest

# Environment smoke test
make test-arkhai-env
```

## Release and Deploy

After training, copy the checkpoint and release it as a GitHub asset:

```bash
# 1. Copy checkpoint to model directory
cp experiments/puffer_arkhai_<run_id>.pt domains/vms/negotiation/rl/models/arkhai_seller.pt
cp experiments/puffer_arkhai_<run_id>.pt domains/vms/negotiation/rl/models/arkhai_buyer.pt

# 2. Release to GitHub (requires gh CLI authenticated)
make release-models VERSION=model-v0.1.0

# 3. Download models (on other machines or in CI)
make download-models VERSION=model-v0.1.0
make download-models  # downloads latest
```

The `.pt` files are **not committed to git** (listed in `.gitignore`). They travel through GitHub Releases as binary assets. Cloud Build downloads them before building the Docker image.

## Training Configs

| Config | File | Description |
|--------|------|-------------|
| Seller | `config/single_agent_seller.ini` | 1 AI seller vs 3 scripted buyers |
| Buyer | `config/single_agent_buyer.ini` | 1 AI buyer vs 3 scripted sellers |
| Bilateral | `config/bilateral.ini` | Both AI seller and buyer (experimental) |

All configs use sweep-tuned PPO hyperparameters from upstream ArkhaiPufferEnv. If training is unstable, alternate hyperparameters are commented in the config files.

## GPU Node Type Configuration

The RL environment models a compute marketplace with configurable GPU node types. Each node type occupies a **slot** in the observation vector, contributing 3 dimensions: cluster total nodes, cluster free nodes, and request nodes.

```
obs_dim = 12 + 3 * ARKHAI_NODE_TYPES
```

### Default slot mapping (3 node types, obs_dim=21)

| Slot | GPU Model | Env Value |
|------|-----------|-----------|
| 0 | H200 | `H200` |
| 1 | Tesla V100 | `Tesla V100` |
| 2 | RTX 5080 | `RTX 5080` |

### Customizing the slot map

Set these environment variables (or add to `.env`):

```bash
# Number of GPU node types
ARKHAI_NODE_TYPES=4

# Comma-separated GPU_NAME:SLOT pairs
ARKHAI_GPU_SLOT_MAP="H200:0, Tesla V100:1, RTX 5080:2, A100:3"

# Per-slot job GPU node counts (comma-separated, one per slot)
ARKHAI_JOB_GPU_NODES="10,10,10,10"

# Or set individually per slot
ARKHAI_JOB_GPU_0_NODES=10
ARKHAI_JOB_GPU_1_NODES=10
ARKHAI_JOB_GPU_2_NODES=10
ARKHAI_JOB_GPU_3_NODES=10
```

GPU names in `ARKHAI_GPU_SLOT_MAP` must match the `GPUModel` enum values in `app/schema/pydantic_models.py`. Slot indices must be in `[0, ARKHAI_NODE_TYPES)`. When the env var is unset, the default 3-slot mapping above is used.

Training configs in `config/` set per-slot cluster capacities (`cluster_gpu_N_capacity`) and job sizes (`job_gpu_N_nodes`). These must be consistent with the slot map.

See `agent/.env.sample` for a complete reference of all configurable variables.

## Policy Integration

The trained models are loaded by the policy adapters at runtime:

- `domains/vms/negotiation/rl/torch_arkhai_strategy.py` loads `arkhai_seller.pt`
- `domains/vms/negotiation/rl/torch_arkhai_strategy.py` loads `arkhai_buyer.pt`
- Override paths via env vars: `ARKHAI_SELLER_MODEL_PATH`, `ARKHAI_BUYER_MODEL_PATH`

The policy manager chains: RL seller -> RL buyer -> rule-based accept. Each RL policy returns `None` when its `.pt` file is absent, falling through gracefully.

## Notes

1. If training fails with `batch_size`/`minibatch_size` errors, pass compatible values in `ARGS`.
2. If `total_timesteps` is too small relative to batch size, training may fail with a division error. Use at least 1M steps.
3. Keep dependency pinning immutable in `pyproject.toml` and sync `uv.lock`.
4. If upstream env keys change, update local Makefile/test config to match upstream key names.
5. `pyproject.toml` uses `pytorch-cu128` on Linux and `pytorch-cpu` on macOS.
