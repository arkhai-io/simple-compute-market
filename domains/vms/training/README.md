# Arkhai negotiation training scripts

This directory holds the scripts and configurations that trained the RL negotiation
checkpoints the VM negotiation policy loads. It is not a project: it has no
`pyproject.toml`, `Makefile`, or lock, and no project in the repository installs
`pufferlib` with its `ArkhaiPufferEnv` C environment, or `gymnasium`, which the
scripts import beside `torch`. No Makefile, CI job, or image runs them.

## Contents

| Path | What it is |
|------|------------|
| `train_arkhai.py` | Trains through pufferlib's `pufferl` API, then copies the newest checkpoint from `experiments/` to `arkhai_negotiator_seller.pt` and `arkhai_negotiator_buyer.pt` under `--checkpoint-dir` |
| `eval_arkhai.py` | Runs a checkpoint for a number of episodes and prints score, profit, expense, and episode length |
| `config/single_agent_seller.ini` | One AI seller against scripted buyers |
| `config/single_agent_buyer.ini` | One AI buyer against scripted sellers |
| `config/bilateral.ini` | An AI seller and an AI buyer together |

Each script's `--help` lists its options. `--config` layers one of these `.ini` files'
`[env]` and `[vec]` sections over pufferlib's own defaults, so the file chooses which
agents train; without it, `train_arkhai.py` trains pufferlib's default for the
environment.

## Inference

Inference does not use pufferlib. The VM negotiation policy loads the committed
checkpoints in `domains/vms/negotiation/src/arkhai_vms_negotiation/rl/models/`
(`arkhai_negotiator_seller.pt` and `arkhai_negotiator_buyer.pt`) into the inline
`ArkhaiInferencePolicy` in
`domains/vms/negotiation/src/arkhai_vms_negotiation/rl/arkhai_common.py`, through
`torch_arkhai_strategy.py` beside it. `ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH` and
`ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH` override the paths. The VM storefront's and VM
buyer's `rl` extras install `torch` for it.

A checkpoint's observation size depends on how many GPU node types it was trained
with, so inference must be configured with the same layout. `arkhai_common.py` reads
it from the environment:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ARKHAI_NODE_TYPES` | `5` | Number of GPU node-type slots in the observation |
| `ARKHAI_GPU_SLOT_MAP` | `H200:0`, `Tesla V100:1`, `RTX 5080:2`, `RTX A5000:3`, `RTX 4090:4` | Comma-separated `GPU_NAME:SLOT` pairs; slots outside `[0, ARKHAI_NODE_TYPES)` are dropped |
| `ARKHAI_JOB_GPU_NODES` | `10` per slot | Comma-separated job node counts, one per slot; a short list repeats its last value |
| `ARKHAI_JOB_GPU_<n>_NODES` | `10` | One slot's job node count, read only when `ARKHAI_JOB_GPU_NODES` is unset |

`.github/workflows/validate-model-release.yml` loads a GitHub release's `.pt` assets and
runs a forward pass over each, when a `model-v*` tag is pushed or the workflow is
dispatched with a release tag.
