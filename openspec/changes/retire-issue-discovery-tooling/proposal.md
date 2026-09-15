# Retire the issue-discovery tooling

## Why

`tools/issue-discovery` is 2,051 lines that nothing invokes. No Make target
reaches it, and its phase configuration names directories that no longer exist,
so it could not run if something did.

It survived because a change was going to repair it. That repair is not
happening: the qualification suite is being built new elsewhere, and this tool's
phase-pipeline model has no actor in it and does not map onto how that suite
executes. Repairing it would produce something with no consumer.

Leaving it is not neutral. Code in the tree reads as code that works, and the
next person to find it will either try to use it or spend an afternoon
establishing that they should not. The documentation half of the same problem is
`correct-testing-documentation`, which is not blocked and lands first.

## What Changes

- Removes `tools/issue-discovery` and its configuration, fixtures, and schemas.
- Removes the Make targets and packaging entries that reference it.
- Leaves the four test levels and their jurisdiction statement intact — a
  separate suite still sits outside them, and that boundary is unchanged by this
  removal.

## Not in scope

The replacement. This repository does not host the qualification suite and gains
nothing from this change beyond the removal of something that misleads.

## Sequencing

Removal is safe once a working replacement exists. Until then this change is
retained and not started: deleting the tool while nothing has replaced it trades
a misleading artifact for a missing one, and the argument for removing it rests
on there being something to point at instead.

## Permanent documentation impact

- [ ] `docs/development/TESTING.md` — already corrected by `correct-testing-documentation`
- [ ] No specification change

## Impact

- Affected code: `tools/issue-discovery/`, `Makefile`
- Sequenced after `correct-testing-documentation`, which holds the documentation
  half and is not blocked
- Rescoped from the archived `restore-issue-discovery-thin-runner`
