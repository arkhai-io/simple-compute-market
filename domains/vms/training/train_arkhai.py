"""Training script for Arkhai negotiation models (single-agent mode).

Trains a seller RL agent against a scripted buyer using the ArkhaiPufferEnv
via pufferlib 3.0's pufferl API.

Checkpoints land in experiments/ by default. After training, the script
copies the final checkpoint to:
  negotiation/rl/models/arkhai_negotiator_seller.pt
  negotiation/rl/models/arkhai_negotiator_buyer.pt

Usage (from domains/vms/):
    # Short smoke-test (CPU / MPS):
    uv run python training/train_arkhai.py --total-timesteps 50000

    # Full run:
    uv run python training/train_arkhai.py

    # GPU override:
    uv run python training/train_arkhai.py --device cuda --total-timesteps 10000000

Equivalent puffer CLI (no checkpoint rename):
    python -m pufferlib.pufferl train puffer_arkhai \\
        --env.request-timeout 10 \\
        --train.total-timesteps 10000000 \\
        --train.device cpu
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train Arkhai negotiation model in single-agent mode (pufferlib 3.0)"
    )
    parser.add_argument(
        "--total-timesteps",
        type=int,
        default=10_000_000,
        help="Training steps (default: 10M)",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=200,
        help="Save checkpoint every N epochs (default: 200)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Torch device: cuda | mps | cpu (auto-detected if not set)",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=str,
        default="negotiation/rl/models/",
        help="Where to copy final checkpoints",
    )
    parser.add_argument(
        "--num-envs",
        type=int,
        default=None,
        help="Number of vec envs (default: from puffer arkhai config)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to .ini config file to layer over pufferlib defaults.",
    )
    parser.add_argument(
        "--wandb",
        action="store_true",
        default=False,
        help="Enable Weights & Biases logging.",
    )
    parser.add_argument(
        "--wandb-project",
        type=str,
        default="arkhai-negotiation",
        help="W&B project name (default: arkhai-negotiation).",
    )
    parser.add_argument(
        "--wandb-group",
        type=str,
        default="single-agent",
        help="W&B run group (default: single-agent).",
    )
    return parser.parse_args()


def detect_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def main() -> None:
    args = parse_args()

    try:
        from pufferlib.pufferl import load_config, train
    except ImportError as exc:
        print(f"[train_arkhai] Failed to import pufferlib.pufferl: {exc}", file=sys.stderr)
        sys.exit(1)

    # load_config calls argparse.parse_args() internally and would trip on our
    # own flags. Temporarily clear sys.argv to let it read only its own args.
    saved_argv = sys.argv[:]
    sys.argv = sys.argv[:1]
    try:
        puffer_args = load_config("puffer_arkhai")
    finally:
        sys.argv = saved_argv
    
    # Layer our .ini on top of pufferlib package defaults
    if args.config:
        import configparser
        ini = configparser.ConfigParser()
        ini.read(args.config)
        for section in ("env", "vec"):
            if ini.has_section(section):
                for key, raw in ini.items(section):
                    val: Any = raw
                    try:
                        val = int(raw)
                    except ValueError:
                        try:
                            val = float(raw)
                        except ValueError:
                            pass
                    puffer_args.setdefault(section, {})[key] = val

    # Single-agent mode: ai_sellers=1, scripted_buyers=1 (ini defaults).
    # Bilateral (ai_buyers=1) is intentionally disabled: pufferlib's C env
    # assigns each game one observation slot but bilateral writes 2 rows per
    # game, causing buyer obs to corrupt adjacent slots and an OOB write on
    # game 1023. Fixing this requires recompiling pufferlib's env_binding.h.
    # The shared checkpoint serves both seller and buyer roles at inference.

    # Match negotiation guard max_rounds
    puffer_args["env"]["request_timeout"] = 10

    # Serial backend required for bilateral (multiprocessing hangs with 2 AI agents)
    puffer_args["vec"]["backend"] = "Serial"
    puffer_args["vec"]["num_envs"] = 1

    if args.num_envs is not None:
        puffer_args["env"]["num_envs"] = args.num_envs

    device = args.device or detect_device()
    # On macOS, wandb spawns threads that corrupt the MPS autorelease pool.
    # Fall back to CPU automatically when --wandb is requested on MPS.
    if args.wandb and device == "mps":
        import platform
        if platform.system() == "Darwin":
            print("[train_arkhai] WARNING: wandb + MPS causes autorelease pool corruption on macOS. Falling back to cpu.")
            device = "cpu"
    puffer_args["train"]["device"] = device
    puffer_args["train"]["total_timesteps"] = args.total_timesteps
    puffer_args["train"]["checkpoint_interval"] = args.checkpoint_interval

    # Compute effective batch_size = num_envs * bptt_horizon.
    # total_timesteps must be >= batch_size (otherwise total_epochs=0 → ZeroDivisionError).
    # Also cap minibatch_size so it never exceeds batch_size.
    num_env_total = puffer_args["env"].get("num_envs", 1024)
    bptt = puffer_args["train"].get("bptt_horizon", 64)
    if bptt == "auto":
        bptt = 64
    effective_batch = num_env_total * bptt
    min_timesteps = effective_batch * 2
    if puffer_args["train"]["total_timesteps"] < min_timesteps:
        print(
            f"[train_arkhai] WARNING: total_timesteps {puffer_args['train']['total_timesteps']} "
            f"< 2×batch_size ({min_timesteps}). Raising to {min_timesteps}."
        )
        puffer_args["train"]["total_timesteps"] = min_timesteps
    if puffer_args["train"].get("minibatch_size", 8192) > effective_batch:
        puffer_args["train"]["minibatch_size"] = max(256, effective_batch // 4)

    # wandb flags live at the top level of puffer_args (not under "train")
    puffer_args["wandb"] = args.wandb
    puffer_args["wandb_project"] = args.wandb_project
    puffer_args["wandb_group"] = args.wandb_group

    print(f"[train_arkhai] device={device}")
    print(f"[train_arkhai] total_timesteps={args.total_timesteps:,}")
    print(f"[train_arkhai] single-agent: ai_sellers=1 scripted_buyers=1")
    if args.wandb:
        print(f"[train_arkhai] wandb: project={args.wandb_project} group={args.wandb_group}")
    print(f"[train_arkhai] Checkpoints → experiments/ (will copy to {args.checkpoint_dir})")

    train("puffer_arkhai", args=puffer_args)

    _copy_checkpoints(args.checkpoint_dir)

    # Force clean exit — wandb's atexit handlers can raise after training
    # completes, producing a non-zero exit code that propagates to the CLI.
    os._exit(0)


def _copy_checkpoints(dest_dir: str) -> None:
    """Copy the most recent pufferlib checkpoint to our canonical model paths."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # pufferlib saves to experiments/puffer_arkhai_<run_id>.pt or
    # experiments/model_puffer_arkhai_<epoch>.pt depending on version.
    candidates = sorted(
        glob.glob("experiments/puffer_arkhai*.pt") +
        glob.glob("experiments/model_puffer_arkhai*.pt"),
        key=os.path.getctime,
    )
    if not candidates:
        print("[train_arkhai] No checkpoint found in experiments/ — nothing copied.")
        return

    latest = candidates[-1]
    # Single shared checkpoint (puffer doesn't split seller/buyer in bilateral mode —
    # the policy learns to play both sides). Copy to seller path; symlink buyer.
    seller_dst = dest / "arkhai_negotiator_seller.pt"
    buyer_dst = dest / "arkhai_negotiator_buyer.pt"
    shutil.copy2(latest, seller_dst)
    shutil.copy2(latest, buyer_dst)
    print(f"[train_arkhai] Copied {latest} → {seller_dst}")
    print(f"[train_arkhai] Copied {latest} → {buyer_dst}")


if __name__ == "__main__":
    main()
