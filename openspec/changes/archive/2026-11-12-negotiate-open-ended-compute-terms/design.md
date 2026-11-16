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

Core's `agreed_price(agreement, listing=None, *, project_billing=None)` reads the
accepted amount once and never recomputes it. Core stays schema-opaque: for a selected
option it requires a mechanism-owned projection, with no schema switch, period parser
or implicit prepaid fallback; an Agreement without an option keeps `total`. A recurring
projection carries the exact period text and its positive whole-second length, a total
projection neither, and an amount outside uint256 is refused. A supplied listing is an
acceptance-bound snapshot: the accessor checks its identity and that it holds the exact
selected option, and never recomputes money from its rates; signature, trust and
transcript-price verification are the caller's before recovery or mandate approval
(D2b).

Each installed registration owns its optional `project_billing`, which
`SettlementConfigurationRegistry.project_billing` and its `agreed_price` convenience
dispatch; a missing hook refuses. Reading an accepted option needs installed code, not
current enablement or readiness. Alkahest and the installed once-only payments adapter
project totals — Alkahest for both its published accepted-escrow selections and
explicit negotiated `EscrowProposal` parameters, refusing lifecycle terms and unknown
shapes — and contact projects its rateless introduction whole; the payments parameter
codec refuses rate and setup fields until a rate adapter supports them. Exact escrow
recovery requires a total quote, and its callers in the VM and API-credit compositions
supply Alkahest's projection. Generic negotiation keeps one raw Agreement equality check
against the codec's expected money, a transport invariant rather than a billing or
spending decision. VM's multiplier arithmetic takes a validated neutral
`PriceBasis` — one period for recurring, the duration for a total — applies the
multiplier as exact rational arithmetic, rounds upward once and refuses a result above
uint256; flat absolute quotes keep their truncating path, and core's generic rate
helpers are unchanged. The payments mandate policy's own refusal of a non-total quote
is defence in depth: the installed projection's strict codec refuses any `period`
first, so no test reaches it. `dependency-contracts.md` records the accessor, helper
and servicing contracts handed to spot and convergence.

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
For rate-structured listings, both VM buyer recording paths retain, through one
deep-copy helper, the complete signed seller publication, request and publisher
provenance beside the pricing fields, with the listing's storefront URL and seller
principal; missing proof is never manufactured for a legacy record. Rateless and exact
selections carry no negotiated multiplier.

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
- `delivery_deadline_seconds` is published under that name on every compute option
  whose mechanism has a lifecycle adapter, recurring or once: the pool port's value the
  composition supplies (`delivery_deadline_for_pool`) when it gives one, else the
  payments clause's configured `delivery_deadline_seconds` (owner record 01, R21).
  Pool-first precedence keeps the site and the published term from disagreeing once
  `renewable-compute-lease-deadlines` enables the pool's tag and the site enforces it.
  The clause value is not an unenforced raw tag: the seller's deal-servicing journal
  files non-delivery at whatever deadline the deal accepted
  (`kit/deal-servicing/src/market_deal_servicing/journal.py`).
  The clause's value is in its mechanism-owned input, which the shared per-clause step
  (D9) never parses, so the precedence is applied where the mechanism reads it: the
  step hands the pool's value, or `None`, to the once option builder as the
  `delivery_deadline_seconds` resource, which falls back to its clause's own; and a
  recurring preset helper returns its clause's value as
  `RatePresetPricing.delivery_deadline_seconds`, which `derive_rate_preset` takes only
  when the pool gives none. Rejected: the step reading
  `mechanism_input["delivery_deadline_seconds"]`, which would make neutral publication
  parse a mechanism's field. Spot's hosted helper therefore owes one line, returning its
  clause's deadline through `RatePresetPricing.delivery_deadline_seconds`; without it a
  hosted recurring option takes only the pool's deadline (`dependency-contracts.md`,
  "Servicing handoff"). The clause fallback amends the foundation's `deal-lifecycle`
  requirements, which had a compute option omit the deadline wherever its site enforces
  none; the delta renames the first "The delivery deadline is the availability term the
  site or the clause sets".
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

The mode hint holds independent optional `max_duration_seconds` and
`available_until_utc` fields; capacity facts never sit in rate entries, settlement
clauses or resource shapes, and an unknown mode name stays opaque. The absolute bound
accepts an aware UTC ISO datetime, or a UTC datetime from TOML, serializes canonically
with `Z`, and refuses naive values, epoch numbers and nonzero offsets rather than guess
a timezone; relative bounds are strict integers. At every tier null or omission defers
to the next, while a nonpositive relative statement masks the tiers below. The pool
contracts own the pure reading, validation and tier selection (`capacity_bounds.py`),
which the pool service applies to documents and write models alike. Shared storefront
storage carries the absolute bound in an additive column, null by default; an update
distinguishes omission from explicit null, so a withdrawn bound clears, and publication
sends the bound as a top-level listing term through the existing registry carrier.
Bare-metal storage and publication do not copy the relative maximum into the listing
resource; rows that did remain readable, and public responses omit the copy. Changing
or withdrawing a bound refreshes the listing on its capacity identity. A bare-metal
override's minimum/maximum compatibility is judged against the live projection the
override write already fetches, through the pool-override contribution's
`projection_problems`, before persistence, so a corrected live hint is never refused for
tags the storefront still holds; publication rechecks on its held generation under
`pool_override_terms_conflict`, and an unreadable bound holds the pool as
`capacity_bounds_unreadable`. VM supplies no projection-dependent term refusal.
`resolve_horizon` and the buyer's check take bounds, period and minimum terms as data
and know no compute package or mechanism; publication evaluates the default horizon from
a whole-second reference start.

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
horizons (owner record 01, R9). The four paths are opening acceptance, seller counter
acceptance, buyer acceptance and administrative acceptance; one fixed instant avoids an
earlier acceptance clock or artifacts mutated after the runtime persisted another
horizon. An implicit recurring start resolves once to whole seconds before signing, an
explicit fractional recurring start is refused, and an integer explicit horizon fits a
fractional upper bound exactly without extending it. `rate_term_projections` is a
composition-owned mapping from mechanism to a callable taking the exact selected
`SettlementOption` to `RateTermTiming` — positive whole-second period and approval window
plus the foundation's `TermContext` — so the installed mechanism owns parsing and its
supported partial-period treatments; a missing projection refuses even with a
declaration, and no deployed composition supplies one. Bare metal's exact pricing and
admission use a provisional horizon without rewriting the requested wire; final
acceptance repeats resolution at the fixed instant, rebuilds its obligation, service
terms and physical duration, and refuses a changed exact payment; Agreement-only rate
pricing uses a period, not the horizon. VM's final hook binds the same bounds before
deriving accepted money. The selected option and the buyer's provision wire stay
unchanged in both Agreements. The buyer's check is one shared pure function beside
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
[Settlement.rate_servicing.arkhai_payments]
treatments = ["charged"]
setup = false        # true once the hosted mediation service rules delivery_end
```

Absent or empty means no rate servicing. An option is admitted only where the
mechanism's helper supports a treatment (D3) and the composition declares it. A form
naming a contract revision per mechanism, with `published`/`proposed` status and a
proposed-lane identity, is rejected: it could not say which treatments were qualified.
Tests inject declarations
directly. Deployed compositions declare no treatments, so recurring offers stay dark
(R16). No additional minimum-spend primitive gates it.

The tables live in the seller's `[Settlement]` root, keyed by each installed
mechanism's configuration key; a buyer's root refuses them, since only a selling
composition services a rate. Their one definition is settlement-runtime's typed table
model, which the configuration loader parses and the values schema renders, so the Helm
schema and the loader cannot disagree on the table's keys or treatment names.

No installed mechanism supplies a recurring encoder, term timing or billing projection,
so no storefront integration test drives a recurring option through the served
composition. A fixture at one of those composition ports would be a mock inside the
codebase, which `docs/development/TESTING.md`, "Integration Tests", forbids: it permits
a mock only at the external I/O boundary. That rule stays as written (owner, closeout,
2026-11-12): it is what keeps a test of functionality that does not exist yet from
merging. Each door keeps a test at the lowest level that proves it without such a
fixture. The storefront integration cases that needed one leave this change: their
copies are kept in the change that installs the recurring mechanism,
`spot-deals-through-arkhai-payments`, which supplies the recurring encoder and adds them
once its code stands at those ports (owner, 2026-11-12). A case whose behaviour needs no
unimplemented port is rewritten here without the fixture rather than moved. The
production VM buyer client cannot open a recurring payments negotiation either: it
sizes its bounds through the installed buyer registry, whose payments projection
refuses rate parameters.

Publication checks both recurring clauses and final option envelopes, so an ordinary
builder cannot leak a rate past the gate, and either rate marker requires servicing even
when its peer is missing or malformed; a `setup_amount` beside a rate marker is a setup
charge. Both storefronts hand one composition-held `RateServicing` to publication and
negotiation, and a recurring preset request carries its selected declaration to the
encoder. Acceptance checks the selected cached option before policy and pricing effects
and again while building final artifacts, before the runtime persists acceptance; the
listing's retained rate terms never stand in for the declaration.

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

Both buyers write the disclosure to stderr, visible without a confirmation prompt, so
bare metal's JSON stdout stays usable. Fresh presentation reads the listing's bounds and
the requested horizon, an omitted recurring horizon shown as awaiting the seller's
resolution; accepted presentation reads only the Agreement's selected option, money,
start, unrounded duration and end, never a current listing or a maximum recovered from
one. VM's accepted recovery renders it before dispatching any approval effect; bare metal
has no separate reapproval command, and its fresh accepted path renders the same rows.
Core accepts an optional per-match unit-count hook without knowing those units: VM
scales its hourly bounds by one projected period for a flat recurring quote and by the
requested span for a reserved one, and shape-priced negotiations use the multiplier
codec, which requires a positive duration only for a whole-term quote. Bare metal
compares the accepted amount, asset and billing basis with its exact quote, and the
duration only where it requested one. Mechanism and policy validation stay
independent of display. Bare metal's installed purchase stage is payments-only: its shared rights policy and
disclosure admit an Alkahest peer as making no delivery promise, and no Alkahest stage is
fabricated to buy it (owner record 01, R20; the unowned gap in
`openspec/changes/README.md`).

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
adjudication, capabilities and the clause's configured delivery deadline (D3), and
encodes the option; the common derivation checks the
authority, derives the penalty (D3), checks the default horizon's runway (D5) and
validates the lifecycle, and refuses an encoder that changes mechanism, asset, period,
reserve or lifecycle. A missing helper, undeclared servicing or an unbounded horizon
omits only that recurring option, with a diagnostic; reserved peers and capacity
identity are unaffected.

That per-clause step — the pool's deadline lookup (D3), the recurring-or-once branch,
`derive_rate_preset`, the diagnostics and the penalty setting — is one
`kit/settlement-runtime` function both compositions call; the `compute` flag and the
deadline lookup are parameters, so it knows no family (owner record 01, R26). Each
`resolve_acceptance` hook keeps only its domain's artifact rebuilding over
`resolve_horizon`. The step, `ClausePublication`, holds what is fixed per composition
— registry, configuration, servicing declaration, helpers, authorities, the `compute`
flag and the penalty multiple — and publishes one ready mechanism's clause per call;
readiness and which clauses reach it stay the composition's. It publishes each option
as its builder built it, the bytes its ID was derived from, after the servicing
declaration's check has validated it whole. The older differences between the domains
are unified in this change: the reserved-bound rule (D5) and the clause source (D10).
Diagnostics are kept in cycle reports even when reserved peers stay publishable. API
credits still builds its once options through the registry itself; it publishes no
recurring option.

### D10. One source for compute settlement clauses

Both domains resolve settlement clauses and listing terms field by field: override >
pool hint per GPU model (`pricing.gpu.<model>`) > pool hint for the pool
(`pricing.settlements`, new) > configuration per model
(`[pricing.defaults.gpu.<model>]`) > flat configuration (`[pricing]`) (owner record 01,
R28). Bounds keep D5's order, with `capacity_bounds.<mode>` ahead of the model hint.
A v0.3.0 VM configuration or hint means what it meant; an older VM storefront ignores
the pool-level key. Bare metal's unreleased `pricing.bare_metal.settlements` hint is
replaced, needing no compatibility path (D12). VM's family rates stay VM's. One shared
resolver, moved out of `arkhai_vms_listings.pricing_resolution`, lives in
`kit/resource-pools-contracts` beside `capacity_bounds.py` and `raw_pricing`, taking the
`gpu` key from the compute vocabulary as data. Closeout confirmed it there (owner,
2026-11-12): it resolves the pool's `pricing` hint, which the contracts package already
reads, names no compute concept, and needs no compute-family kit.

The resolver (`market_resource_pools_contracts.listing_terms`) resolves the settlement
terms — the clause list and VM's legacy accepted-escrow list — and not the bounds, which
keep D5's order through the shared `resolve_capacity_bounds`: VM composes its per-model
bound tiers below the mode hint, the compatibility v0.3.0 is owed, from the resolver's
`model_hint_bounds`; bare metal resolves bounds per pool (override, mode hint,
configuration), as its admission and override write check read them, and never shipped
model bound tiers. Bare metal resolves clauses per candidate, the model being its
machine's GPU model, and gains `[pricing.defaults.gpu.<model>].settlements`, compiled at
startup like `[pricing].settlements`, so its fourth tier exists. The pool-level hint
states clauses only. A hint field of the wrong shape falls through as an absent one in
both domains: that is what v0.3.0's VM resolver does, and bare metal's earlier hold
(`pool_pricing_unreadable`) was never released (D12), so the released behaviour is the
one both keep. The family key bare metal passes is read from the compute vocabulary's
schema (the family of `GPU_MODEL_ATTRIBUTE`), not restated.

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
`bare-metal buy` gives a reserved option without a duration its configured
`default_duration_seconds` (3600 unless configured), shown as the buyer's default in the
disclosure, never for recurring ones. v0.3.0 validated that setting and read nothing
from it, using a constant 3600; the owner chose at closeout (2026-11-12) to honour it
rather than retire a key a release shipped. VM's `market
buy`/`negotiate` gain `--duration-seconds` beside `--duration-hours`; giving both is an
error naming the conflict (owner record 01, R18).

Each default refusal is a named term (`no_delivery_deadline`, `no_penalty`,
`charged_preemption`, `charged_term_end`) in `kit/settlement-runtime`'s publication
module, so the seller's diagnostic and the buyer's refusal read one wording per term;
`buyer_terms` holds the four waivers with their flags and help, the shorthand's
expansion and the rule that only the deadline's waiver sets the foundation's
allowance, and the three buyer commands declare the flags from that one table. The
run metadata records the waivers in force by flag (`compute_term_waivers`), the
shorthand recorded as all four. Both disclosures before approval — the selected
option's, before negotiation, and the accepted Agreement's — name each waiver in force
and mark the refusal it waives, so an accepted option is never shown as refused
without its waiver beside it. A resumed or recovered VM run (`market buy --from`,
`market negotiate --from`, `market settle --from`) reads the waivers from its run log's
`compute_term_waivers`, the ones its selection was made under, and refuses waiver
flags given to the resuming command, as it refuses a new shape or settlement clause.
Whether a reserved option takes bare metal's default is the mechanism's billing
projection (`unit` of `total`), never a payment field the buyer reads; the run records
`default_duration`. VM's conflict and positivity checks run before any identity or
registry read, on fresh and resumed runs alike.

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
- A seller-only started-period refund: only a committed payment term survives an adversarial seller and independent dispute execution.
- Refusing an omitted horizon whose limiting bound has fractional seconds: the buyer asked for the default, and flooring to whole seconds gives it without rounding signed bytes (D5, owner record 01, R9).
- Holding a bare-metal pool that resolves no positive maximum: sibling domains behave alike, and every reserved deal's explicit duration is checked against both bounds at acceptance (D5, D12, owner record 01, R27).
- A family-keyed bare-metal clause hint (`pricing.bare_metal.settlements`): one clause source serves both domains (D10, owner record 01, R28).
- Storefront integration tests with fixtures at the recurring encoder, term-timing and billing-projection ports: a mock inside the codebase, which `docs/development/TESTING.md` forbids; the cases are carried by the change that installs those ports (D6).

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

## Round-1 triage

The owner's record of round 1 (`reviews/01-implementation-owner.md`) stood in for the
design review this change never had. Its accepted decisions are recorded above: R3 in
D2a; R4 and R5 in D2b; R6 in D2; R7 in D1 and D4; R8, R9 and R27 in D5; R10 and R26 in
D9; R11, R13 and R21 in D3; R12 and R17 in D7; R14 and R18 in D11; R15, R16 and R19 in
D6 and D8; R28 in D10; R29 in D12. Review 04's F1 and F2 are recorded in D5, and
validation 05's V1 was R4's adaptation of the retained pricing record to the
publication's `pricing` object, fixed in that triage. The code each decision needs is
the round-2 sections of `tasks.md`.

Before round 1, the design was reconciled with the Goal 8 campaign's cross-change
reviews (foundation 18 F4/F13/F14, spot external F1/F9/F10/F12 and 03 F2, convergence
external F6), which settled the foundation-owned `settles_through` values, one
term-end carrier, the terms-owned default buyer policy and the seller's delivery_end as
a dispute filing; the owner's 2026-10-29 review moved the horizon out of the option.
Round 1's checkpoint evidence — each slice's setup, focused results and probe replays,
as observed then — is in `docs/attachments/negotiate-open-ended-compute-terms/`; where
round 2 changed a behaviour, the decisions above and `tasks.md` hold the final form.

### Implementation cadence

Round 1 was sections 1–4. Round 2 implements the decisions above and is reviewed as
one implementation round. It was first planned as one section; its first session found
that section larger than one session holds, and the owner returned the change to
planning (2026-11-12) to split it into sections that each fit one session, still
reviewed as one round. Each session ends at its section's verification point and
commits it; the round's review and validation follow its last section.

Round 3 is one section, 12a, the version pass. The first closeout attempt found the
packages this change edits not versioned as `docs/development/RELEASING.md`,
"Versioning policy", requires (`tasks.md` 13.7's note), and closeout edits no code.
The owner confirmed the return to implementation and directed (2026-11-12) that
planning add the version pass as a section before closeout, run as a one-section round
whose validation and implementation review are waived, since a version, pin and lock
change alters no behaviour the round's validation and review have not already judged;
the change then goes to closeout.

Round 4 is one section, 12b. The second closeout attempt put four questions to the owner
(`tasks.md` 13.3's note); two answers need code — the fixture-port storefront tests
leave this change (D6) and `bare-metal buy` honours `default_duration_seconds` (D11) —
and closeout edits no code. The owner confirmed the return and directed (2026-11-12)
that planning add the fix as a section before closeout, run as a one-section round
whose validation and implementation review are owed, since it changes tests and buyer
behaviour; the change then goes to closeout, which resumes at 13.3.

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

Completed at closeout (2026-11-12). Every decision is permanent and implemented; the
round-1 forms round 2 replaced are rejected alternatives above, not promoted. A
`spec.md` named here is written by the archive merging this change's delta for that
capability; every other destination was written at closeout, except the operator
handbook's two upgrade steps, written in implementation (9.2) and confirmed.

| Accepted decision | Permanent location |
|---|---|
| D1 derived classes | `openspec/specs/storefront-publication/spec.md` ("Compute product classes are derived options", delta); `docs/development/ARCHITECTURE.md#discovery-and-negotiation`; `openspec/specs/storefront-publication/architecture.md#compute-terms-of-sale` |
| D2/D2a monetary Agreement, unit-bearing accessor, tested money readers, no static inventory | `openspec/specs/negotiation-protocol/spec.md` ("Agreed compute prices carry their unit", delta); `docs/development/ARCHITECTURE.md#discovery-and-negotiation`; `openspec/specs/negotiation-protocol/architecture.md#the-agreed-price-and-its-unit`; `openspec/specs/settlement-configuration/architecture.md#registration-and-ownership` (the mechanism's `project_billing`) |
| D2b signed-acceptance pricing pin, verified against the retained publication | `openspec/specs/negotiation-protocol/spec.md` ("Acceptance pins the published rate identity", delta); `docs/development/ARCHITECTURE.md#authority-boundaries` (the authority row); `openspec/specs/negotiation-protocol/architecture.md#the-agreed-price-and-its-unit` |
| D3 shared codec consumption, penalty default and its setting, the deadline's source, the window floor, the seller-side refusal diagnostic | `openspec/specs/storefront-publication/spec.md` ("Recurring presets expose the premature-stop penalty", "A compute option's delivery deadline is its pool's, else its clause's", delta); `openspec/specs/deal-lifecycle/spec.md` (its delivery-deadline requirement, renamed "The delivery deadline is the availability term the site or the clause sets", and "Lifecycle terms are part of the selected option", delta); `openspec/specs/storefront-publication/architecture.md#one-per-clause-step-for-both-compute-domains`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust` (the penalty multiple's startup refusal) and `#storefront-listing-shapes-and-pool-overrides` (the default penalty bullet). The codec and its authority checks stay `deal-lifecycle`'s; nothing here restates them |
| D4 the terms are the option's `lifecycle` | `openspec/specs/deal-lifecycle/spec.md` ("Lifecycle terms are part of the selected option", the foundation's own requirement, which this change's delta amends only for the deadline) |
| D5 listing bounds, the horizon as the Agreement's, the acceptance hook, the floored default, the runway, the buyer's check and its seams, the reserved-bound rule | `openspec/specs/negotiation-protocol/spec.md` ("Compute horizons bind both seller bounds", "The horizon is the Agreement's, and the option is unchanged by it", "The negotiation runtime resolves acceptance through a domain hook", "Recurring starts resolve before signature", delta); `openspec/specs/storefront-publication/spec.md` ("Compute listings carry two capacity bounds", "Unbounded recurring candidates close independently", "A storefront that cannot publish refuses to start", delta); `openspec/specs/resource-pool-management/spec.md` ("Capacity bounds are validated publication hints", delta); `openspec/specs/storefront-publication/architecture.md#two-capacity-bounds` and its "Autonomous publication" and "Storefront pool overrides" paragraphs; `openspec/specs/negotiation-protocol/architecture.md#acceptance-resolves-the-domains-terms-once`; `openspec/specs/resource-pool-management/architecture.md#capacity-bounds-and-listing-terms`; `openspec/specs/buyer-orchestration/architecture.md#compute-terms-before-approval`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides` (capacity bounds, the bare-metal override bullets); `docs/operator-handbook.md#what-the-upgrade-from-v030-changes` ("Bare-metal lease bounds"); `docs/bare-metal-seller-quickstart.md` (the retired hold) |
| D6 servicing declaration and its three doors; why no storefront integration test drives a recurring option | `openspec/specs/settlement-configuration/spec.md` ("Rate servicing is a composition capability", "Terms expose servicing declaration without enabling rate execution", delta); `openspec/specs/negotiation-protocol/spec.md` ("Acceptance checks current rate servicing", delta); `openspec/specs/storefront-publication/spec.md` ("Recurring publication checks servicing", delta); `openspec/specs/storefront-publication/architecture.md#the-servicing-declaration-and-its-three-doors`; `openspec/specs/settlement-configuration/architecture.md#registration-and-ownership`; `docs/development/DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover` |
| D7 display, the mechanism's presenter, the default buyer's policy | `openspec/specs/buyer-orchestration/spec.md` ("Buyers approve explicit compute price and end terms", "Buyer display separates billing guarantees from cooperation", "The buyer refuses seller ends that keep the started period", "Default acceptance requires an on-demand seller penalty", "The mechanism supplies the numbers a buyer is shown", "The bare-metal buyer purchases hosted options only", delta); `openspec/specs/buyer-orchestration/architecture.md#compute-terms-before-approval`; `openspec/specs/settlement-configuration/architecture.md#registration-and-ownership` (`present_payment`) |
| D8 setup pricing and churn refusal as seller policy | `openspec/specs/storefront-publication/spec.md` ("Recurring publication checks servicing", delta); `openspec/specs/buyer-orchestration/spec.md` ("Recurring purchase may omit a horizon", delta); `openspec/specs/buyer-orchestration/architecture.md#compute-terms-before-approval` |
| D9 recurring publication and the shared per-clause step | `openspec/specs/storefront-publication/spec.md` ("Compute product classes are derived options", "Recurring presets expose the premature-stop penalty", "Unbounded recurring candidates close independently", delta); `openspec/specs/storefront-publication/architecture.md#one-per-clause-step-for-both-compute-domains`; `docs/development/ARCHITECTURE.md#family-kits` (the step as a worked instance of the sibling rule) |
| D10 the unified clause source; the resolver in `kit/resource-pools-contracts` | `openspec/specs/storefront-publication/spec.md` ("Compute settlement clauses resolve from one shared source", delta); `openspec/specs/storefront-publication/architecture.md#one-source-for-settlement-clauses`; `openspec/specs/resource-pool-management/architecture.md#capacity-bounds-and-listing-terms`; `docs/development/ARCHITECTURE.md#kit-areas` (what the contracts package holds); `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides` (the five tiers) and `#combined-compute-family-storefront` (the storefront-wide terms); `docs/operator-handbook.md#what-the-upgrade-from-v030-changes` ("Bare-metal clauses from the pool's `pricing` hint"). `resource-pool-management/spec.md` keeps `pricing` values the reading domain's to define, so it gains no requirement for the pool-level clause key |
| D11 per-term waivers and duration flags | `openspec/specs/buyer-orchestration/spec.md` ("Each default refusal has its own waiver", "Both buyer CLIs take a duration in seconds", "Recurring purchase may omit a horizon", delta); `openspec/specs/buyer-orchestration/architecture.md#compute-terms-before-approval` |
| D12 compatibility owed to releases; sibling domains alike | `docs/development/RELEASING.md#versioning-policy`; `docs/development/ARCHITECTURE.md#family-kits` |
| Goal currency | `docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops` (the gap row archived, the current state's terms paragraph); Goal 5's default-horizon row stays unowned, now citing the permanent spec |
| Campaign currency | `openspec/changes/README.md` (this change's row and its unowned-work table; the Goal 8 graph's placement unchanged) |
| No new capability | `openspec/specs/README.md` needs no entry |
