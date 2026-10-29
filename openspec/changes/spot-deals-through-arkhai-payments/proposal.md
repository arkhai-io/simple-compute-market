## Why

VM and bare-metal sellers need to sell compute by the period from prepaid credits,
with a buyer stop and, for spot, a seller stop on notice. Approval alone is not
continued payment authorization: rate parts start after provisioning and end at
authority-recorded stops, exhaustion, or the agreed maximum term.

The lifecycle foundation in
[agreed-evidence-and-early-termination](../agreed-evidence-and-early-termination/)
supplies the terms, payment/dispute adapter boundary, evidence stores and end
service. This change completes its hosted payment adapter for rate parts and
supplies both-domain presets and the seller notice command. Storefront-side
continuation is a separate dependent change.

## What Changes

- Extend arkhai.payments.v1 option parameters and mandate derivation for time
  rate parts, optionally combined with an honestly named setup once part.
  Default on-demand and spot presets include setup; sellers may omit it.
  Prices come from the agreed-price accessor, not direct reads of Agreement.amount.
- Derive per-part authorities from early_termination and adjudication:
  payee-only rate start, entitled stop accounts with their priced notice, and the
  dispute authority's stop/reverse/extend permissions. On-demand has no payee stop.
  Use part end, {afterStop: dispute_window} and maxHoldExtension.
- Extend the hosted adapter's command translation, reads and watch source with
  per-part start, pending/final stop, funding and maximum-term observations.
  Expose immutable operation descriptors and cumulative correction-target
  arithmetic for caller-owned journals, including half-open periods and the
  seller-caused started-period reversal rule.
- Add the seller half's notice command through the existing seller-authenticated,
  negotiation-keyed lifecycle submit; a typed client method and a deals preempt
  operator CLI verb in both domains. Submit stop immediately to the payment
  authority, which hosts the pending stop. Never schedule a payment stop locally.
- Publish independently priced spot and on-demand options from one pool in both
  domains. They are combinations of parts and terms, not runtime classes.
- Support service-identity overlap and re-anchoring through the foundation's
  verified-snapshot interface. Snapshot-proof verification itself remains owned
  by agreed-evidence-and-early-termination round 2.
- Qualify mechanics against published vectors and the in-lane payment/mediation
  doubles. A lane-only proposed servicing declaration permits qualification
  before hosted deployment; it cannot produce live evidence.

This absorbs the mechanics and spot scenarios of the superseded designs
settle-ongoing-compute-through-arkhai-payments and
publish-and-preempt-spot-compute; their directories are removed.

## Capabilities

### Modified Capabilities

- settlement-servicing: rate mandates, adapter events, start/stop translation,
  cumulative correction arithmetic and identity re-anchoring.
- settlement-configuration: typed rate parameters and servicing declaration.
- storefront-publication: both-domain rate presets and per-option prices.
- deal-lifecycle: seller notice command, status and operator surface, extending
  the capability introduced by the foundation.
- test-compatibility: vector and qualification boundaries for rate parts.

### New Capabilities

None.

## Dependencies and acceptance boundary

Implementation gates on:

1. agreed-evidence-and-early-termination: term codec, hosted contract vendoring
   and once-part adapter, lifecycle commands, evidence stores and verified snapshots
   (round 2). This change consumes, and does not duplicate, those facilities.
2. negotiate-open-ended-compute-terms: agreed-price accessor and period unit,
   listing bounds, accepted option shape and publication/acceptance gates.
3. add-arkhai-payments-lane-double: payment and mediation doubles with the
   revised contract and deterministic controls.

converge-ongoing-compute-leases depends on this change: it owns rate servicing
in kit/deal-servicing, funding timers, journal persistence/replay, start admission
and domain lease effects. The spot e2e scenarios are specified here and run once
that consumer is composed; that is a verification gate, not a reverse implementation
dependency. activate-per-period-compute-servicing owns switch-on and hosted
qualification after the contract revision is deployed.

Complete here means exact buyer/seller derivation, usable adapter mechanics and
both-domain publication/notice surfaces, with vector, kit and application evidence.
Cross-service spot acceptance additionally needs the continuation consumer. Passing
a double-backed scenario never qualifies the external payment or dispute authority.

## Non-Goals

- A billing horizon, vouch, minimum-spend primitive, payee backdating, or local
  payment-stop scheduler.
- Storefront continuation loops, queues, funding timers, site deadline/renewal
  policy, provisioning or teardown implementation.
- Snapshot-proof implementation, buyer end_delivery implementation, evidence
  capture or mediation rulings (foundation-owned).
- Discovery sugar, automated preemption strategy, Alkahest splitter execution,
  API-credit rate servicing, metering other than time, or reserved fixed-interval
  deals expressed as rate parts.
- Guarantees depending on a cooperative storefront: the buyer's backstop is its
  own authority stop and a case over held money.

## Compatibility and impact

No backwards-compatibility promise for pre-upgrade hosted mandates; rollout is
forward only as in the foundation. New rate/setup shapes receive new option IDs.
Reserved and API-credit options retain once-part mechanics. Examples use USD/6;
production derivation reads the selected Agreement's asset.

Affected code: kit/arkhai-payments, lifecycle contracts/client and seller-half
command dispatch, both compute storefront compositions and operator CLIs, and the
two compute lanes' qualification scenarios. No mechanism kit imports a domain or
the persistence-owning servicing kit.

## Permanent documentation impact

- [x] docs/development/ARCHITECTURE.md — adapter/servicing ownership and release flow
- [x] Existing subsystem specifications — the five capabilities above
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Rate-part derivation, holds, authorities, arithmetic and re-anchoring:
  openspec/specs/settlement-servicing/spec.md and its architecture companion.
- Servicing declarations and identity-overlap configuration:
  openspec/specs/settlement-configuration/spec.md and
  docs/development/DEPLOYMENT_AND_CONFIG.md.
- Presets, setup pricing and independent spot/on-demand publication:
  openspec/specs/storefront-publication/spec.md and its architecture companion.
- Seller notice command and pending-stop observation:
  the foundation-created deal-lifecycle spec.md (see its
  [delta](../agreed-evidence-and-early-termination/specs/deal-lifecycle/spec.md))
  and its architecture companion before this change lands.
- External payment contract context and guarantee limits:
  openspec/specs/deal-lifecycle/architecture.md.
- Vectors and evidence classification:
  openspec/specs/test-compatibility/spec.md and its architecture companion.
