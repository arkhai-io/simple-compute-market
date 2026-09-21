# Site Capacity Architecture

The [normative contract](spec.md) defines reservation and projection behavior. This document explains why capacity admission is a separate authority from storefront publication and fulfillment execution.

## Admission authority

A site is the serialization point for competing reservations in one failure domain. Storefronts may cache and aggregate availability, but only the site can atomically decide whether capacity remains admissible.

```text
storefront projection (advisory)
            ↓ request
site reservation ledger (authoritative)
            ↓ committed reservation
fulfillment scheduling
```

Putting the ledger outside storefronts allows several sellers or processes to share supply without treating independently refreshed caches as locks. It also lets a reservation outlive the storefront process that initiated it.

## Declared capacity and connection identity

What a site sells is declared by capacity declarations: a Physical Resource's shape
and quantity across every dimension it names, its pool, the categorical attributes
claims match, and, where it is delivered through a host, that host's `host_id`. A
host record is connection identity — how the provisioner reaches a machine — and
supplies no capacity. The resource-pool projection is built from declarations; a
host that no declaration names is not projected.

The alternatives each left capacity with more than one authority. Adding vCPU, RAM,
and disk columns to hosts would have folded sellable capacity into records whose
job is SSH users, key material, and addressing, and an Ansible inventory is a poor
carrier for declarations because it exists to describe how to reach a machine.
Keeping GPUs on hosts and moving the other dimensions to declarations would have
left two partial authorities in one service. So declarations own every dimension,
and a host's legacy GPU count is only input: where INI inventory enters, and once
at upgrade, a host with GPUs that no declaration names gets a declaration derived
from it, and after that its inventory no longer affects capacity.

One declaration type serves every entry point — single registration, a mounted or
submitted definitions document, and derivation — with the same validation and the
same refusals, so a declaration means the same thing however it arrives.

Administration composes with the ledger's serialization rather than around it. A
declaration's checks against stored state (a pool move while the resource holds a
live reservation, a host another declaration names) are true only until something
else commits, so a caller writing declarations into its own transaction holds the
ledger's serialization lock through that transaction's commit, and the ledger's
in-session writers refuse to run without it.

## Private accounting

Multidimensional balances are represented by private capacity buckets and current reservation debits. The public reservation identifies its lifecycle and reserved dimensions; it does not expose a backing bucket or physical-resource identity. Scheduling may atomically move the debit when selection binds the reservation to another eligible bucket.

Admission and scheduling use the same fit semantics. Every requested dimension must be present and sufficient; a missing dimension means zero availability rather than an unconstrained match. This avoids accepting a request under one predicate and selecting a resource under another.

## Reservation lifecycle

A hold protects negotiation-time intent for a bounded period. Commit makes capacity durable for execution. Release returns capacity only through the owning lifecycle. Expiry and early termination may initiate release, but physical capacity remains held until executor or provider teardown succeeds or an operator explicitly force-releases it.

## Resize as one transaction, not two calls in either order

When a negotiated shape changes for an already-held reservation, the ledger supersedes it (`resize_reservation`) rather than mutating it in place or composing two ordinary `reserve()`/`release()` calls. Two simpler designs were considered and rejected because each has a real correctness bug the other doesn't:

- **Reserve-new-then-release-old** evaluates the new shape's availability while the old hold is still artificially consuming capacity. A resource that would satisfy the new request the instant the old hold clears can incorrectly report as unavailable, because that capacity is invisible until release actually happens — a false negative, most visible exactly when the new shape targets the same resource or pool the old hold already occupies.
- **Release-old-then-reserve-new** as two separate calls fixes that visibility problem but reintroduces a different risk: if the new reservation then fails, the old one is already gone, leaving the negotiation with nothing.

Both properties — evaluating the new shape's availability *as if* the old hold were already released, and leaving the old reservation completely untouched if the new shape can't be satisfied — are only simultaneously achievable inside one transaction that releases-then-reserves internally, committing only on success and rolling back in full on failure. This generalizes the atomic-rebind pattern scheduling already uses for moving a settlement assignment between resources, to the case that pattern doesn't cover on its own: source and destination can legitimately be the same resource or pool, which is exactly when the visibility problem shows up.

## Projection boundaries

The site exposes two independent storefront views:

- per-resource inventory for deliberately individual-resource offerings;
- grouped currently available shapes for fungible capacity publication.

Each view has its own revision and canonical digest. Grouped rows use deterministic criteria and counts, omit physical-resource identifiers, and are never allocation targets. These properties let storefronts replace one cached projection without conflating publication convenience with admission truth.

## Event privacy and convergence

Capacity events are anonymous availability changes. Broadcasting deal context would leak one storefront's customer activity to another seller sharing the site. Deal-scoped outcomes therefore use an owner-specific channel.

Revisions make missed events detectable. A consumer that sees a gap refreshes a complete snapshot rather than attempting to infer unknown intermediate deltas. Reconciliation reacts to every capacity change, not only changes caused by the local storefront.

## Routing identity

`site_id` is selected and trusted at the storefront aggregation boundary, where it is bound to a configured provisioning connection. Provisioning-local rows are already scoped by their database authority and do not encode routing endpoints or credentials into reservation identifiers.

## Projected feasibility matching

Ranking multiple sites for a claim (`most_available` placement) and
authoritative admission at a single site use the same claim-matching
semantics, but not the same code path by default. The core-layer
aggregator's default matcher is deliberately coarse (pool/resource
identity and quantitative dimensions only) — it cannot depend on any
kit-layer package, so it cannot know a domain's categorical attributes
(region, GPU model) the way the site's own admission path does. A
domain composing the aggregator MAY inject an exact `ClaimMatcher` that
delegates to its backing site's own authoritative matching function,
so ranking and admission agree on every field the site actually checks,
without moving site-specific matching logic into the core layer. This
is composition, not a shared implementation: the aggregator's own
default remains available to any domain whose backing site doesn't
warrant the exact match, and the same package-layering rule that keeps
core backend-agnostic still applies.

## Current limits

The current ledger is not a distributed consensus system for active-active replicas. Generic deal-event ownership across arbitrary storefront topologies and universal aggregation across every physical resource type are not established by the capacity contract.

## Related contracts

- [Storefront publication](../storefront-publication/spec.md)
- [Fulfillment](../fulfillment/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
