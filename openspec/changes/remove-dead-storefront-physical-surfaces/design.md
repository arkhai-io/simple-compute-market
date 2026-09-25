# Design

The evidence that each surface is dead was gathered by the 2026-08-06 Goal 1
sweep and is recorded, with the docstrings it contradicts, in
`pools-9-retire-local-physical-authority`'s `design.md` under "Goal 1 sweep
findings (2026-08-06)": the sections "`compute_allocations` is a dead execution
ledger", "Physical identity threaded across the service boundary is provably
`None`", "Two admin endpoints have outlived their only caller", and "Dead
methods confirmed by exhaustive search". It is not duplicated here. Task 1.1
re-runs every confirming search before anything is deleted.

## Decisions

### Freeze `compute_allocations`; do not drop it

The campaign's schema posture is additive-only until a deployment cycle
confirms a freeze never needed rolling back. The table has accumulated no rows
since the ledger moved to `kit/site`, so freezing costs nothing and dropping
gains nothing yet.

### Remove the routes rather than deprecate them

Both admin resource routes are pre-1.0 and have no caller in the repository.
A deprecation window would keep alive a `PATCH` whose docstring describes a
provisioning-service call that no longer exists, which is how these surfaces
outlived their callers in the first place.

### No delta specification

The requirement this work serves already exists in draft in
`pools-9-retire-local-physical-authority` and describes the terminal state,
which this change reaches only in part. Two changes adding overlapping
requirements to the same specification would leave archival to reconcile them;
one owns the requirement and the other removes dead code toward it.
