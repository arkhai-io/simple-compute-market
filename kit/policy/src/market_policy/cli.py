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

    Requires the training extras installed (pufferlib, torch). Install
    with ``uv pip install -e ".[training]"`` from the ``kit/policy/``
    directory (or ``market-policy[training]`` from a sibling). The
    storefront / buyer ``[rl]`` extras are inference-only and don't
    include pufferlib.
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
