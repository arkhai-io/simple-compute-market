# Design — a pool declares what it advertises and whether it can be admitted against

## Context

`deliverable_modes` was built to close a specific hole: pools carrying legacy mode
metadata wider than anything their configuration could execute. The resulting
contract is deliberately unforgiving — empty authorizes nothing, a set must be
derived from configuration proving delivery, and a declaration wider than its
proof is narrowed to empty rather than retained. Its own migration scenario states
the preference plainly: an unproved capability is worse than no capability.

None of that is wrong. It is a contract about execution and it is correct about
execution. The problem is that it became the only place a pool says which modes
its listings may name.

Separately, nothing on a Resource Pool says whether it can be admitted against.
That has never mattered because every pool can. It starts mattering the moment a
site declares supply it intends to trade by private arrangement.

## Goals / Non-Goals

**Goals.** Let a pool authorize advertising a mode without proving it can deliver
it. Let a pool declare whether it can be admitted against. Keep every delivery
proof and execution recheck exactly as it is. Change no existing deployment's
behaviour on upgrade.

**Non-Goals.** No change to `deliverable_modes`. No consumption of either
declaration — that is the storefront's, and belongs to the change that reads
them. No new provider kind.

## Decisions

### Two declarations, one change, split by service rather than by feature

An earlier version of this work put `advertisable_modes` here and `capacity_backing`
in the downstream storefront change. That produced a dependency cycle: the subset
rule below is scoped to backed pools, so this change's normative text needed a
concept the change that depends on it owned. The cycle was not terminological — the
integration plan asked an operator to create an unbacked pool that could not exist,
and `resource-pool-management` would have permanently defined behaviour for backed
and unbacked pools before either existed.

The cause was splitting by feature when the seam is a service boundary. Both tags
are declarations a site makes about a Resource Pool. They travel the same
policy-tag channel with the same precedence, need the same derive-on-upgrade
migration, and take the same fail-closed validation. Everything that *reads* them —
candidate derivation, listing binding, registry publication, version-skew
tolerance — is storefront-side and belongs to `unbacked-listing-publication`.

Splitting declaration from consumption also gives the site-side migration a home.
Someone has to persist an explicit backing value on every existing pool at
upgrade; that is a provisioning-service migration against `resource-pool-management`,
and putting it in a storefront change would blur a boundary this campaign has spent
several rounds sharpening.

The consequence, accepted deliberately: this change is observable to operators and
to no one else. No listing behaviour changes until the storefront reads the tags.
Its acceptance boundary is that the declarations exist, are validated, and every
existing pool has one.

### A separate declaration, not a conditional reading of `deliverable_modes`

`unbacked-listing-publication` first proposed reading `deliverable_modes` as two
jobs — advertise-authorization for every listing, execute-authorization for backed
ones — and scoping only the second. That does not survive the contract. For an
execution-less seller the proved set is *empty*, and empty "authorizes no mode."
Reading a second job out of a field does not help when the field's value is
nothing.

An earlier draft called the pool conjunct outright vacuous for unbacked listings.
Worse: it would let a pool proving no VM delivery advertise VMs, which is the exact
failure `deliverable_modes` exists to prevent, reintroduced through another door.

So `deliverable_modes` keeps its meaning, derivation, and rechecks, and
`advertisable_modes` answers a question nobody was asking it.

### Backed pools are constrained; unbacked pools are not

A backed pool's advertisable set must be a subset of its deliverable set. Without
that, this change reopens the hole: a pool that can be reserved against could
advertise a mode it cannot execute, and a buyer would reach admission for
something the provider will refuse.

An unbacked pool carries no such risk because nothing reaches admission. Its
advertisable set stands alone, and its deliverable set will ordinarily be empty
and correct.

The asymmetry is the point rather than an exception: the subset rule protects a
path unbacked pools never enter.

### Derive both on upgrade, and emit both on every pool

An existing pool advertises exactly what it delivers, because that is the only
declaration it has, and it can be admitted against, because every pool can. So the
derived values are the proved deliverable set and `backed`. Upgrading changes
nothing; any divergence afterwards is an explicit operator act.

Defaulting absence to "advertise anything" is the failure `deliverable_modes` was
built to fix, and repeating it in a neighbouring field would be indefensible.
Absent authorizes nothing here too.

The emit-on-every-pool requirement is what makes the consuming side's version-skew
rule possible, and it is worth stating here rather than assuming. Without it, an
upgraded site holding ten legacy pools emits the tags nowhere and reads as an old
producer indefinitely — and the moment an operator creates one explicitly unbacked
pool, the other nine become partially-populated omissions and fail closed. A
correct operator action would detonate nine working pools. Deriving on upgrade and
requiring complete emission is what prevents that; the consumer's rule then only
has to distinguish "no pool has it" from "some pool is missing it."

### A malformed backing value fails closed

`capacity_backing` is a discriminator, so an unrecognized value is refused rather
than resolved to either side. Administration rejects it on write, and ingestion
fails that pool closed rather than letting a malformed declaration reach candidate
derivation. This differs deliberately from the cardinality hint, where an
unrecognized value falls back to a domain's structural default: a cardinality
default is a reasonable guess about how many candidates to publish, while a
backing default is a claim about whether anything stands behind a listing.

### Not a publication-only provider kind

The alternative considered was a provider kind meaning "never dispatches", letting
an execution-less pool satisfy the existing schema honestly. Rejected: it puts a
pool into the fleet whose provider exists to be never called, and every dispatch
path then depends on a handler doing nothing rather than on a declaration saying
nothing. A missing declaration is a safer thing to get wrong than a no-op
executor.

### Both tags are projected

Every other pool policy tag travels the projection, and the storefront needs both
values as inputs rather than as checks — it derives candidates from the projection
and has no other route to a pool's record. An earlier draft left this open while
simultaneously prescribing projection in the task list and the delta, which is the
shape of a decision made somewhere a reviewer would not look. It is decided here.

### Nothing to split

`resource-pool-management`'s mode contract comes from the archived
`pool-declared-offering-modes` change. No active change owns it, so there was no
in-flight work to carve a minimal piece out of — this amends a permanent
specification directly, which is the ordinary path.

## Risks / Trade-offs

- **[Two mode declarations drift]** → An operator can widen advertisable while
  deliverable narrows, which for a backed pool is exactly what the subset rule
  refuses. Enforced on write *and* on ingestion, because the two sides upgrade
  independently and a write-side-only check would accept from a projection what it
  refuses from an operator.
- **[The subset rule is read as universal]** → It applies to backed pools.
  Stating the scope in the requirement rather than leaving it inferred is what
  keeps an unbacked pool from being forced back into an execution proof.
- **[A change with no observable behaviour ships and is forgotten]** → Its value is
  entirely in what depends on it. Mitigated by it being a declared prerequisite
  with a named consumer rather than speculative groundwork.
- **[A second and third policy tag invite a fourth]** → Accepted. The line worth
  holding is that each tag answers one authorization or capability question about
  the pool; a tag answering a question about cardinality or settlement belongs in
  the field that already owns it.

## Open questions

- **Does an unbacked pool with a non-empty deliverable set mean anything?** It is
  representable — a seller with real execution integration who chooses to trade out
  of band — and nothing here forbids it. Whether that combination should be
  allowed, warned about, or refused is deferred; no task decides it.

## Migration Plan

1. Add both tags with validation and typed resolution alongside
   `deliverable_modes`.
2. Derive every existing pool's advertisable set from its proved deliverable set
   and its backing as `backed`, reporting each derived value.
3. Enforce the subset rule for backed pools on write and on ingestion, and reject
   malformed backing values on write.

No deployment behaviour changes at any step: every pool advertises exactly what it
advertised before and remains admissible, until an operator changes it. Rollback is
a code rollback; the derived tags remain and are ignored by a restored reader.
