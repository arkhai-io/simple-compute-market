# Contact Exchange Architecture

The [specification](spec.md) owns introduction settlement behavior. The contact
kit owns public profiles/options, the non-financial mechanism, start/read
orchestration, and reveal persistence. Bare-metal callbacks interpret accepted
domain state and authorize its canonical parties; the shared settlement runtime
owns obligation transitions.

## Acceptance and capture

Acceptance freezes public commercial context, not contacts. New bare-metal
contact acceptances persist the plan and pending obligation identity together,
so a party can resolve the reference before sharing. The
[shared transaction seam](../market-composition/architecture.md#accepted-plan-persistence)
performs bookkeeping only. Opening transcripts are outside that transaction;
contact capture and lifecycle effects occur later.

Explicit buyer-authorized start supplies the buyer contact and captures the
configured seller contact with the accepted introduction package. The reveal is
persisted before completion. Completion uses the existing materialize/check/
collect lifecycle and an introduction reference, not a physical reservation or
executor. If completion fails, the durable reveal remains readable; an identical
start can retry completion. Different payloads conflict rather than replace the
record.

Party reads return only the counterparty contact and accepted context. They do
not capture contact or service the obligation. Registered but unstarted references
return signed pending HTTP 409, including after restart. An opaque reference alone
cannot locate an old plan without bookkeeping: it remains HTTP 404 until an
ordinary authorized start supplies the negotiation identity. There is no scan,
backfill, or parallel lookup authority.

## Composition and optional delivery

Introduction-only bare-metal operation is derived from the enabled mechanism
set, not a deployment flag. No site, capacity, provisioning, chain, or hosted
financial runtime is needed. An unbacked binding records absent authority; machine
and host labels are descriptive, not provisionable supply.

General contact composition can inject [recipient-side delivery](../introduction-delivery/spec.md). The seller sends
its view to its own configured sinks; the buyer CLI can deliver its view to its
own sinks. Delivery is best-effort and non-authoritative. The synthetic
[file publisher](../storefront-publication/architecture.md#synthetic-contact-file-publication)
requires that seller delivery be absent; this does not remove optional delivery
from other contact compositions. A delivered copy is outside marketplace
retention control.

## Privacy boundary

Contact payloads are deliberately persisted, bounded PII. The deletion primitive
removes a reveal without deleting its settled obligation; automatic retention
and encrypted-at-rest storage are not supplied by the contact kit.

`contains_contact_value` compares each configured nonempty contact value with
decoded public string keys and values recursively through mappings and arrays.
Profile validation, option construction, accepted-obligation construction, and
file publication share it. JSON escaping changes serialized representation, not
the public string the recipient sees, so serialized-JSON substring matching would
miss literal leaks.

This guard is case-sensitive literal matching. It does not infer unconfigured
private data, normalize Unicode or case, parse URLs, or undo arbitrary encodings.
Operators remain responsible for keeping all public inputs free of private data;
the guard is not general data-loss prevention.

## Frozen text and accepted listing context

The private `ContactText` profile reuses one existing `text` entry, preserving one complete reviewed blurb within the established 512-scalar limit. It does not reinterpret arbitrary old contact maps. Routes remain independently owned and private. Review commits to exact text, own route, parties, the full accepted package and seller snapshot; context drift therefore invalidates a prior review without a second approval mechanism.

Explicit `context_contract: "accepted-listing.v1"` eligibility separates new capture from historical packages. Bare-metal acceptance validates an immutable declaration intent and selected option, captures the machine facts and non-access terms, and gives the kit an opaque domain value. The kit hashes that value into the obligation. This avoids a recursive plan hash and any upward domain dependency. Protected accepted lookup checks the stored context against the obligation rather than reconstructing it from registry or current configuration. Public fact digests are not substitutes for the keyed, private review fingerprints.

The [source carrier tables](spec.md#primitive-rules) own exact shapes, Unicode rules, digests, failure behavior and versions. Declaration/file admission is described by [storefront publication](../storefront-publication/spec.md#requirement-general-declaration-input-has-finite-strict-bounds). No historical plan or obligation is backfilled.

## Reviewed exchange and recipient rendering

The explicit delivery policy uses the same accepted package and immutable contact
record as protected party reads. Review binds caller text/route and the seller
snapshot; finalization captures one record and two awaiting-completion intents
in the role-owned SQLite transaction. Completion and SMTP are different stages:
only journaled settlement success releases intents, while a committed retry
observes the record without taking another completion lease.

Accepted profile terms and channel belong to the accepted package, not current
configuration. Their later edits and SMTP credential rotation do not change the
reviewed facts. Seller contact/route drift still invalidates a pending review;
missing required configuration remains unavailable. No extra fingerprint or
schema is needed. After capture the record and routes remain frozen, and terminal
recipient states remove routing data from the intents.

A caller validating a signed acceptance must compare the package, obligation
params and conditions against independently retained advertised option,
declaration, machine and requested-term expectations. Internal digest consistency
alone does not establish that the seller returned the caller's selection. The
shared buyer performs universal acceptance checks before invoking its supplied
callback; it imports no storefront validator.

The [delivery renderer](../introduction-delivery/architecture.md) consumes only
recipient projections of this record. Neither rendering nor recovery recaptures
machine facts from the registry. Local fake-SMTP and lost-HTTP-response tests
qualify these source boundaries, not inbox delivery or exactly-once delivery.
