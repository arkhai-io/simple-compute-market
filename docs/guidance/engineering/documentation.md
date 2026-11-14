---
tags: [engineering, documentation]
---

# Documentation

What a permanent document says, where the history of its changes is kept, and what
its citations must do. A permanent document is one a repository keeps as the
description of its system or its rules — a specification, an architecture
reference, a guide, a handbook — as against a record of one piece of work.

## Permanent documents describe the current state

Permanent documentation and guidance describe the system they apply to, declaratively
and in the present, and read as timeless even while they change constantly. They
describe the current state rather than announcing completion or recounting how the
system came to be, and no wording is relative to a migration, a reorganization, or a
planned change: not "now", "no longer", "moved from", or "will be". A document that
is wrong is corrected in place.

## Provenance lives in version control

The history of a change — who made it, why, the alternatives considered, and the
review discussion — is the version control history's and its pull requests', not a
permanent document's.

## Citations resolve

Every path a permanent document cites exists on the branch that cites it. A
permanent document describing behaviour its branch does not implement is not a
harmless forward reference: it is how work from another branch, or from an earlier
plan, gets treated as inherited without anyone deciding to inherit it. Treat an
unresolvable citation as a blocking defect rather than a stale link to fix later.
