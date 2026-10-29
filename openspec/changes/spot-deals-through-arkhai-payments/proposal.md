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
  dispute authority's stop/reverse/extend permissions. Add the explicit seller
  {account: seller, notice: PT0S, partialPeriod: returned} restitution entry on every
  part. On-demand has only that seller entry: its no-preemption promise is not
  mandate-enforced; the remedy is a buyer case over held money and any supported bond.
  Spot's additional immediate entry depends on unscheduled payments support for
  several stop entries per account per part. Until then emergency exit waits out
  seller notice. Payments has no implicit role-based privileges or notice waivers.
  Use part end, {afterStop: dispute_window} and maxHoldExtension.
- Extend the hosted adapter's command translation, reads and watch source with
  per-part start, pending/final stop, funding and maximum-term observations.
  Expose immutable operation descriptors for caller-owned journals. Started-period
  treatment is a required per-stopper partialPeriod payment term, not a storefront
  refund. On the returned-capable revision each rate end requires it (once ends
  do not), and the dispute stop entry is chosen with treatment in each stop event.
  Interim treatment fields are absent and vector-qualified fixed charged semantics
  apply, including dispute stops. Periods earn at period end or part stop, not start.
  Term end also carries partialPeriod: compute presets use returned. Fail closed
  on unexpressible terms; interim rate options commit started_period on all present entitlements. Recommend
  explicitly disclosed charged term ends for interim spot/on-demand rate options.
  Negotiation decides accepted treatment. Seller presets offer last_boundary;
  the terms-owned buyer policy by default refuses other payee or term-end
  treatments. Interim spot and on-demand therefore require explicit buyer acceptance of
  started_period for every affected term and cannot reach default buyers until returned
  is expressible in the vendored contract.
- Add the seller half's notice command through the existing seller-authenticated,
  negotiation-keyed lifecycle submit; a typed client method and a deals preempt
  operator CLI verb in both domains. Submit stop immediately to the payment
  authority, which hosts the pending stop. Never schedule a payment stop locally.
- Supply setup/rate preset helpers to the terms change's publication adapters.
  Presets are combinations of parts and terms, not runtime classes. Setup ends
  at activation through a qualified rate-start-linked trigger; until qualified,
  setup-bearing presets refuse and sellers may explicitly opt out. A lawful
  pre-activation stop returns setup in full without seller-fault attribution.
- Implement the hosted rate authorize hook for commit/dispatch/start/disclose,
  consuming the foundation's versioned activation envelope; convergence composes it.
  Keep delivery authorization pure. Translate the separate post-activation
  start_billing effect using the end service's sole journaled operation key;
  delivery keeps a reference, not a second start intent.
- Re-drive the canonical rate buyer-end flow: stop then hint, continue delivery
  during priced notice, and end through authority watch. Keep end_delivery for
  explicit immediate surrender and unreachable-payment-authority buyer_end(at).
  End service does not waive payer notice. Receipt-timed payer-priced storefront
  stop needs an explicit authorizing entry; otherwise it is the buyer half's stop.
- Translate journaled seller exceptional_end through the payment adapter, not a
  dispute: stop {part} under the seller's explicit PT0S/returned entry, plus
  reverse {part, amount} under existing reverse authority; no exceptional-end kind
  or field enters payments vocabulary. Preserve the gated spot notice fallback,
  earned-since-at rate reversal,
  time-unserved once reversal (setup all before delivery, none after) and supported
  bond award. Keep timing/journaling; refuse unexpressible contract behavior.
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
  authority-enforced started-period terms and rate-deal identity re-anchoring.
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
   listing bounds, accepted-price carrier and option shape, declaration contract,
   whole-second pre-signature start/identity freeze and publication/acceptance gates. Only those sections gate mechanics; the terms
   change must not wait for this change's door-3 evidence to archive.
3. The foundation's in-process contract fakes gate kit library integration.
   add-arkhai-payments-lane-double supplies HTTP doubles, wall-time typed due-work
   barriers and the three named aggregate evidence classes
   only for lane/e2e evidence, not as a whole-change implementation prerequisite.

converge-ongoing-compute-leases depends on this change: it owns rate servicing
in kit/deal-servicing, funding timers, journal persistence/replay, start admission
and domain lease effects. Convergence owns the complete spot e2e matrix and runnable
entry points when that consumer is composed; no unrun consumer requirement is
promoted here. This design's scenario-ownership table records the handoff without
a reverse implementation dependency. activate-per-period-compute-servicing owns
switch-on and hosted qualification after the contract revision is deployed.

Complete here means exact buyer/seller derivation, usable adapter mechanics and
both-domain preset/notice surfaces plus the rate buyer-end re-drive, with vector,
kit and application evidence.
Cross-service spot acceptance additionally needs the continuation consumer. Passing
a double-backed scenario never qualifies the external payment or dispute authority.

## Non-Goals

- A minimum-spend primitive, payee backdating, or local payment-stop scheduler;
  design records rejected payment primitives.
- Storefront continuation loops, queues, funding timers, site deadline/renewal
  policy, provisioning or teardown implementation.
- Snapshot-proof implementation, immediate end_delivery transport/evidence capture
  or mediation rulings (foundation-owned). The rate buyer-end re-drive is in scope.
- Cooperative corrections to entitled stop pricing, a second seller-command
  journal, or mediation mapping of exceptional_end. Seller self-correction remains
  the existing journaled payment-adapter command.
- Durable once-only identity re-anchoring; those deals must drain before key retirement.
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
- Preset helpers, setup pricing and their terms-owned publication integration:
  openspec/specs/storefront-publication/spec.md and its architecture companion.
- Seller notice command, pending-stop observation and the rate buyer-end re-drive:
  the foundation-created deal-lifecycle spec.md (see its
  [delta](../agreed-evidence-and-early-termination/specs/deal-lifecycle/spec.md))
  and its architecture companion before this change lands.
- External payment contract context and guarantee limits:
  openspec/specs/deal-lifecycle/architecture.md.
- Vectors and evidence classification:
  openspec/specs/test-compatibility/spec.md and its architecture companion.
