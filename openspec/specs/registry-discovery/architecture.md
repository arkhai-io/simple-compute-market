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

## Stable publisher and listing subjects

Cryptographic principals are credentials; publishers and listings are durable registry subjects. A valid first publication can establish a publisher without a separate preregistration service or chain lookup, but later replacement and removal resolve the caller's complete canonical principal to that stable publisher. Possession of a listing identifier, an identifier text that matches under another scheme, or a body-level ownership claim is therefore insufficient.

The publisher chooses the listing identifier and signs it with the rest of the publication body. Reusing that identifier by the same publisher addresses the existing listing, while a different publisher cannot take it over. Keeping registry-assigned publisher identity and publisher-chosen listing identity independent of the current credential lets key rotation and schema migration preserve discovery URLs, replay outcomes, and storefront recovery state.

Storefront-local listing state is not global discovery truth. A storefront decides what it intends to advertise; the registry decides which authenticated publication is currently visible under its configured schema.

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

## Injected signer boundary

The registry client depends on the scheme-neutral signer interface rather than a raw key or an address. The signer exposes only its canonical public principal and signing operation, so Ed25519 and EIP-191 follow the same client and server path and private material does not enter request models, listing payloads, logs, or registry persistence. The registry resolves the exact `{scheme, identifier}` to a stable publisher; it never infers ownership from identifier shape.

## Body-bound exchanges and durable replay

The version 2 marketplace envelope binds the complete canonical request body, semantic mutation, resource, caller role and principal, request identity, and time. The route supplies the expected operation and resource independently of URL spelling, and query inputs that affect discovery are represented in the signed semantic body. Authentication precedes schema validation and dispatch, ensuring a valid proof cannot accompany altered listing fields.

Registry responses are authenticated in the opposite direction. Their proof binds the authority principal, request identity, operation, resource, status, timestamp, and response body; the client checks it against an explicit registry trust set before treating a publication, read, update, close, or rotation result as authoritative.

Replay reservations are durable database state keyed by principal and request ID. A reservation is acquired before dispatch and leased to one attempt. Changed reuse is rejected, a concurrent attempt cannot run beside the lease owner, and an expired unfinished lease can be reclaimed. Once complete, the recorded status and body are returned under a newly signed response for an exact retry. This makes retry after a lost acknowledgement safe without weakening request freshness or duplicating a mutation.

## Publisher principal rotation

Publisher identity history is separate from publisher and listing records. Rotation proves possession of both the active current principal and the replacement over one canonical intent scoped to the stable publisher and this registry authority. A nonce and intent hash make application idempotent; row locking, uniqueness constraints, and a single-active-overlap rule serialize competing ownership transitions.

The replacement becomes primary immediately. The old credential is either retired immediately or remains an active overlap credential until the bounded deadline, and only the replacement primary can retire it early. The registry exposes the recorded rotation state so a multi-authority coordinator can verify convergence before retiring an old credential elsewhere; no cross-service database transaction is assumed. Neither rotation nor retirement rewrites publisher IDs, listing IDs, or listing ownership.

## Atomic legacy identity migration

Supported legacy address-owned state is converted to canonical `eip191` bindings as one schema transaction. The migration validates the complete publisher, identity, and listing population before removing legacy ownership columns: principal normalization and uniqueness, exactly one active owner binding, stable publisher mapping, listing referential integrity, and non-conflicting storefront ownership must all hold.

Preserving publisher and listing identifiers avoids turning an identity-format change into resource replacement. Aborting the whole transaction on malformed identities, cross-scheme ambiguity, duplicate bindings, partial conversion, or missing references avoids a mixed schema in which different routes could disagree about authority. Rollback is therefore safer than a best-effort row-by-row conversion.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
