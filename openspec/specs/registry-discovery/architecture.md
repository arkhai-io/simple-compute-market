# Registry Discovery Architecture

The [normative contract](spec.md) defines publication and query behavior. This document explains why the registry is the schema-centralizing boundary for one market composition.

## Discovery-schema authority

A registry operator chooses one active listing/filter vocabulary. The registry validates publication and evaluates discovery filters against that vocabulary while remaining opaque to domain payload meaning beyond configured validation and indexing rules.

```text
storefront publication
        ↓ signed mutation
registry validation and storage
        ↓ schema-defined query
buyer discovery
```

Centralizing filter meaning prevents every buyer and storefront from independently inventing discovery semantics. Domain packages still own interpretation of listing fields; the registry owns whether a document conforms and how declared filter operations are evaluated.

## Publisher authority

Signed publication is both authentication and mutation authority. A valid first publication can establish publisher identity without a separate preregistration service or chain lookup. Later replacement and removal remain bound to that identity, so possession of a listing identifier alone is insufficient to mutate another publisher's state.

Storefront-local listing state is not global discovery truth. A storefront decides what it intends to advertise; the registry decides which signed publication is currently visible under its configured schema.

## Query-semantic concurrency

The filter specification has an entity tag because a query has meaning only under the vocabulary against which it was constructed. `If-Match` protects a client from silently submitting an old query after operator configuration changed:

```text
read filter specification + ETag
        ↓ construct query under that meaning
query with If-Match
        ↓
execute, or reject if meaning changed
```

This is stronger than ordinary cache freshness. It is semantic concurrency control. Clients that omit the precondition do not receive that protection, and the ETag does not by itself provide rolling compatibility across non-additive schema changes.

## Configuration boundary

A registry may load another vocabulary on restart, but safe live rotation and coexistence of incompatible client generations are separate rollout concerns. The baseline does not treat a configured registry as a universal domain interpreter.

## Related contracts

- [Market composition](../market-composition/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
