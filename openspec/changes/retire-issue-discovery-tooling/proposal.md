# Retire the issue-discovery tooling and correct the testing documentation

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
establishing that they should not. The same is true of the documentation: this
repository currently describes a subsystem that has never existed on `dev`, so a
reader looking for it cannot tell whether it was removed, was never built, or
lives on a branch they should go find.

## What Changes

- Removes `tools/issue-discovery` and its configuration, fixtures, and schemas.
- Removes the Make targets and packaging entries that reference it.
- Removes the section of `docs/development/TESTING.md` describing a subsystem
  absent from this branch.
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

- [x] `docs/development/TESTING.md`
- [ ] No specification change

## Impact

- Affected code: `tools/issue-discovery/`, `Makefile`, `docs/development/TESTING.md`
- Supersedes the scope of `correct-testing-documentation`, which held only the
  documentation half
- Rescoped from the archived `restore-issue-discovery-thin-runner`
