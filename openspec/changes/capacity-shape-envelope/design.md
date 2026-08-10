# Design

## Context

- `kit/site`'s matching contract (`resource_satisfies_requirement`,
  `dict_resource_satisfies_claim`, `_find_candidate`) answers whether a *specific
  resource* satisfies a claim right now. It does not answer whether a shape is one the
  seller would entertain.
- `kit/resource-pools/hints.py` already carries domain-neutral pool policy through
  `policy_tags`, with typed readers per tag and validation limited to what has a
  universal meaning. Bounds fit this mechanism exactly.
- `domains/vms/negotiation/policies.py`'s `has_matching_inventory_guard` is the only
  seller-side shape check today and is categorical-only.
- The roadmap records that reservable capacity per dimension is expected to become a
  function of current occupancy rather than a constant.

## Goals / Non-Goals

**Goals:** one domain-neutral admissibility concept; an interface that survives the
move from static to coupled bounds; bounds expressed through existing pool policy.

**Non-Goals:** coupled bounds, availability, pricing, categorical constraints.

## Decisions

### A predicate plus a range query, not a readable bounds pair

The tempting interface is a getter returning `(min, max)` per dimension, with callers
comparing against it. It is rejected, and this is the change's central decision.

A readable bounds pair leaks the assumption that bounds exist independently of the rest
of the shape. Every caller that reads it and compares locally encodes that assumption
in its own code, so replacing the static implementation later means finding and
rewriting every such caller — the rewrite this change exists to avoid.

Two operations are exposed instead:

- **Is this whole shape admissible for this pool?** The caller supplies the entire
  proposed shape and receives a decision. A coupled implementation needs the whole
  shape; a box implementation ignores the parts it does not use. The signature does not
  change between them.
- **What range is admissible for dimension *d*, given the rest of this shape?** The
  caller supplies the remainder, so the answer may legitimately depend on it. The static
  implementation ignores the remainder and returns its configured bounds; a coupled one
  does not.

The second exists so a seller can counter-offer usefully — "not 512 GiB, but up to 256
with those cards" — rather than only rejecting. A bare predicate would force the
negotiation layer to search for an acceptable value, which is both wasteful and a place
where the box assumption would reappear as a linear scan.

### Admissibility is separate from availability, deliberately

A shape can be admissible (the seller would sell it) and unservable (nothing free right
now). Collapsing the two into one answer would mean a transiently full pool reports a
shape as out of range, and a buyer would reasonably conclude the shape is wrong rather
than the timing. Keeping them separate lets negotiation distinguish "ask for something
else" from "ask again shortly," which are different counter-offers.

This also keeps the two answerable from different sources: admissibility from declared
pool policy, availability from the authoritative ledger. Only the second requires a
round trip to the site.

### Bounds live in pool policy tags, not a new channel

`policy_tags` already carries region, SLA, pricing, listing mode, and hold caps, with
typed readers and universal-meaning validation. Bounds are the same kind of fact.
Reusing it means bounds inherit projection, precedence, and administration for free, and
kit gains no new configuration surface.

### Kit stays free of dimension names

The dimension vocabulary is supplied by the composition root, as `kit/site` already does
for its dimension names. Kit validates that a bound is well formed — a range with a
sensible order — and never that `gpu_count` is a real dimension. This is what keeps the
capability usable by a pod, inference-token, or model-training domain without
modification, which is the reason it is in kit at all.

## Risks / Trade-offs

- **[The interface is heavier than a static box needs]** → Accepted deliberately. The
  extra cost is one parameter that the first implementation ignores; the avoided cost is
  rewriting every caller when bounds become coupled.
- **[Callers bypass the interface and read the tags directly]** → The failure mode that
  would undo the whole design. `policy_tags` is readable, so this needs an explicit
  check at closeout rather than trust.
- **[Admissible-but-unservable confuses buyers]** → Mitigated by keeping the two
  answers distinct so negotiation can say which one failed. Conflating them is the worse
  outcome.
- **[Bounds go stale relative to real capacity]** → True of any declared bound and
  unchanged by this design; the coupled implementation is what eventually addresses it,
  which is why the interface is shaped for it now.

## Migration Plan

Purely additive. No pool declares bounds initially, and a pool with no bounds admits any
shape — preserving today's behavior, where no shape check exists. Rollback is a code
revert; declared tags on unmigrated pools are ignored by the restored reader.

## Open Questions

- **Should a pool with no declared bounds admit everything, or nothing?** Admit
  everything is chosen here to make the change additive, but a fail-closed default is
  defensible once bounds are routinely declared. Deferrable: it is a default, changeable
  without touching the interface or its callers.
- **Should the range query report a reason when a dimension has no admissible range at
  all?** Useful for counter-offer messages, but the vocabulary for such reasons is a
  negotiation concern. Deferrable until a caller needs it.
