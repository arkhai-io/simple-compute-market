# Design

## Context and authority

This change builds compute terms on the archived
`agreed-evidence-and-early-termination`. Its vocabulary and codec win. Design for
an adversarial counterparty and make the reference implementation cooperative.
The buyer can rely on authority records and kept signed bytes, not seller uptime.
This change owns compute terms and presentation, not authority operations.

A settlement option is `{option_id, price, settlement, lifecycle}`, with `lifecycle`
in the option ID (`core/src/market_core/schemas.py`), and the codec in
`kit/deal-lifecycle` validates it. The vendored payments contract publishes every
`partialPeriod` treatment, per-part authorities, end rules and stop-relative holds
(`kit/arkhai-payments/schema/SOURCE.md`), and the kit maps all of them. What limits a
treatment is whether a composition has qualified it against its payment authority,
not the vendored contract (D6). VM falls back to the requested duration, else
`max_duration_seconds`, else an hour, for every option
(`domains/vms/storefront/src/market_storefront/negotiation_runtime.py`); bare metal
requires a positive lease bound.

Goal 8's MVP change `offer-per-period-vm-terms` lands first. It publishes on-demand
and spot options on fixed-shape, flat-priced VM listings with every treatment
`started_period`, no penalty and no setup part; ships the accessor with its absolute
reading; resolves the horizon from `max_duration_seconds` with whole-second starts;
omits unbounded per-period VM candidates; gates publication and acceptance on the
declared treatment list `[charged]`; shows the VM buyer the class, per-period price,
reserve, latest end, notices and the charged started period; and ships MVP buyer
defaults that accept a started-period final period everywhere and require no
penalty. Its delivery deadline is the seller's configured payments-clause value.
This design states the full product on top of it; D10 records what moved.

## Decisions

### D1. Classes are derived presets, never stored

| Selected option billing | Payer entitlement | Payee entitlement | Display |
|---|---|---|---|
| prepaid once | — | absent | reserved |
| per period (`period` present) | present | absent | on-demand |
| per period | present | present | spot |
| prepaid existing Alkahest splitter | — | release condition permits interruption | prepaid interruptible |

`offer-per-period-vm-terms` derives these classes for VM display; this change
derives them identically for bare metal and for every option a buyer is shown.
A setup once charge beside a rate does not make it prepaid. One listing can offer
several combinations at different rates over its existing pool/shape identity;
options add no publication-derivation dimension or duplicated capacity. `--class`
is discovery sugar, not a wire field.

The existing splitter stays seller-trusted with its current service terms. The
foundation removes `listing_resource.interruptible` and `settlement_model`,
migrates flags to `release_models`, and retains bare metal's unsupported-splitter
refusal. Read the accepted release condition for display; do not invent lifecycle
terms for a mechanism with no lifecycle adapter.

### D2. Quote once with its unit; guard every read

Core's unit-bearing accessor, shipped by `offer-per-period-vm-terms` with its
absolute reading, returns price and unit `total` or `per_period` (with the actual
period for presentation), never an unlabelled integer. Both domains'
policies/reference quotes, buyer caps/display, amount checks, mandate derivation and
buyer mandate checks use it; this change migrates bare metal's readers. Additional
setup pricing is explicit, not hidden in the recurring quote.

The negotiated multiplier's reading — basis points over the rate structure the
accepted option binds, evaluated over Agreement duration for prepaid and one option
period for recurring, with upward rounding and the asset's amount-range refusal — is
`negotiation-driven-capacity-resize`'s, together with the discriminator that tells a
multiplier Agreement from an absolute one and the guarantee that an absolute-reading
Agreement stays absolute. It extends whichever accessor exists when it lands. This
change neither waits for it nor reimplements it.

A fail-closed repository check refuses direct `Agreement.amount` reads outside the
accessor and declared raw negotiation hooks. Cover actual attribute/mapping reads
and aliases/wrappers; an unclassified reader fails rather than escaping detection.
Model declaration/serialization is not price interpretation. Each hook allowlist
entry records why it negotiates the scalar instead of spending it.
The guard is AST-based, using the existing architecture-check pattern,
with positive/negative fixtures in its owning script tests; use the smallest
implementation that rejects every repository reader found during migration.

### D3. One shared codec, no interruption object

Keep the foundation's exact shapes and names:

- `early_termination = {version, entitlements, settles_through, premature_stop_penalty?}` — the deal's horizon is not in it (D5);
  its top-level `settles_through` is the sole term-end treatment carrier (no mechanism-specific duplicate), separate from
  entitlements keyed by `payer`/`payee`, each `{notice_seconds, settles_through}`.
  Foundation D5 owns the `settles_through` mapping: `started_period` ↔ charged,
  `last_boundary` ↔ returned, `stop` ↔ prorated. Seller presets offer payer charged and,
  for spot, payee returned once the composition declares `returned` (D6); until then the
  shipped spot preset names payee `started_period`, as the MVP's does. The buyer's
  default acceptance policy refuses a payee entitlement or a term end whose treatment is
  not `last_boundary` — the seller's preemption and the term end are the ends the buyer
  does not time: billing starts at activation, so the term end falls mid-period and a
  charged one bills past the agreed maximum — and accepts charged treatment on its own
  payer stop. A buyer may loosen or tighten it. Publication and acceptance
  refuse any treatment the composition has not declared. `exposure_seconds` and `stop+exposure` are retired.
- `adjudication = {version, dispute, dispute_window_seconds, case_hold_max_seconds}`;
  `dispute = {interface, origin, account, record_key, params}`.
- `premature_stop_penalty` is a nonnegative integer amount in the option asset's minor units, encoded as a canonical decimal string; absent/zero means none. It applies to an unentitled seller end, including a spot emergency without notice, not an entitled notice stop. On-demand presets default to 24 periods' price (calculated through the agreed-price accessor), with seller override. The default buyer displays the penalty as a ceiling and never requires one; a buyer may configure a minimum. This revises the round-8 disposition, which kept refusing an unpenalized on-demand offer by default: the MVP's buyers take on-demand without one, and a default refusal would turn away every MVP seller's offer for a remedy that is often uncollectible, as follows. The number is a ceiling, not a guarantee: the remedy takes `min(penalty, earned amounts still held)` after the refunds, and early in a deal what is earned and held is the setup charge alone — an on-demand VM pulled minutes after activation, with its started period returned, leaves nothing else to take, and zero with no setup charge. A seller-funded stake that makes the ceiling collectible is the reserved `bond` term (foundation D5), not this change's.
- `bond` stays reserved where the mechanism cannot hold a seller-funded stake.
- `delivery_deadline_seconds` is the value the composition supplies to publication,
  published under that name on every compute option whose mechanism has a lifecycle
  adapter, recurring or once. Its source is not this change's: today it is the seller's
  configured payments-clause value, and in the full product it is the pool's
  `delivery_deadline_seconds` tag, read from the site projection at publication,
  carried with the commit and enforced by the site — all
  `renewable-compute-lease-deadlines`'. The default buyer already refuses a compute
  option without the term unless its operator opts out (`deal-lifecycle`, "The delivery
  deadline is the site's availability term"). This change consumes the value in the
  runway (D5) and the display (D7). An Alkahest compute option carries no `lifecycle`
  and so no deadline term: the runway check does not apply to it and the display says
  the option makes no delivery promise; a mixed hosted/Alkahest listing under default
  selection is a first-use fixture (tasks, section 4).

A payee entitlement means the seller may interrupt; the payment authority enforces
its notice as a pending stop on that stop authority, not a local schedule.
On-demand has no payee stop entry. The mandate therefore does not enforce that the seller
won't preempt; that is enforced by the penalty and a buyer's case over held money, not by the mandate.
The seller's own exit is `delivery_end(cause=payee)`, a dispute filing the seller half journals with
the end and files with the dispute authority; the seller sends no stop or reverse of its own.
Arkhai mediation rules payee-agreed delivery_end under its mapping/time/replay guards; the cause=payee branch is the standard self-penalty (`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`); the terms this change publishes are what that
ruling reads — the penalty, the treatment of the started period, the setup charge — and
the display explains them against it (D7). A buyer contesting the account files a case;
mediation triages claims lacking payee agreement or failing its mapping/time/replay guards; matching receipt-backed payer claims rule automatically. There is no compensation enum. The delivery_end revision and its vectors are vendored (`kit/arkhai-mediation/schema/SOURCE.md`); vendoring does not qualify a hosted deployment, so a production composition declares setup-bearing presets only after the hosted mediation service runs that revision (`activate-per-period-compute-servicing`). Setup-free presets are independently eligible.
Entitled rate stops follow the committed per-stopper `settles_through`, computed by the
payment authority, not a later storefront refund or promise to prorate every end.

Hosted once options carry adjudication but no early_termination: no part is
stoppable. Recurring presets carry payer and optionally payee entitlement. Buyer
notice is offered/priced and may be zero; it is the only paid stop tail.
Polling/watchdog/teardown budgets are seller recommendations, not another term.
Adjudication must use an accepted authority and satisfy its advertised minimums, and on a
compute option its `dispute_window_seconds` must be at least `delivery_deadline_seconds`
plus the authority's advertised minimum window (foundation D5): a setup part pays out one
window after its end, non-delivery is provable one deadline after the anchor, and the
margin is what the authority says a filer needs. Derivation refuses the option with the
diagnostic "the dispute window ends before the delivery deadline can be filed on", and
the buyer refuses one offered anyway.
Unsupported/malformed terms and unknown versions fail closed in the shared codec.

The shipped buyer acceptance policy is one object this change owns, so publication
evaluates every recurring option against it and reports the result where the seller
looks: the derivation log and the seller's listing diagnostics name each term a
default buyer refuses — a payee treatment other than `last_boundary` — as "a default
buyer refuses this option: <term>". The option still publishes; the seller is told,
not stopped, and can see why no default buyer takes the offer. This change owns that
policy object; `offer-per-period-vm-terms` ships its MVP defaults, and this change's
policy replaces them.

Resolve seller preferences through override > pool hint > configured default,
keyed per offered preset like its rate. These are seller choices, not a protocol
requirement to price identically. Shipped recurring presets have
a payer entitlement with `notice_seconds: 0` — a buyer who stops is charged to the started
period and nothing after, and a seller who wants a tail prices it as a number the buyer sees;
spot adds a payee entitlement. A setup once part is a seller opt-in with a configured price
on VM and is required, seller-priced, on bare metal (D8). Omission
never grants the payee an implicit entitlement. The foundation owns validation and
identity inclusion; do not create a second hash rule or require early_termination
on every compute option. Terms injects a preset-helper interface: selected quote/unit,
period/reserve (`derive-rate-parts-in-the-payments-kit`'s parameters), setup, bounds,
adjudication, payout hold and early-termination declarations in; a canonical candidate
option or a named derivation refusal out. The payments kit supplies the hosted helper;
generic publication tests use injected helpers. Missing helper omits the recurring
candidate, never reconstructs the mechanism's parameters.

### D4. The terms are the option's `lifecycle`

`early_termination` and `adjudication` are objects under the option's `lifecycle`, beside `price` and `settlement`, and so in the Agreement bytes and the option ID (foundation D5, "The option's shape"). They are the parties' rights after commitment — who may end the deal, on what notice, with what treatment of the period in progress, and who decides a dispute — and become payment facts only when exercised, when the adapter derives stop authorities from the entitlements and the hold from the window; they are owned by the lifecycle codec, not by any settlement mechanism, so they do not sit in the mechanism's own parameters under the mechanism's model. The codec reads both keys by the same names and shapes whatever the settlement schema, and never branches on it or decodes Alkahest arbiter demand trees to read them. A mechanism adapter separately refuses terms it cannot enforce: carrying the keys is not permission to advertise an unsupported Alkahest lifecycle promise. The placement is implemented and promoted (`deal-lifecycle`, "Lifecycle terms are part of the selected option"), and the codec refuses lifecycle terms on a mechanism with no adapter.

### D5. Two listing bounds compose at the agreed start

`max_duration_seconds` is the longest deal from its start; `available_until_utc` is
the last possible lease end. Both are listing capacity facts, not option copies or
`listing_resource` fields. Resolve through override > pool hint > configured
default per offering mode. Nonpositive/unset relative bound means no relative
limit; a stated absolute bound is timezone-aware UTC. Malformed bounds hold
derivation with a diagnostic, not a guessed default.

At resolved `start_utc`, let `B = min(positive max_duration_seconds,
available_until_utc - start_utc)` over stated bounds. Default recurring selection
binds `duration_seconds = B`.
If one bound is absent use the other. Require at least one whole period, but do not
round the horizon. Bind an explicit shorter buyer horizon unchanged, show the
effective horizon before signature, and refuse a longer, expired or sub-period
selection. Every reserved duration must fit both bounds.

**The runway.** A horizon must leave room to deliver after the latest approval the
option permits. At acceptance the seller requires, for a recurring option,

    start_utc + duration_seconds ≥ max(approval expiry, start_utc)
                                   + delivery_deadline_seconds + period

where the approval expiry is the mandate's own, `floor(accepted_at) + approval_window`
by the foundation's settlement rule — the authority's exact expiry instant, not an
approximation of it — and refuses otherwise, naming the minimum horizon that passes,
so the buyer can re-propose. Derivation applies the same inequality to the default
horizon *B* at publication and reports a failing *B* as a derivation close reason
beside the F13 diagnostics; that keeps a fresh listing from advertising a default the
seller would refuse, and no more: the absolute availability bound shrinks while a
listing stays published, so a default that passed at publication can fail later, and
acceptance-time revalidation is the safeguard, refusing with the minimum as for any
other stale bound. A reserved option needs no runway: its term end is its one delivery
instant and the deadline bounds it from the other side. The three quantities have
three owners — `approval_window` and `period` are settlement parameters,
`delivery_deadline_seconds` is the lifecycle term the composition supplies — and the check is
the only place they meet; a buyer that approves at the last permitted instant gets
its period, and no timing the Agreement permits is a seller breach.

Rate billing starts at activation, potentially later than the Agreement start,
while the payments end is absolute: horizon rounding cannot align that end to a
billing boundary. Foundation D5 therefore gives the term end its own
`settles_through`, mapped to the rate part's `end.partialPeriod` with the same
values as stop authorities. Shipped presets name `last_boundary` at the term end
where the composition declares `returned`, so billing never runs past the agreed
maximum, and `started_period` otherwise, disclosed in the option; the default buyer
refuses the latter (D3), since no seller can align the term end to an activation-offset
billing period. Exhaustion
needs no separate rule: reserve-ahead places it on a period boundary.

Recurring start_utc must resolve to whole-second precision before the final signature;
refuse a fractional rate start rather than round signed bytes. Preserve once-only
fractional handling. The horizon is the Agreement's `duration_seconds` and nothing
else: the option carries no maximum term, so the same option serves every buyer and
its ID is stable from the registry to the Agreement; the seller's signed acceptance
carries the advertised option unchanged and the resolved `duration_seconds`, which the
buyer checks against both listing bounds at the agreed start. The rate part's end is
`start_utc + duration_seconds` (spot D2). No option is minted at acceptance and no
identity changes.

`offer-per-period-vm-terms` resolves the VM horizon from `max_duration_seconds`,
requires whole-second recurring starts and omits unbounded per-period VM candidates;
this change applies the same rules to bare metal and adds `available_until_utc` and
the runway to both. An unbounded bare-metal recurring candidate yields no option and a
derivation close reason, not a hold merely for being unbounded; valid reserved
candidates remain. Bare
metal's existing positive-bound rule for reserved candidates remains. A later
listing-date edit never extends an accepted lease. The shared delivery change
uses accepted start plus duration in both domains, not `now`. Here remove VM's
fallback for a reserved option with no requested duration, which today substitutes
the listing maximum or an hour; delivery owns its resume fallbacks.

### D6. Three doors read one declared treatment list

Composition, not a listing or buyer, declares rate servicing as the list of
`partialPeriod` treatments it has qualified against its payment authority — for
example `[charged]`, or `[charged, returned]`. An empty or absent list means no rate
servicing. The vendored contract expresses every treatment, so the list records what
a deployment has qualified, not what the contract can say. No additional
minimum-spend primitive gates it.

1. Publication omits a recurring candidate naming any undeclared treatment, on an
   entitlement or at the term end, using existing no-settlement-option diagnostics if
   none remain.
2. Acceptance refuses a cached recurring selection naming a treatment the composition
   no longer declares, using the withdrawn-option/refetch outcome before persisting
   acceptance.
3. Materialization refuses to derive a rate mandate naming an undeclared treatment,
   even across an acceptance/restart gap.

The MVP's composition flag in `offer-per-period-vm-terms` is this list, `[charged]`,
from the start, and `derive-rate-parts-in-the-payments-kit`'s materialization gate is
the third door. This change owns the declaration contract and wires both storefronts'
publication and acceptance to it; `spot-deals-through-arkhai-payments` lifts
derivation for each declared treatment; `switch-on-hosted-per-period-vm` and
`activate-per-period-compute-servicing` extend each production composition's list
after hosted qualification. Startup refuses to strand accepted rate deals without
their continuation, and withdrawing a treatment never disables accepted-deal
servicing (`serve-running-rate-deals-on-vm` for VM, `converge-ongoing-compute-leases`
in full). This plan qualifies publication and acceptance with injected declarations;
neither consumer's completion gates this change's archive.

### D7. Display what the authority can enforce

Both CLIs show class, recurring charge/period or total, separate setup once charge,
initial reserve (not spend), maximum end/horizon, the delivery deadline ("active within
N of your approval, or the seller has not delivered"), payer/payee entitlements, notice,
per-stopper and term-end `settles_through` treatment, the payout hold (D9), the premature-stop penalty as
"up to N, taken from what the seller has earned and not yet been paid — at the start of a
deal, the setup charge" with its worst case (nothing earned, nothing taken) stated rather
than implied, dispute authority/window/case-hold cap and evidence retention. A filed case
is shown by the authority's per-part answer, `held` with its extension or `not_held`
with the reason, never as a refund pending: an accepted case over paid-out money
recovers none of it. Values come from the selected option, not a stored class. Asking rate keeps its stated unit.
`offer-per-period-vm-terms` shows the VM buyer the class, the per-period price, the
reserve, the latest end, each party's notice and the charged started period; this
change brings bare metal to that display and adds the setup charge, the penalty, the
payout hold, returned treatment, adjudication and retention to both.
The seller's side of the same display is the default-buyer refusal diagnostic (D3), so
seller and buyer read one policy.

Explain rate start as a journaled effect after lease activation, distinct from buyer
credential disclosure; explain each stopper's started-period charge/return/proration,
the one priced notice, authority-hosted pending stops and adjudication for
unentitled loss of service. Reserve-ahead is not a dishonest-seller billing cap, and
no number the seller publishes caps an honest crash: if the resource is lost while the
seller's storefront is down, the buyer is charged until its own stop lands, a seller that
recovers within the dispute window returns everything since the loss, and a case is the
remedy after that.
Holds last through stop plus dispute window and accepted case extensions. Keep
signed evidence through at least the window after the latest delivery end, last
payout or case close. Sellers file delivery_end for failed/non-started delivery;
the buyer's stop/case is its backstop. The buyer's end — stop first, hint, `end_delivery` as end-now, the journaled retry while
billing runs, the receipt-backed `delivery_end(cause=payer)` or triage — is the foundation's (`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-buyers-end`); the display
explains each step as that statement gives it. The setup charge is
owed from approval; a payment stop alone does not reverse it. A qualified delivery_end returns it iff delivered=false for either cause, keeping it iff true — which is the F14 ground with the filer generalized: it returns only when the seller never delivered, by its own filing, its signature on the buyer's claim, or a person's ruling on the buyer's evidence. The display says so before approval: stopping keeps the setup charge with the seller; only the seller's non-delivery returns it.

### D8. Churn is seller pricing/policy, not a protocol gate

Neither domain requires minimum spend. A setup once charge beside the rate is honestly
named. On VM it is a seller opt-in with a configured price, so a VM per-period preset
carries none by default; on bare metal it is required and seller-priced. Sellers may
price differently or refuse churners,
including by principal blacklist, without claiming resistance to identity rotation.
No new minimum-spend request goes to payments. This change displays setup pricing;
the rate change derives it.

### D9. The payout hold is a seller-chosen term the buyer sees

How long the seller's earnings stay held is a lifecycle term the codec owns, in the
option ID and filterable like the other lifecycle projections. Its default is the
foundation's hold, until the part stops plus the dispute window
(`{afterStop: dispute_window_seconds}`). A seller may choose a shorter hold — for
example releasing each period's earnings a window after it is earned — to be paid
during a long deal. The display states a shorter hold as reduced buyer protection:
less earned money remains held for a case or a penalty to take. The default buyer
never refuses a hold; a buyer may configure a minimum. This change owns the term, its
validation and its display; `spot-deals-through-arkhai-payments` derives it into the
mandate (`for` versus `afterStop`) and checks it in the buyer's exact mandate check.
MVP options carry no hold term and keep the foundation's hold.

### D10. What the MVP took and what this change keeps

`offer-per-period-vm-terms` took reduced forms of tasks 2.1 (the accessor, absolute
reading only), 2.2 (VM's `max_duration_seconds`), 2.3 (VM on-demand and spot
options), 3.1 (the declared list over VM publication and acceptance), 3.2 (VM horizon
resolution and whole-second starts), 4.1 (the VM CLI, display and MVP defaults) and
D1's derived classes for display, and omits unbounded per-period VM candidates.
`negotiation-driven-capacity-resize` took the multiplier reading (task 1.1).
`renewable-compute-lease-deadlines` took the pool tag and its publication read. This
change keeps bare metal throughout, `available_until_utc`, the runway, the
amount-read guard, the penalty, setup and returned presets, the payout hold term, the
declaration contract and the full default acceptance policy and display. Task 1.2 and
its placement probe were withdrawn: the placement is implemented and promoted.

## Rejected alternatives

- Stored class: it can disagree with selected terms.
- Horizon admission by period count alone (this design's first form, replaced 2026-10-29): one period is a billing floor, not room to deliver; a buyer approving at the end of its window inside a one-period horizon left the seller a term it could not deliver and a self-penalty for it.
- A delivery deadline kept seller-internal: the buyer could not compute the runway, and late activation inside a long term was no failure.
- `interruption {seller_may_interrupt, notice_seconds, compensation}`: duplicates the shared codec.
- Lifecycle terms inside the settlement mechanism's parameters: the parties' rights read by lifecycle adapters placed in a dictionary the mechanism owns, under a name that says the wrong thing (D4; foundation D5).
- A default buyer that refuses an unpenalized on-demand offer (round 8's disposition, revised 2026-11-10): the penalty is often uncollectible early in a deal, and the refusal would turn away every MVP offer.
- A default buyer that refuses charged treatment on its own stop: the buyer chose that moment, so a charged started period there is a price, not a seller's taking.
- A default buyer that accepts a charged term end because the buyer chose the horizon: billing starts at activation, so the term end falls mid-period whatever the horizon, and a charged one bills past the agreed maximum (owner disposition, 2026-11-10).
- Reading the pool's deadline tag in terms: the tag, its publication read and its enforcement have one owner, the site's deadline change.
- A servicing declaration naming a contract revision, `proposed` in a lane: the vendored contract has no unpublished candidate; what differs between compositions is which treatments each has qualified.
- Payee notice entry on on-demand: grants the seller a priced reclaim. On-demand carries no seller stop entry, so won't-preempt is enforced by remedy, a buyer case and the bond, and the seller's exit is the mechanically ruled delivery_end filing.
- Bare-metal minimum spend/new payments primitive: churn is seller pricing/refusal policy.
- Rejecting setup once because it is not minimum spend: name the additive fee honestly.
- Banning principal-blacklist policy: goodwill is not a decentralized protocol guarantee.
- Billing horizon/vouch or payee-advanced horizon: a dishonest seller can advance it forever.
- Backdated/effective-time payee stops: stop now plus held-money reversal covers correction.
- Storefront-local notice scheduling: it dies with the storefront.
- Listing/site/registry copies of an option policy: duplicate truth and cross authority boundaries.
- Early_termination on every option: once/unsupported mechanisms cannot bind it.
- One bound only or a second offer-end date: relative and absolute capacity bounds suffice.
- One listing per class: existing capacity/shape identity can carry multiple options.
- A maximum term in the option, with the seller's acceptance minting a final option whose ID differs from the advertised one: the horizon is the deal's, already in `duration_seconds`; an option identity that changes between listing and Agreement needs a protocol amendment and a correlation step in discovery to carry a number the Agreement already carries.
- New Agreement rate field, zero duration or hourly reinterpretation: preserve scalar semantics and finite lease window.
- Publication-only/materialization-only gates: either permits an unserviceable accepted deal.
- Reserve-ahead as worst-case buyer-loss cap: guarantees require authority actions, holds and evidence.
- Prorating every buyer end/prepaid provisioning time here: changes pricing outside this reconciliation.

## Dependency gates and sequence

The foundation is archived. `offer-per-period-vm-terms` precedes this change.
`period` and `reserve_ahead_seconds` are `derive-rate-parts-in-the-payments-kit`'s;
setup pricing, the preset encoding and the payout hold's derivation are frozen with
`spot-deals-through-arkhai-payments`. This change can archive with its own
declaration/publication/acceptance/display evidence; spot's materialization and
convergence's continuation evidence are not prerequisites. A preset naming a
treatment a composition has not declared stays unpublished there (D6). Discovery and activation
also require the registry carrier chain; hosted deployment gates activation, not
implementation against an in-lane double. Site lapse choices are seller policy,
not buyer protocol guarantees.

## Goal 8 review triage

No standalone review of this terms change was supplied this round. Applied the terms-facing findings from spot external F1/F9/F10/F12 and convergence external F6: foundation-owned `settles_through` values and fail-closed expressibility, one notice without exposure, unrounded horizons with explicit term-end billing treatment, accepted pricing evidence, truthful stop-and-hint and setup display. Rejected: a seller-only started-period refund, because only a committed payment term survives an adversarial seller and independent dispute execution. The owner's 2026-10-29 review moved the horizon out of the option: D5's bounded final-option refinement and its negotiation-protocol requirement were replaced by the horizon as the Agreement's `duration_seconds` with a stable option ID.

Second-review triage applies foundation 18 F4/F13/F14 and spot 03 F2: one term-end carrier,
terms-owned default buyer policy, all interim charged term ends refused by default, and no
terms-to-materialization/startup closeout cycle. The final owner decision makes the seller's
delivery_end a dispute filing using the cause=payee remedy, and makes receipt-backed payer claims mechanical under the same payee-agreement guards.
The focused cross-change re-check settled the design; the campaign index's row is
the authoritative status (`in design` until this change's own design review has
run and its triage advances it), and this section does not restate it.

## Design validation

On 2026-10-29, pinned OpenSpec 1.14.0 and installed `openspec` strict validation
passed without long-requirement warnings, and
`make check-change CHANGE=negotiate-open-ended-compute-terms` passed, including
comment hygiene, agent skills, citations, task structure and the current change
index. No runtime implementation, new tests, deployment or
permanent-document promotion was performed; packaging and runtime suites are future
implementation gates, not claimed evidence here.

## Goal 8 MVP rescoping

On 2026-11-10 the owner sequenced Goal 8's MVP changes before this one and disposed
its rescoping: the default buyer refuses charged treatment on a seller's preemption
and at the term end, accepts it on its own stop, and never requires a penalty, revising
round 8 (D3); the pool's deadline
tag moved to `renewable-compute-lease-deadlines`; the multiplier reading moved to
`negotiation-driven-capacity-resize` (D2); the servicing declaration lists qualified
treatments (D6); `offer-per-period-vm-terms` omits unbounded per-period VM candidates
and amends the permanent partial-period rules; VM setup is a seller opt-in and
bare-metal setup is required (D8); the payout hold became a seller-chosen term (D9).
D10 states the resulting split. The delta specifications mark, inline, each
requirement the MVP owns or that went stale, and keep its text until this change's
design reconciles them.

## Design promotion record

Destinations are planned, not claims of implemented behavior. Parts the MVP promotes
first are promoted by it; this change's archive modifies them.

| Accepted decision | Permanent location |
|---|---|
| D1, D2 classes in both domains and the amount-read guard (the absolute reading is the MVP's) | `docs/development/ARCHITECTURE.md`; `openspec/specs/negotiation-protocol/spec.md` |
| D3 penalty preset default (24 periods) and the default acceptance policy replacing the MVP defaults; D4 placement (already promoted by the foundation) | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/buyer-orchestration/spec.md` |
| D5 both listing bounds, the runway and bare-metal omission (VM horizon resolution is the MVP's) | `openspec/specs/negotiation-protocol/spec.md`; `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/architecture.md`; `openspec/specs/resource-pool-management/spec.md` |
| D6 the declared treatment list and its three doors | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/storefront-publication/architecture.md` |
| D7, D8 display, setup defaults and seller-policy distinction | `openspec/specs/buyer-orchestration/spec.md`; `openspec/specs/buyer-orchestration/architecture.md` |
| D9 the payout hold term | `openspec/specs/deal-lifecycle/spec.md`; `openspec/specs/buyer-orchestration/spec.md` |
| D10 scope split | none — a sequencing record, reflected in Goal 8 of `docs/development/ROADMAP.md` |
| Goal/dependency currency | `docs/development/ROADMAP.md`; `openspec/changes/README.md` at integration/closeout |
