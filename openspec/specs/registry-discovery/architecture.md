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

The resource-query compiler therefore reads the active filter specification before parsing field semantics. Aliases, accepted operators, types, and missing-value rules come from that document rather than a VM-specific CLI table. The compiled canonical parameters retain the same ETag and behavior-affecting values enter the signed semantic request body.

This pushdown boundary is semantic, not a promise about physical execution. A declared predicate can be evaluated through the registry's current scan path whether or not metadata mentions indexing. Explanation reports that the registry owns the predicate; it does not claim an index or alternate route. A future indexed path must first prove semantic equivalence under its own activation contract.

## Configuration boundary

A registry may load another vocabulary on restart, but safe live rotation and coexistence of incompatible client generations are separate rollout concerns. The baseline does not treat a configured registry as a universal domain interpreter.

## Self-description boundary

The well-known registry descriptor assembles facts without creating a second
authority for them. Its principal comes from the loaded response signer, its
schema identity comes from the active filter specification, and its access
posture comes from the read gate. Only the public base URL, display name,
operator identity, and—when reads are gated—the acquisition pointer are
operator-authored configuration. Contradictory or incomplete inputs stop
startup.

The descriptor is returned through the ordinary authenticated registry
exchange. Its response proof shows that the named principal controls the
active signing credential. That is proof of possession, not an endorsement of
the claimed URL or operator. A directory may separately curate and sign the
portable descriptor body; that offline assertion is a different trust layer
from the registry's online response proof.

## Injected signer boundary

The registry client depends on the scheme-neutral signer interface rather than a raw key or an address. The signer exposes only its canonical public principal and signing operation, so Ed25519 and EIP-191 follow the same client and server path and private material does not enter request models, listing payloads, logs, or registry persistence. The registry resolves the exact `{scheme, identifier}` to a stable publisher; it never infers ownership from identifier shape.

## Body-bound exchanges and durable replay

The version 2 marketplace envelope binds the complete canonical request body, semantic mutation, resource, caller role and principal, request identity, and time. The route supplies the expected operation and resource independently of URL spelling, and query inputs that affect discovery are represented in the signed semantic body. Authentication precedes schema validation and dispatch, ensuring a valid proof cannot accompany altered listing fields.

Registry responses are authenticated in the opposite direction. Their proof binds the authority principal, request identity, operation, resource, status, timestamp, and response body; the client checks it against an explicit registry trust set before treating a publication, read, update, close, or rotation result as authoritative.

Replay reservations are durable database state keyed by principal and request ID. A reservation is acquired before dispatch and leased to one attempt. Changed reuse is rejected, a concurrent attempt cannot run beside the lease owner, and an expired unfinished lease can be reclaimed. Once complete, the recorded status and body are returned under a newly signed response for an exact retry. This makes retry after a lost acknowledgement safe without weakening request freshness or duplicating a mutation.

## Publisher principal rotation

Publisher identity history is separate from publisher and listing records. Rotation proves possession of both the active current principal and the replacement over one canonical intent scoped to the stable publisher and this registry authority. A nonce and intent hash make application idempotent; row locking, uniqueness constraints, and a single-active-overlap rule serialize competing ownership transitions.

The replacement becomes primary immediately. The old credential is either retired immediately or remains an active overlap credential until the bounded deadline, and only the replacement primary can retire it early. The registry exposes the recorded rotation state so a multi-authority coordinator can verify convergence before retiring an old credential elsewhere; no cross-service database transaction is assumed. Neither rotation nor retirement rewrites publisher IDs, listing IDs, or listing ownership.

## Retained publication documents

A registry stores the complete body a publication was admitted with, as one JSON document, and serves it with its own fields overlaid: publisher identity and principals, creation and update times, and the publication and update evidence below. Every term the configured schema admits survives, including properties the schema does not name and explicit nulls, so a domain adds a listing term by declaring it in its filter specification, with no registry code change. Keeping the body whole is less fragile than mirroring the listing schema in database columns, and it is what keeps the registry opaque to domain payloads: the alternative, keeping only a fixed set of carriers, would acknowledge a term and then discard it, and pushes every new commercial term into the capacity description, where it does not belong.

Publication authenticates first, then validates the complete body against the configured listing shape, as the dry run does, so the dry run and publication cannot disagree on whether a listing is valid; a publisher sends a complete schema-valid document, never a patch. A refused publication or republication changes nothing: the listing last stored stays in place and served. Names the registry owns in its responses are refused at publication by that exact list, so a published document cannot spoof registry metadata or seller evidence. A current limit: by default a registry admits publication from any self-generated key (`REGISTRY_REQUIRE_WRITE_API_KEY` defaults to false) and sets no request-body size limit, so nothing but the schema bounds what a retained document holds; write hardening is an unowned gap in the [change index](../../changes/README.md).

Republication replaces the document whole. A term the publisher omits disappears, and a null is kept as a null rather than read as a request to keep an old value: a per-field merge would leave a withdrawn term live. Listing and publisher identity and creation time stay stable; status survives a republication that states none, since close and reopen are explicit updates. The update route stays narrow, status and oracle address alone, and refuses any other key by name rather than discarding it.

A row stored without a document is served by rebuilding the old discovery shape from its carrier columns, with null publication evidence. Nothing backfills such rows: a backfill cannot recover a term the carriers discarded or a signature never kept, and nothing may attribute either to the seller. The seller's next valid republication stores the document and its proof together. On every other row the carriers other than `oracle_address`, which the update route still writes, are stale and are not read. Filters evaluate the served document, rebuilt rows included, so indexed execution, when activated, must project the document and match rebuilt rows rather than read the carriers. A rebuilt row carries no `pricing`, so it drops out of asking-rate filters until republished.

A listing's signed `storefront_url` is its own, so a storefront that moves reaches each listing at its next republication; the publisher record's URL serves rebuilt rows and the publisher detail. The database revision that adds the document and evidence columns refuses to downgrade, because dropping them would discard every retained document and seller proof, which the carriers cannot rebuild; rollback is restoring the pre-upgrade backup.

## Seller publication evidence

The registry's response signature proves what the registry served, not what the seller published. A listing therefore also carries the seller's own evidence: `publisher_publication` holds `body_base64`, the exact HTTP body bytes received, and `request`, the complete authenticated version 2 envelope — principal, operation, resource, request ID, timestamp, body hash, and proof. The marketplace signature binds the canonical JSON hash, not whitespace; keeping the transport bytes preserves the original representation without pretending the protocol signs it. No secret is retained, and the per-row size is acceptable at this scale.

A consumer verifies a listing's terms by decoding the body, checking its canonical hash and the envelope's signature, checking the listing identity and the `listing.publish` operation, and then reading the terms from that verified body. Historical verification uses the signed timestamp, not the live request freshness window. The registry attests which keys belong to the publisher, in `publisher_principals` at read time; the seller's proof attests the terms. One consequence of rotation follows: a listing signed by a key since retired no longer verifies until its seller republishes. An independent seller identity beside the registry-attested keys is a candidate for that write hardening. A rebuilt row has no seller evidence, and says so with nulls.

Status and oracle updates do not rewrite the publication evidence. `publisher_updates` holds, per mutable field, the latest signed update in the same `{body_base64, request}` shape, so an oracle change is never presented as part of the original signed publication. A republication replaces the publication evidence and clears the oracle update's, since it replaces the commercial content; it keeps the status update's when it states no status. Full mutation history is not kept; a consumer that needs it, or a versioned identity protocol that changes the envelope, is the trigger to revisit the shape.

## Listing pricing and the resize carrier

A compute listing's listing-level prices travel together in one top-level `pricing` object: the `asking_rate` that rate filters read, and, for a shape-priced listing, the `rate_structure` of resolved family rates its prices derive from, keyed directly by family. A settlement option's price stays with its option, and the capacity description carries no price. The compute specification declares the object and names no family; the registry stores and serves it like any admitted term and never names or calculates a rate, so a domain's rate vocabulary belongs to its publication codec and schema, never to registry storage.

The specification refuses a price at its earlier locations, `listing_resource.asking_rate` and a top-level `rate_structure`, naming the replacement in the refusal, as it refuses its other retired names: admitted, a rate there would publish, store, and match no rate bound, and its seller would get no signal. Reading both locations was rejected, since it needs a precedence rule and temporary logic in every reader. Registries and storefronts therefore upgrade together: a storefront writing the earlier location is refused by a registry that requires `pricing`, visibly, and a registry that keeps only named carriers drops `pricing` with every other unnamed term. No publisher reads its registry's specification to adapt, which would be a new interface across every domain.

A buyer pricing a shape the listing does not offer reads `pricing.rate_structure` from the registry listing and can check it against the seller's publication evidence, so the registry is the carrier of the seller's own rates rather than an authority on them. Whether and how a buyer verifies before pricing is decided where the buyer's resize negotiation is built; no buyer reads the evidence today. A rebuilt row has no seller evidence to verify, and a buyer sees a local rate change only once its seller republishes.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)

## Buyer fan-in identity

Buyer discovery retains registry provenance because subsequent publisher-trust
refreshes resolve through the selected authority. Its merge key is the stable
registry authority plus publisher-chosen listing ID, not the URL or listing ID
alone. Multiple endpoints for one authority can represent the same record;
independent registries do not establish shared ownership merely by returning
equal IDs. Cross-authority advertisement equivalence requires a separate trust
contract and is not inferred by discovery.

Ordinary discovery can report an unavailable registry and retain other results.
Resource-query and explain paths require all authenticated query preparations
to succeed, preventing an unavailable or incompatible registry from silently
changing the requested search scope.
