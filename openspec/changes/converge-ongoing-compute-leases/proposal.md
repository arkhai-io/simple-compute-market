## Why

Goal 8's MVP changes land first. After them, both compute storefronts serve
running rate deals: `serve-running-rate-deals` lifts end service's refusal to
commit a rate deal (`spot-deals-through-arkhai-payments` D12, D13, archived),
composes the rate adapter and authorization hook in both domains, binds rate start
through the shared delivery path, classifies each verified stop cause, records the
physical release and defines *ended* (physically released, every part stopped or
ended at the authority, no open end-related case), shows a deal ending while its
rate still runs, refuses an incoherent startup, recovers on restart, and qualifies
the baseline rows of the rate matrix in both lanes. The authority's recorded stops
are its only end source, and Arkhai operators handle every dispute by hand.
`drive-the-storefront-clock-in-lanes` gives both storefronts a perceived clock the
lane moves with the doubles'. The archived spot change already supplies the
mechanics: rate and setup parts, every `partialPeriod` treatment, the `chosen`
dispute entry, seller notice, the buyer's end and watchdog, and a receipt key
change as a drained cutover.

What the MVP leaves is the servicing the full product needs. The financial
completion fact is not scoped to an end revision, so earlier evidence arriving
after an end has nowhere to go. A seller's unentitled end is not filed as its
self-penalty, and mechanical rulings on rate parts are not qualified; revised cases
do not net prior ruling effects; there is no stateless recovery runner, no evidence
export and no audited physical acknowledgement. A seller cannot protect itself from
serving unpaid compute through a payments outage. Each storefront still runs its
own cycle over the MVP's per-deal step order. And most of the rate lane matrix —
every row that needs a self-penalty, a ruling's `stop` or `penalty` effect, the
opt-in funding timer or a revised case — is unqualified. A buyer's protection has
to rest on authority records, held earnings and kept signed bytes even when the
seller is dishonest or absent.

## What Changes

- The per-deal step order `serve-running-rate-deals` gives both storefront cycles
  becomes one `kit/deal-servicing` loop registered through `kit/storefront`, with
  whole-page physical, bounded authority and second physical passes.
- The financial completion fact is scoped to an end revision, counts pending and
  unknown operations, and reopens on earlier evidence, under the meaning of
  *ended* the MVP defines. An audited administrator acknowledgement can close the
  physical fact when no authenticated release proof will come. The seller's
  lifecycle read and list expose both facts, their gaps, pending work and repair
  reasons beyond the MVP's operator signal.
- A seller may enable a funding timer in its composition: at expiry the loop
  reads the payment authority and ends on the bare timer only when the authority
  is unreachable or unverifiable. With the setting off, the authority's recorded
  stops remain the only end source.
- Ends the terms do not entitle are filed as the seller's self-penalty through
  the dispute adapter; a buyer's `end_delivery` and an authority's stop are never
  seller self-penalties. Earlier evidence becomes revision-bound dispute work
  through the dispute adapter's mapping and verified prior ruling effects, never a
  seller-direct stop or reverse and never local end-pricing arithmetic.
- Operator recovery is stateless: a seller-authenticated evidence export and an
  immutable command envelope drive the injected adapters, with no offline second
  storefront database writer.
- The mediation double executes a programmed ruling's `stop` and `penalty`
  effects, with its suite's proof.
- This change owns the rest of the rate lane matrix in both lanes, including
  spot's prepared maximum-term and emergency entry points, the opt-in timer
  variants, and the row variants `serve-running-rate-deals` leaves.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: whole-page end-service passes, revision-scoped financial
  completion, opt-in timer classification, diagnostics and recovery commands.
- `market-composition`: the neutral storefront loop. Both domains' rate
  composition, startup coherence and withdrawal are `serve-running-rate-deals`';
  the delta under `specs/` keeps them, marked, until that change writes its own.
- `test-compatibility`: the remaining rate matrix, restart jurisdiction and lane
  time.
- `settlement-servicing`: none of its own; the delta under `specs/` is owned by
  `serve-running-rate-deals` and kept until that change writes its delta.

### New Capabilities

None.

## Dependencies and scope

Depends on `serve-running-rate-deals` (and through it the rest of Goal 8's MVP
set, `drive-the-storefront-clock-in-lanes` included). It builds on the landed
`deal-lifecycle`, `compute-delivery`, `settlement-servicing` and lane-double
specifications and on the archived `spot-deals-through-arkhai-payments`, whose
"Dependencies and ownership" names what it leaves here. Row 12a also needs the
site-enforced delivery deadline from `renewable-compute-lease-deadlines`. Hosted
enablement of the full product is `activate-per-period-compute-servicing`'s.

The seller's exceptional end is a journaled dispute filing, not a direct payment
effect; mediation alone rules the qualifying payee self-penalty mechanically;
seller stop entries exist only for entitlements such as spot's notice, and a spot
emergency files the same case. `end_delivery` supplies signed receipt evidence
only; the buyer half owns the payment stop and its same-key retry, and billing
continues until that stop lands.

This change owns no payment arithmetic, mandate codec, authority policy, buyer
acceptance policy, buyer-half implementation, site renewal, rotation work or
hosted deployment. A receipt key change is a drained cutover
(`spot-deals-through-arkhai-payments` D17, D21), and re-anchoring running deals
across it is an unowned gap in the roadmap. Started-period settlement is a payment
term, not a local correction. Notice belongs to the selected stop entry, with no
waiver and no payer early release. Servicing latency, reserve-ahead sizing and the
funding timer are the seller's risk choices, not buyer billing promises or codec
gates.

## Impact

`kit/deal-servicing`'s loop, state and recovery runner; the seller lifecycle
contracts and client (the evidence export and the audited local recovery
command); both storefronts' loop registration; `tools/mediation-lane-double`'s
ruling effects; both lanes' scenario stages and fixtures. Mechanism and dispute
operations stay in the injected `kit/arkhai-payments` and `kit/arkhai-mediation`
adapters. No runtime changes at this design stage.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — composition and authority boundaries
- [x] Existing subsystem specification: `deal-lifecycle`, `market-composition`,
  `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- End-service behaviour and the guarantee's limits — `deal-lifecycle` spec and
  architecture companion.
- The opt-in funding timer and its setting — `deal-lifecycle` spec;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- The one neutral loop — `market-composition` spec.
- Scenario jurisdiction and lane time — `test-compatibility` spec.
- Neutral ownership and mechanism-owned adapter continuation — `ARCHITECTURE.md`.
- At closeout: Goal 8 and campaign dependency currency, and the nine diagram
  pairs under `diagrams/` promoted to `docs/development/diagrams/`, less any pair
  `serve-running-rate-deals` promotes with the rows it qualifies; the further
  matrix rows are qualified without duplicate diagrams.
