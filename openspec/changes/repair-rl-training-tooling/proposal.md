## Why

The VM negotiation models' training tooling is derelict. `resolve-compute-family-findings`
(its design's decision D7, 2026-10-27) removes the broken parts from where they do harm,
and this change exists so that removal is not the end of them: it carries what was
removed, verbatim, in `removed-tooling.md`, and repairs the tooling into something that
runs.

What that change found:

- `kit/policy`, a published, domain-agnostic foundation kit, shipped the `market-policy`
  console script (`market_policy/cli.py`): `train` and `eval` run
  `domains/vms/training/train_arkhai.py` and `eval_arkhai.py` as subprocesses, and
  `export` copies a checkpoint into a models directory. It could not run.
  `REPO_ROOT = Path(__file__).resolve().parents[3]` resolved to `kit/`, so every script
  path pointed under `kit/domains/…`; its default models directory,
  `domains/vms/agent/app/policy/models`, does not exist (the models live under
  `domains/vms/negotiation/src/arkhai_vms_negotiation/rl/models/`); and installed from a
  wheel, no repository path resolves. Nothing in a Makefile, CI, or image called it.
- `kit/policy`'s `pyproject.toml` carried the training environment: a `training`
  dependency group (torch, and pufferlib from a Git reference PyPI metadata cannot carry)
  and the `[tool.uv]` build settings and CPU torch index pufferlib needs.
- `domains/vms/training/` is two argparse scripts and three `.ini` configurations, with
  no `pyproject.toml`; its README describes an `agent/` directory, `make train-arkhai`
  targets, and configuration paths that no longer exist.

Inference is unaffected: the `rl` strategy in `domains/vms/negotiation` loads released
`.pt` files with torch alone, through the storefront's and buyer's `[rl]` extras.

## What Changes

Proposed; design not started. Expected direction: training becomes a runnable,
unpublished tooling project at `domains/vms/training`, with its own environment carrying
the training dependencies and pufferlib's build settings, entry points or commands whose
paths resolve from the project's own location, a README that describes what exists, and
proof that training and evaluation each run once. The design decides:

- the project's shape and its place among the tooling projects `ARCHITECTURE.toml` skips;
- what `domains/vms/negotiation/src/arkhai_vms_negotiation/rl/policy-making.md` says, since
  it still documents `market policy train` and `market policy eval`, which no longer
  exist;
- whether `market-policy`'s three commands return, over the scripts, or the scripts'
  own arguments suffice;
- how pufferlib's Python 3.12 constraint and native build are met, and whether any CI job
  builds the environment;
- where trained models are released and how the inference packages find them.

## Capabilities

### New Capabilities

None expected.

### Modified Capabilities

None expected. `.openspec.yaml` sets `skip_specs`.

## Non-Goals

- Inference, the `rl` negotiation strategy, and the `[rl]` extras.
- Publishing the training tooling.

## Dependencies and Related Changes

- Opened by `resolve-compute-family-findings`, which removes the material in
  `removed-tooling.md` from `kit/policy`, `RELEASING.md`, and the training README.
  Neither change depends on the other: if this one lands first, that one has nothing
  left to remove.

## Impact

`domains/vms/training/`, possibly a new tooling project there, and the documentation that
names it.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification
- [ ] New subsystem specification
- [x] No permanent documentation change expected beyond the training README and, if the
      project is placed among the skipped tooling, `docs/development/ARCHITECTURE.toml`

### Knowledge to promote

To be determined at design completion.
