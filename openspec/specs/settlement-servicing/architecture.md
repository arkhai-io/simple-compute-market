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

Core owns restartable lifecycle structure and stable claim state. It does not understand an oracle predicate, token transfer, or domain-specific evidence. This lets persistence, retries, and operator inspection remain consistent while mechanism implementations evolve independently.

## Plan and codec boundary

A plan carries lifecycle-universal fields and versioned mechanism payloads. Kit codecs translate between shared carriers and mechanism-specific obligations. Domain policy selects conditions and interprets their business meaning.

Keeping codecs explicit is safer than generic dispatch on an arbitrary escrow-kind string: each supported `(kind, schema_version)` has an owning validator and materializer, and unknown versions fail instead of being guessed into a current model.

## Claims and persisted hook state

Claim servicing records enough state to retry condition checks and collection without reconstructing decisions from mutable configuration. Hook scratch state is part of the servicing record when a mechanism needs a cursor, receipt, or retry token. It is not an invitation to persist arbitrary provider objects.

Condition interpretation and collection remain separate because an asynchronous condition may be false many times before collection is valid. Same-wallet chain operations may need serialization to avoid nonce races, but that mechanism constraint does not become a generic marketplace lock.

## Heartbeat evidence

A heartbeat timestamp serves two purposes: it is part of the signed value and the monotonic replay key for one deal. Signature verification proves authorship; bounded clock skew and strict monotonicity prevent capture of an older valid heartbeat from extending an obligation after a newer one was accepted. Domain code owns the heartbeat payload's meaning, while core owns authentication and replay protection.

## Capacity coupling

Commercial abandonment may request early physical termination, but it does not directly free capacity. Settlement servicing shortens or ends the relevant lease intent; physical provisioning must still prove teardown before the site authority releases capacity.

## Current limits

The baseline does not provide a universal `service(plan) → receipt` implementation, arbitrary plan materialization, or generic reclaim for every future mechanism. Compatibility coercions for older plan shapes are not the enduring extension model.

## Related contracts

- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
