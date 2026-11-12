# Design

## Context and authority

This design-stage change reconciles compute terms onto
`agreed-evidence-and-early-termination`. Its vocabulary and codec win. Design for
an adversarial counterparty and make the reference implementation cooperative.
The buyer can rely on authority records and kept signed bytes, not seller uptime.
This change owns compute terms and presentation, not authority operations.

Current `SettlementOption.params` is a dictionary, hashed with mechanism, asset and
rates; the selected option reaches Agreement verbatim. VM substitutes durations in
negotiation/resume; bare metal requires a positive lease bound. Alkahest's option
builder uses `params.accepted_escrow`; typed `EscrowTerms` describes obligation
params, not option params. Recheck these seams after dependencies land.

## Decisions

### D1. Classes are derived presets, never stored

| Selected option billing | Payer entitlement | Payee entitlement | Display |
|---|---|---|---|
| prepaid once | — | absent | reserved |
| per period (`period` present) | present | absent | on-demand |
| per period | present | present | spot |
| prepaid existing Alkahest splitter | — | release condition permits interruption | prepaid interruptible |

A setup once charge beside a rate does not make it prepaid. One listing can offer
several combinations at different rates over its existing pool/shape identity;
options add no publication-derivation dimension or duplicated capacity. `--class`
is discovery sugar, not a wire field.

The existing splitter stays seller-trusted with its current service terms. The
foundation removes `listing_resource.interruptible` and `settlement_model`,
migrates flags to `release_models`, and retains bare metal's unsupported-splitter
refusal. Read the accepted release condition for display; do not invent lifecycle
terms for a mechanism with no lifecycle adapter.

### D2. Quote once with its unit; test every money reader

`Agreement.amount` is the accepted monetary quote, following the implemented
resize carrier (D2a), never the negotiation multiplier. Billing kind changes the
evaluation duration before acceptance: Agreement duration for prepaid, option
period for recurring. Retain upward rounding once and the asset's amount-range
refusal.

#### D2a. Keep the signed Agreement monetary

Settled by the owner's round-1 review (record 01, R3).

The signed Agreement is what both parties commit to, and payment mandates bind
money. A buyer or verifier must be able to read what is owed from the Agreement
alone without re-deriving it from rates and a multiplier. Resize already writes
money there and keeps the basis-point scalar in the negotiation transcript; keep
that mechanism rather than introducing a protocol migration.

The multiplier stays negotiation-transcript state. Recurring quotes are derived
before acceptance using one option period and upward rounding once, and that
per-period monetary amount is written to the Agreement. `agreed_price(agreement,
listing)` returns the accepted amount, with `total` or `per_period` determined by
the selected option's billing kind bound in acceptance. Recovery and buyer mandate
checks still verify the amount against the acceptance-bound rate structure and
multiplier, never a current listing. D2b supplies signed acceptance evidence for
the transcript multiplier without changing this monetary carrier.

Core's `agreed_price(agreement, listing)` returns price and unit `total` or
`per_period` (with the actual period for presentation), never an unlabelled integer.
Both policies/reference quotes, buyer caps/display, VM amount checks, mandate
derivation and buyer mandate checks use it. Additional setup pricing is explicit,
not hidden in the recurring quote. At 2,500,000 USD/6 per hour and 10,000 bps,
two-hour prepaid is 5,000,000 total; PT15M is 625,000 per period; PT1M is 41,667.
Recovery and buyer mandate checks use the signed-acceptance-bound rate structure and selected option, never a current or registry-cached listing. `negotiation-driven-capacity-resize` task 2.1a's carrier decision gates this accessor: retain the bound structure or its verifiable digest in accepted evidence before approval.

After this change `Agreement.amount` means a total for a reserved deal and one
period's price for a recurring one, so a reader assuming a total charges or caps a
recurring deal wrongly. Every consumer that spends, caps, displays, recovers or
confirms accepted money reads it through the accessor, and each is tested with a
per-period Agreement: mandate derivation, buyer caps and display, recovery and
confirmation. No static check inventories `amount` reads (owner record 01, R6): a
syntactic inventory of every read named `amount` cannot tell money from the many
other amounts, and a two-party misread fails loudly in an end-to-end run that
produces a per-period Agreement. No such run exists yet; it is recorded as a gap for
this change's or `spot-deals-through-arkhai-payments`' planning.

#### D2b. Signed-acceptance pricing pin

Settled by the owner's round-1 review (record 01, R4, amended).

The seller-signed acceptance binds the agreed multiplier and the rate-structure
digest: the same digest D-e pins at opening, computed by
`negotiation-driven-capacity-resize`'s single function over the publication's
`pricing.rate_structure` and seller-signed in the registry's retained publication (D-c).
The buyer retains the publication's whole `pricing` object and compares it with the
signed body, which verifies `asking_rate` along with the family rates; the family
rates the amount codec reads are a copy lifted from `pricing.rate_structure` and
must equal the signed ones.
Opening, every round and acceptance refer to this one rate identity. The buyer
verifies it against the retained seller-signed registry publication, never a
snapshot supplied by the seller. Historical publication verification, exact option
and listing context, and transcript/Agreement verification precede accepted reads.
Legacy records missing bound evidence fail closed; fresh listings cannot repair them.

Rejected: returning the full seller database snapshot under the existing hash.
That would turn a private storage shape into a public contract.
`Agreement.listing_hash` remains unchanged: it commits the seller's database
listing rather than the published document, and nothing verifies it. This change
does not depend on it; the mismatch is an unowned gap in `openspec/changes/README.md`
(owner record 01, R5).

Permanent destinations after review: `openspec/specs/negotiation-protocol/spec.md`
and the authority description in `docs/development/ARCHITECTURE.md`.

### D3. One shared codec, no interruption object

Keep the foundation's exact shapes and names:

- `early_termination = {version, entitlements, settles_through, premature_stop_penalty?}` — the deal's horizon is not in it (D5);
  its top-level `settles_through` is the sole term-end treatment carrier (no mechanism-specific duplicate), separate from
  entitlements keyed by `payer`/`payee`, each `{notice_seconds, settles_through}`.
  Foundation D5 owns the `settles_through` mapping: `started_period` ↔ charged,
  `last_boundary` ↔ returned, `stop` ↔ prorated. Seller presets offer payer charged and
  payee returned; the buyer's default acceptance policy refuses a payee entitlement
  or term end that is not returned (the buyer benefits, so the buyer enforces it in
  negotiation), and a buyer may loosen it. `returned` is vendored
  (`kit/arkhai-payments/schema/payments.schema.json`, `partialPeriod`): presets default
  the payee stop and the term end to `last_boundary`, and a seller may state
  `started_period`, which is disclosed and refused by default buyers. A treatment is
  admitted where the mechanism's helper declares support for it and the composition's
  servicing declaration qualifies it (D6, owner record 01, R13). Publication and
  acceptance fail closed on any unsupported treatment. `exposure_seconds` and `stop+exposure` are retired.
- `adjudication = {version, dispute, dispute_window_seconds, case_hold_max_seconds}`;
  `dispute = {interface, origin, account, record_key, params}`.
- `premature_stop_penalty` is a nonnegative integer amount in the option asset's minor units, encoded as a canonical decimal string; absent/zero means none. It applies to an unentitled seller end, including a spot emergency without notice, not an entitled notice stop. On-demand presets with no stated penalty default to the quoted per-period price times the storefront setting `[pricing].default_premature_stop_penalty_periods`, which defaults to 24; a penalty stated on a clause, including an explicit `"0"`, wins, and spot carries none by default (owner record 01, R11). Buyer default acceptance refuses on-demand without a positive penalty because the buyer benefits and enforces it, like partialPeriod. Expose seller override and explicit buyer opt-out; never silently downgrade the default. The number is a ceiling, not a guarantee: the remedy takes `min(penalty, earned amounts still held)` after the refunds, and early in a deal what is earned and held is the setup charge alone — an on-demand VM pulled minutes after activation, with its started period returned, leaves nothing else to take, and zero with no setup charge. A seller-funded stake that makes the ceiling collectible is the reserved `bond` term (foundation D5), not this change's.
- `bond` stays reserved where the mechanism cannot hold a seller-funded stake.
- `delivery_deadline_seconds` is supplied by the composition and published under that
  name on every compute option whose mechanism has a lifecycle adapter, recurring or
  once: the pool port's value (`delivery_deadline_for_pool`) when it gives one, else the
  payments clause's configured `delivery_deadline_seconds` (owner record 01, R21).
  Pool-first precedence keeps the site and the published term from disagreeing once
  `renewable-compute-lease-deadlines` enables the pool's tag and the site enforces it.
  The clause value is not an unenforced raw tag: the seller's deal-servicing journal
  files non-delivery at whatever deadline the deal accepted
  (`kit/deal-servicing/src/market_deal_servicing/journal.py`).
  A compute option with neither yields an option without the term, and the default
  buyer refuses such an option without it — the buyer benefits and enforces it, with an
  explicit opt-out — so the derivation log and listing diagnostics name it like the
  penalty: "a default buyer refuses this option: no delivery deadline". An Alkahest
  compute option carries no `lifecycle` and so no deadline term (the binding rule,
  foundation D5): the runway check does not apply to it, its lease takes the pool's
  policy as the site's own safeguard, and the display says the option makes no delivery
  promise; a mixed hosted/Alkahest listing under default selection is a first-use
  fixture (tasks, section 4). Changing the pool's value changes
  future options' IDs, never a committed deal's deadline; a deal accepted before the
  change commits with its accepted value, which the site enforces where the pool still
  grants that much and refuses where it does not (renewable D1), so publication
  republishes on a pool change rather than letting the two readings drift.

A payee entitlement means the seller may interrupt; the payment authority enforces
its notice as a pending stop on that stop authority, not a local schedule.
On-demand has no payee stop entry. The mandate therefore does not enforce that the seller
won't preempt; that is enforced by the penalty and a buyer's case over held money, not by the mandate.
The seller's own exit is `delivery_end(cause=payee)`, a dispute filing the seller half journals with
the end and files with the dispute authority; the seller sends no stop or reverse of its own.
Arkhai mediation rules payee-agreed delivery_end under its mapping/time/replay guards; the cause=payee branch is the standard self-penalty (`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`); the terms this change publishes are what that
ruling reads — the penalty, the on-demand returned treatment, the setup charge — and
the display explains them against it (D7). A buyer contesting the account files a case;
mediation triages claims lacking payee agreement or failing its mapping/time/replay guards; matching receipt-backed payer claims rule automatically. There is no compensation enum. The `delivery_end` revision is vendored in the mediation contract (`kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/`), but the hosted mediation service still runs an older revision, so a setup-bearing option is admitted only where the composition's declaration sets `setup` for its mechanism (D6, owner record 01, R19); setup-free presets remain independently eligible.
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
default buyer refuses — an on-demand option with no premature-stop penalty, a payee
or term-end treatment other than `last_boundary` — as "a default buyer refuses this
option: <term>". The option still publishes; a seller who prices no penalty is told,
not stopped, and can see why no default buyer takes the offer.

Resolve seller preferences through override > pool hint > configured default,
keyed per offered preset like its rate. These are seller choices, not a protocol
requirement to price identically. Recommendation: shipped recurring presets have
a payer entitlement with `notice_seconds: 0` — a buyer who stops is charged to the started
period and nothing after, and a seller who wants a tail prices it as a number the buyer sees —
and a setup once part only where the seller states its amount (D8); spot adds a payee entitlement. Omission
never grants the payee an implicit entitlement. The foundation owns validation and
identity inclusion; do not create a second hash rule or require early_termination
on every compute option. Terms injects a preset-helper interface: selected quote/unit,
period/reserve, setup, bounds, adjudication and early-termination declarations in;
a canonical candidate option or a named derivation refusal out. Spot supplies the
hosted helper; generic publication tests use injected helpers. Missing helper omits
the recurring candidate, never reconstructs the mechanism's parameters. Neither archive waits
for the other's execution.

### D4. The terms are the option's `lifecycle`

`early_termination` and `adjudication` are objects under the option's `lifecycle`, beside `price` and `settlement`, and so in the Agreement bytes and the option ID (foundation D5, "The option's shape"). They are the parties' rights after commitment — who may end the deal, on what notice, with what treatment of the period in progress, and who decides a dispute — and become payment facts only when exercised, when the adapter derives stop authorities from the entitlements and the hold from the window; they are owned by the lifecycle codec, not by any settlement mechanism, so they do not sit in the mechanism's own parameters under the mechanism's model. The codec reads both keys by the same names and shapes whatever the settlement schema, and never branches on it or decodes Alkahest arbiter demand trees to read them. A mechanism adapter separately refuses terms it cannot enforce: carrying the keys is not permission to advertise an unsupported Alkahest lifecycle promise. `placement-probe.md` records the earlier experiment of carrying both objects inside the mechanism's parameters; task 1.2 runs the full codec check against the nested shape as a regression test, not a decision gate.

### D5. Two listing bounds compose at the agreed start

`max_duration_seconds` is the longest deal from its start; `available_until_utc` is
the last possible lease end. Both are listing capacity facts, not option copies or
`listing_resource` fields. Each resolves independently through override > pool hint
`policy_tags.capacity_bounds.<mode>` > configured default, VM keeping its per-model
tiers below the mode hint (D10). Nonpositive/unset relative bound means no relative
limit and masks lower tiers; a stated absolute bound is strict timezone-aware UTC.
Malformed bounds hold the pool with a diagnostic, not a guessed default; override
checks use the live projection. Both are published as top-level listing fields
(owner record 01, R8). The site and watchdog hold only each lease's
`lease_end_utc`, written at commit from the Agreement's start plus duration; neither
bound is copied to them, and neither expresses the other.

At resolved `start_utc`, let `B = min(positive max_duration_seconds,
available_until_utc - start_utc)` over stated bounds. Default recurring selection
binds `duration_seconds = B`.
If one bound is absent use the other. Require at least one whole period, but do not
round the horizon to periods. When the buyer names no horizon and the limiting bound
is a fractional-second `available_until_utc`, floor *B* to whole seconds, at
acceptance and at publication, rather than refusing (owner record 01, R9). Bind an explicit shorter buyer horizon unchanged, show the
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
`delivery_deadline_seconds` is the lifecycle term the pool feeds — and the check is
the only place they meet; a buyer that approves at the last permitted instant gets
its period, and no timing the Agreement permits is a seller breach.

Rate billing starts at activation, potentially later than the Agreement start,
while the payments end is absolute: horizon rounding cannot align that end to a
billing boundary. Foundation D5 therefore gives the term end its own
`settles_through`, mapped to the rate part's `end.partialPeriod` with the same
values as stop authorities. Compute presets use `last_boundary` (returned), so
billing never runs past the agreed maximum; `returned` is vendored, and the
treatment is admitted where the composition's declaration qualifies it (D6). A
seller may state term-end `started_period`, which is disclosed and refused by
default buyers. Exhaustion needs no separate rule: reserve-ahead places it on a
period boundary.

Recurring start_utc must resolve to whole-second precision before the final signature;
refuse a fractional rate start rather than round signed bytes. Preserve once-only
fractional handling. The horizon is the Agreement's `duration_seconds` and nothing
else: the option carries no maximum term, so the same option serves every buyer and
its ID is stable from the registry to the Agreement; the seller's signed acceptance
carries the advertised option unchanged and the resolved `duration_seconds`, which the
buyer checks against both listing bounds at the agreed start. The rate part's end is
`start_utc + duration_seconds` (spot D2). No option is minted at acceptance and no
identity changes.

The schema-opaque negotiation runtime fixes one acceptance instant and calls the
optional `resolve_acceptance` domain hook before artifacts or writes, on all four
acceptance paths; `resolve_horizon` binds the buyer's horizon unchanged or the
default *B* and refuses longer, expired, sub-period, no-runway and missing-reserved
horizons (owner record 01, R9). The buyer's check is one shared pure function beside
`resolve_horizon` in `kit/settlement-runtime`, sharing its bound arithmetic, which
both buyers call before approval: it refuses a duration above either bound at the
Agreement's start, holds an explicit horizon to the buyer's request and an omitted one
to the default bound. The seller's resolver protects only against the seller's own
mistakes; the buyer's check is what holds against a counterparty that signs other
terms (review 04 F1). A buyer that named no horizon compares a provision duration with
the Agreement's only where it requested one: the seller keeps the buyer's signed
provision terms, which carry no duration, beside the resolved one (review 04 F2).

The buyer's check needs the listing the buyer selected, which core's acceptance guard
does not receive: the guard sees only the outcome. Core's negotiate hook therefore takes
an optional per-listing `acceptance_validator`, a factory from the candidate listing to a
check of the accepted outcome, run after the stage's own acceptance check and before the
acceptance is observed; core knows nothing of bounds, and a domain binds them. The VM
buyer's direct negotiation binds the listing it was given and the duration it opened
with — on a resume, the seller's round-zero echo of the buyer's terms. The VM
acceptance record keeps both bounds, so a resumed run checks against what was
advertised, never a current listing. A record written before it kept bounds checks the
duration against the buyer's request only; a v0.3.0 VM run always named a duration, so
no released run reaches the omitted-horizon branch without bounds, which refuses.

An unbounded recurring candidate yields no option and a derivation close reason,
not a hold merely for being unbounded; valid reserved candidates remain. In both
domains no positive relative maximum means no relative limit: bare metal's reserved
hold (`pool_lease_bound_missing`, `reserved_lease_bound_missing`) is retired, and
every reserved deal carries the buyer's explicit duration, checked at acceptance
against both bounds (owner record 01, R27). A bare-metal pool previously held for
lack of a maximum now publishes reserved options with none; the operator handbook's
upgrade step says to set `default_max_duration_seconds`, an override or a hint to
keep a ceiling. A later
listing-date edit never extends an accepted lease. The shared delivery change
uses accepted start plus duration in both domains, not `now`. Here remove VM's
round-zero missing-reserved-duration fallback; delivery owns its resume fallbacks.

### D6. Three doors read one servicing declaration

Composition, not a listing or buyer, declares rate servicing (owner record 01, R15,
R19). The declaration lists, per mechanism, the `settles_through` treatments the
composition has qualified against that mechanism's payment authority, and whether it
services a setup charge:

```toml
[settlement.rate_servicing.arkhai_payments]
treatments = ["charged"]
setup = false        # true once the hosted mediation service rules delivery_end
```

Absent or empty means no rate servicing. An option is admitted only where the
mechanism's helper supports a treatment (D3) and the composition declares it. The
earlier form — a contract revision per mechanism, `published`/`proposed` status and a
proposed-lane identity — served an unvendored contract that no longer exists and could
not say which treatments were qualified; it is removed. Tests inject declarations
directly. Deployed compositions declare no treatments, so recurring offers stay dark
(R16). No additional minimum-spend primitive gates it.

The tables live in the seller's `[Settlement]` root, keyed by each installed
mechanism's configuration key; a buyer's root refuses them, since only a selling
composition services a rate. Their one definition is settlement-runtime's typed table
model, which the configuration loader parses and the values schema renders, so the Helm
schema and the loader cannot disagree on the table's keys or treatment names. The
storefronts' integration tests run the real composition with the declaration injected
and, since no installed mechanism supplies a recurring encoder, term timing or billing
projection, a fixture at each of those composition ports, standing where the payment
mechanism's code would; what they prove is the two doors and the served acceptance, not
a mechanism's encoding.

1. Publication omits a recurring candidate naming any undeclared treatment on an
   entitlement or at the term end, or a setup charge where `setup` is not declared,
   using existing no-settlement-option diagnostics if none remain.
2. Acceptance refuses such a cached selection, using the withdrawn-option/refetch
   outcome before persisting acceptance.
3. Materialization refuses to derive a rate mandate for such an option, even across
   an acceptance/restart gap.

Startup additionally refuses to strand accepted rate deals without their
continuation. Disabling offers never disables accepted-deal servicing.
`converge-ongoing-compute-leases` owns startup/continuation wiring; the rate adapter
owns materialization. This change supplies the common declaration contract and
publication/acceptance gates. This plan qualifies those two gates using injected declarations;
spot owns materialization execution/evidence and convergence owns startup/continuation
execution/evidence. Neither consumer's completion gates this change's archive. Rate offers
remain disabled in deployed compositions until their consumer gates pass.

### D7. Display what the authority can enforce

Both CLIs show class, recurring charge/period or total, separate setup once charge,
initial reserve (not spend), maximum end/horizon, the delivery deadline ("active within
N of your approval, or the seller has not delivered"), payer/payee entitlements, notice,
per-stopper and term-end `settles_through` treatment, the premature-stop penalty as
"up to N, taken from what the seller has earned and not yet been paid — at the start of a
deal, the setup charge" with its worst case (nothing earned, nothing taken) stated rather
than implied, dispute authority/window/case-hold cap and evidence retention. A filed case
is shown by the authority's per-part answer, `held` with its extension or `not_held`
with the reason, never as a refund pending: an accepted case over paid-out money
recovers none of it. Values come from the selected option, not a stored class. Asking rate keeps its stated unit.
The seller's side of the same display is the default-buyer refusal diagnostic (D3), so
seller and buyer read one policy.

The mechanism owns the numbers (owner record 01, R17):
`MechanismRegistration.present_payment(option, requested_duration, accepted_quote)`
returns `PaymentPresentation {quote, setup_once, initial_reserve}` in the quote's asset
and minor units, zero meaning none and null undetermined; the registry checks basis and
asset and that accepted money is unchanged, and a missing presenter refuses. Both buyers
render these with the class, price unit, asking rate, bounds, horizon and lifecycle rows
on stderr; accepted displays read only the Agreement. VM's public price bounds stay
hourly and are scaled to one period for a recurring option; the ceiling is compared per
period for a recurring option and per term for a reserved one.

The default buyer's policy (owner record 01, R12) is `default_buyer_refusals`, which
refuses, on an option whose mechanism has a lifecycle adapter: no
`delivery_deadline_seconds`; on-demand with no positive penalty; a payee stop or term
end whose `settles_through` is not `last_boundary`. Both buyers compose
`BuyerTermsPolicy` over the foundation's `AuthoritySelection`, refusals before ranking.

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

Neither domain requires minimum spend. A setup once charge beside the rate is the
seller's choice: `setup_amount` is optional, there is no amount to default to, and an
honestly named setup part is published only where the seller states one and the
servicing declaration sets `setup` (D6, owner record 01, R19). Sellers may price
differently or refuse churners, including by principal blacklist, without claiming
resistance to identity rotation. No new minimum-spend request goes to payments. This
change displays setup pricing; the rate change derives it.

### D9. Recurring options are derived by one shared per-clause step

A settlement clause may carry an optional mechanism-neutral `recurring` request
(`RecurringPublicationPreset`); each clause resolves whole (owner record 01, R10). The
injected `RatePresetHelper` supplies the per-period quote, approval window,
adjudication and capabilities and encodes the option; the common derivation checks the
authority, derives the penalty (D3), checks the default horizon's runway (D5) and
validates the lifecycle, and refuses an encoder that changes mechanism, asset, period,
reserve or lifecycle. A missing helper, undeclared servicing or an unbounded horizon
omits only that recurring option, with a diagnostic; reserved peers and capacity
identity are unaffected.

That per-clause step — deadline resolution (D3), the recurring-or-once branch,
`derive_rate_preset`, the diagnostics and the penalty setting — is one
`kit/settlement-runtime` function both compositions call; the `compute` flag and the
deadline lookup are parameters, so it knows no family (owner record 01, R26). Each
`resolve_acceptance` hook keeps only its domain's artifact rebuilding over
`resolve_horizon`. The older differences between the domains are unified in this change:
the reserved-bound rule (D5) and the clause source (D10).

### D10. One source for compute settlement clauses

Both domains resolve settlement clauses and listing terms field by field: override >
pool hint per GPU model (`pricing.gpu.<model>`) > pool hint for the pool
(`pricing.settlements`, new) > configuration per model
(`[pricing.defaults.gpu.<model>]`) > flat configuration (`[pricing]`) (owner record 01,
R28). Bounds keep D5's order, with `capacity_bounds.<mode>` ahead of the model hint.
A v0.3.0 VM configuration or hint means what it meant; an older VM storefront ignores
the pool-level key. Bare metal's unreleased `pricing.bare_metal.settlements` hint is
replaced, needing no compatibility path (D12). VM's family rates stay VM's. One shared
resolver, moved out of `arkhai_vms_listings.pricing_resolution`, lives provisionally in
`kit/resource-pools-contracts` beside `capacity_bounds.py` and `raw_pricing`, taking the
`gpu` key from the compute vocabulary as data; closeout's documentation-compliance step
confirms or moves it, since it is compute-family resolution and no compute family kit
exists yet.

### D11. The buyer waives each default refusal on its own, and names its duration once

One flag per default refusal, in both buyers (`market buy`/`negotiate`, `bare-metal
buy`): `--allow-no-delivery-deadline`, `--allow-no-penalty`,
`--allow-charged-preemption`, `--allow-charged-term-end`, each waiving exactly its term;
the foundation's `allow_missing_delivery_deadline` is set only by the first.
`--allow-unprotected-terms` stays as shorthand for all four. Every waiver used, singly
or through the shorthand, is recorded in run metadata and named in the pre-approval
disclosure; codec, capability and authority checks are never waived (owner record 01,
R14). A single blanket waiver made the E2E drivers waive all four protections to pass
one missing term.

Duration is optional for recurring and required for reserved in both CLIs.
`bare-metal buy` keeps v0.3.0's 3600-second default for reserved options only, shown as
the buyer's default in the disclosure, never for recurring ones. VM's `market
buy`/`negotiate` gain `--duration-seconds` beside `--duration-hours`; giving both is an
error naming the conflict (owner record 01, R18).

### D12. Compatibility is owed to releases; sibling domains behave alike

Two principles the owner's round-1 review settled (record 01, R29), promoted with this
change:

- Compatibility is owed to what an official release has shipped. A decision made on
  `dev` and changed again before any release ships it affects no one, so revising it
  needs no compatibility path, migration or deprecation; a change to anything a release
  has shipped is judged as an incompatible change under `docs/development/RELEASING.md`'s
  rules.
- Sibling domains of one family behave alike unless a reason specific to one of them is
  stated where the difference lives. A difference with no stated reason is a defect to
  reconcile, and the reconciled behaviour moves to the family's shared code under the
  scope rule; similar-looking code with genuinely different domain meaning stays in its
  domains.

## Rejected alternatives

- Stored class: it can disagree with selected terms.
- Horizon admission by period count alone (this design's first form, replaced 2026-10-29): one period is a billing floor, not room to deliver; a buyer approving at the end of its window inside a one-period horizon left the seller a term it could not deliver and a self-penalty for it.
- A delivery deadline kept seller-internal: the buyer could not compute the runway, and late activation inside a long term was no failure.
- `interruption {seller_may_interrupt, notice_seconds, compensation}`: duplicates the shared codec.
- Lifecycle terms inside the settlement mechanism's parameters: the parties' rights read by lifecycle adapters placed in a dictionary the mechanism owns, under a name that says the wrong thing (D4; foundation D5).
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
- A static inventory of `Agreement.amount` reads, or renaming the attribute behind the wire alias so a raw read fails in the type: a syntactic guard over every read named `amount` cannot tell money from other amounts; tested consumers and an end-to-end per-period run catch the misread (D2, owner record 01, R6).
- One run-scoped waiver of every default refusal: to pass one missing term it waives all four (D11).
- A servicing declaration naming a contract revision and `published`/`proposed` status with a lane identity: it cannot say which treatments are qualified (D6).
- Dropping VM's per-model bound tiers: `marketplace-v0.3.0` ships them (D5, owner record 01, R8).

## Dependency gates and sequence

Foundation codec, authority validation and release-model migration precede wire edits. Reverify resize before accessor migration. Freeze recurring
`period`, `reserve_ahead_seconds`, setup pricing and servicing declaration with the
rate change. Resolve the horizon into `duration_seconds` at acceptance (D5).
Sections 1–2's accessor/codec and 3.1's declaration are section-level handoffs to spot.
This change can archive with its own declaration/publication/acceptance/display evidence;
spot's materialization and convergence's continuation evidence are not prerequisites.
Publication and buyers can then proceed while adapter/continuation are prepared;
rate offers remain dark until all three doors can succeed. Discovery and activation
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
index. `placement-probe.md` records the partial carriage experiment; the full codec check
is task 1.2. No runtime implementation, new tests, deployment or
permanent-document promotion was performed; packaging and runtime suites are future
implementation gates, not claimed evidence here.

## Dependency re-verification (2026-11-06)

The initial D2 wording assumed a scalar Agreement carrier; D2a reconciles that
wording with the stacked resize implementation. Its `design.md`, "Slice B scalar and payment boundary", deliberately
keeps policy scalars separate from monetary outcomes:

- `domains/vms/negotiation/src/arkhai_vms_negotiation/amounts.py` applies the
  multiplier as exact rational arithmetic, rounds upward once, and refuses a
  result above uint256. The default floor is 10,000 basis points.
- `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`,
  `_build_response_artifacts` and `_with_agreement`, put that computed payment
  in the Agreement and mechanism artifacts. The scalar survives in the transcript
  and the thread's `agreed_price`, not in `Agreement.amount`.
- `domains/vms/storefront/tests/integration/test_vm_multiplier.py` explicitly
  asserts the derived monetary amount in the Agreement, persisted Agreement
  bytes and settlement plan. The existing test passes on the merged stack.
- `core/tests/unit/test_rate_helpers.py` still verifies truncating generic rate
  arithmetic. Resize did not move its upward-rounding shape quote into core.
- The registry top-level `rate_structure` and retained seller publication proof
  are available after PR #349's merge; their carrier/authority decisions D-a–D-e
  are not reopened by this finding.

**Resolved by D2a:** the alternatives were preserving the existing monetary
Agreement carrier and labeling the accepted quote (with recurring amounts derived
per period before acceptance), or carrying the multiplier with an explicit
acceptance-bound pricing carrier and coordinated settlement-reader migration.
The owner chose the former because it preserves the signed and persisted
settlement contract delivered by resize. D2 and the sub-hour scenario now retain
the monetary carrier. The scalar alternative would require a protocol and
recovery migration and is rejected. This decision alone does not change product
behavior; recurring derivation and accepted-evidence validation remain work to
implement.

Evidence and repeatable focused commands:
`docs/attachments/negotiate-open-ended-compute-terms/dependency-contract.md`.

## Frozen dependency handoff

`dependency-contracts.md` records the section 1 price/evidence, helper and servicing
inputs for the terms, rate and continuation implementations. The terms change
owns publication and acceptance qualification, not hosted rate execution. Existing
regressions plus `codec_probe.py` and `registry_codec_probe.py` exercise the shared
codec and retained carrier without adding permanent acceptance tests. The hosted
builder and both buyer checks exercise once-only terms; early termination is a
structural codec/identity check, not a qualified recurring mandate.

Implementation choice: preserve the standing no-new-tests instruction by replacing
1.2's proposed permanent regression with these reproducible diagnostics and the
existing foundation suites. No mechanism-specific lifecycle codec is introduced.
The core accessor must remain schema-opaque: billing interpretation belongs to the
selected mechanism's accepted-option projection, not a core branch on a mechanism
schema. The exact projection plumbing is part of 2.1; the frozen behavioral contract
is D2a's accepted monetary amount and acceptance-bound unit.

## Partial quote implementation (2026-11-07)

The first 2.1 slice defines neutral `PriceBasis` and `AgreedPrice` carriers in core.
`agreed_price(agreement, listing=None, *, project_billing=None)` reads the accepted
monetary amount once. For a selected option, it requires an explicitly injected
mechanism-owned projection; no schema switch, period parser or implicit prepaid
fallback belongs in core. Absolute Agreements without an option retain `total`.
A recurring projection carries both exact period text and its validated positive
whole-second length; a total projection carries neither. The quote refuses amounts
outside uint256 even though the existing generic decimal-string parser does not
impose an upper bound. Core's old generic rate helpers remain unchanged.

A supplied listing is an acceptance-bound snapshot: the accessor checks listing
identity and exact option membership, never recomputes the money from its rates.
Signature/trust and transcript-price verification belong to the caller before
recovery or mandate approval. The optional snapshot argument does not claim that
an arbitrary or current listing authenticates accepted pricing.

For rate-structured listings, both VM recording paths use one deep-copy helper to retain the signed seller
publication/request and publisher provenance alongside the existing pricing
fields. A complete raw publication prevents loss of signed fields that a subset
cannot reconstruct. Missing proof is not manufactured for legacy records. This
slice retains evidence but does not yet enforce verification or wire the accessor
into consumers; task 2.1 remains unchecked. That boundary avoids migrating recovery
readers to an accessor before their evidence checks exist. `price_probe.py` replays
retention, a historical signature check and explicit injected projections; it does
not qualify a recurring payment adapter. These choices need the same post-review
promotion destinations as D2/D2a; no permanent documentation has been promoted.

## Billing projection continuation (2026-11-07)

Installed registrations now own an optional `project_billing` hook, dispatched by
`SettlementConfigurationRegistry.project_billing` and its `agreed_price` convenience.
A missing hook refuses interpretation. Reading an accepted option needs installed
code, not current role enablement/readiness. Alkahest and the installed once-only
payments adapter explicitly project totals; contact projects its rateless whole
introduction. The payments parameter codec refuses rate/setup fields until its
own adapter supports them. Core and VM pricing never parse a payments period.

VM multiplier arithmetic takes a validated neutral `PriceBasis`: one period for
recurring, the duration for total, with one upward rounding and uint256 refusal.
The VM buyer codec and storefront policy/reference/final derivation receive the
projection from their composition. Raw mathematical helper calls retain an explicit
total default; production selected-option calls resolve the installed owner.
Injected proposed projections qualify period arithmetic, not hosted rate execution.
Absolute/flat pricing retains its existing truncation path. Proof enforcement and
reader migration remain unfinished, so this does not qualify accepted recovery.

## Acceptance-evidence binding resolution (2026-11-07)

D2b resolves the carrier gap: the signed acceptance carries the agreed multiplier
and D-e's rate-structure digest. The digest uses the published rate structure;
verification uses D-c's retained seller-signed registry publication. The buyer does
not authenticate seller database snapshots. The existing Agreement hash mismatch
is an unowned gap in `openspec/changes/README.md`, with no change to its semantics here.
Implementation and focused evidence belong to 2.1b before reader migration in 2.1c.

## Accepted-reader and guard continuation (2026-11-07)

Accepted financial reads now use the unit-bearing accessor: payments mandate
policy and buyer/stored-mandate checks, bare-metal quote/recovery checks and exact
escrow recovery. An escrow requires a total quote; selected mechanisms require
an explicit installed projection. Exact escrow callers in VM and API-credit
compositions supply Alkahest's projection. No accepted money is recomputed from
a current listing, and hosted recurring parameters remain unsupported.

The Alkahest projector recognizes both existing acceptance carriers: published
accepted-escrow selections and explicit negotiated EscrowProposal parameters.
This is an installed mechanism decision, not schema interpretation in core.
Lifecycle terms and unknown parameter shapes are still refused.

The guard avoids Python type/name inference for amount reads: it inventories all
production amount attribute, literal/aliased-key mapping and reflective/getter
reads, including wrapper bodies. Exact path/function/expression/count entries
classify quote/resource/obligation/authority/proposal reads and their reason;
unknown reads, changed counts and stale entries fail closed. Generic negotiation
retains one raw Agreement equality check against codec-derived expected money,
not a billing or spending decision. This syntactic rule is not a proof about
runtime-generated Python or an authentication boundary. Its positive/negative
fixtures are a temporary committed change probe rather than new permanent tests,
following the standing test instruction. Both packaging and change checks run it.

Post-review destinations remain D2's negotiation specification and repository
architecture; UI disclosure remains in 4.1. Replay and focused validation are in
`docs/attachments/negotiate-open-ended-compute-terms/reader-guard-checkpoint.md`.

## Capacity-bound implementation (2026-11-07)

D5's mode-level pool hint uses
`policy_tags.capacity_bounds.<offering_mode>`, with independent optional
`max_duration_seconds` and `available_until_utc` fields. This is the
conservative placement choice for the previously unspecified hint nesting: it
does not put capacity facts in rate entries, settlement clauses or physical
resource shapes. Unknown mode names stay opaque. UTC values accept an aware
UTC ISO datetime (or a UTC datetime from TOML), serialize canonically with Z,
and refuse naive values, epoch numbers and nonzero offsets rather than
guessing a timezone. Relative hints/overrides/defaults accept strict integers;
a nonpositive statement masks lower tiers before becoming an absent relative
limit. Null/omission defers to the next tier.

Both storefronts resolve override > mode hint > configuration independently per
bound. VM retains its existing per-model pricing hint and configured-model
defaults as compatibility tiers: the mode hint precedes the legacy model hint,
then the model default and flat default. A malformed stated bound raises and
holds derivation instead of falling through, including a malformed legacy VM
relative hint. Bare metal retains its positive relative bound rule for reserved
publication; an absolute bound alone does not relax that admission rule.

The pool contracts own pure bound reading/validation and tier selection; the
pool service applies it to document validation as well as the HTTP write models.
Domain listing/override models consume it. Shared storefront storage carries an
optional absolute-bound column with an additive, null-by-default migration.
Updates distinguish omission from explicit null for both capacity bounds, so
withdrawing a bound clears it. Domain publication sends the absolute bound as a
listing-level opaque extra through the existing registry carrier, not in the
option or listing resource. Bare-metal storage/publication also stops copying
the relative maximum into the resource; the listing codec reads the envelope and
existing negotiation readers retain the same relative-bound guard. Existing rows
with a resource copy remain readable, while public responses omit the copy.
Changing/withdrawing a bound refreshes the existing capacity/shape identity.
Accepted Agreements are not touched here.

Bare-metal minimum/maximum compatibility must be judged against the same live
projection the override write fetches, not a held projection or configuration
alone: a pool hint can replace the configured maximum, and a corrected live hint
must not remain refused because the storefront still holds malformed old tags.
The pool-override contribution therefore supplies `projection_problems` beside
its vocabulary and shape judgements. The service calls it after live-pool
existence and before persistence, using the existing fetch (no additional
network call). VM supplies no projection-dependent term refusal. Publication
rechecks minimum/maximum compatibility on its held generation and retains the
existing `pool_override_terms_conflict` diagnostic; unreadable bounds use
`capacity_bounds_unreadable`.

Validation and first-use recipes are in
`docs/attachments/negotiate-open-ended-compute-terms/capacity-bounds-checkpoint.md`.
The temporary probe drives typed administrator publication/override/read surfaces
with real SQLite and existing injected site/chain/registry boundaries. It does
not prove deployed registry persistence, buyer horizon enforcement or rate
servicing. No permanent tests were added: kept expectations follow D5's deliberate
strict/nonpositive semantics and the new listing term. D5 promotion remains
post-review to resource-pool management, storefront publication and negotiation
specifications/architecture; the shared projection-aware override check belongs
in storefront publication's override contract.

## Recurring publication implementation choices

Task 2.3 will add a mechanism-neutral, structured `recurring` request on each
settlement publication clause. An omitted request preserves once publication;
separate clauses price payer-only and payer/payee combinations independently.
Clauses already resolve whole through override > pool hint > configured default,
so the preset's notices, penalty and setup resolve with their own quoted rate,
not by merging rights across sellers' tiers. No stored class is introduced.

The injected helper supplies a unit-bearing reference quote, parsed period,
approval window, adjudication and the mechanism's lifecycle capabilities, then
encodes a fully resolved preset. Publication computes the default penalty from
that quote and validates shared lifecycle terms before calling the encoder.
The encoder cannot replace those rights or insert a horizon into option identity.
No hosted rate encoder is supplied here; absent helpers omit only recurring
clauses. Setup support is an explicit helper capability tied to the vendored
delivery-end revision, not inferred from the presence of setup fields.

The pool's effective deadline must come from a composition-injected pool-facts
reader, keyed by site/pool, not the clause's historical delivery-deadline input
or an unenforced raw tag. The renewable dependency has not implemented that port
on this base. Its absence resolves no enforced deadline; once publication remains
possible with the default-buyer diagnostic, and injected qualification supplies
the port. This change does not invent provider defaults or enable site enforcement.
Diagnostics are kept in cycle reports even when reserved peers remain publishable.
The shared refusal function is `default_buyer_refusals`; task 4.1 must consume it
rather than maintaining another buyer recommendation policy.

Bare-metal pool clauses use `policy_tags.pricing.bare_metal.settlements`; a
stated override replaces that list, which replaces configured clauses whole.
An empty list withholds every option. Malformed hint structure holds the pool,
not a lower tier's price. Reserved-only pools retain their positive-relative-
maximum hold; pools offering recurrence reach per-option derivation instead.
An absolute-only horizon can therefore publish recurring options while reserved
capacity options are omitted with their existing positive-bound requirement.
With no finite bound, recurrence is omitted and reported, not held as an unknown
mechanism; a listing left without any valid option closes through the existing
no-settlement-option path. Capacity/shape identity never includes billing presets.

Publication resolves its diagnostic reference start to a whole second; an
absolute bound with fractional seconds cannot yield the integer Agreement horizon
unchanged, so that recurring default is refused instead of rounded. Acceptance
remains responsible for checking the later actual start and approval expiry.
Permanent destinations remain D3/D5's publication and settlement homes, post-review.

## Servicing-declaration implementation choices

Task 3.1 implements the neutral contract in
`kit/settlement-runtime/src/market_settlement_runtime/rate_servicing.py`.
`RateServicing` holds adapter-required revisions, current composition declarations
and an optional explicit proposed-lane identity. Selection requires the exact
mechanism and revision. A proposed declaration must name a stable lane matching
that opt-in; neither a proposed flag alone nor an arbitrary test-mode setting
makes it deployable. Revision values come from the installed adapter, not a
listing, buyer or implicit default. No deployed adapter/revision is supplied on
this base. The diagnostic uses an explicitly fictional `fixture-rate-v1` contract.

Both storefronts hand their composition's exact selector object to publication
and negotiation. The preset request includes its selected declaration for the
encoder. Publication checks both recurring clauses and final option envelopes,
so an ordinary builder cannot leak a rate outside the clause gate. Either of
the flat period/reserve markers requires servicing, even if the other is missing
or invalid; this is a conservative admission guard, not another period parser.
The installed mechanism still validates the wire and projects the billing unit.

Acceptance checks the selected cached option before policy/pricing effects and
again during final artifact construction before the shared runtime persists
acceptance. Withdrawn contracts report `settlement_option_withdrawn_refetch` as a
409, including revision/lane mismatch; the listing's retained rate terms do not
supply the missing declaration. This admission object is not read by accepted-deal
continuation: disabling offers cannot disable work already owed. Spot's
materialization consumer must call this same selector; convergence owns startup
and continuation. This checkpoint qualifies only the terms-owned two doors.

The replayable publication diagnostic now drives typed buyer refusals and checks
real SQLite negotiation rows remain unchanged. Its injected published/proposed
fixtures do not implement a live rate service. A kept shape-priced buyer
integration scenario additionally needed its captured as-published body and real
seller signature/trust: local storefront rows cannot substitute for the proof
required by D2b. No verification assertion was relaxed. D6's permanent homes
remain settlement configuration and storefront publication architecture after
code review. Focused evidence and setup are recorded in
`docs/attachments/negotiate-open-ended-compute-terms/servicing-declaration-checkpoint.md`.

## Acceptance-horizon implementation choices

Both domains use the pure `resolve_horizon` in settlement runtime. Capacity bounds
and minimum terms arrive as data; the helper knows no compute package or mechanism.
The negotiation runtime fixes its acceptance instant and calls an optional opaque
`resolve_acceptance` domain hook before artifact construction or persistence. All
four paths (opening acceptance, seller counter acceptance, buyer acceptance and
administrative acceptance) use it. This avoids inventing an earlier acceptance
clock or mutating artifacts after the runtime already persisted a different horizon.

An implicit recurring `now` has no buyer-signed instant to preserve, so it resolves
once to the authority's whole-second precision before signing. Explicit fractional
recurring starts refuse; once-only fractional handling stays unchanged. An integer
explicit horizon fits a fractional upper bound exactly without extending it. If
the omitted default's limiting bound is fractional, refuse and ask for an explicit
shorter horizon; a fractional non-limiting bound does not change an integer maximum.
No horizon is rounded to a billing-period multiple. Missing reserved duration is
refused in negotiation without changing delivery/resume fallbacks.

`rate_term_projections` is a composition-owned mapping of mechanism to a callable
from the exact selected `SettlementOption` to `RateTermTiming`. The latter contains
positive whole-second period and approval window plus foundation `TermContext`.
The installed mechanism owns parsing and supported partial-period treatment, not
neutral terms code reading payment field names. Missing projection refuses, even
with a declaration. No deployed projection or rate declaration is supplied. The
foundation codec validates the selected lifecycle at acceptance, including term-end
treatment; existing payments derivation already maps it through `partial_period`.
This port is an implementation handoff, not a newly enabled payments wire revision.

Bare-metal exact pricing/admission uses a provisional horizon without rewriting
requested wire. Final acceptance repeats resolution with the fixed clock, rebuilds
its mechanism obligation/service terms and physical duration, and refuses a changed
exact payment. Agreement-only rate pricing uses a period, not the service horizon.
VM's final hook binds the same listing bounds before deriving accepted money.
The selected option and original provision wire remain unchanged in both Agreements.

Task 3.3's two doors are qualified by the replayable declaration fixtures after
this integration; spot's materialization and convergence's startup/continuation
remain consumer responsibilities, not archive dependencies. The valid bare-metal
fixture stops at the runtime's no-write opening plan: its payments-capture consumer
requires a real mandate and correctly refuses an empty placeholder. The VM fixture
can commit signed artifacts with an injected accepted-data placeholder, but neither
fixture is live rate/mandate execution. Detailed evidence and resolved attempts
are in `docs/attachments/negotiate-open-ended-compute-terms/horizon-acceptance-checkpoint.md`.
D5's permanent destinations remain negotiation/publication/resource-pool specs and
publication architecture after code review; the opaque hook also belongs in the
negotiation specification. No permanent promotion is made at this checkpoint.

## Buyer-rights policy and lifecycle disclosure continuation

`kit/settlement-runtime/buyer_terms.py` composes the existing publication diagnostic
policy with foundation `AuthoritySelection`. Recommendation refusal precedes
ranking, so missing deadline/penalty and non-returned payee/term-end treatments
have the same explanation on both sides. The explicit run-scoped
`--allow-unprotected-terms` switch waives these recommendations together; it does
not waive the codec, installed payment capabilities or authority acceptance.
The foundation's missing-deadline opt-out is set only for that explicit switch.
No hidden profile default or new payments wire capability is introduced.

Both compositions declare adapter contexts and render shared codec-derived
lifecycle rows. Selected terms precede fresh negotiation; exact accepted terms
precede fresh approval. Disclosure goes to stderr even in noninteractive mode,
keeping bare-metal JSON stdout usable. No-adapter options make no lifecycle
promise and are not refused for lacking a deadline. Penalty prose states the
asset/minor-unit ceiling and earned-held cap, not an available seller stake;
setup prose is explicitly conditional until the separate mechanism-owned pricing
presentation supplies its actual amount. Foundation authority identity, evidence,
retention and stop/end semantics remain owned there, not duplicated codecs here.

The committed `buyer_terms_probe.py` consumes either buyer's context factory and
injects proposed charged/returned rate capabilities for shared policy/disclosure
qualification. It is not a rate-capable CLI or hosted service. Its initial wrong
fixture interface and an entitlement-key typing error were corrected; both domain
replays and targeted typing pass. Existing buyer and settlement suites remain
unchanged. Exact setup and evidence limits are in
`docs/attachments/negotiate-open-ended-compute-terms/buyer-rights-checkpoint.md`.

This is task 4.1a, not completion of 4.1. Optional recurring horizon plumbing,
class/unit-bearing monetary/setup/reserve/bounds display, recovery pre-approval
disclosure, full selection first use, E2E and closeout remain. Billing projections
are deliberately once-only in the installed payment adapter. The continuation
must inject mechanism-owned proposed rate pricing/presentation rather than parse
payment fields in a neutral buyer or infer deployed support. D3/D7 permanent homes
remain settlement-configuration and buyer-orchestration specs/companions after
code review; none are promoted in this checkpoint.

## Buyer numerical presentation and optional horizon continuation

`MechanismRegistration.present_payment` takes the selected option, optional
requested duration and optional exact accepted accessor quote. Its typed result
contains `quote`, `setup_once` and `initial_reserve` in the quote's asset/minor-unit
scale. Zero states none; null states undetermined, never a guessed zero. The
registry checks the returned billing basis and asset and forbids changing accepted
money. Setup/reserve arithmetic and payment-field interpretation belong to the
mechanism, including for proposed diagnostics. Installed payments and Alkahest
supply once-only presentation; their billing projections still refuse unsupported
rate fields. This is an injected disclosure contract, not an adapter capability.

Fresh presentation reads listing bounds and the requested horizon; an omitted
recurring horizon is explicitly awaiting the seller's finite resolution. After
acceptance, presentation reads only the Agreement's selected option, money, start,
duration and resulting maximum accepted end. It does not recover listing maxima
from a current offer or pretend an accepted horizon can be extended. VM's accepted
recovery entry renders those retained bytes before dispatching approval effects.
Bare-metal has no separate reapproval command; its fresh accepted path renders the
same shared disclosure. Mechanism/policy validation remains independent of display.

VM keeps public price bounds hourly: flat recurring quotes scale by one projected
period, reserved quotes by the requested lease span, and shape-priced negotiations
still use the multiplier codec. Core accepts an optional per-match unit-count hook
without knowing those units. The codec no longer converts an absent recurring
horizon with `int(None)`; quote derivation requires a positive duration only for a
whole-term quote. Bare-metal's CLI removes its implicit one-hour default and
compares accepted amount, asset and billing basis to its exact quoted value, plus
an explicitly requested duration when one was supplied. No minimum spend is added.

The kept VM CLI regression now checks an explicitly nonpositive duration instead
of requiring duration before option selection. Two kept schema-opaque negotiation
fixtures explicitly omit the production mechanism acceptance callback: their
synthetic Alkahest-tagged options are not real escrow parameters, and their existing
selection-pin/plan-hook assertions remain unchanged. New permanent acceptance tests
were not added. The proposed replay and focused results are recorded in
`docs/attachments/negotiate-open-ended-compute-terms/buyer-presentation-checkpoint.md`.
D2/D7 permanent destinations remain the negotiation and buyer specifications and
buyer architecture companion after review; full selection first use is 4.2, not
claimed by this numerical/horizon continuation.

## Mixed-selection first-use boundary

Both command surfaces consume actual mixed published options using proposed mechanism billing/presentation/capability ports. Reserved hosted, on-demand and spot display both bounds and preserve omitted/shorter requests. VM also selects Alkahest with no lifecycle and shows no delivery promise. Bare metal's installed purchase command remains payments-only; no Alkahest buyer stage is fabricated merely to display the common no-adapter rights result. Its shared rights/disclosure accepts the Alkahest peer, while its CLI exercises the hosted reserved peer. The selection replay stops before protected effects; signed cached refusals and horizon artifacts use the existing application diagnostic separately. This preserves the distinction between terms qualification and rate mandate/capture execution.

Both prescribed-provider E2E setups fail before readiness. The existing Compose-assembly gap carries the reproductions; this does not qualify deployed rate servicing or permanent live capabilities. Full setup/results are in `docs/attachments/negotiate-open-ended-compute-terms/mixed-selection-checkpoint.md`.

## Reserved-purchase E2E and the deadline source

Round 1 left the deployed compositions reading only `delivery_deadline_for_pool`,
which none wires, while the payments builder ignored the clause's configured
`delivery_deadline_seconds` for compute options. No deployed seller published a
deadline, every default buyer refused every hosted compute option, and the
reserved-payment E2E drivers passed `--allow-unprotected-terms` to get through.
The owner's round-1 review settled the source (record 01, R21, R22): the composition
supplies the pool port's value when it gives one, else the clause's configured value
(D3). The drivers then drop `--allow-unprotected-terms` and again assert that the
published `delivery_deadline_seconds` equals the configured value, and
`e2e-tests/tests/unit/test_dispute_coverage.py` returns to its earlier fixtures. That
work is in the round-2 sections of `tasks.md`; `renewable-compute-lease-deadlines` later
supplies the pool port, which takes precedence.

## Round-1 triage

The owner's record of round 1 (`reviews/01-implementation-owner.md`) stood in for the
design review this change never had. Its accepted decisions are recorded above: R3 in
D2a; R4 and R5 in D2b; R6 in D2; R7 in D1 and D4; R8, R9 and R27 in D5; R10 and R26 in
D9; R11, R13 and R21 in D3; R12 and R17 in D7; R14 and R18 in D11; R15, R16 and R19 in
D6 and D8; R28 in D10; R29 in D12. Review 04's F1 and F2 are recorded in D5, and
validation 05's V1 was R4's adaptation of the retained pricing record to the
publication's `pricing` object, fixed in that triage. The code each decision needs is
the round-2 sections of `tasks.md`.

### Implementation cadence

Round 1 was sections 1–4. Round 2 implements the decisions above and is reviewed as
one implementation round. It was first planned as one section; its first session found
that section larger than one session holds, and the owner returned the change to
planning (2026-11-12) to split it into sections that each fit one session, still
reviewed as one round. Each session ends at its section's verification point and
commits it; the round's review and validation follow its last section.

Part B of the record compares this change with the Goal 8 MVP replan on
`goal-8-mvp-design`. The owner decided that this change is finished and merged as
built, judged on its own design, and the replan refactored afterwards around what
landed; each contradiction's default outcome is an amendment to the replan, which this
change records but does not make. The triage found none of this change's behaviour
wrong on its own terms, so every contradiction (C1–C11: the deadline's source, the
servicing declaration's `setup` entry, the default buyer's penalty refusal and its
defaults, the presets' payee and term-end treatments, setup on bare metal, the
`max_duration_seconds` rule, the duration flags, the multiplier reading, the amount
guard and the reserved-bound rule) is left to the replan's amendment.

## Design promotion record

Destinations are planned, not claims of implemented behavior.

| Accepted decision | Permanent location |
|---|---|
| D1, D2/D2a/D2b classes, monetary quote unit, tested money readers and acceptance pricing pin | `docs/development/ARCHITECTURE.md` (with the authority description); `openspec/specs/negotiation-protocol/spec.md` |
| D3 penalty preset default and its setting, the deadline's source, buyer acceptance recommendations; D4 placement result | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/storefront-publication/spec.md`; foundation-owned lifecycle contract |
| D5 the horizon as the Agreement's, listing bounds, the acceptance hook, the floored default, the buyer's check and its seams, and the reserved-bound rule | `openspec/specs/negotiation-protocol/spec.md`; `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/architecture.md`; `openspec/specs/resource-pool-management/spec.md`; `openspec/specs/buyer-orchestration/architecture.md` (the per-listing acceptance validator and the bounds a resumed run keeps); `docs/operator-handbook.md` (bare-metal upgrade step) |
| D6 servicing declaration and its three doors | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/storefront-publication/architecture.md` (with the storefronts' integration fixtures at the composition ports no installed mechanism supplies); `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Settlement consumer configuration and cutover": the seller root's `rate_servicing` tables) |
| D7, D8 display, the mechanism's presenter, the default buyer's policy and seller-policy distinction | `openspec/specs/buyer-orchestration/spec.md`; `openspec/specs/buyer-orchestration/architecture.md`; `openspec/specs/settlement-configuration/spec.md` |
| D9 recurring publication and the shared per-clause step | `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/architecture.md`; `openspec/specs/settlement-configuration/spec.md` |
| D10 the unified clause source | `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/architecture.md`; `openspec/specs/resource-pool-management/spec.md` |
| D11 per-term waivers and duration flags | `openspec/specs/buyer-orchestration/spec.md` |
| D12 compatibility owed to releases; sibling domains alike | `docs/development/RELEASING.md` ("Versioning policy"); `docs/development/ARCHITECTURE.md` ("Family kits") |
| Goal/dependency currency | `docs/development/ROADMAP.md`; `openspec/changes/README.md` at integration/closeout |
