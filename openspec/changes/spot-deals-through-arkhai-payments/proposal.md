## Why

VM and bare-metal sellers need to sell compute by the period from prepaid credits,
with a buyer stop and, for spot, a seller stop on notice. Approval alone is not
continued payment authorization: a rate part starts after provisioning and ends at
an authority-recorded stop, at exhaustion, or at the agreed maximum term.

The lifecycle foundation,
[`agreed-evidence-and-early-termination`](../archive/2026-11-03-agreed-evidence-and-early-termination/),
supplies the terms, the payment and dispute adapter boundary, the evidence stores
and end service. This change completes its hosted payment adapter for rate parts
and supplies both domains' presets and the seller notice command. The storefront's
continuation is a separate, dependent change.

## What Changes

- The `arkhai.payments.v1` settlement parameters and mandate derivation gain time
  rate parts, optionally combined with an honestly named setup `once` part. A setup
  amount is the seller's choice in both compute domains, and the bare-metal example
  configuration recommends pricing it for hosts. Prices come from the agreed-price
  accessor, never from a direct read of `Agreement.amount`. The option carries one
  `asset`, in `price`; the hosted parameters no longer repeat it.
- Per-part authorities are derived from the option's `lifecycle`: payee-only rate
  `start`, each entitled party's stop entry with its priced notice, and the dispute
  authority's stop, reverse and extend permissions. Seller stop entries exist only
  for entitlements, such as spot's notice; on-demand has none, and its no-preemption
  promise is enforced by remedy — the premature-stop penalty and a buyer case over
  held money, with a bond reserved — not by the mandate. The seller's emergency
  exit is an `delivery_end` dispute filing, on spot too. There is no restitution
  entry, implicit favourable stop privilege, multiple-entry gate, notice waiver or
  payer early release. Parts carry their `end`, `{afterStop: dispute_window}` and
  `maxHoldExtension`. The shipped presets price the payer's notice at zero.
- The hosted adapter's command translation, reads and `watch` source gain per-part
  `start`, pending and final stops, funding and maximum-term observations, and
  record each descriptor's digest through the caller's operation store before any
  I/O. Started-period treatment is a per-stopper `partialPeriod` payment term, not
  a storefront refund: the published contract expresses every treatment, every rate
  stop entry and part end carries it (`once` and setup ends the inert `returned`
  the schema requires), and the dispute authority's stop entry is `chosen`, with the
  treatment in each stop event. Periods earn at period end or at the part's stop,
  not at period start. The term end carries its own `partialPeriod`, `returned` in
  the compute presets. A composition offers only the treatments its servicing
  declaration lists, declared after hosted qualification. Negotiation decides the
  accepted treatment: seller presets offer `last_boundary`, and the terms-owned
  buyer policy by default refuses any other payee or term-end treatment unless the
  run waives that term; payment approval applies the same run's policy.
- One payments transaction adapter implements the lifecycle `PaymentAdapter`
  protocol by composition — shared components and per-part-kind behaviour — with no
  inheritance between once and rate behaviour; the protocol's `authorize` gains an
  optional journaled billing-start argument and `start_billing` takes
  `OperationKeys`. The rate `authorize` decides on a snapshot observed within a
  configured freshness window of the storefront's clock, checking every bound at
  the storefront's `now`.
- Stop requests stay distinct from final stops in the lifecycle contracts, and the
  `read`/`list` routes omit the new empty fields so once-deal reads stay valid for
  released 0.1.0 clients.
- Approval expiry has one name, `approval_window`: this release's readers accept the
  released `window` as an alias and refuse both together, rate options write
  `approval_window`, and once-option writers switch and the alias is removed in the
  next two releases.
- The seller half's notice command runs through the existing seller-authenticated,
  negotiation-keyed lifecycle `submit`, with a typed client method and a
  `deals preempt` operator verb in both domains. The stop is submitted at once to
  the payment authority, which hosts the pending stop; no payment stop is ever
  scheduled locally. The administrator interrupt's `interruption_kind` is classified
  in `kit/deal-servicing`'s seller half, and both storefronts mount the route over
  it, bare metal gaining the route and its typed admin client.
- Setup and rate preset helpers are supplied to the terms change's publication
  adapters. A preset is a combination of parts and terms, not a runtime class.
  Setup is an ordinary `once` part owed by the buyer from approval, ending at the
  later of the Agreement start and approval; a buyer's stop before or after
  activation leaves it with the seller, and delivery_end with delivered=false for either cause returns it.
- The hosted rate `authorize` hook for commit, dispatch, start and disclose
  consumes the foundation's versioned activation envelope; convergence composes it.
  Delivery authorization is pure. The separate post-activation `start_billing`
  effect uses end service's sole journaled operation key, and delivery keeps a
  reference rather than a second start intent.
- The canonical buyer end verb is `end` in both domains, `bare-metal teardown`
  becoming a deprecated alias for one release. The canonical rate buyer end is stop,
  then hint: delivery continues through the
  priced notice and ends through authority `watch`. `end_delivery` remains the
  explicit immediate surrender and the path when the payment authority is
  unreachable; it carries no `at`, the storefront signs its receipt time as
  evidence, and the storefront cannot stop the buyer's billing. When payments is
  unreachable the buyer half journals its stop and retries it under the same key,
  and billing runs until the stop lands. An optional delivery_end case is mechanical with matching receipt concurrence and the foundation guards, otherwise triaged, carrying the signed request, the receipt and the exact Agreement verified
  against the mandate's deal hash; its ruling preserves the payer's notice and
  `partialPeriod`. An opt-in foreground watchdog in the buyer's `buy` command sends
  the buyer's ordinary stop when the disclosed access fails its configured probes,
  a bound stated as conditional on the command running. The buyer's read shows it
  monitored only while its last probe is fresh, a status the buyer half computes
  and no lifecycle wire model carries.
- A servicing declaration enables rate offers, not their execution: end service
  refuses to commit a rate deal while it services no rate deals, before any capacity
  is placed. The refused deal is repair-required with a named reason, carried as a
  closed refusal code on the delivery authorization, until the existing delivery
  deadline rule classifies non-delivery and files — for a rate deal, only after a
  payment read at or after the deadline shows no earlier buyer stop, so a stop made
  while the storefront was down wins. Convergence lifts the refusal
  when it composes rate servicing.
- A seller's `delivery_end(cause=payee)` is journaled and filed through the dispute
  adapter to the Agreement's dispute authority, never future-dated: a pre-start
  failure journals at once and files at the Agreement start, and the seller sends
  no stop or reverse. Mediation's payee-agreed rule, whose cause=payee branch is the standard self-penalty
  (`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`), applies. The adapter consumes the
  foundation's dispute intent, request vocabulary and published mapping, and
  neither calculates nor partially applies the package.
- Service-identity overlap and re-anchoring run through the foundation's
  verified-snapshot interface; snapshot-proof verification itself stays with the
  foundation's round 2.
- Mechanics are qualified against published vectors and the in-lane payment and
  mediation doubles, labelled lane-double evidence; live evidence comes only from
  deployed authorities. One recurring-purchase E2E scenario per compute lane runs
  from a lane-only servicing declaration through approval and commit, observes end
  service refuse the commit, and ends by the buyer's own stop.

This change absorbs the mechanics and spot scenarios of the superseded
`settle-ongoing-compute-through-arkhai-payments` and
`publish-and-preempt-spot-compute`, whose directories are removed.

## Capabilities

### Modified Capabilities

- `settlement-servicing`: rate mandates, adapter events, start and stop
  translation, authority-enforced started-period terms and rate-deal identity
  re-anchoring.
- `settlement-configuration`: typed rate parameters, the materialization door on the
  servicing declaration, and the staged `approval_window` rename.
- `storefront-publication`: both domains' rate presets and per-option prices.
- `deal-lifecycle`: the seller notice command, status and operator surface, the
  administrator interrupt classification, the canonical end verb, committed
  partial-period treatment, and end service's refusal to commit a rate deal it
  cannot service, extending the capability the foundation introduces.
- `compute-delivery`: both compute storefronts' administrator interrupt route, and
  the repair reason a refused rate deal reports.
- `buyer-orchestration`: payment approval under the run's terms policy.
- `test-compatibility`: vector and qualification boundaries for rate parts and the
  recurring-purchase E2E.

### New Capabilities

None.

## Dependencies and acceptance boundary

Implementation builds on:

1. `agreed-evidence-and-early-termination`: the term codec, hosted contract
   vendoring and the `once`-part adapter, lifecycle commands, dispute intents and
   mediation's published self-penalty mapping, the evidence stores and verified
   snapshots (its round 2). This change consumes those facilities and duplicates
   none.
2. `negotiate-open-ended-compute-terms` (archived): the agreed-price accessor and
   period unit, the listing bounds, the option shape, the servicing declaration,
   the per-term buyer waivers, the whole-second start resolution before signature,
   and the publication and acceptance gates.
3. The foundation's in-process contract fakes gate kit library integration. The
   in-lane payments double supplies the HTTP double and the lane-double evidence
   label for lane and e2e evidence only, not as an implementation prerequisite.

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
`USD/6`; production derivation reads the selected Agreement's asset. Released
clients keep working across this release: once options keep writing `window`, the
lifecycle reads stay valid for `kit/deal-lifecycle-contracts` 0.1.0 clients, the
administrator interrupt keeps `failure` as the once-only default, and `bare-metal
teardown` stays an alias for one release.

Affected code: `kit/arkhai-payments` (the composed transaction adapter, presets,
the `approval_window` alias, approval policy), the lifecycle protocol, contracts,
client and seller-half command dispatch and interrupt classification, end
service's rate-deal refusal and the delivery authorization's refusal code, the
compute delivery path's repair reasons, the buyer
half's end and watchdog, both compute storefront compositions, administrator routes
and operator CLIs, both compute buyers' end verbs and approval, and the two compute
lanes' qualification and recurring-purchase scenarios. No mechanism kit imports a
domain or the persistence-owning servicing kit.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — adapter and servicing ownership, the
  release flow, the subclassing principle and the timestamp principle
- [x] Existing subsystem specifications — the seven capabilities above
- [x] `docs/development/RELEASING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`,
  `AGENTS.md` and the change workflow's guidance
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1 rate parameters, the setup part as the seller's choice in both domains, presets
  and the shared composition wiring: `openspec/specs/storefront-publication/spec.md`
  and its architecture companion; `openspec/specs/settlement-servicing/spec.md`.
- D2 exact per-part derivation and the buyer's check:
  `openspec/specs/settlement-servicing/spec.md`.
- D3 the published contract, its vectors and qualification limits:
  `openspec/specs/deal-lifecycle/architecture.md`, "External authorities".
- D4 adapter commands, descriptor recording through the caller's operation store,
  pure rate authorization and the freshness window:
  `openspec/specs/settlement-servicing/spec.md` and its architecture companion;
  `docs/development/DEPLOYMENT_AND_CONFIG.md` for the setting.
- D5 authority-priced treatment and approval under the run's terms policy:
  `openspec/specs/settlement-servicing/spec.md`;
  `openspec/specs/buyer-orchestration/spec.md`.
- D6 seller notice and the administrator interrupt classification and routes:
  `openspec/specs/deal-lifecycle/spec.md` and its architecture companion, "Buyer
  surrender and cases" and "External authorities";
  `openspec/specs/compute-delivery/spec.md` for both compute storefronts' route.
- D6a the rate buyer end, the canonical `end` verb and the watchdog, its status
  resting on a fresh last probe: `openspec/specs/deal-lifecycle/spec.md`;
  `openspec/specs/buyer-orchestration/spec.md` and its architecture companion, a new
  section "The buyer's watchdog".
- D7 servicing declarations, the materialization door, the `chosen` presupposition
  and identity rotation: `openspec/specs/settlement-configuration/spec.md`;
  `openspec/specs/settlement-servicing/spec.md`;
  `openspec/specs/deal-lifecycle/architecture.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D8 vectors, the two evidence labels and the recurring-purchase E2E:
  `openspec/specs/test-compatibility/spec.md` and its architecture companion.
- D9 the staged `approval_window` rename:
  `openspec/specs/settlement-configuration/spec.md`;
  `docs/development/RELEASING.md`.
- D10 stop requests distinct from final stops, wire-compatible for released readers:
  `openspec/specs/deal-lifecycle/spec.md`;
  `openspec/specs/settlement-servicing/spec.md`.
- D11 the composed payments transaction adapter:
  `openspec/specs/settlement-servicing/spec.md` and its architecture companion;
  `openspec/specs/deal-lifecycle/spec.md` for the protocol.
- D12 end service's refusal to commit a rate deal it cannot service, the one place
  delivery fails closed before rate servicing: `openspec/specs/deal-lifecycle/spec.md`
  and its architecture companion, "One end instant, transactional admission";
  `openspec/specs/compute-delivery/architecture.md`, "Commit and hold adoption", for
  the refused commit.
- D13 the refusal as an unconditional invariant convergence modifies:
  `openspec/specs/deal-lifecycle/spec.md`.
- D14 the refused deal's repair state, its `rate_servicing_unavailable` reason and the
  delivery authorization's refusal code: `openspec/specs/compute-delivery/spec.md`
  for the reason and the site-refusal wording of the undelivered hand-off;
  `openspec/specs/deal-lifecycle/spec.md` for the code and the deadline barrier for
  a deal that is not once-only, with the barrier's rationale in its architecture
  companion, "One end instant, transactional admission".
- D15 the door reading the committed seller projection:
  `openspec/specs/deal-lifecycle/spec.md`.
- D16 the recurring-purchase scenario through commit, ended by the buyer:
  `openspec/specs/test-compatibility/spec.md`; its architecture companion, "Ordinary
  Arkhai purchase evidence".
- Each change is mergeable to `dev` on its own merits: `openspec/README.md` or
  `docs/agents/change-workflow.md`.
- Check a sibling domain before adding behaviour to one; a difference needs a
  reason stated where it lives: `AGENTS.md`, "Package and dependency discipline".
- A versioned contract's field may be renamed or retired in stages, a path for
  deprecating a field and not a limit on how a contract may change:
  `docs/development/RELEASING.md`.
- Contradictory classes implement a shared interface or a common base rather than
  subclass one another: `docs/development/ARCHITECTURE.md`.
- A timestamp is its source's claim, never an ordering between parties:
  `docs/development/ARCHITECTURE.md`, authority boundaries.
