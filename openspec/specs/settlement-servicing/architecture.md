# Settlement Servicing Architecture

The [normative contract](spec.md) defines plans, claims, and heartbeat behavior. This document explains why settlement is modeled as a lifecycle rather than a terminal payment receipt.

## Servicing lifecycle

Some obligations complete immediately; others depend on conditions that become true later. Settlement therefore produces a mechanism-neutral plan that can be persisted and serviced over time:

```text
accepted Terms
      ↓ materialize
SettlementPlan
      ↓
active obligations ── evaluate ── collect / abandon / expire
```

The settlement-runtime kit owns restartable lifecycle structure and stable obligation state. It does not understand an oracle predicate, token transfer, or domain-specific evidence. Core supplies schema-opaque carriers and storefront composition contracts; persistence adapters, retries, and operator inspection remain consistent while mechanism implementations evolve independently.

## Plan and codec boundary

A plan carries lifecycle-universal fields and versioned mechanism payloads. Kit codecs translate between shared carriers and mechanism-specific obligations. Domain policy selects conditions and interprets their business meaning.

Keeping codecs explicit is safer than generic dispatch on an arbitrary escrow-kind string: each supported `(kind, schema_version)` has an owning validator and materializer, and unknown versions fail instead of being guessed into a current model.

## Conditional-escrow clients and durable mechanism state

Mechanism implementations satisfy one `ConditionalEscrowClient` port for
materialize, authoritative status, check, collect, and expired reclaim. They
receive a stable operation reference and may return only public-safe opaque
references, actions, anchors, receipts, and mechanism state. The repository
persists returned mechanism state even when a condition remains pending. This
is what makes request-once/poll workflows survive restart without repeating an
external mutation.

Condition interpretation and collection remain separate because an asynchronous condition may be false many times before collection is valid. Same-wallet chain operations may need serialization to avoid nonce races, but that mechanism constraint does not become a generic marketplace lock.

## Obligation identity and competing terminal effects

Plan identity stays out of the negotiation wire carrier. The servicing
repository combines a stable agreement reference, ordered obligation index,
and canonical validated obligation snapshot to derive an immutable
`obligation_ref`. This keeps legacy model dumps stable while giving every
mechanism operation one durable idempotency boundary.

Materialization, condition evaluation, collection, and reclaim have separate
state because their failure and recovery semantics differ. Mutation attempts
are journaled before external I/O; uncertain acknowledgement is retained so a
restart retries the same operation rather than inventing a new effect.
Collection and reclaim use one database serialization point because they are
financially exclusive even when separate workers and roles initiate them.

Aggregate status is derived from obligation rows rather than stored as another
authority. Partial completion is a normal inspectable state: a completed
payment does not erase a bond that needs repair, and a failed bond does not
replay a completed payment.

## Interval and bond policy

Intervals allocate accepted integer value in proportion to each interval's
duration, then distribute the bounded rounding remainder to the earliest
intervals. This rule is deterministic on both sides and conserves the accepted
total without zero-value mechanism obligations.

A penalty bond is an ordinary directional obligation, not a special runtime
branch. Policy changes payer and claimant to seller and buyer while preserving
the accepted mechanism demand. The same materialize/check/collect/reclaim
engine therefore handles payment intervals and bonds.

## Heartbeat evidence

A heartbeat timestamp serves two purposes: it is part of the signed value and the monotonic replay key for one deal. Signature verification proves authorship; bounded clock skew and strict monotonicity prevent capture of an older valid heartbeat from extending an obligation after a newer one was accepted. Domain code owns the heartbeat payload's meaning, while core owns authentication and replay protection.

## Capacity coupling

Commercial abandonment may request early physical termination, but it does not directly free capacity. Settlement servicing shortens or ends the relevant lease intent; physical provisioning must still prove teardown before the site authority releases capacity.

## Current limits

Heartbeat evidence remains persisted but is not an automated adjudication
policy. Evidence freshness, neutral oracle authority, disputed outcomes, and
splitter/oracle contract selection require a separate accepted design.

## Related contracts

- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
