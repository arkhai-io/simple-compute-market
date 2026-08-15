# Contact-Exchange Settlement Mechanism

## Why

A large share of real capacity deals are arranged person-to-person — private channels,
brokered introductions — where the marketplace's value is discovery, negotiation, and a
trustworthy introduction, not payment custody or provisioning. Listings of that kind
are looser than machine-settleable inventory: sparse metadata, commercial terms that
are freeform prose because they cannot be parametrized, and no expectation of
automated fulfillment.

The hosted-settlement work made this cheap. Settlement mechanisms are composed
`MechanismRegistration`s with their own configuration, readiness, publication options,
selection, and servicing; the registry accepts option-only listings; marketplace
identities need no chain; and the accepted plan's `service_terms` are durably
persisted at acceptance. What is still missing is the mechanism itself: nothing
completes a deal by introduction, negotiation cannot reach acceptance without a scalar
amount, and no surface reveals one party's contact to the other — the hosted "action"
analog is deliberately transient, while an introduction must be re-readable.

## What Changes

- A new `kit/contact-exchange` exporting `create_contact_exchange_registration()`:
  `mechanism_id="contact-exchange.v1"`, `config_key="contact"`, buyer and seller
  roles, a preflight that checks configuration only, and a mechanism client whose
  `materialize` returns ready immediately, `check` reports satisfied, `collect`
  produces the receipt, and reclaim is trivial. Import fence identical to the other
  mechanism kits.
- Publication: an option builder emitting one `SettlementOption` per offered contact
  profile with `rates: []`, prose commercial terms in `params`, and `option_id` via
  `derive_settlement_option_id`. Contact data itself never appears in options or
  listings.
- Negotiation: rides the existing `settlement_selection` carrier and declares no
  scalar, so rounds are take-it-or-leave-it over the published option (per
  `finish-settlement-mechanism-neutrality`'s declinable-scalar capability), with
  freeform counter-context in the domain message payload.
- Accepted context: the introduction package is written into
  `SettlementPlan.service_terms["contact-exchange.v1"]`, which acceptance already
  persists durably.
- Reveal: a third signed route family (`/api/v1/introductions`) mirroring the hosted
  settlement routes — start supplies the buyer's contact payload, and an idempotent
  authenticated read serves the counterparty's payload plus the agreed context to each
  party after acceptance. The reveal is the settlement; the deal is terminal once the
  reveal is available to both sides.
- Composition: the registration added to the domain composition roots and enabled via
  `[Settlement.contact]` plus a `priority` entry; composed first on bare metal.
- Discovery: a loose-listing registry filter-spec profile for introduction markets —
  option-only listings, few filters, missing-field-tolerant matching.

## Capabilities

### New Capabilities

- `contact-exchange-settlement`: introduction-only settlement — held-then-revealed
  contact exchange that completes a deal with no payment and no provisioning.

### Modified Capabilities

- `settlement-servicing`: a non-financial obligation — no amount, no asset, no funding
  — is valid and serviceable, completing on the mechanism's availability signal.

## Non-Goals

- No counterparty vetting, reputation, or identity verification beyond the existing
  request signing.
- No in-band messaging after reveal; the introduction ends the marketplace's role in
  the deal.
- No payment fallback and no hybrid escrow-plus-introduction mechanism.
- No automated bargaining over freeform terms.

## Dependencies and Related Changes

- Depends on `finish-settlement-mechanism-neutrality` for exactly two items: the
  declinable-scalar negotiation capability, and resolution of the buyer-side rejection
  of non-empty `service_terms` on the option-selected path. Everything else composes
  against machinery already on `main`.
- Coordinate lightly with `consume-expanded-stripe-funding` on shared registration and
  publication surfaces; this change is otherwise additive.

## Impact

- Affected code: new `kit/contact-exchange`; the introductions route family mounted in
  storefront compositions; contact-payload persistence beside the obligation record;
  domain composition roots; a registry filter-spec profile; buyer CLI surface for
  supplying a contact payload and reading an introduction.
- Affected tests: mechanism registration/readiness/option units, reveal authorization
  and idempotency, persistence across restart, an end-to-end introduction deal on bare
  metal.
- Not affected: hosted and Alkahest deal behavior, capacity, fulfillment,
  provisioning.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — system overview note: a market may settle
      by introduction, with no payment and no physical delivery.
- [x] Existing subsystem specification — `settlement-servicing`.
- [x] New subsystem specification — `openspec/specs/contact-exchange-settlement/`.

### Knowledge to promote

- Introduction-only settlement lifecycle and reveal authorization —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- Non-financial obligations as valid, serviceable obligations —
  `openspec/specs/settlement-servicing/spec.md`.
- Contact payloads as deliberate, bounded PII persistence with a recorded retention
  posture — the new capability's `architecture.md`.
