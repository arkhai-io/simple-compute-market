# Correct the testing documentation

## Why

`docs/development/TESTING.md` describes a subsystem that has never existed on
`dev`. A reader following it looks for something that is not there, and cannot
tell whether it was removed, was never built, or lives on a branch they should
find.

This is a defect in the document regardless of what any harness does. It was
previously bundled with a repair of `tools/issue-discovery`; that repair is not
happening, and the correction should not wait on it.

## What Changes

- Removes the section describing a subsystem absent from this branch.
- Leaves the four test levels and their jurisdiction statement intact.

## Permanent documentation impact

- [x] `docs/development/TESTING.md`
- [ ] No specification change

## Impact

- Affected code: `docs/development/TESTING.md`
- Rescoped from `restore-issue-discovery-thin-runner`; the runner repair, phase
  configuration, and Make targets are dropped
- `tools/issue-discovery` remains in the tree. Removing it is deferred until a
  working replacement exists and is carried as a task there, not here
