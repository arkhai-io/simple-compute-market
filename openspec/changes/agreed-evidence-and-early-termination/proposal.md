## Why

Seller-initiated interruption ships in part: an interruptible VM listing, a storefront admin endpoint that shortens the capacity lease, and Alkahest splitter plumbing whose money side returns `splitter_declaration_pending`. Bare metal separately has a buyer teardown route. Nothing describes what happens after an agreement is committed in terms both payment mechanisms and every domain can share:

- Seller reclaim, buyer stop, funding exhaustion, and exceptional ends such as failed hardware have no shared model, so each is built as a separate feature and the hosted and Alkahest paths diverge. This change supplies the model and the hosted path for today's `once` parts; the rate-part early ends build on it in `spot-deals-through-arkhai-payments`.
- It is undefined which steps are protocol and which are dealings between the parties after commitment.
- An agreement does not state how a dispute about it is decided, and the evidence a dispute would need is not kept.

## What Changes

- **The protocol is what a party must do to continue:** discovery, negotiation, and the mechanism's commitment act. Everything after commitment is lifecycle, visible to arbitration only through evidence. Moving the settle contract out of core is its own change, `move-settle-out-of-core`.
- **The committed agreement is the mechanism's:** Alkahest's arbiter and `DemandData`, the hosted payments mandate, or a countersigned Agreement. The buyer verifies it is the derivation of the negotiated terms before committing. There is no universal agreement digest.
- **Clauses name their adjudicator.** For deals through the official Arkhai registry the default is optimistic, Arkhai-adjudicated; a deferred dispute authority automates some cases later.
- **An `early_termination` clause in each settlement option's `params`,** emitted only on part shapes that can end early. Entitlements per initiator are the mechanism's stop authorities. Exceptional ends are disputes the seller may concede, subject to a concession floor in the clause. The authority itself stops billing at exhaustion and at the maximum term. Buyer stops settle through the seller's declared exposure. Notice is a scheduled stop the authority applies. A semantics table covers absent, unknown and conflicting input. Early termination is filtered per option through the settlement query language; the listing-wide interruptible flag becomes option-scoped Alkahest configuration.
- **One lifecycle interface on each side of the mechanism.** Authority events (`start`, `notice`, `stop`, `reverse`, `dispute`, `concede`) are kept apart from buyer-to-seller peer messages (`commit`, `hint`). Commands have defined outcomes and stable operation keys; `watch` replays from a durable cursor; the seller can `list` its deals. Seller-authenticated and buyer-authenticated lifecycle routes expose them. The seller's refund becomes `reverse`; reconciliation stays as a backstop. This change ships the hosted adapter; the Alkahest adapter waits for a specialized arbiter.
- **The authority's record decides.** Parties act at the authority with their own credentials; only the payee can `start`, after provisioning; hints only bring a read forward.
- **End service at T** takes authority events and local delivery decisions (bare-metal teardown, failed start, terminal settlement), earliest *T* winning: a maximum-term lease as backstop, terminate when *T* has passed, truncate at full precision otherwise.
- **Each party keeps its evidence,** keyed by negotiation ID, with a disclosed retention window. A dispute is one exportable case payload.
- **Hosted first; a neutral trustless alternative stays possible.** Alkahest is at the user's own risk until a specialized arbiter exists.

## Capabilities

### New Capabilities

- `deal-lifecycle`: the lifecycle event, command and peer-message model, the early-termination clause and its semantics, the buyer and seller halves and their routes, the evidence store, the dispute case payload, and end service.

### Modified Capabilities

- `negotiation-protocol`: the protocol ends at commitment; regimes are chosen per option.
- `buyer-orchestration`: "Payment buyers approve and settle by negotiation" generalizes to verifying the mechanism's committed form; buyer `commit`, stop, dispute, and read go through the buyer half.
- `market-composition`: "Deals compose negotiate, settle, and provision stages" treats settle as the post-commitment handoff; "Marketplace roles hold no payment ledger" admits lifecycle observation cursors.
- `settlement-servicing`: "Signed heartbeat evidence" keeps exact signed envelopes when the regime names heartbeats.
- `settlement-configuration`: hosted start and stop authorities derive from the clause; Alkahest interruption is option configuration with no listing-level marker.
- `storefront-publication`: early termination is published per option; the admin interrupt route reads the accepted option.
- `cli-query-language`: mechanism registrations project early-termination fields per option.
- `vm-storefront-fulfillment`: "Full settlement convergence ownership" is modified, since end service writes the lease.
- `site-capacity`: a truncated lease end keeps the requested instant.

## Dependencies and Related Changes

- `spot-deals-through-arkhai-payments` depends on this change. It implements the hosted rate part and its early ends against this change's kits and owns the four-path end-to-end scenario.
- `move-settle-out-of-core` depends on this change and on `move-escrow-into-alkahest`.
- `automate-seller-spot` depends on both hosted changes and is rescoped to the strategy runner.
- `version-accepted-artifacts` later types the evidence store's raw bytes; it is not a prerequisite.
- The hosted payments contract must provide this change's items in design.md, "Dependencies on the hosted payments service", vendored through `kit/arkhai-payments/schema/SOURCE.md`; they gate implementation, not planning.
- Issue #269 tracks hosted rate parts.

## Non-Goals

- An automated dispute authority, a managed metering gateway, a specialized Alkahest arbiter, or an Alkahest lifecycle adapter.
- Hosted rate parts and their early ends (`spot-deals-through-arkhai-payments`).
- Moving the settle contract out of core (`move-settle-out-of-core`).
- Lease extension (top-up).
- Delivering courtesy notices to buyer-supplied webhooks.
- Preemption between reservations inside the site authority (`pools-6-fair-scheduling-policy`).
- Choosing seller interruption strategy (`automate-seller-spot`).
- Merging the VM and bare-metal domains.

## Impact

- **Wire:** the clause inside option `params` changes option IDs, so listings re-derive them on republish; new lifecycle routes. There is no backwards-compatibility promise; storefronts and buyer clients upgrade together.
- **Persistence:** an evidence store keyed by negotiation ID, lifecycle observation cursors, and an end-service journal per deal.
- **Packaging:** new `kit/deal-lifecycle` (foundation), `kit/deal-lifecycle-contracts`, `kit/deal-lifecycle-client`, and `kit/deal-servicing` (storefront side); the hosted adapter in `kit/arkhai-payments`; storefronts and buyer stages bind them.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1 protocol boundary, D2 mechanism-defined commitment, D3 evidence, D12 worst-case rule, D13 neutral-alternative test, D14 information placement → `docs/development/ARCHITECTURE.md` ("Composition from above and below", "Authority boundaries", major flows).
- D2 committed-form verification → `openspec/specs/buyer-orchestration/spec.md`.
- D4 adjudicator and admissibility → `openspec/specs/negotiation-protocol/spec.md`.
- D5 clause, D6 lifecycle interface and packaging, D7 authority record, D8 end service, D9 evidence store, D10 case payload → the new `deal-lifecycle` capability's `spec.md` and `architecture.md`.
- D5 option-level clause emission and query projection → `openspec/specs/settlement-configuration/spec.md`, `openspec/specs/storefront-publication/spec.md`, and `openspec/specs/cli-query-language/spec.md`.
- D6 settle as handoff and observation cursors → `openspec/specs/market-composition/spec.md`.
- D6 role-table adapters and D11 optimistic adjudication → `openspec/specs/settlement-servicing/architecture.md` ("Capacity coupling" and "Current limits" are modified).
- D8 lease primitives → `openspec/specs/site-capacity/spec.md` and `openspec/specs/vm-storefront-fulfillment/spec.md`.
