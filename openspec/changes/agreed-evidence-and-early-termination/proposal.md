## Why

Seller-initiated interruption ships in part: an interruptible VM listing, a storefront admin endpoint that shortens the capacity lease, and Alkahest splitter plumbing. The money side returns `splitter_declaration_pending`, and nothing describes what an interruption *is* in terms the rest of the system can reason about. Three gaps follow from that:

- Seller reclaim ("spot" in the cloud sense), buyer early stop, and payer funding exhaustion are treated as different features, although they are one lifecycle event with different permitted initiators.
- It is undefined which parts of a deal belong to the market protocol and which are private dealings between buyer and seller after agreement. The settlement receipt, the fulfillment result (SSH endpoint), and the buyer's SSH key each travel at a different stage with no stated rule for why.
- An agreement does not state how a dispute about it would be decided: which evidence counts, who produces it, and what happens when nobody submits any. Each settlement mechanism answers this implicitly — an Alkahest arbiter and demand, an `arkhai.payments.v1` mandate's authorities and holds, buyer-signed heartbeats — but the agreement does not say so as a rule.

This change fixes the model first: what the agreement must contain, where the protocol ends, and how early termination fits in. It then plans the code changes needed to realize it.

## What Changes

- **Protocol boundary.** The market protocol covers discovery, negotiation to a mutually authenticated agreement, and settlement. Everything the parties exchange after that — access details, action handles, notices, evidence — is outside the protocol unless a dispute brings it before an arbiter. Core gains no interruption or other post-agreement lifecycle verb.
- **The agreement is the demand.** An agreement contains everything needed to decide a dispute about it, in the form `arbitrate(demand, evidence)`. For each clause it names the evaluator, the evidence regime that evaluator accepts (for example a trusted metering gateway that retains records, an oracle declaration, or peer signatures that a party submits in its own interest), and the outcome when no evidence is submitted.
- **Clauses must be enforceable when agreed.** A clause is admissible only if its regime can produce evidence that decides it, and both parties confirm at negotiation that they can take part in the regime it names.
- **Early termination is one clause family.** It records the permitted initiators (seller reclaim, buyer stop, payer exhaustion), the notice period, the rule for settling used and unused service, and the evidence that proves an early end. Spot and interruptible offerings are parameter choices within it. A mechanism that cannot settle a partial term is not offered with this clause.
- **One storefront operation executes an early end.** "End service at T" accepts every trigger, shortens the capacity lease through the site authority, and calls a mechanism-neutral early-end operation on the settlement mechanism. Each half is retried and resumed independently.
- **Ending early is a party action.** It is sent with the initiator's own credentials to the authority the agreement names, whose record is authoritative. The operator interrupt route is not the parties' interface.
- **Worst case first, cooperative defaults.** Each party's safety depends only on the authority's record and its own records, with exposure bounded by the agreed terms; for example, the seller watches the authority at a cadence derived from the settlement rule. Our implementations still send courtesy notices, but these are hints that trigger a check of the authority, never a second path to the same result.
- **Commitment follows the mechanism.** Hosted approval, on-chain funding, or exchanged signed messages, each binding one canonical agreement digest. Alkahest demands gain that digest.
- **Dispute data is one case payload.** The agreement digest is the root, and every evidence item uses one envelope, so a future dispute authority receives a single self-contained case instead of reconciling mechanism-specific stores.
- **Hosted first, decentralizable always.** The hosted payments mechanism is the production path and is implemented completely first. Alkahest is maintained so that a neutral trustless alternative remains possible for every managed component. Its seller-as-oracle behavior is trusted, not secure. New decisions are tested on whether a neutral arbiter (a third-party oracle or a signature-based arbiter) could implement them.
- **The post-agreement exchange is minimal and placed by rule.** After agreement and funding, buyer and seller make one exchange: the buyer sends the funding reference and the information the seller needs; the seller replies, possibly asynchronously, with access details and action handles. Information goes in the agreement when it must be binding and is known in advance; in a receipt or result when it is created later; and after acceptance when it must not be disclosed before commitment.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `negotiation-protocol`: agreements name an evaluator, evidence regime, and default outcome per clause; regime participation is checked before acceptance; the seller's acceptance is authenticated.
- `settlement-servicing`: a mechanism-neutral early-end operation beside collect and reclaim, implemented per mechanism or declared unsupported.
- `settlement-configuration`: a mechanism declares whether it can settle a partial term, and which evidence regimes it supports.
- `storefront-publication`: listings advertise the early-termination clause and its parameters.
- `vm-storefront-fulfillment` and `fulfillment`: the storefront's end-service operation; lease truncation stays distinct from proven teardown.
- `introduction-delivery`: possibly a delivery target for buyer-side notices (open question).

## Dependencies and Related Changes

- `automate-seller-spot` is seller-only and splitter-specific. Once this change is accepted it should be rescoped to the seller-decision runner and its decision evidence, with splitter execution becoming the Alkahest implementation of the early-end operation.
- `spot-deals-through-arkhai-payments` (in design) is the hosted production path for VM interruptible deals: a rate part with `until: stop`, teardown by the signed funded-through time or on a stop, and stops issued for seller preemption and buyer cancellation. Under D13 it is the first implementation of this change's model. This change does not duplicate it. Two points must be reconciled with it: notice periods (it forbids future-dated stops) and the settlement point of a stop (D5).
- `replace-polling-with-authenticated-push` covers provisioning-to-storefront delivery only; buyer-side notices are not covered there.
- Payer funding exhaustion on hosted payments is `spot-deals-through-arkhai-payments`' rate parts; issue #269 tracks the same.
- The hosted payments service may need notice support and initiator-dependent settlement terms (open in design). Stops by authorized accounts, cause recording, funding exhaustion, the deal digest, and signed snapshots already exist.

## Non-Goals

- Building a mechanical dispute authority or a managed metering gateway. They are deferred and will be built together. Until then the Alkahest splitter oracle is the seller itself. This change defines the agreement contents and the dispute case format such an authority will consume.
- Adding post-agreement messages to the core protocol.
- Preemption between reservations inside the site authority (`pools-6-fair-scheduling-policy`).
- Choosing seller interruption strategy; that remains in `automate-seller-spot`.

## Impact

Design phase; not yet planned. Expected impact, to be confirmed by the code audit that follows:

- **Wire:** additive fields in domain terms and settlement options for clause evaluator, regime, and default outcome; versioned where they change a signed body.
- **Persistence:** a durable early-end record per deal, independent of stage events.
- **Packaging:** the end-service operation and early-end mechanism contract belong in shared kit, not the VM domain, so bare metal can use them.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Protocol boundary and the agreement-as-demand model → `docs/development/ARCHITECTURE.md` (core role contracts and major flows).
- Clause evaluator, regime, default outcome, and regime-participation checks → `openspec/specs/negotiation-protocol/spec.md`.
- Early-end operation and per-mechanism support → `openspec/specs/settlement-servicing/spec.md` and `architecture.md`; mechanism declarations → `openspec/specs/settlement-configuration/spec.md`.
- End-service operation and its independent halves → `openspec/specs/vm-storefront-fulfillment/spec.md` and `openspec/specs/fulfillment/spec.md`.
- Information placement rule → `docs/development/ARCHITECTURE.md`.
