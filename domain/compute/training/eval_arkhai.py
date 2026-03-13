"""Evaluate a trained Arkhai negotiation checkpoint for N episodes.

Runs the model in single-agent mode (seller vs scripted buyer, same config as training) and
reports aggregate stats: score, profit, expense, episode_length.

Model loading matches production inference: loads into pufferlib.models.Default
(no LSTM), stripping the 'policy.' prefix from Recurrent checkpoints. This
evaluates the base network — the same weights the runtime callable uses.

Usage (from core/):
    uv run python ../domain/compute/training/eval_arkhai.py \\
        --checkpoint ../domain/compute/agent/app/policy/models/arkhai_negotiator_seller.pt \\
        --episodes 20

Or via CLI:
    market policy eval --episodes 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Arkhai negotiation checkpoint")
    parser.add_argument("--checkpoint", required=True, help="Path to .pt checkpoint")
    parser.add_argument("--episodes", type=int, default=10, help="Episodes to evaluate (default: 10)")
    parser.add_argument("--device", type=str, default=None, help="Torch device (auto-detected if not set)")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to .ini config file (e.g. single_agent_seller.ini). Overrides pufferlib package defaults.",
    )
    return parser.parse_args()


def load_model(checkpoint: Path, obs_dim: int, device: str) -> "torch.nn.Module":
    """Load checkpoint into Default (no-LSTM) model — matches production inference."""
    import torch
    import gymnasium as gym
    import pufferlib.models

    class _EnvStub:
        def __init__(self, d: int) -> None:
            self.single_observation_space = gym.spaces.Box(0.0, 1.0, (d,), "float32")
            self.single_action_space = gym.spaces.MultiDiscrete([9, 2])
            self.observation_space = self.single_observation_space
            self.action_space = self.single_action_space

    model = pufferlib.models.Default(_EnvStub(obs_dim), hidden_size=128)
    raw = torch.load(str(checkpoint), map_location="cpu", weights_only=False)
    sd = raw if isinstance(raw, dict) else {}
    # Recurrent checkpoints wrap the base policy under 'policy.*'
    if any(k.startswith("policy.") for k in sd):
        sd = {k.removeprefix("policy."): v for k, v in sd.items() if k.startswith("policy.")}
    model.load_state_dict(sd, strict=False)
    model.eval()
    return model.to(device)


def main() -> None:
    args = parse_args()

    checkpoint = Path(args.checkpoint)
    if not checkpoint.exists():
        print(f"[eval_arkhai] Error: checkpoint not found: {checkpoint}", file=sys.stderr)
        sys.exit(1)

    try:
        import torch
        import numpy as np
        from pufferlib.pufferl import load_config, load_env
    except ImportError as exc:
        print(f"[eval_arkhai] Failed to import pufferlib: {exc}", file=sys.stderr)
        sys.exit(1)

    device = args.device or detect_device()

    # Load config (isolate sys.argv so pufferlib's argparser doesn't choke on ours)
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

    # node_types and obs_dim derived from merged config (ini wins over package default)
    node_types = int(puffer_args.get("env", {}).get("node_types", 5))
    obs_dim = 12 + 3 * node_types

    print(f"[eval_arkhai] checkpoint : {checkpoint.name}")
    print(f"[eval_arkhai] device     : {device}")
    print(f"[eval_arkhai] episodes   : {args.episodes}")
    print(f"[eval_arkhai] obs_dim    : {obs_dim}")

    model = load_model(checkpoint, obs_dim, device)

    # Apply single-agent eval settings — identical to training config
    puffer_args["env"]["node_types"] = node_types  # keep env in sync with obs_dim computed above
    puffer_args["env"]["request_timeout"] = 10
    puffer_args["env"]["num_envs"] = 1   # single env instance for clean eval
    puffer_args["vec"]["backend"] = "Serial"
    puffer_args["vec"]["num_envs"] = 1
    puffer_args["train"]["device"] = device

    env = load_env("puffer_arkhai", puffer_args)

    episode_length = int(puffer_args["env"].get("episode_length", 100))
    # Run enough steps to cover the requested episodes and trigger at least
    # one vec_log call (every 128 steps).
    total_steps = max(args.episodes * episode_length, 256)

    obs, _ = env.reset()
    # env.driver_env is the underlying Arkhai instance for direct step/log access

    all_logs: list[dict] = []
    for step in range(total_steps):
        obs_t = torch.as_tensor(obs, dtype=torch.float32).to(device)
        if obs_t.dim() == 1:
            obs_t = obs_t.unsqueeze(0)  # (1, obs_dim)

        with torch.no_grad():
            output = model(obs_t)

        # Decode MultiDiscrete action from model output
        logits = output[0]
        if isinstance(logits, (tuple, list)) and len(logits) >= 2:
            price_idx = int(torch.argmax(logits[0][0] if logits[0].dim() > 1 else logits[0]).item())
            sell_flag = int(torch.argmax(logits[1][0] if logits[1].dim() > 1 else logits[1]).item())
        elif isinstance(logits, torch.Tensor):
            flat = logits[0] if logits.dim() > 1 else logits
            price_idx = int(torch.argmax(flat[:9]).item())
            sell_flag = int(torch.argmax(flat[9:11]).item()) if flat.shape[-1] >= 11 else 0
        else:
            price_idx, sell_flag = 4, 0

        n_agents = env.num_agents
        action = np.array([[price_idx, sell_flag]] * n_agents, dtype=np.int32)
        obs, reward, terminated, truncated, info = env.step(action)

        if info:
            for log_entry in info:
                if isinstance(log_entry, dict) and "score" in log_entry:
                    n = int(log_entry.get("n", 0))
                    if n > 0:
                        all_logs.append(log_entry)
                        print(
                            f"  step {step+1:5d}  "
                            f"score={log_entry['score']:10.1f}  "
                            f"profit={log_entry.get('profit', 0):10.1f}  "
                            f"expense={log_entry.get('expense', 0):10.1f}  "
                            f"ep_len={log_entry.get('episode_length', 0):.0f}  "
                            f"n={n}"
                        )

    env.close()

    if not all_logs:
        print(
            "\n[eval_arkhai] No stats collected — try increasing --episodes "
            "(need enough steps for vec_log, min ~128 per env)."
        )
        return

    def _mean(key: str) -> float:
        vals = [d[key] for d in all_logs if key in d]
        return sum(vals) / len(vals) if vals else 0.0

    print("")
    print(f"── Summary ({len(all_logs)} log windows) ────────────────────────────")
    print(f"  score    : {_mean('score'):10.1f}")
    print(f"  profit   : {_mean('profit'):10.1f}")
    print(f"  expense  : {_mean('expense'):10.1f}")
    print(f"  ep_len   : {_mean('episode_length'):6.1f}")


if __name__ == "__main__":
    main()
