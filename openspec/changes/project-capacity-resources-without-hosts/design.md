# Design — project capacity resources that have no executor host

## Context

`Host` is a connection record. Its `kvm_host`, `ssh_user`, `ssh_key_type`, and
`ssh_key_value` columns are all `NOT NULL`, and the model's own docstring says
why: "The registry is the authority for how a host is reached — address, user,
key, and port — and every execution path derives its connection from a rendered
inventory rather than constructing one."

GPU columns were added to that record, which is how a host-seeded deployment came
to publish and sell. `capacity-resource-administration` is undoing that: it moves
compute shape to the site-ledger capacity resource, makes `Host` executor
identity only, and retires the host-derived capacity fallback. Its stated
reasoning — "Splitting capacity across two authorities inside one service — GPUs
on `Host`, everything else on capacity resources — would relocate the duplication
this consolidation exists to remove" — is the same separation this change
depends on.

What that change does not touch is the iteration. `capacity_inventory` maps
resources by host identity, then runs over `Host` rows and projects one entry
each. Task 4.1 redirects `_project_host` to read capacity and attributes from the
declared resource; task 4.4 reasons about "hosts that previously projected no
`available`". Both are per-host. So after the consolidation lands, compute shape
lives on the capacity resource, the projection claims resources are
authoritative, and a resource still cannot appear unless a connection record
exists for it.

## Goals / Non-Goals

**Goals.** Make the projection's iteration match its stated authority model.
Allow a capacity declaration with no executor host to reach storefronts. Keep
every currently projected entry byte-identical.

**Non-Goals.** No change to what a capacity resource declares or how it is
administered. No commercial interpretation of hostless declarations. No relaxation
of executor requirements anywhere an execution path runs.

## Decisions

### Invert the loop rather than union two loops

The alternative was to keep the host loop and append hostless resources
afterwards. Rejected: it leaves two code paths producing entries that must stay
structurally identical, which is the shape of a divergence rather than a fix.
`capacity-resource-administration` is already fixing one divergence of exactly
this kind — `attributes` derived from the host unconditionally while `capacity`
preferred the resource, so a declaration disagreeing with a host row projected
contradictory values in one row — and reintroducing a second producer immediately
after would be a poor trade.

Iterating resources and correlating hosts in gives one producer, and it makes the
correlation explicitly optional at the only place that needs to know.

### Omit executor fields rather than emptying them

A hostless entry has no executor identity. It must omit those fields, not carry
empty strings.

The precedent is load-bearing and already documented: a storefront reconciler
distinguishes an absent projection from a loaded empty one under an "ignorance is
not zero" rule, and `capacity-resource-administration` flags the `available`-key
semantics change as the highest-risk item in its own change for the same reason.
An empty executor identifier would be indistinguishable from a correlated host
whose identifier failed to populate, which is a real failure worth surfacing.

### Execution paths keep requiring executor correlation

Making a resource projectable without a host must not make it schedulable without
one. Placement, provider dispatch, and inventory rendering continue to require
executor correlation and fail closed without it.

This is the boundary that keeps the change honest. The risk in relaxing a
precondition is that the relaxation propagates to consumers who were relying on
it implicitly; the mitigation is to state the requirement normatively at the
paths that still need it rather than to rely on those paths happening to check.

### Shape authority and admission authority are different claims

`capacity-resource-administration` makes the capacity resource "the authoritative
declaration of a Physical Resource's sellable capacity". Read as one claim, that
sentence conflates two things: being authoritative for what is declared sellable,
and implying that something can be sold against it.

A hostless resource still has a Physical Resource — that term means the real supply
resource, "host, pod allocation, storage, power, or bandwidth", and this change's
own delta has a hostless resource projecting its Physical Resource identity. What a
missing `Host` removes is the executor connection record, not the supply the
declaration describes. So the problem is not that there is nothing for the capacity
to be *of*; it is that "sellable" carries an admission implication the declaration
should not be making on its own, and downstream work needs a declaration
authoritative for shape without it.

The alternative considered was a second site-owned declaration object carrying
shape for resources that are not admissible. Rejected, because it reintroduces
what the prerequisite exists to remove: that change's own reasoning is that
"splitting capacity across two authorities inside one service ... would relocate
the duplication this consolidation exists to remove", and a second object
carrying compute shape is a second shape authority that can disagree with the
first.

So the requirement is scoped rather than duplicated. The capacity resource stays
the single authoritative declaration of *shape and quantity*; whether that shape
can be admitted against is a property resolved elsewhere. Nothing is weakened — no
consumer that could previously admit against a resource loses that ability — and
the sentence becomes true for hostless resources, which it has to be for this
change alone.

**Where that scoping lives.** In `capacity-resource-administration`, not here. A
first draft carried it as a `MODIFIED` delta in this change against a requirement
that only exists once the prerequisite lands, which strict validation correctly
refused: a delta that cannot validate on the branch reviewing it is not reviewable,
and two active changes would have described a capacity resource differently in the
window before either archived. Amending the prerequisite gives the campaign one
definition. This change depends on that wording and asserts it rather than
restating it.

### This change takes no position on why a resource has no host

A hostless capacity resource is a declaration of sellable capacity with no
configured connection. That covers a seller who arranges delivery out of band, an
operator staging inventory before configuring connections, and an operator whose
connection configuration is temporarily absent. The projection does not
distinguish them and should not: it reports what was declared and what was
correlated.

Keeping the change agnostic is what makes it a defect fix with independent value
rather than a piece of the unbacked-listing feature. If that feature were
abandoned, the projection would still be wrong today in the same way.

## Risks / Trade-offs

- **[A hostless entry reaches a path that assumes a host]** → The failure would be
  a `None` dereference or a rendered inventory with a blank address, both
  discovered late. Mitigated by omitting rather than emptying the fields, so the
  failure is a missing key at the boundary rather than a plausible-looking empty
  value carried deeper, and by covering the fail-closed behavior at scheduling
  and inventory rendering directly rather than reasoning about it.
- **[Existing projections change shape]** → The change is additive by
  construction, but "by construction" has been wrong before in this campaign.
  Verify by diffing a full projection for a host-complete deployment before and
  after, not by reading the loop.
- **[Ordering against `capacity-resource-administration`]** → Landing this first
  would project hostless entries whose capacity could not be resolved, since the
  fallback it retires is host-derived. The dependency is a hard one, not a
  coordination note.

## Open questions

- **Should a hostless capacity resource be visible to operator-facing inventory
  listings, or only to the projection?** The two audiences differ: a storefront
  needs the entry to publish, while an operator listing inventory may reasonably
  expect to see only machines. Deferred rather than prescribed; no task instructs
  an implementer either way.

## Migration Plan

1. Land `capacity-resource-administration`.
2. Invert the loop, correlating hosts by their existing identity keys.
3. Confirm a host-complete deployment projects identically, by diff.
4. Add hostless coverage and the fail-closed execution-path coverage together.

No schema change, no data migration, no deployment-contract change. Rollback is a
code rollback; declared resources remain and are ignored by the restored reader,
exactly as they are ignored today.
