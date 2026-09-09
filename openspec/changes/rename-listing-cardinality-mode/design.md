# Design — name the cardinality hint for its scope

## Context

`listing_mode` is a projected pool policy tag. `storefront-publication` gives it
two domain-owned values and defines both in cardinality terms: a `fungible`
pool's "publishable capacity range is bounded by what a single member can
currently satisfy, never by a sum across members"; a `specific_resource` pool
"publishes one independently identified, independently reservable listing
candidate per currently enabled member, regardless of member count."

So the field answers a counting-and-identity question. Its name does not say so,
and the general reading — "how is this pool listed" — is both natural and wrong
in a way that only shows up when someone proposes a value.

## Goals / Non-Goals

**Goals.** Make the enum's boundary legible at the point of use. State the scope
normatively so it survives the rename. Remove an unconditional operator-visible
notice that will fire on pools where it carries no information.

**Non-Goals.** No new values, no behavior change to either existing value, no
adjacent renames. The value of this change is that it is reviewable as a rename;
bundling the backing field into it would destroy that.

## Decisions

### Rename to `listing_cardinality_mode`

The alternative was to leave the name and document the scope in the requirement
only. Rejected: the ambiguity is at the point of use, and a reader adding a value
to an enum reads the enum, not the specification paragraph that constrains it. A
name that states its own scope is the cheaper control, and the rename is
mechanical.

### Reject a third value describing backing or settlement

During design it was proposed that the enum gain a value such as `unbacked` or
`contact`, on the reasoning that when a listing is unbacked, "capacity buckets or
individual resources" is not a meaningful question. The proposal is recorded here
with its rebuttal because it is a reasonable-sounding move that would have been
expensive to undo.

**The premise does not hold under the chosen design.** Unbacked pools declare
capacity resources carrying compute shape. A seller declaring an A100 box, an
H100 box, and an H200 box in one pool is asking exactly the cardinality question:
one listing or three. That question is live for unbacked pools and has the same
two possible answers it has for backed ones.

**A settlement-shaped value re-couples what registration decoupled.** Settlement
mechanism is a composed registration choice, deliberately independent of
inventory declaration. A pool declaring `contact` would hard-wire a mechanism into
an inventory record, and it would be wrong on the first finite, hosted-settled
unbacked offering — a shape already anticipated as the next version of this
market.

**A backing-shaped value creates a representable contradiction.** Backing is
carried as its own declared field. With `capacity_backing: backed` and
`listing_cardinality_mode: unbacked` both expressible, the pair has a meaning
nobody has defined, and two fields encoding one fact drift. The forward test is
concrete: a finite, hosted-settled, one-listing-per-pool offering is backed, so it
cannot take an `unbacked` value and is not `contact` — it needs a cardinality
value. Under the rejected proposal, v1 and v2 would encode the same cardinality in
different fields.

### Absence, not a sentinel, encodes "no cardinality question"

Where a pool genuinely has no cardinality answer, the field is absent. The
specification already handles absence: it falls back to the domain's structural
default rather than failing ingestion. No new mechanism is required, and no
sentinel value has to be invented for a case the fallback already covers.

### Scope the operator-visible explanation

The existing requirement pairs the fallback with an operator-visible explanation.
That is correct for a supplied-but-unrecognized value, which indicates a
misconfiguration or a version skew worth surfacing. It is wrong for absence on a
pool that has no cardinality question, where the notice would fire on every
projection refresh forever. An explanation channel that emits unconditionally is
one operators learn to filter, which costs the cases where the notice does mean
something.

The requirement therefore keeps the explanation for unrecognized values and drops
it for absence where no cardinality question exists.

### Accept the old key as a deprecated alias

The alternative was a hard rename. Rejected because the projection crosses a
service boundary and the two sides upgrade independently: a storefront that
recognized only the new key would read an unupgraded site's projection as absent
and silently apply the structural default. Silent reclassification of listing
cardinality is exactly the failure mode this change exists to prevent, and it
would be introduced by the fix.

The alias carries a deprecation notice, which is a supplied-value case and so
keeps the explanation obligation above. Removing the alias is a later decision
needing its own deployment evidence, consistent with the freeze-then-redirect
pattern used elsewhere in the physical-authority consolidation.

### The delta replaces the requirement rather than adding one

`openspec/specs/storefront-publication/spec.md` already carries a normative
"Domain-owned publication and hold hints" requirement naming `listing_mode`. An
`ADDED` delta would synchronize into a permanent specification holding two live
requirements for the same hint under different names, with no statement of which
governs. The delta is therefore `MODIFIED` and carries the complete replacement
text including the untouched hold, region, SLA, and pricing paragraphs — a
modified requirement is a whole-requirement replacement, not a patch.

## Risks / Trade-offs

- **[Rename churn against in-flight projection work]** → `capacity-resource-administration`
  and `pools-8-capacity-projection-and-listing-hints` edit adjacent lines.
  Mitigated by keeping the change mechanical and by not bundling the backing
  field, so a rebase is textual rather than semantic.
- **[The alias outlives its usefulness]** → Named as a later decision with an
  evidence bar rather than a scheduled removal, matching how the campaign handles
  other freeze-then-redirect steps. An alias with no removal owner is a real cost;
  an alias removed on a guess is a worse one.
- **[The scope statement is read as forbidding future values]** → It forbids
  values that are not cardinalities. A third cardinality — should one ever be
  needed — is in scope by construction.

## Open questions

- **When is the deprecated alias removed?** Deliberately deferred. Removal is a
  deployment-contract decision, and this repository has no fleet-wide deployment
  signal to gate it on: sellers self-host and self-operate their own storefront
  and site deployments. Recorded here rather than prescribed in `tasks.md`, and
  the task list contains no instruction to remove it.

## Migration Plan

1. Add the new key to the projection producer alongside the old one.
2. Teach the storefront consumers to prefer the new key and accept the old as a
   deprecated alias.
3. Update the specification requirement and its scenario.
4. Stop emitting the old key from the producer once consumers accept both.

Rollback within the alias window is a code rollback with no data consequence: the
hint is read live from the projection each time it is needed and is never
persisted into storefront-local storage.
