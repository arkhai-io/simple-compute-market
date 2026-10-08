# Settlement Servicing Architecture

The [normative contract](spec.md) defines Agreement-based payments, plans, claims, and heartbeat behavior. This document distinguishes obligation servicing from receipt-gated payment delivery.

## Servicing lifecycle

Some obligations complete immediately; others depend on conditions that become true later. For Alkahest and other obligation-runtime mechanisms, settlement produces a plan persisted and serviced over time:

```text
accepted Agreement
      ↓ materialize
SettlementPlan
      ↓
active obligations ── evaluate ── collect / abandon / expire
```

The settlement-runtime kit owns restartable lifecycle structure and stable obligation state. It does not understand an oracle predicate, token transfer, or domain-specific evidence. Core supplies schema-opaque carriers and storefront composition contracts; persistence adapters, retries, and operator inspection remain consistent while mechanism implementations evolve independently.

## Plan and codec boundary

Existing plans carry participant, value, and escrow lifecycle fields and versioned mechanism payloads. Kit codecs translate between shared carriers and mechanism-specific obligations. Domain policy selects conditions and interprets their business meaning.

Keeping codecs explicit is safer than generic dispatch on an arbitrary escrow-kind string: each supported `(kind, schema_version)` has an owning validator and materializer, and unknown versions fail instead of being guessed into a current model.

## Conditional-escrow clients and durable mechanism state

Obligation-runtime mechanisms satisfy the shared `ConditionalEscrowClient` port for
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

Marketplace authorization binds payer, claimant, storefront, and service actors as complete scheme-tagged principals throughout plans, fulfillment references, heartbeats, start/status/reclaim requests, claims, and operation-journal reservations. Bare identifiers, payment account references, provider identifiers, and EVM addresses inside mechanism payloads are resources or effect inputs, not credentials.

A principal is a credential identity, while agreement, obligation, account, and
provider references remain stable subjects or resources. The mechanism-neutral
runtime therefore carries principals opaquely and never derives or persists a
wallet or private-key alias from them.

Wallet and chain configuration is mechanism-scoped. Arkhai payment calls use owner-scoped WorkOS credentials; signed receipt verification uses the trusted service's Ed25519 identity, with no EVM wallet or RPC dependency. Alkahest validates its own chain inputs without reinterpreting marketplace principals.


## Configuration and durable runtime state

Typed registration controls readiness, publication, and selection. Alkahest and contact exchange use the obligation lifecycle and operation journal. Arkhai payments consumes accepted Agreement bytes and its persisted mandate directly and does not produce a plan or obligation.

Current priority and readiness govern new deals only. Recovery uses exact accepted state and the same transaction or obligation identity.

## Accepted domain continuity

The accepted negotiation binding is a second routing dimension beside the
settlement mechanism. It selects the domain plan builder and schema-opaque
fulfillment hook while the mechanism registry selects financial effects. Core
carriers retain the accepted buyer, site, mode, domain payload, and public
operation identity without provider configuration or credentials. Hooks return
validated lifecycle projections, including a domain result that is decoded by
only the selected contract.

Fulfillment contexts persist the exact binding and site. Restart, result
retrieval, failure handling, and teardown compare those values before any call;
they do not consult current listings or payload kinds. Provisioning remains the
executor authority and dispatches teardown from its durable offering mode, so
the storefront never derives VM versus bare-metal teardown locally.



## Charge-first payment settlement

The seller derives the mandate at acceptance from exact Agreement bytes, the selected option, and buyer `settlement_params.payer_account`. The mandate lives in shared `negotiation_threads.settlement_data` next to `agreement_bytes`, not a per-domain mandate table. Transaction identity is `sha256(JCS(mandate))`; deal identity is `sha256(JCS(agreement))`. Whole-second hold intervals round up and approval expiry rounds down, without changing accepted timestamps.

Buyer approval validates both the mandate and local policy. Buyer and seller poll the same deterministic transaction ID; seller settlement reloads accepted state by negotiation ID and verifies the signed receipt against it. A pending transaction authorizes no domain effect. Retries return completed state or re-drive nonterminal provisioning/issuance with the same durable identity.

VM and bare-metal retain selected-site physical authority and teardown; API credits retains its grant and credential authority. Those domain journals are not ledger state. Refund uses `reverse`; hold release, fees, disputes, and cash movement remain payments-service responsibilities. The kit has no servicing daemon.

## Current limits

Heartbeat evidence remains persisted but is not an automated adjudication
policy. Evidence freshness, neutral oracle authority, disputed outcomes, and
splitter/oracle contract selection require a separate accepted design.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
