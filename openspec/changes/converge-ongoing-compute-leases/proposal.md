## Why

Goal 8's MVP change set lands first. After it, the VM storefront serves running
rate deals: `serve-running-rate-deals-on-vm` composes the rate adapter and
authorization hook, classifies each verified stop cause, records the physical
release and defines *ended* (physically released, every part stopped or ended at
the authority, no open end-related case), shows a deal ending while its rate
still runs, submits the seller's entitled notice, stops the buyer's rate,
refuses an incoherent startup, recovers on restart, and qualifies four VM lane
rows. The authority's recorded stops are its only end source, and Arkhai
operators handle every dispute by hand.

What the MVP leaves is the servicing the full product needs. Bare metal serves no
rate deal. The financial completion fact is not scoped to an end revision, so
earlier evidence arriving after an end has nowhere to go. A seller's unentitled
end is not filed as its self-penalty and mechanical rulings on rate parts are not
qualified; revised cases do not net prior ruling effects; there is no stateless
recovery runner, no evidence export and no audited physical acknowledgement. A
seller cannot protect itself from serving unpaid compute through a payments
outage. Running rate deals cannot survive the payments signing key's rotation
except by draining. And most of the rate lane matrix — every row that needs a
self-penalty, a ruling's `stop` or `penalty` effect, the bare-metal lane, or
rotation — is unqualified. A buyer's protection has to rest on authority records,
held earnings and kept signed bytes even when the seller is dishonest or absent.

## What Changes

- The per-deal step order `serve-running-rate-deals-on-vm` gives both storefront
  cycles becomes one `kit/deal-servicing` loop registered through
  `kit/storefront`, with whole-page physical, bounded authority and second
  physical passes.
- The financial completion fact is scoped to an end revision, counts pending and
  unknown operations, and reopens on earlier evidence, under the meaning of
  *ended* the MVP defines. An audited administrator acknowledgement can close the
  physical fact when no authenticated release proof will come. The seller's
  lifecycle read and list expose both facts, their gaps, pending work and repair
  reasons.
- Bare metal composes the rate adapter, hook, stop-cause classification, startup
  coherence and withdrawal the MVP composes in VM.
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
- During a payments identity overlap, servicing persists spot's re-anchoring
  evidence for each running rate deal before the old key retires.
- The mediation double executes a programmed ruling's `stop` and `penalty`
  effects, with its suite's proof.
- This change owns the rest of the rate lane matrix in both lanes, including
  spot's prepared maximum-term and emergency entry points, and the bare-metal
  storefront's perceived clock.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: whole-page end-service passes, financial completion,
  opt-in timer classification, diagnostics, recovery commands and rotation
  consumption.
- `market-composition`: the neutral storefront loop, and bare metal's startup
  coherence and withdrawal.
- `test-compatibility`: the remaining rate matrix, restart jurisdiction and
  lane time.
- `settlement-servicing`: none of its own; the delta under `specs/` is owned by
  `serve-running-rate-deals-on-vm` and kept until that change writes its delta.

### New Capabilities

None.

## Dependencies and scope

Depends on `serve-running-rate-deals-on-vm` (and through it the rest of Goal 8's
MVP set) and on `spot-deals-through-arkhai-payments` (setup parts, `returned` and
`prorated` treatment, the premature-stop penalty, mediation's self-penalty on
rate parts, and identity re-anchoring). It builds on the landed `deal-lifecycle`,
`compute-delivery` and lane-double specifications. Row 12a also needs the site's
delivery deadline from `renewable-compute-lease-deadlines`. Hosted enablement of
the full product is `activate-per-period-compute-servicing`'s.

The seller's exceptional end is a journaled dispute filing, not a direct payment
effect; mediation alone rules the qualifying payee self-penalty mechanically;
seller stop entries exist only for entitlements such as spot's notice, and a spot
emergency files the same case. `end_delivery` supplies signed receipt evidence
only; the buyer half owns the payment stop and its same-key retry, and billing
continues until that stop lands.

This change owns no payment arithmetic, mandate codec, authority policy, buyer
acceptance policy, buyer-half implementation, site renewal or hosted deployment.
Started-period settlement is a payment term, not a local correction. Notice
belongs to the selected stop entry, with no waiver and no payer early release.
Servicing latency, reserve-ahead sizing and the funding timer are the seller's
risk choices, not buyer billing promises or codec gates.

## Impact

`kit/deal-servicing`'s loop, state, adapter composition and recovery runner; the
bare-metal storefront's composition root, clock source and physical ports; the
seller lifecycle contracts and client (the evidence export and the audited local
recovery command); `tools/mediation-lane-double`'s ruling effects; both lanes'
scenario stages and fixtures. Mechanism and dispute operations stay in the
injected `kit/arkhai-payments` and `kit/arkhai-mediation` adapters. No runtime
changes at this design stage.

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
- Composition ownership and startup coherence — `market-composition` spec.
- Scenario jurisdiction and lane time — `test-compatibility` spec.
- Neutral ownership and mechanism-owned adapter continuation — `ARCHITECTURE.md`.
- At closeout: Goal 8 and campaign dependency currency, and the nine diagram
  pairs promoted to `docs/development/diagrams/`; the further matrix rows are
  qualified without duplicate diagrams.
