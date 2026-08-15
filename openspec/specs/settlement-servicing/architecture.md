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

Heartbeat authorization resolves the signer as the complete scheme-tagged
principal assigned to the deal buyer. Matching identifier text under another
scheme does not authenticate evidence even when the signature itself is
cryptographically valid for that other principal.

## Capacity coupling

Commercial abandonment may request early physical termination, but it does not directly free capacity. Settlement servicing shortens or ends the relevant lease intent; physical provisioning must still prove teardown before the site authority releases capacity.

## Principal and mechanism boundaries

Marketplace authorization binds payer, claimant, storefront, and service actors as complete scheme-tagged principals throughout plans, fulfillment references, heartbeats, start/status/reclaim requests, claims, and operation-journal reservations. Bare identifiers, hosted account references, provider identifiers, and EVM addresses inside mechanism payloads are resources or effect inputs, not credentials.

A principal is a credential identity, while agreement, obligation, account, and
provider references remain stable subjects or resources. The mechanism-neutral
runtime therefore carries principals opaquely and never derives or persists a
wallet or private-key alias from them.

Wallet and chain configuration is mechanism-scoped. A hosted non-EVM obligation materializes, checks, collects, reclaims, and reconciles through an injected marketplace signer without an EVM wallet or RPC dependency. An Alkahest transaction or explicitly EVM-tagged condition validates its own address, wallet, RPC, chain, and contract inputs inside the owning adapter and never reinterprets an Ed25519 principal.

## Hosted identity ownership

The hosted adapter passes the marketplace signer through the exact manifest-pinned hosted client identity interface. Hosted canonicalization, headers, scheme wrappers, response verification, account-link behavior, and provider models remain owned by that released client. The adapter neither reproduces those bytes nor persists its private credential. Startup and publication preflight require the released manifest to advertise the configured principal scheme and contract version; otherwise the hosted mechanism remains unavailable.

## Configuration and durable runtime state

Typed mechanism registration controls which clients are constructed and which new options may be published. It does not create another runtime or status authority: every enabled client dispatches through the same obligation identity, operation journal, leases, retries, claim engine, and aggregate projection.

Configuration and readiness are admission inputs, not durable-plan interpreters. Once Terms are accepted, the stored canonical mechanism, exact parameters, payer/claimant direction, and operation identities govern recovery. Disabling or deprioritizing a mechanism may stop new publication, but funded obligations continue authoritative status, collection, and reclaim convergence through their original client.

## Profile-bound hosted servicing

New hosted settlement records bind the accepted funding profile and the operation-scoped authorization reference without changing the already derived agreement or obligation identity. The binding is immutable and participates in the materialization operation fingerprint, so an exact retry can converge after an unknown acknowledgement while changed reuse fails before another financial effect.

Only the hosted authority's normalized `funded` result after the selected profile's success and availability gate releases the VM fulfillment lease. Redirect completion, confirmation, transfer instructions, pending ACH, webhook timing, and local policy are not funding evidence. Provider-neutral reason, deadline, and action metadata may be projected, but raw URLs and provider payloads are transient and authority-owned.

Reclaim uses the same opaque settlement and operation identity and never asks marketplace code to choose refund, return, reversal, or dispute behavior. A pre-collection return blocks collection; a post-fulfillment/pre-collection return preserves fulfillment attribution while domain teardown and hosted financial recovery converge independently. A post-collection loss becomes operator-required state rather than rewriting completed marketplace identities.

## Current limits

Heartbeat evidence remains persisted but is not an automated adjudication
policy. Evidence freshness, neutral oracle authority, disputed outcomes, and
splitter/oracle contract selection require a separate accepted design.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
