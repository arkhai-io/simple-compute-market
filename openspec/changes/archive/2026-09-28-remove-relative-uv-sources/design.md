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

### CI wheelhouse assembly

- Python CI builds internal distributions through one root Make target. The
  workflow does not maintain a second package inventory as a list of `uv build`
  commands.
- The internal-distribution target does not fetch the separately released
  hosted-settlement client. Matrix entries that consume that client, including
  through an internal adapter, declare the hosted prerequisite explicitly and
  stage it before building repository wheels.
- Every Python job creates `.dist` before passing it to `uv --find-links`.
  Packages without internal dependencies therefore receive an empty, valid
  wheelhouse rather than a nonexistent path.
- Lockfile source selection remains authoritative. A `--find-links` argument
  does not replace a lock entry pinned to a published artifact, so projects
  under test are relocked against the built wheelhouse when they must exercise
  current same-version internal distributions.

## Risks / Trade-offs

- **[Wheel metadata is incomplete]** → Treat installation failure as a package defect rather than restoring path sources.
- **[Stale same-version wheel remains installed]** → Require explicit upgrade/reinstall in reinit targets.
- **[Lock regeneration drifts dependencies]** → Diff lock changes and pin/resolve intentionally.

## Migration Plan

Update projects in dependency order, rebuild wheels, regenerate locks, run package tests from clean environments, then enable the repository check. Rollback may restore a lock but must not normalize editable sibling paths as permanent policy.

## Permanent Documentation Promotion

Package-resolution and reinit requirements belong in `openspec/specs/deployment-state/spec.md` and `architecture.md`; contributor/release commands belong in `docs/development/RELEASING.md` and repository guidance.

The Python CI wheelhouse command and matrix rule belong in
`docs/development/TESTING.md`; they instantiate the existing wheel-only package
boundary. The bare-metal pool-binding correction belongs in
`openspec/specs/physical-provisioning/spec.md` because it restores an existing
publication invariant exposed by testing the current wheel closure.

## Design promotion record

| Accepted decision | Permanent destination |
|---|---|
| Python CI creates `.dist`, builds the repository-owned wheel closure through `make dist-ci`, and stages the separately released hosted client only for declared consumers | `docs/development/TESTING.md#boundary-change-validation` |
| Bare-metal publication retains the inventory host's authoritative pool binding | `openspec/specs/physical-provisioning/spec.md#requirement-bare-metal-inventory-binds-an-existing-provider-pool` |
| Roadmap disposition | No update: this repair restores existing delivery and does not change a goal's current state or remaining gap. |
