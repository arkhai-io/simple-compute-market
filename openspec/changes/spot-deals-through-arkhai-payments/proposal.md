## Why

VM and bare-metal sellers need to sell compute by the period from prepaid credits,
with a buyer stop and, for spot, a seller stop on notice. Approval alone is not
continued payment authorization: a rate part starts after provisioning and ends at
an authority-recorded stop, at exhaustion, or at the agreed maximum term.

The lifecycle foundation,
[`agreed-evidence-and-early-termination`](../agreed-evidence-and-early-termination/),
supplies the terms, the payment and dispute adapter boundary, the evidence stores
and end service. This change completes its hosted payment adapter for rate parts
and supplies both domains' presets and the seller notice command. The storefront's
continuation is a separate, dependent change.

## What Changes

- The `arkhai.payments.v1` settlement parameters and mandate derivation gain time
  rate parts, optionally combined with an honestly named setup `once` part. The
  default on-demand and spot presets include setup, a seller may omit it, and the
  bare-metal preset ships no default amount: a bare-metal seller states its setup
  price or publishes no recurring option. Prices come from the agreed-price
  accessor, never from a direct read of `Agreement.amount`. The option carries one
  `asset`, in `price`; the hosted parameters no longer repeat it.
- Per-part authorities are derived from the option's `lifecycle`: payee-only rate
  `start`, each entitled party's stop entry with its priced notice, and the dispute
  authority's stop, reverse and extend permissions. Seller stop entries exist only
  for entitlements, such as spot's notice; on-demand has none, and its no-preemption
  promise is enforced by remedy — the premature-stop penalty and a buyer case over
  held money, with a bond reserved — not by the mandate. The seller's emergency
  exit is an `exceptional_end` dispute filing, on spot too. There is no restitution
  entry, implicit favourable stop privilege, multiple-entry gate, notice waiver or
  payer early release. Parts carry their `end`, `{afterStop: dispute_window}` and
  `maxHoldExtension`. The shipped presets price the payer's notice at zero.
- The hosted adapter's command translation, reads and `watch` source gain per-part
  `start`, pending and final stops, funding and maximum-term observations, and
  export immutable operation descriptors for caller-owned journals. Started-period
  treatment is a per-stopper `partialPeriod` payment term, not a storefront
  refund: on the returned-capable revision every rate end carries it (`once` ends
  do not) and the dispute authority's stop entry is `chosen`, with the treatment in
  each stop event; on the interim revision the fields are absent and the
  vector-qualified fixed charged semantics apply, dispute stops included. Periods
  earn at period end or at the part's stop, not at period start. The term end
  carries its own `partialPeriod`, `returned` in the compute presets; unexpressible
  terms fail closed, and an interim rate option commits `started_period` on every
  present entitlement and, where only a charged end is expressible, on the term
  end, disclosed. Negotiation decides the accepted treatment: seller presets offer
  `last_boundary`, and the terms-owned buyer policy by default refuses any other
  payee or term-end treatment, so interim spot and on-demand need the buyer's
  explicit `started_period` acceptance and reach default buyers only once
  `returned` is expressible in the vendored contract.
- The seller half's notice command runs through the existing seller-authenticated,
  negotiation-keyed lifecycle `submit`, with a typed client method and a
  `deals preempt` operator verb in both domains. The stop is submitted at once to
  the payment authority, which hosts the pending stop; no payment stop is ever
  scheduled locally.
- Setup and rate preset helpers are supplied to the terms change's publication
  adapters. A preset is a combination of parts and terms, not a runtime class.
  Setup is an ordinary `once` part owed by the buyer from approval, ending at the
  later of the Agreement start and approval; a buyer's stop before or after
  activation leaves it with the seller, and only the seller's self-penalty for
  non-delivery returns it.
- The hosted rate `authorize` hook for commit, dispatch, start and disclose
  consumes the foundation's versioned activation envelope; convergence composes it.
  Delivery authorization is pure. The separate post-activation `start_billing`
  effect uses end service's sole journaled operation key, and delivery keeps a
  reference rather than a second start intent.
- The canonical rate buyer end is stop, then hint: delivery continues through the
  priced notice and ends through authority `watch`. `end_delivery` remains the
  explicit immediate surrender and the path when the payment authority is
  unreachable; it carries no `at`, the storefront signs its receipt time as
  evidence, and the storefront cannot stop the buyer's billing. When payments is
  unreachable the buyer half journals its stop and retries it under the same key,
  and billing runs until the stop lands. An optional `buyer_end` case goes to human
  triage with the signed request, the receipt and the exact Agreement verified
  against the mandate's deal hash; its ruling preserves the payer's notice and
  `partialPeriod`.
- A seller's `exceptional_end(at)` is journaled and filed through the dispute
  adapter to the Agreement's dispute authority, never future-dated: a pre-start
  failure journals at once and files at the Agreement start, and the seller sends
  no stop or reverse. Mediation's one mechanical ruling applies: an at-least-standard
  payee self-penalty of `returned` rate stops now, reversal of earnings since `at`,
  reversal of the time-unserved `once` shares (all of setup before delivery, none
  after), then the premature-stop penalty capped by the earned amounts still held,
  across parts in mandate order; bond award is reserved. The adapter consumes the
  foundation's dispute intent, request vocabulary and published mapping, and
  neither calculates nor partially applies the package.
- Service-identity overlap and re-anchoring run through the foundation's
  verified-snapshot interface; snapshot-proof verification itself stays with the
  foundation's round 2.
- Mechanics are qualified against published vectors and the in-lane payment and
  mediation doubles. A lane-only `proposed` servicing declaration permits
  qualification before hosted deployment and produces no live evidence.

This change absorbs the mechanics and spot scenarios of the superseded
`settle-ongoing-compute-through-arkhai-payments` and
`publish-and-preempt-spot-compute`, whose directories are removed.

## Capabilities

### Modified Capabilities

- `settlement-servicing`: rate mandates, adapter events, start and stop
  translation, authority-enforced started-period terms and rate-deal identity
  re-anchoring.
- `settlement-configuration`: typed rate parameters and the servicing declaration.
- `storefront-publication`: both domains' rate presets and per-option prices.
- `deal-lifecycle`: the seller notice command, status and operator surface,
  extending the capability the foundation introduces.
- `test-compatibility`: vector and qualification boundaries for rate parts.

### New Capabilities

None.

## Dependencies and acceptance boundary

Implementation builds on:

1. `agreed-evidence-and-early-termination`: the term codec, hosted contract
   vendoring and the `once`-part adapter, lifecycle commands, dispute intents and
   mediation's published self-penalty mapping, the evidence stores and verified
   snapshots (its round 2). This change consumes those facilities and duplicates
   none.
2. `negotiate-open-ended-compute-terms`: the agreed-price accessor and period
   unit, the listing bounds, the accepted-price carrier and option shape, the
   declaration contract, the whole-second start resolution before signature, and
   the publication and acceptance gates. The terms change archives on its own
   evidence; it does not wait for this change's materialization door.
3. The foundation's in-process contract fakes gate kit library integration.
   `add-arkhai-payments-lane-double` supplies the HTTP doubles, wall-time typed
   due-work barriers and the three named evidence classes for lane and e2e evidence
   only, not as an implementation prerequisite.

`converge-ongoing-compute-leases` depends on this change and on
`unify-compute-delivery-path`: it owns rate servicing in `kit/deal-servicing`,
funding timers, journal persistence and replay, start admission and the domain
lease effects, and the complete rate qualification matrix with its runnable entry
points. This change prepares those entry points and runs no lane qualification of
them. `activate-per-period-compute-servicing` owns the switch-on and hosted
qualification once the contract revision is deployed.

Complete here means exact buyer and seller derivation, usable adapter mechanics,
both domains' preset and notice surfaces, and the rate buyer end, with vector, kit
and application evidence. Cross-service spot acceptance additionally needs the
continuation; a passing double-backed scenario never qualifies the external payment
or dispute authority.

## Non-Goals

- A minimum-spend primitive, payee backdating, or a local payment-stop scheduler;
  the design records the rejected payment primitives.
- Storefront continuation loops, queues, funding timers, site deadline or renewal
  policy, provisioning or teardown.
- Snapshot-proof verification, immediate `end_delivery` transport and evidence
  capture, and mediation rulings, which are the foundation's. The rate buyer end
  is in scope.
- Cooperative corrections to entitled stop pricing, a second seller-command
  journal, or seller-side exceptional-end payment effects; mediation's published
  self-penalty mapping is foundation-owned and consumed here.
- Durable once-only identity re-anchoring; those deals drain before a key retires.
- Discovery sugar, automated preemption strategy, Alkahest splitter execution,
  API-credit rate servicing, metering other than time, and reserved fixed-interval
  deals expressed as rate parts.
- Any guarantee that depends on a cooperative storefront: the buyer's backstop is
  its own authority stop and a case over held money.

## Compatibility and impact

No backwards-compatibility promise for pre-upgrade hosted mandates; rollout is
forward only, as in the foundation. New rate and setup shapes receive new option
IDs. Reserved and API-credit options keep `once`-part mechanics. Examples use
`USD/6`; production derivation reads the selected Agreement's asset.

Affected code: `kit/arkhai-payments`, the lifecycle contracts, client and
seller-half command dispatch, both compute storefront compositions and operator
CLIs, and the two compute lanes' qualification scenarios. No mechanism kit imports a
domain or the persistence-owning servicing kit.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — adapter and servicing ownership and the
  release flow
- [x] Existing subsystem specifications — the five capabilities above
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Rate-part derivation, holds, authorities, arithmetic and re-anchoring:
  `openspec/specs/settlement-servicing/spec.md` and its architecture companion.
- Servicing declarations and identity-overlap configuration:
  `openspec/specs/settlement-configuration/spec.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Preset helpers, setup pricing and their terms-owned publication integration:
  `openspec/specs/storefront-publication/spec.md` and its architecture companion.
- The seller notice command, pending-stop observation and the rate buyer end: the
  foundation-created `deal-lifecycle` `spec.md` (see its
  [delta](../agreed-evidence-and-early-termination/specs/deal-lifecycle/spec.md))
  and its architecture companion.
- External payment contract context and guarantee limits:
  `openspec/specs/deal-lifecycle/architecture.md`.
- Vectors and evidence classification: `openspec/specs/test-compatibility/spec.md`
  and its architecture companion.
