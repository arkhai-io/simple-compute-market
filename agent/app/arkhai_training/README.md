# Arkhai Training (Library-First)

This project uses `ArkhaiPufferEnv` via `pufferlib` directly.

## Source of Truth

- Environment and training contracts come from upstream `pufferlib`.
- Local scripts in this folder are intentionally minimal.
- Training and evaluation should run through `puffer` CLI commands.

## Recommended Commands

Run from `/agent`:

```bash
# Train with defaults
make train-arkhai

# Train with explicit controls
make train-arkhai DEVICE=cpu TOTAL_TIMESTEPS=1000000 ARGS="--vec.num-envs 1 --env.num-envs 64 --train.batch-size 16384 --train.minibatch-size 2048"

# Evaluate latest checkpoint
make eval-arkhai

# Evaluate specific checkpoint
make eval-arkhai MODEL=experiments/puffer_arkhai_*/model_puffer_arkhai_000001.pt

# Export puffer-native weights binary
make export-arkhai-weights MODEL=latest

# Environment smoke test
make test-arkhai-env
```

## Notes

1. If training fails with `batch_size`/`minibatch_size` errors, pass compatible values in `ARGS`.
2. Keep dependency pinning immutable in `pyproject.toml` and sync `uv.lock`.
3. If upstream env keys change, update local Makefile/test config to match upstream key names.

## Deprecated Local Workflow

The previous custom scripts `eval.py` and `export_model.py` were removed in favor of library-native `puffer eval` and `puffer export`.
