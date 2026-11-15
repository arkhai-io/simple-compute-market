---
tags: [engineering, documentation]
---

# Documentation

What a permanent document says, which kind of material it holds, where the history
of its changes is kept, and what its citations must do. A permanent document is one
a repository keeps as the description of its system, its rules, or its procedures —
a specification, an architecture reference, a guide, a handbook — as against a
record of one piece of work.

## Permanent documents describe the current state

Permanent documentation and guidance describe the system they apply to, declaratively
and in the present, and read as timeless even while they change constantly. They
describe the current state rather than announcing completion or recounting how the
system came to be, and no wording is relative to a migration, a reorganization, or a
planned change: not "now", "no longer", "moved from", or "will be". A document that
is wrong is corrected in place.

## A document holds one kind of material

A repository's permanent documents hold three kinds of material, and each document
holds one:

- **A description of the system** — what it is and why: its shape, the authorities
  over its state, its vocabulary, its flows, and its topology. Everyone who works on
  the system reads it, so it is written once, as narrative, and the rules and
  procedures that rest on it link it rather than repeat it.
- **Rules for work** — what a change must produce or satisfy, wrong if a change's
  work product were otherwise. Each is stated once, in a document of rules, linking
  the description it rests on.
- **Procedures** — what a person does or types: deploying, releasing, recovering.
  They are kept in handbooks, apart from the description and the rules, each whole,
  rather than cut into the rules each step touches.

For example, "the billing service owns the ledger, and other services read it
through the billing service's API" describes the system; "a new service reads the
ledger only through the billing service's API" is a rule; "to rebuild the ledger
after a restore, stop the billing service and run its replay command" is a
procedure, kept in the operator's handbook.

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
