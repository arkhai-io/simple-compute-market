"""market policy — CLI commands for Arkhai RL policy lifecycle.

Subcommands:
  train   Train bilateral seller+buyer negotiation models.
  eval    Run a trained checkpoint for N episodes and print metrics.
  export  Copy the latest checkpoint from experiments/ to the runtime models dir.
"""
from __future__ import annotations

import glob
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer

from ..common import REPO_ROOT, run_step

policy_app = typer.Typer(no_args_is_help=True)

# Directories relative to repo root
_CORE_DIR = REPO_ROOT / "core"
_MODELS_DIR = REPO_ROOT / "domain" / "compute" / "agent" / "app" / "policy" / "models"
_TRAIN_SCRIPT = Path("..") / "domain" / "compute" / "training" / "train_arkhai.py"
_EVAL_SCRIPT = Path("..") / "domain" / "compute" / "training" / "eval_arkhai.py"


@policy_app.command("train")
def policy_train(
    total_timesteps: int = typer.Option(
        10_000_000,
        "--total-timesteps",
        "-t",
        help="Number of environment steps to train for.",
    ),
    device: Optional[str] = typer.Option(
        None,
        "--device",
        "-d",
        help="Torch device: cuda | mps | cpu (auto-detected if not set).",
    ),
    checkpoint_dir: str = typer.Option(
        str(_MODELS_DIR),
        "--checkpoint-dir",
        "-c",
        help="Directory to copy final checkpoints into.",
    ),
    checkpoint_interval: int = typer.Option(
        200,
        "--checkpoint-interval",
        help="Save intermediate checkpoint every N epochs.",
    ),
    wandb: bool = typer.Option(
        False,
        "--wandb",
        help="Enable Weights & Biases logging.",
    ),
    wandb_project: str = typer.Option(
        "arkhai-negotiation",
        "--wandb-project",
        help="W&B project name.",
    ),
    wandb_group: str = typer.Option(
        "bilateral",
        "--wandb-group",
        help="W&B run group.",
    ),
) -> None:
    """Train bilateral Arkhai negotiation models (seller + buyer).

    Uses pufferlib's bilateral ArkhaiPufferEnv. Both agents learn simultaneously.
    Checkpoints land in experiments/ and are then copied to --checkpoint-dir as:
      arkhai_negotiator_seller.pt
      arkhai_negotiator_buyer.pt

    Requires the core venv (pufferlib installed there):
      cd core && uv sync --dev
    """
    cmd = [
        "python",
        str(_TRAIN_SCRIPT),
        "--total-timesteps", str(total_timesteps),
        "--checkpoint-dir", str(checkpoint_dir),
        "--checkpoint-interval", str(checkpoint_interval),
    ]
    if device:
        cmd += ["--device", device]
    if wandb:
        cmd += ["--wandb", "--wandb-project", wandb_project, "--wandb-group", wandb_group]

    run_step(
        f"Train bilateral Arkhai negotiation models ({total_timesteps:,} steps)",
        cmd,
        _CORE_DIR,
    )


_CONFIG_DIR = REPO_ROOT / "domain" / "compute" / "training" / "config"
_ROLE_CONFIG = {
    "seller": _CONFIG_DIR / "single_agent_seller.ini",
    "buyer":  _CONFIG_DIR / "single_agent_buyer.ini",
}


@policy_app.command("eval")
def policy_eval(
    checkpoint: Optional[str] = typer.Option(
        None,
        "--checkpoint",
        "-k",
        help="Absolute path to .pt checkpoint. If omitted, resolved from --role.",
    ),
    role: str = typer.Option(
        "seller",
        "--role",
        "-r",
        help="Which model to evaluate: seller or buyer.",
    ),
    episodes: int = typer.Option(
        10,
        "--episodes",
        "-n",
        help="Number of episodes to evaluate.",
    ),
    device: Optional[str] = typer.Option(
        None,
        "--device",
        "-d",
        help="Torch device: cuda | mps | cpu (auto-detected if not set).",
    ),
    config: Optional[str] = typer.Option(
        None,
        "--config",
        help="Path to .ini config file. Defaults to role-matched ini in domain/compute/training/config/.",
    ),
) -> None:
    """Run a trained Arkhai checkpoint for N episodes and print metrics.

    Reports per-episode and aggregate: score, profit, expense, episode_length.

    Examples:
      market policy eval                        # seller, 10 episodes
      market policy eval --role buyer -n 20     # buyer, 20 episodes
    """
    if checkpoint:
        ckpt = str(Path(checkpoint).resolve())
    else:
        filename = f"arkhai_negotiator_{role}.pt"
        ckpt = str(_MODELS_DIR / filename)

    config_path = Path(config).resolve() if config else _ROLE_CONFIG.get(role)

    cmd = [
        "python",
        str(_EVAL_SCRIPT),
        "--checkpoint", ckpt,
        "--episodes", str(episodes),
    ]
    if device:
        cmd += ["--device", device]
    if config_path and config_path.exists():
        cmd += ["--config", str(config_path)]

    run_step(
        f"Evaluate Arkhai policy ({episodes} episodes)",
        cmd,
        _CORE_DIR,
    )


@policy_app.command("export")
def policy_export(
    src: Optional[str] = typer.Option(
        None,
        "--src",
        "-s",
        help="Source .pt checkpoint. Defaults to the most recent file in experiments/.",
    ),
    dest_dir: str = typer.Option(
        str(_MODELS_DIR),
        "--dest-dir",
        "-o",
        help="Destination directory for renamed checkpoints.",
    ),
    seller_name: str = typer.Option(
        "arkhai_negotiator_seller.pt",
        "--seller-name",
        help="Filename for the seller checkpoint.",
    ),
    buyer_name: str = typer.Option(
        "arkhai_negotiator_buyer.pt",
        "--buyer-name",
        help="Filename for the buyer checkpoint.",
    ),
) -> None:
    """Copy the latest trained checkpoint to the runtime models directory.

    pufferlib's bilateral training produces a single shared policy (not split
    per-agent). export copies it to both seller and buyer paths so the runtime
    can load them independently via ARKHAI_NEGOTIATOR_{SELLER,BUYER}_MODEL_PATH.

    To publish a release after exporting:
      gh release create model-vX.Y.Z \\
        <dest-dir>/arkhai_negotiator_seller.pt \\
        <dest-dir>/arkhai_negotiator_buyer.pt \\
        --title "Model vX.Y.Z" --notes "Bilateral run, 10M steps"
    """
    experiments_dir = _CORE_DIR / "experiments"
    dest = Path(dest_dir)

    # Resolve source checkpoint
    if src:
        source = Path(src)
        if not source.exists():
            typer.echo(f"Error: checkpoint not found: {source}", err=True)
            raise typer.Exit(1)
    else:
        candidates = sorted(
            glob.glob(str(experiments_dir / "puffer_arkhai*.pt")),
            key=os.path.getctime,
        )
        if not candidates:
            typer.echo(
                f"Error: no checkpoints found in {experiments_dir}. "
                "Run 'market policy train' first.",
                err=True,
            )
            raise typer.Exit(1)
        source = Path(candidates[-1])
        typer.echo(f"Using latest checkpoint: {source.name}")

    dest.mkdir(parents=True, exist_ok=True)

    for name in (seller_name, buyer_name):
        dst = dest / name
        shutil.copy2(source, dst)
        typer.echo(f"  {source.name} → {dst}")

    typer.echo(f"Exported to {dest}")
    typer.echo("")
    typer.echo("To publish a GitHub release:")
    typer.echo(
        f"  gh release create model-vX.Y.Z "
        f"{dest / seller_name} {dest / buyer_name} "
        f'--title "Model vX.Y.Z" --notes "Bilateral run"'
    )
