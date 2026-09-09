# Design — separate advertisement authorization from delivery authorization

## Context

`deliverable_modes` was built to close a specific hole: pools carrying legacy
mode metadata wider than anything their configuration could execute. The
resulting contract is deliberately unforgiving — empty authorizes nothing, a set
must be derived from configuration that proves delivery, and a declaration wider
than its proof is narrowed to empty rather than retained. Its own migration
scenario spells out the preference: an unproved capability is worse than no
capability.

Nothing about that is wrong. It is a contract about execution, and it is correct
about execution. The problem is that it became the only place a pool says which
modes its listings may name, so a seller with no execution integration inherits an
execution proof requirement for an act that involves no execution.

## Goals / Non-Goals

**Goals.** Let a pool authorize advertising a mode without proving it can deliver
it. Keep every delivery proof and execution recheck exactly as it is. Change no
existing deployment's behaviour on upgrade.

**Non-Goals.** No change to `deliverable_modes`. No implication of backing from
either declaration. No new provider kind.

## Decisions

### A separate declaration, not a conditional reading of the existing one

`unbacked-listing-publication` first proposed reading `deliverable_modes` as two
jobs — advertise-authorization for every listing, execute-authorization for backed
ones — and scoping only the second. That does not survive contact with the
contract. For an execution-less seller the proved set is *empty*, and empty
"authorizes no mode." Reading one job out of the field does not help when the
field's value is nothing.

An earlier draft of the same idea called the pool conjunct outright vacuous for
unbacked listings. That was worse: it would let a pool proving no VM delivery
advertise VMs, which is the exact failure `deliverable_modes` exists to prevent,
reintroduced through a different door.

So the answer is a second declaration rather than a reinterpretation of the first.
`deliverable_modes` keeps its meaning, its derivation, and its rechecks;
`advertisable_modes` answers a question nobody was asking it.

### Backed pools are constrained; unbacked pools are not

A capacity-backed pool's advertisable set must be a subset of its deliverable set.
Without that, this change would reopen the hole — a pool that can be reserved
against could advertise a mode it cannot execute, and a buyer would reach
admission for something the provider will refuse.

An unbacked pool has no such risk, because nothing reaches admission. Its
advertisable set stands alone, and its deliverable set will ordinarily be empty
and correct.

The asymmetry is the point rather than an exception: the subset rule exists to
protect a path that unbacked listings never enter.

### Derive the initial set from the proved deliverable set

An existing pool advertises exactly what it delivers today, because that is the
only declaration it has. Deriving the initial advertisable set from the proved
deliverable set means upgrading changes nothing, and any widening is an explicit
operator act afterwards.

The alternative — defaulting absent to "advertise anything" — is the failure mode
`deliverable_modes` was built to fix, and repeating it in a neighbouring field
would be hard to defend. Absent authorizes nothing here too.

### Not a publication-only provider kind

The alternative considered was a provider kind meaning "never dispatches", letting
an execution-less pool satisfy the existing schema honestly. Rejected: it puts a
pool into the fleet whose provider exists to be never called, and every dispatch
path then depends on a handler doing nothing rather than on a declaration saying
nothing. A missing declaration is a safer thing to get wrong than a no-op
executor.

### Nothing to split

`resource-pool-management`'s mode contract comes from the archived
`pool-declared-offering-modes` change. No active change owns it, so there is no
in-flight work to carve a minimal piece out of — this change amends a permanent
specification directly, which is the ordinary path.

That also means the POOLS campaign inherits an amended contract rather than
having one changed underneath work in progress. It should be re-read for
consistency when that campaign resumes, which is true of the whole surface after
this goal lands.

## Risks / Trade-offs

- **[Two mode declarations drift]** → An operator can widen advertisable while
  deliverable narrows, and for a backed pool that is exactly what the subset rule
  refuses. Enforce it on write and on projection ingestion rather than only on
  write, since the two sides upgrade independently.
- **[The subset rule is read as applying everywhere]** → It applies to
  capacity-backed pools. Stating the scope in the requirement rather than leaving
  it to be inferred is what stops an unbacked pool from being forced back into an
  execution proof.
- **[A second policy tag invites a third]** → Accepted. The line worth holding is
  that a mode declaration answers a question about authorization; a tag answering
  a question about backing, cardinality, or settlement belongs in the field that
  already owns that question.

## Open questions

- **Should `advertisable_modes` be projected, or resolved storefront-side from
  the pool's own record?** Projection is the obvious choice since every other
  policy tag travels that way, but the storefront already resolves a listing's
  offering mode from its frozen registration, so the projected value may be a
  check rather than an input. Confirm which at implementation rather than
  designing both.
- **Does an unbacked pool with a non-empty deliverable set mean anything?** It is
  representable — a seller with real execution integration who chooses to trade
  out of band — and nothing here forbids it. Whether that combination should be
  allowed, warned about, or refused is deferred; no task decides it.

## Migration Plan

1. Add the tag with validation and typed resolution alongside `deliverable_modes`.
2. Derive every existing pool's advertisable set from its proved deliverable set
   and report each derived set, matching how the deliverable sets were derived.
3. Enforce the subset rule for capacity-backed pools on write and on ingestion.

No deployment behaviour changes at any step: every pool advertises exactly what it
advertised before until an operator changes it. Rollback is a code rollback; the
derived tag remains and is ignored by a restored reader.
