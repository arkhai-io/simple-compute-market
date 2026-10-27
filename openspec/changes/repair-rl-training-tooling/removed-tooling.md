# Removed training tooling

What `resolve-compute-family-findings` removes, copied verbatim from `dev` at `421eeac`
so this change's design starts from the code. Kept as Markdown so no tool that walks the
tree for projects or tests picks it up.

## `kit/policy/src/market_policy/cli.py` (deleted)

````python
"""`market-policy` — RL negotiation policy lifecycle: train, eval, export.

The policy package is what produces strategy artifacts that buyers
(`market`) and sellers (`market-storefront`) load at runtime. Training
and eval are tooling concerns separate from either runtime, so they
live here as their own console script. Run `market-policy --help`.

Implementation note: train/eval delegate to the legacy training
scripts under `domains/vms/training/`. The cwd is the repo root so
puffer's `experiments/` checkpoint dir lands at a stable path
regardless of which package the user is in.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Optional

import typer


# parents[3]: market_policy → src → policy → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

_TRAINING_DIR = REPO_ROOT / "domains" / "vms" / "training"
_TRAIN_SCRIPT = _TRAINING_DIR / "train_arkhai.py"
_EVAL_SCRIPT = _TRAINING_DIR / "eval_arkhai.py"
_CONFIG_DIR = _TRAINING_DIR / "config"
_DEFAULT_MODELS_DIR = (
    REPO_ROOT / "domains" / "vms" / "agent" / "app" / "policy" / "models"
)

_ROLE_CONFIG = {
    "seller": _CONFIG_DIR / "single_agent_seller.ini",
    "buyer": _CONFIG_DIR / "single_agent_buyer.ini",
}


app = typer.Typer(no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        try:
            v = version("arkhai-kit-policy")
        except PackageNotFoundError:
            v = "unknown (not installed)"
        typer.echo(f"market-policy version {v}")
        raise typer.Exit()


@app.callback()
def main(
    version_flag: bool = typer.Option(
        None, "--version", "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """market-policy — train, evaluate, and export Arkhai negotiation models."""
    pass


def _run(label: str, cmd: list[str], cwd: Path) -> None:
    typer.echo(f"==> {label} at {cwd}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


@app.command("train")
def policy_train(
    total_timesteps: int = typer.Option(
        10_000_000, "--total-timesteps", "-t",
        help="Number of environment steps to train for.",
    ),
    device: Optional[str] = typer.Option(
        None, "--device", "-d",
        help="Torch device: cuda | mps | cpu (auto-detected if not set).",
    ),
    checkpoint_dir: str = typer.Option(
        str(_DEFAULT_MODELS_DIR), "--checkpoint-dir", "-c",
        help="Directory to copy final checkpoints into.",
    ),
    checkpoint_interval: int = typer.Option(
        200, "--checkpoint-interval",
        help="Save intermediate checkpoint every N epochs.",
    ),
    wandb: bool = typer.Option(
        False, "--wandb",
        help="Enable Weights & Biases logging.",
    ),
    wandb_project: str = typer.Option(
        "arkhai-negotiation", "--wandb-project",
        help="W&B project name.",
    ),
    wandb_group: str = typer.Option(
        "bilateral", "--wandb-group",
        help="W&B run group.",
    ),
    config: Optional[str] = typer.Option(
        None, "--config",
        help="Path to .ini config file. Defaults to bilateral.ini.",
    ),
) -> None:
    """Train bilateral Arkhai negotiation models (seller + buyer).

    Uses pufferlib's bilateral ArkhaiPufferEnv. Both agents learn
    simultaneously. Checkpoints land in `experiments/` (relative to cwd
    = repo root) and are then copied to --checkpoint-dir as:
      arkhai_negotiator_seller.pt
      arkhai_negotiator_buyer.pt

    Requires the training dependency group installed (pufferlib, torch).
    Install with ``uv sync --group training`` from the ``kit/policy/``
    directory. The storefront / buyer ``[rl]`` extras are inference-only
    and don't include pufferlib.
    """
    config_path = Path(config).resolve() if config else _CONFIG_DIR / "bilateral.ini"

    cmd = [
        "python", str(_TRAIN_SCRIPT),
        "--total-timesteps", str(total_timesteps),
        "--checkpoint-dir", str(checkpoint_dir),
        "--checkpoint-interval", str(checkpoint_interval),
    ]
    if device:
        cmd += ["--device", device]
    if wandb:
        cmd += ["--wandb", "--wandb-project", wandb_project, "--wandb-group", wandb_group]
    if config_path.exists():
        cmd += ["--config", str(config_path)]

    _run(
        f"Train bilateral Arkhai negotiation models ({total_timesteps:,} steps)",
        cmd,
        REPO_ROOT,
    )


@app.command("eval")
def policy_eval(
    checkpoint: Optional[str] = typer.Option(
        None, "--checkpoint", "-k",
        help="Absolute path to .pt checkpoint. If omitted, resolved from --role.",
    ),
    role: str = typer.Option(
        "seller", "--role", "-r",
        help="Which model to evaluate: seller or buyer.",
    ),
    episodes: int = typer.Option(
        10, "--episodes", "-n",
        help="Number of episodes to evaluate.",
    ),
    device: Optional[str] = typer.Option(
        None, "--device", "-d",
        help="Torch device: cuda | mps | cpu (auto-detected if not set).",
    ),
    config: Optional[str] = typer.Option(
        None, "--config",
        help="Path to .ini config file. Defaults to role-matched ini.",
    ),
) -> None:
    """Run a trained Arkhai checkpoint for N episodes and print metrics.

    Reports per-episode and aggregate: score, profit, expense,
    episode_length.

    Examples:
      market-policy eval                        # seller, 10 episodes
      market-policy eval --role buyer -n 20     # buyer, 20 episodes
    """
    if checkpoint:
        ckpt = str(Path(checkpoint).resolve())
    else:
        ckpt = str(_DEFAULT_MODELS_DIR / f"arkhai_negotiator_{role}.pt")

    config_path = Path(config).resolve() if config else _ROLE_CONFIG.get(role)

    cmd = [
        "python", str(_EVAL_SCRIPT),
        "--checkpoint", ckpt,
        "--episodes", str(episodes),
    ]
    if device:
        cmd += ["--device", device]
    if config_path and config_path.exists():
        cmd += ["--config", str(config_path)]

    _run(f"Evaluate Arkhai policy ({episodes} episodes)", cmd, REPO_ROOT)


@app.command("export")
def policy_export(
    src: Optional[str] = typer.Option(
        None, "--src", "-s",
        help="Source .pt checkpoint. Defaults to the most recent file in experiments/.",
    ),
    dest_dir: str = typer.Option(
        str(_DEFAULT_MODELS_DIR), "--dest-dir", "-o",
        help="Destination directory for renamed checkpoints.",
    ),
    seller_name: str = typer.Option(
        "arkhai_negotiator_seller.pt", "--seller-name",
        help="Filename for the seller checkpoint.",
    ),
    buyer_name: str = typer.Option(
        "arkhai_negotiator_buyer.pt", "--buyer-name",
        help="Filename for the buyer checkpoint.",
    ),
) -> None:
    """Copy the latest trained checkpoint to the runtime models directory.

    pufferlib's bilateral training produces a single shared policy
    artifact; export copies it to both seller and buyer paths so the
    runtime can load them independently.
    """
    experiments_dir = REPO_ROOT / "experiments"
    dest = Path(dest_dir)

    if src:
        source = Path(src)
        if not source.exists():
            typer.echo(f"Error: checkpoint not found: {source}", err=True)
            raise typer.Exit(1)
    else:
        candidates = sorted(
            glob.glob(str(experiments_dir / "puffer_arkhai*.pt"))
            + glob.glob(str(experiments_dir / "model_puffer_arkhai*.pt")),
            key=os.path.getctime,
        )
        if not candidates:
            typer.echo(
                f"Error: no checkpoints found in {experiments_dir}. "
                "Run 'market-policy train' first.",
                err=True,
            )
            raise typer.Exit(1)
        source = Path(candidates[-1])
        typer.echo(f"Using latest checkpoint: {source.name}")

    dest.mkdir(parents=True, exist_ok=True)
    for name in (seller_name, buyer_name):
        dst = dest / name
        shutil.copy2(source, dst)
        typer.echo(f"  {source.name} -> {dst}")

    typer.echo(f"Exported to {dest}")
    typer.echo("")
    typer.echo("To publish a GitHub release:")
    typer.echo(
        f"  gh release create model-vX.Y.Z "
        f"{dest / seller_name} {dest / buyer_name} "
        f'--title "Model vX.Y.Z" --notes "Bilateral run"'
    )


if __name__ == "__main__":
    app()
````

## `kit/policy/pyproject.toml` (sections removed)

The description's CLI clause, the console script, the `[tool.uv]` settings, and the
`training` dependency group:

````toml
description = "Domain-agnostic policy engine for the market — negotiation thread store, action builders, callable registry, and policy evaluation. Ships with the `market-policy` CLI for the train/eval/export lifecycle."

[project.scripts]
market-policy = "market_policy.cli:app"

[tool.uv]
# pufferlib 3.0 ships only as a source tarball whose ``setup.py`` runs
# its own Cython + numpy import path; uv's PEP 517 build isolation
# strips those out and the build fails.
no-build-isolation-package = ["pufferlib"]

[tool.uv.extra-build-dependencies]
# pufferlib 3.0 ``setup.py`` imports numpy + Cython at build time.
# Pinned to numpy<2 because its C env was compiled against the 1.x ABI.
pufferlib = ["setuptools", "Cython", "numpy<2"]

[tool.uv.sources]
# Pin torch to the CPU index so installs don't hit the multi-GB CUDA
# wheels on hosts that don't have an NVIDIA GPU. Trainers with a GPU
# can override this in their own venv.
torch = [
    { index = "pytorch-cpu" },
]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

# Retrain Arkhai negotiation models from scratch via ``market-policy
# train`` / ``market-policy eval``. This is a dev dependency group, not a
# published extra: PyPI rejects the ``pufferlib @ git+...`` direct
# reference in wheel metadata, so it lives here and is installed locally
# with ``uv sync --group training`` (or ``pip install --group training``).
# Pulls in pufferlib's C-backed bilateral env + trainer plus torch.
# Inference at the storefront / buyer needs only ``torch>=2.7.0`` (see
# their ``[rl]`` extras) — the trained ``.pt`` files load into a small
# inline ``ArkhaiInferencePolicy`` without pufferlib at runtime.
#
# Caveats for whoever installs this:
#   * pufferlib 3.0's C env compiles against the numpy<2 ABI, so the
#     resolved Python must be 3.12 (it won't build on 3.13). Use a
#     dedicated training venv with ``uv python pin 3.12``.
#   * The build wants Cython + numpy<2 as build-time deps and disables
#     build isolation for pufferlib — see ``[tool.uv]`` above.
#   * On macOS with a uv-managed Python, ``setup.py``'s leaked
#     ``-isysroot`` / ``-LModules/_hacl`` flags can break the linker.
#     Workaround: override the sysroot at install time, e.g.::
#
#         LDCXXSHARED="clang++ -bundle -undefined dynamic_lookup \
#             -arch arm64 -mmacosx-version-min=11.0 \
#             -isysroot $(xcrun --sdk macosx --show-sdk-path)" \
#         uv sync --group training
training = [
    "torch>=2.7.0",
    "pufferlib @ git+https://github.com/arkhai-io/ArkhaiPufferEnv@f18e3b42c0ae22e8aec5e8d26a26f424e6b18a30",
]
````

## `docs/development/RELEASING.md` (the console-script example)

````markdown
Distribution names are prefixed `arkhai-`. PyPI does not namespace
distribution names by organization, so the prefix is the project's
namespace. Import names and console scripts (`market`,
`market-storefront`, `market-policy`) are independent of the
distribution name.
````

## `domains/vms/training/README.md` (rewritten to what exists)

````markdown
# Arkhai Training (Library-First)

This project uses `ArkhaiPufferEnv` via `pufferlib` directly. Training produces `.pt` checkpoint files that are released as GitHub Release assets and downloaded at deployment time.

Training pulls in pufferlib's C-backed env + trainer (heavy build, Python 3.12 only). **Inference does not** — the storefront and buyer load the trained `.pt` files into a small inline `ArkhaiInferencePolicy` (see `domains/vms/negotiation/src/arkhai_vms_negotiation/rl/arkhai_common.py`) with just `torch` as a dep. The two paths are explicitly separate — training in a dev dependency group, inference in an `[rl]` extra — so a seller / buyer install doesn't drag in pufferlib. (Training is a dependency group rather than a published extra because its `pufferlib @ git+…` direct reference can't go in PyPI wheel metadata.)

## Install

```bash
# Training (this folder + market-policy train/eval CLI)
cd kit/policy && uv sync --group training

# Inference only (storefront / buyer at runtime)
cd domains/vms/storefront && uv pip install -e ".[rl]"   # torch only, no pufferlib
cd domains/vms/buyer && uv pip install -e ".[rl]"
```

On macOS with uv-managed Python the pufferlib C extension build can pick up stale Xcode SDK paths from the Python sysconfig. If linking fails with `library 'c++' not found` or references to a non-existent `Xcode_15.2.app`, override the sysroot:

```bash
LDCXXSHARED="clang++ -bundle -undefined dynamic_lookup -arch arm64 \
    -mmacosx-version-min=11.0 -isysroot $(xcrun --sdk macosx --show-sdk-path)" \
  uv sync --group training
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
cp experiments/puffer_arkhai_<run_id>.pt domains/vms/negotiation/src/arkhai_vms_negotiation/rl/models/arkhai_seller.pt
cp experiments/puffer_arkhai_<run_id>.pt domains/vms/negotiation/src/arkhai_vms_negotiation/rl/models/arkhai_buyer.pt

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

- `domains/vms/negotiation/src/arkhai_vms_negotiation/rl/torch_arkhai_strategy.py` loads `arkhai_seller.pt`
- `domains/vms/negotiation/src/arkhai_vms_negotiation/rl/torch_arkhai_strategy.py` loads `arkhai_buyer.pt`
- Override paths via env vars: `ARKHAI_SELLER_MODEL_PATH`, `ARKHAI_BUYER_MODEL_PATH`

The policy manager chains: RL seller -> RL buyer -> rule-based accept. Each RL policy returns `None` when its `.pt` file is absent, falling through gracefully.

## Notes

1. If training fails with `batch_size`/`minibatch_size` errors, pass compatible values in `ARGS`.
2. If `total_timesteps` is too small relative to batch size, training may fail with a division error. Use at least 1M steps.
3. Keep dependency pinning immutable in `pyproject.toml` and sync `uv.lock`.
4. If upstream env keys change, update local Makefile/test config to match upstream key names.
5. `pyproject.toml` uses `pytorch-cu128` on Linux and `pytorch-cpu` on macOS.
````
