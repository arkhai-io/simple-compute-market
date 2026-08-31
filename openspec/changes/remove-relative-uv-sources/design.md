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
