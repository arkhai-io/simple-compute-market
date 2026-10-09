## Why

The settlement slot is shaped like the first mechanism that filled it. Alkahest is escrow: money stays the payer's until a condition is proven, and the payer reclaims after expiry. `SettlementObligation` carries that model as typed "lifecycle universals" (`claimant`, `expiration_unix` as the collect-vs-reclaim boundary, `conditions`), and `ConditionalEscrowClient` gives every mechanism escrow verbs (`materialize`, `check`, `collect`, `reclaim_expired`).

Fiat is charge-first: money moves at payment and is undone by refund or dispute. Fitting the hosted Stripe mechanism to the escrow shape produced most of its friction, for example escrowing a maximum amount up front and refunding the unused rest instead of charging the actual amount once it is known. The hosted Stripe service (consumed through `kit/hosted-settlement` as `fiat.stripe.v1`) is being replaced by the Arkhai payments service: a balance ledger on Formance where a buyer approves a mandate from their Arkhai account and receives a service-signed receipt. Its v1 serves fixed-interval deals.

## What Changes

- **The deal is a pipeline, negotiate → settle → provision.** Each stage understands the output of the stage before it and nothing else. A stage may discriminate on its input internally, and stages may fuse, as `contact-exchange.v1` fuses settle and provision. There is no shared adapter API; each mechanism defines its own API towards the domains that support it.
- **Core defines only what at least two of buyer, seller and registry read.** For settlement that is the listing's `settlement_options` and the selected option in the accepted deal. Mechanism status, servicing and refunds belong to the mechanism and the domain.
- **Negotiation emits one explicit Agreement on acceptance**, the output a settle stage consumes. Both parties keep the exact bytes. Core does not define its hash; a settle stage that needs one defines it.
- **Add `arkhai.payments.v1`**, a stateless kit over the Arkhai payments HTTP API, as a peer of Alkahest in the VM, bare-metal and API-credit domains. The seller's kit derives the mandate from the Agreement, with `deal = sha256(JCS(agreement))`, and returns both at acceptance, so both parties know the transaction ID before approval. The buyer approves with its owner's credentials and polls; the seller polls the same ID and delivers once the signed receipt matches. Holds release without SCM calls, so the kit keeps no servicing state and runs no daemon.
- **One payments mechanism implementation.** The kit owns Agreement-to-mandate policy, one `settlement_data` wire shape, buyer approval, the seller receipt check with a typed outcome (pending, verified, invalid, unavailable, or blocked), the seller's Agreement deposit, and reversal. Domains keep payer-account sourcing, HTTP binding, delivery, journals and recovery.
- **Agreement settlement through the typed storefront client.** `StorefrontClient` gains `settle_agreement(negotiation_id)`; the EVM method is renamed `settle_evm`. The settle response carries mechanism-neutral `negotiation_id`, `settlement_ref`, a reserved `pending` status and `retryable`. All three domains verify payment and start delivery in `settle`.
- **Receipt outcomes are classified, not inferred.** Pending is retryable 202, an unreachable or transiently failing service is retryable 503, and a receipt that does not prove the Agreement is non-retryable 409 with no state persisted. A fault in the seller's own integration (a refused credential, an unknown account, a protocol violation, or a non-matching attachment) is blocked: 500, logged as an error for the operator, and never presented as an outage.
- **Agreement attachment is two owned policies.** A buyer-role `attach_agreement` setting, off by default, decides whether the buyer attaches at approval. The seller deposits when its option advertises `deposit_agreement`, after receipt verification and before delivery.
- **Refunds are seller-initiated only.** A seller-authenticated `POST /api/v1/settlements/{negotiation_id}/refund` (`StorefrontClient.refund_settlement`) reverses still-held funds and records a terminal `refunded` state. A storefront's opt-in `refund` failure action also reverses payment deals that fail before any delivery. The normal deal flow never refunds; the buyer's recourse is a dispute.
- **Delete `fiat.stripe.v1` and `kit/hosted-settlement`.** The hosted-fiat changes built on them are superseded (see design).

## Capabilities

### Modified Capabilities

- `settlement-configuration`: hosted funding profiles, release pins and Stripe registration are removed; `arkhai.payments.v1` registers as a peer mechanism with a buyer-role attachment policy.
- `settlement-servicing`: Arkhai payments settles charge-first from the Agreement with classified receipt outcomes, owned attachment policies, and seller-initiated refunds; the obligation servicing lifecycle remains in place for Alkahest and contact exchange.
- `negotiation-protocol`: acceptance produces an explicit Agreement and opaque settlement data.
- `market-composition`: domains compose settle and provision stages rather than an escrow client.
- `buyer-orchestration`: payment buyers approve through the kit and settle by negotiation ID.
- `test-compatibility`: payment tests obtain signed receipts from a vector-pinned kit fixture.

## Non-Goals

- **Moving escrow semantics into `alkahest.v1`.** `claimant`, `claimant_principal`, `expiration_unix` and `conditions` stay on `SettlementObligation`, the listing keeps `accepted_escrows`, and `ConditionalEscrowClient` stays in `kit/settlement-runtime`. Arkhai payments bypasses those carriers. This is an unowned follow-up recorded in the roadmap.
- Identity and negotiation as advertised listing slots, and per-stage kit declarations.
- Rate parts, and spot and interruptible deals through `arkhai.payments.v1`. They come next in `spot-deals-through-arkhai-payments`. This change settles `once` parts only.
- Partial reversal, and automatic refund after delivery.
- Migrating buyer calls from `core_buyer` helpers and domain transports to `StorefrontClient`, owned by `buyers-use-the-storefront-client`.
- Cash movement. Stripe top-ups and payouts are internal to the payments service; SCM trusts the ledger.

## Impact

- Affected code: `core/src/market_core/schemas.py`, `core/storefront`, `core/storefront-client`, `kit/identity`, `kit/settlement-runtime`, `kit/alkahest`, `kit/negotiation-runtime`, a new `kit/arkhai-payments`, the removed `kit/hosted-settlement`, and every domain's settlement composition, settle and refund routes, failure policy, and buyer payment commands (vms, bare_metal, apicredits).
- Affected wire: registry listing columns, the accepted-deal carrier, the negotiation acceptance response, the settle response's neutral fields, the new refund route, and the `settlement_data` shape.
- External dependency: headless callers authenticate to the payments service with WorkOS user-scoped API keys, owned by `arkhai-payments` (`agent-credentials`).
- Merge: this change lands after `bare-metal-mock-provisioned-deal` on the development branch; the merge decisions it raises are in `design.md#merge-with-the-development-branch`.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The negotiate → settle → provision pipeline and "core defines only what two parties read" — `docs/development/ARCHITECTURE.md`.
- The Agreement and acceptance settlement data — `openspec/specs/negotiation-protocol/spec.md`.
- Mandate derivation, receipt outcomes, attachment policies, seller-initiated refunds, and negotiation-scoped settlement — `openspec/specs/settlement-servicing/spec.md` and its `architecture.md`.
- Payments registration and the buyer-role `attach_agreement` setting — `openspec/specs/settlement-configuration/spec.md`.
- Payment buyer approval and agreement settlement — `openspec/specs/buyer-orchestration/spec.md`.
- The vector-pinned receipt fixture rule — `docs/development/TESTING.md` and `openspec/specs/test-compatibility/spec.md`.
- Goal 6 current state names `arkhai.payments.v1` and drops `fiat.stripe.v1` — `docs/development/ROADMAP.md`.
