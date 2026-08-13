## Context

Internal packages are built into `.dist` and downstream tests/installations must exercise wheel metadata. Path sources remain in five newer consumable projects and some lack reinit targets. PyTorch index selectors are external dependency policy and are not violations.

## Goals / Non-Goals

**Goals:** wheel-only internal resolution, deterministic reinit, regression detection, accurate release guidance.

**Non-Goals:** dependency upgrades, external index removal, or publication.

## Decisions

- Classify a violation as an internal distribution resolved through a parent/sibling filesystem path in project or lock metadata.
- Build prerequisites in dependency order, then use `uv sync --find-links .dist --upgrade-package/--reinstall-package` for changed internal wheels.
- Add a repository check over consumable project metadata/locks; allow explicit non-path external indexes.
- Regenerate only the five affected locks and review dependency-version diffs separately.

## Risks / Trade-offs

- **[Wheel metadata is incomplete]** → Treat installation failure as a package defect rather than restoring path sources.
- **[Stale same-version wheel remains installed]** → Require explicit upgrade/reinstall in reinit targets.
- **[Lock regeneration drifts dependencies]** → Diff lock changes and pin/resolve intentionally.

## Migration Plan

Update projects in dependency order, rebuild wheels, regenerate locks, run package tests from clean environments, then enable the repository check. Rollback may restore a lock but must not normalize editable sibling paths as permanent policy.

## Permanent Documentation Promotion

Package-resolution and reinit requirements belong in `openspec/specs/deployment-state/spec.md` and `architecture.md`; contributor/release commands belong in `docs/development/RELEASING.md` and repository guidance.

## Found from adjacent work: the `rl` extra makes `make reinit` unresolvable (2026-08-12)

Reported here because this change already owns "add or repair local init/reinit targets"
and already carries a constraint about the PyTorch index — its non-goals say not to remove
non-path source/index selectors for external dependencies, and that non-goal is exactly
what the fix runs into.

`make reinit` in `domains/vms/storefront` fails for every developer on every host, not
only where a wheel is missing locally. `uv sync` resolves across every environment the
project declares, crossed with `requires-python = ">=3.12,<3.14"`, so a split with no
solution aborts the whole sync regardless of the machine running it:

```
× No solution found when resolving dependencies for split (markers:
  python_full_version == '3.13.*' and platform_machine == 'arm64' and sys_platform == 'darwin'):
  ╰─▶ Because torch was not found in the package registry and
      arkhai-vms-storefront[rl] depends on torch>=2.7.0 ...
```

The change's own task 6.1 recorded this from a darwin/arm64 host and worked around it with
`uv sync --frozen` plus targeted `--reinstall-package`; a later session hit the identical
failure on linux/x86_64 and reached for the same workaround. Two hosts, one cause.

Two fixes were attempted and each moved the failure rather than removing it, so neither is
proposed here:

1. Narrowing the darwin environment to `python_full_version < '3.13'` still fails — the
   `pytorch-cpu` index carries no darwin wheels at all, at any Python version, so the
   restriction addresses the wrong axis.
2. Scoping the index selector to `sys_platform == 'linux'` clears darwin and then fails on
   linux/x86_64/3.13, where only `torch<2.7.0` is visible through that index.

Either fix also regenerates `domains/vms/storefront/uv.lock`.

The questions a real fix has to answer belong to whoever owns this dependency: why the CPU
index is pinned rather than resolving torch from PyPI, whether the `rl` extra should
participate in the default resolution at all when the checkpoints it loads are optional,
and whether `requires-python` should span a version the project's own extras cannot satisfy.
Until then, `uv sync --frozen --find-links <repo>/.dist` with `--reinstall-package` per
internal distribution does what `reinit` intends and resolves against the lockfile — worth
knowing before a third session rediscovers it.

### A second thing blocked behind the same lock regeneration

`dynaconf` is declared `>=3.0.0` in four distributions and `>=3.2` in a fifth. Between 3.2
and 3.3, `settings.set` on a list key changed from replacing to merging: a caller replacing
a list-valued setting silently appends instead. That cost a session's diagnosis when a test
helper overriding a negotiation policy chain appended to it, leaving `bisection` ahead of
the policy under test and failing the test as though the policy were wrong. Nothing pins the
version away from that behaviour, so any resolution outside the lockfile can pick it up.

Bounding it is a one-line change per project and was attempted. It cannot land on its own:
changing a declared bound invalidates each `uv.lock`, and `uv run` — which `make test-unit`
and `make test-integration` both use — then re-resolves and fails on the `rl`/torch split
above. The bound and task 4.1 are therefore the same piece of work, and the bound is
recorded here rather than applied in a change that cannot regenerate the locks.
