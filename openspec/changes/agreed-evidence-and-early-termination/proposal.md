## Why

Seller-initiated interruption ships in part: an interruptible VM listing, a storefront admin endpoint that shortens the capacity lease, and Alkahest splitter plumbing whose money side returns `splitter_declaration_pending`. Bare metal separately has a buyer teardown route. Nothing describes what happens after an agreement is committed in terms both payment mechanisms and every domain can share:

- Seller reclaim, buyer stop, funding exhaustion, and exceptional ends such as failed hardware have no shared model, so each is built as a separate feature and the hosted and Alkahest paths diverge. This change supplies the model and the hosted path for today's `once` parts; the rate-part early ends build on it in `spot-deals-through-arkhai-payments`.
- It is undefined which steps are protocol and which are dealings between the parties after commitment.
- An agreement does not state how a dispute about it is decided, and the evidence a dispute would need is not kept.

## What Changes

- **The protocol is what a party must do to continue:** discovery, negotiation, and the mechanism's commitment act. Everything after commitment is lifecycle, visible to arbitration only through evidence. Moving the settle contract out of core is its own change, `move-settle-out-of-core`.
- **The committed agreement is the mechanism's:** Alkahest's arbiter and `DemandData`, the hosted payments mandate, or a countersigned Agreement. The buyer verifies it is the derivation of the negotiated terms before committing. There is no universal agreement digest.
- **Clauses name their adjudicator.** For deals through the official Arkhai registry the default is optimistic, Arkhai-adjudicated; a deferred dispute authority automates some cases later.
- **A deal is a set of parts, and payment events are per part** at the payment authority; payment adapters translate deal-level commands into them. **Arbitration is per agreement and separate from the payment core:** a case is filed at the regime's intake, and its outcome (a ruling or a seller's concession) is a list of per-part effects, such as partial reverses and partial bond slashes, and optionally a delivery end, possibly several per transaction; a partial slash is a discount while the term continues. One dispute window in `adjudication` drives holds and evidence retention. Each option's `params` carry `adjudication` (the regime), `early_termination` (entitlements, exposure, maximum term) only where a part can be stopped, and an optional seller-funded `bond`. Entitlements are the stoppable parts' stop authorities. Exceptional ends are cases the seller may concede; a bond is slashed in part or in full. The maximum term is an absolute instant shared by billing and the lease. These are common query fields filtered per option; the listing-wide interruptible flag becomes per-option Alkahest release models.
- **One lifecycle interface on each side of the mechanism.** Per-part payment events and per-agreement arbitration events are kept apart from buyer-to-seller peer messages (`commit`, `hint`); payment adapters resolve per mechanism and arbitration adapters per regime. Commands have defined outcomes and stable operation keys; `watch` replays from a durable cursor; the seller can `list` its deals. Seller-authenticated and buyer-authenticated lifecycle routes expose them. The seller's refund becomes `reverse`; reconciliation stays as a backstop. This change ships the hosted payment adapter for `once` and `bond` parts and the `optimistic.arkhai` arbitration adapter; the Alkahest adapter waits for a specialized arbiter.
- **The authority's record decides.** Parties act at the authority with their own credentials; only the payee can `start`, after provisioning; hints only bring a read forward.
- **End service at T** takes final requests from authority stops, arbitration outcomes that end delivery, and local delivery decisions (bare-metal teardown, failed start, terminal settlement), earliest *T* winning; funding is a renewable timer, not an end (built with rate parts in `spot-deals-through-arkhai-payments`); a maximum-term lease is the backstop; exposure budgets are checked at publication and acceptance.
- **Each party keeps its evidence,** keyed by negotiation ID, in a buyer-side and a storefront-side store, until the Agreement's dispute window after the deal and its cases close. A case is one exportable payload.
- **Hosted first; a neutral trustless alternative stays possible.** Alkahest is at the user's own risk until a specialized arbiter exists.

## Capabilities

### New Capabilities

- `deal-lifecycle`: the per-part event, command and peer-message model, the lifecycle terms and their semantics, the buyer and seller halves and their routes, the evidence store, per-agreement arbitration with cases and per-part outcomes, and end service.

### Modified Capabilities

- `negotiation-protocol`: the protocol ends at commitment; regimes are chosen per option.
- `buyer-orchestration`: "Payment buyers approve and settle by negotiation" generalizes to verifying the mechanism's committed form; `commit` replaces `settle_agreement` where the buyer lifecycle route exists; buyer stop, dispute, and read go through the buyer half.
- `market-composition`: "Deals compose negotiate, settle, and provision stages" treats settle as the post-commitment handoff; "Marketplace roles hold no payment ledger" admits lifecycle observation cursors.
- `settlement-servicing`: "The payments mandate is derived exactly from the Agreement" gains payee-only start, entitlement-derived stops, and the bond part.
- `settlement-configuration`: lifecycle terms are common clause fields; Alkahest release models are listed per option, and migration maps the old flag.
- `storefront-publication`: lifecycle terms, including the dispute window, are published per option; the admin interrupt route reads the accepted option.
- `cli-query-language`: lifecycle terms are common settlement fields.
- `vm-storefront-fulfillment`: "Full settlement convergence ownership" is modified, since end service writes the lease, and VM lease ends keep second precision.

## Dependencies and Related Changes

- `spot-deals-through-arkhai-payments` depends on this change. It implements the hosted rate part and its early ends against this change's kits and owns the four-path end-to-end scenario.
- `move-settle-out-of-core` depends on this change and on `move-escrow-into-alkahest`.
- `automate-seller-spot` depends on both hosted changes and is rescoped to the strategy runner.
- `version-accepted-artifacts` later types the evidence store's raw bytes; it is not a prerequisite.
- The hosted payments contract must provide this change's items in design.md, "Dependencies on the hosted payments service", vendored through `kit/arkhai-payments/schema/SOURCE.md`; Arkhai mediation must provide the case intake and record listed there. Both gate implementation, not planning.
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

- **Wire:** lifecycle terms inside option `params` change option IDs; hosted mandates change authorities and may gain a seller-funded bond part, so listings re-derive them on republish; new lifecycle routes. There is no backwards-compatibility promise; storefronts and buyer clients upgrade together.
- **Persistence:** an evidence store keyed by negotiation ID, lifecycle observation cursors, and an end-service journal per deal.
- **Packaging:** new `kit/deal-lifecycle` (foundation), `kit/deal-lifecycle-contracts`, `kit/deal-lifecycle-client`, `kit/deal-lifecycle-buyer` (buyer side), and `kit/deal-servicing` (storefront side); the hosted adapter in `kit/arkhai-payments`; storefronts and buyer stages bind them.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1 protocol boundary, D2 mechanism-defined commitment, D3 evidence, D12 worst-case rule, D13 neutral-alternative test, D14 information placement → `docs/development/ARCHITECTURE.md` ("Composition from above and below", "Authority boundaries", major flows); the buyer-side kit area → `docs/development/ARCHITECTURE.md` ("Kit areas").
- D2 committed-form verification → `openspec/specs/buyer-orchestration/spec.md`.
- D4 adjudicator and admissibility → `openspec/specs/negotiation-protocol/spec.md`.
- D5 per-part events and terms, D6 lifecycle interface and packaging, D7 authority record, D8 end service, D9 evidence store, D10 per-agreement arbitration and per-part outcomes → the new `deal-lifecycle` capability's `spec.md` and `architecture.md`.
- D5 option-level term emission, common query fields and Alkahest release models → `openspec/specs/settlement-configuration/spec.md`, `openspec/specs/storefront-publication/spec.md`, and `openspec/specs/cli-query-language/spec.md`; mandate derivation → `openspec/specs/settlement-servicing/spec.md`; `[Settlement.alkahest].release_models` and the exposure budget settings → `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D6 settle as handoff and observation cursors → `openspec/specs/market-composition/spec.md`.
- D6 role-table adapters and D11 optimistic adjudication → `openspec/specs/settlement-servicing/architecture.md` ("Capacity coupling" and "Current limits" are modified).
- D8 lease precision → `openspec/specs/vm-storefront-fulfillment/spec.md`.
