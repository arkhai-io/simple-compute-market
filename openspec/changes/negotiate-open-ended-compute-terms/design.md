# Design

## Context and authority

This change builds compute terms on the archived
`agreed-evidence-and-early-termination`. Its vocabulary and codec win. Design for
an adversarial counterparty and make the reference implementation cooperative.
The buyer can rely on authority records and kept signed bytes, not seller uptime.
This change owns compute terms and presentation, not authority operations.

A settlement option is `{option_id, price, settlement, lifecycle}`, with `lifecycle`
in the option ID (`core/src/market_core/schemas.py`); the selected option reaches the
Agreement verbatim, and the codec in `kit/deal-lifecycle` validates its terms.

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

### D2. Quote once with its unit; guard every read

`Agreement.amount` is the accepted monetary quote, following the implemented
resize carrier (D2a), never the negotiation multiplier. Billing kind changes the
evaluation duration before acceptance: Agreement duration for prepaid, option
period for recurring. Retain upward rounding once and the asset's amount-range
refusal.

#### D2a. Keep the signed Agreement monetary

**decided by webapp owner 2026-11-06, pending maintainer review**

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

This is what resize left in the code.
`domains/vms/negotiation/src/arkhai_vms_negotiation/amounts.py` applies the
multiplier as exact rational arithmetic, rounds upward once and refuses a result
above uint256, with a default floor of 10,000 basis points. The VM storefront writes
that computed payment into the Agreement and the mechanism artifacts, and the scalar
survives only in the transcript and the thread's agreed price. Core's generic rate
helpers still truncate: resize did not move its upward-rounding quote into core.

Rejected: carrying the multiplier in the Agreement, with an explicit
acceptance-bound pricing carrier and a coordinated settlement-reader migration. It
would change the signed and persisted settlement contract resize delivered and need
a protocol and recovery migration.

#### The accessor and the read guard

Core's `agreed_price(agreement, listing=None, *, project_billing=None)` returns an
`AgreedPrice`: the accepted amount with unit `total` or `per_period` and, for a
recurring option, the exact period text and its validated whole-second length, never
an unlabelled integer. It reads the accepted amount once, never recomputes it from
rates, a duration or the multiplier, and refuses an amount above uint256. Core stays
schema-opaque: a selected option's billing unit comes from an injected,
mechanism-owned projection — the registration's `project_billing` hook, dispatched by
`SettlementConfigurationRegistry` — and a mechanism with no hook refuses
interpretation. Reading an accepted option needs the installed code, not the role's
current enablement or readiness. Alkahest projects a total and recognizes both of its
acceptance carriers, a published accepted-escrow selection and negotiated
`EscrowProposal` parameters; contact exchange projects its rateless whole
introduction; payments projects `per_period` where the option states a `period` and
`total` otherwise. An Agreement with no selected option keeps `total`. A listing
passed to the accessor is an acceptance-bound snapshot: the accessor checks its
identity and that it contains the exact option, and the caller verifies signature,
trust and the transcript price (D2b) before recovery or mandate approval.

Both policies/reference quotes, buyer caps/display, VM amount checks, mandate
derivation and buyer mandate checks, bare-metal quote and recovery checks and exact
escrow recovery use it; an escrow requires a total quote. VM's multiplier arithmetic
takes the neutral `PriceBasis` — one period for recurring, the Agreement duration for
total — with one upward rounding and the uint256 refusal, while absolute and flat
pricing keep their existing truncating path. Additional setup pricing is explicit,
not hidden in the recurring quote. At 2,500,000 USD/6 per hour and 10,000 bps,
two-hour prepaid is 5,000,000 total; PT15M is 625,000 per period; PT1M is 41,667.
Recovery and buyer mandate checks use the signed-acceptance-bound rate structure and selected option, never a current or registry-cached listing; D2b is the carrier `negotiation-driven-capacity-resize` left to be decided, binding that structure's digest in accepted evidence before approval.

A fail-closed repository check refuses direct `Agreement.amount` reads outside the
accessor and declared raw negotiation hooks. Cover actual attribute/mapping reads
and aliases/wrappers; an unclassified reader fails rather than escaping detection.
Model declaration/serialization is not price interpretation. Each hook allowlist
entry records why it negotiates the scalar instead of spending it.
The guard is `scripts/check_agreement_amount_reads.py`, run by the packaging and
change checks. It does not infer Python types or names: it inventories every
production amount attribute read, literal- and aliased-key mapping read and
reflective or getter read, wrapper bodies included, and classifies each by exact
path, function, expression and count as a quote, resource, obligation, authority or
proposal read with its reason. An unknown read, a changed count and a stale entry all
fail. Generic negotiation keeps one raw equality check of the Agreement against the
codec-derived expected money, which is neither a billing nor a spending decision. The
rule is syntactic: it proves nothing about runtime-generated Python and is not an
authentication boundary. Its positive and negative fixtures are the committed
`amount_read_probe.py`.

#### D2b. Signed-acceptance pricing pin

Status: decided by webapp owner 2026-11-06, pending maintainer review.

The seller-signed acceptance binds the agreed multiplier and the rate-structure
digest: the same digest D-e pins at opening, computed over the family rates as
published (D-b) and seller-signed in the registry's retained publication (D-c). A
publication carries its listing-level prices in one closed `pricing` object,
`pricing.asking_rate` and `pricing.rate_structure`
(`core/registry/src/core_registry/filter-spec.yaml`); the registry refuses a top-level
`rate_structure`, and the buyer lifts `pricing.rate_structure` into its listing record
before computing the digest.
Opening, every round and acceptance refer to this one rate identity. The buyer
verifies it against the retained seller-signed registry publication, never a
snapshot supplied by the seller. Historical publication verification, exact option
and listing context, and transcript/Agreement verification precede accepted reads.
Legacy records missing bound evidence fail closed; fresh listings cannot repair them.
For a rate-structured listing both VM recording paths retain the complete signed
seller publication and request with the publisher's provenance beside the pricing
fields, since a subset cannot reconstruct signed fields, and proof is never
manufactured for a legacy record.

Rejected: returning the full seller database snapshot under the existing hash.
That would turn a private storage shape into a public contract.
`Agreement.listing_hash` remains unchanged: it commits the seller's database
listing rather than the published document. This known mismatch must be revisited
with the maintainer, not repaired by this change.

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
  negotiation), and a buyer may loosen it. The vendored payments contract expresses all
  three treatments (`kit/arkhai-payments/schema/SOURCE.md`), so the shipped presets publish
  as stated; the codec still refuses a treatment the selected mechanism's installed contract
  does not support, and what limits a rate offer is the composition's servicing declaration (D6). `exposure_seconds` and `stop+exposure` are retired.
- `adjudication = {version, dispute, dispute_window_seconds, case_hold_max_seconds}`;
  `dispute = {interface, origin, account, record_key, params}`.
- `premature_stop_penalty` is a nonnegative integer amount in the option asset's minor units, encoded as a canonical decimal string; absent/zero means none. It applies to an unentitled seller end, including a spot emergency without notice, not an entitled notice stop. Recommendation: on-demand presets default to 24 periods' price (calculated through the agreed-price accessor), and buyer default acceptance refuses on-demand without a positive penalty because the buyer benefits and enforces it, like partialPeriod. Expose seller override and explicit buyer opt-out; never silently downgrade the default. The number is a ceiling, not a guarantee: the remedy takes `min(penalty, earned amounts still held)` after the refunds, and early in a deal what is earned and held is the setup charge alone — an on-demand VM pulled minutes after activation, with its started period returned, leaves nothing else to take, and zero with no setup charge. A seller-funded stake that makes the ceiling collectible is the reserved `bond` term (foundation D5), not this change's.
- `bond` stays reserved where the mechanism cannot hold a seller-funded stake.
- `delivery_deadline_seconds` is the pool's effective `delivery_deadline_seconds` tag
  (`renewable-compute-lease-deadlines` D3), read from the pool at derivation like the
  bound hints and published under the same name on every compute option whose
  mechanism has a lifecycle adapter, recurring or once; the site enforces exactly that
  value from the deal's commitment instant (foundation D5, "Delivery has a deadline").
  A pool that enforces no deadline yields an option without the term, and the default
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

**Current gap in the deadline's source.** Both compositions take the pool's deadline
through an injected reader keyed by site and pool, `delivery_deadline_for_pool`, and
neither wires it: its default answers that no deadline is enforced. Deployed sellers
therefore publish no `delivery_deadline_seconds`, on once options too, since a raw
clause value does not stand in for the pool fact, and a reserved-payment purchase from
them needs `--allow-unprotected-terms`; the reserved-payment end-to-end scenarios pass
it and assert that no delivery promise is published.
[`renewable-compute-lease-deadlines`](../renewable-compute-lease-deadlines/) closes the
gap by making the deadline a pool policy tag the site enforces at commit and reclaims
on expiry. This change's remaining step is to wire each composition's reader to the
pool's effective value and return those scenarios to protected purchases. Whether a
seller-configured deadline should be the source until then is open with the
maintainer; the bullet above is unchanged and no raw-clause fallback exists.

A payee entitlement means the seller may interrupt; the payment authority enforces
its notice as a pending stop on that stop authority, not a local schedule.
On-demand has no payee stop entry. The mandate therefore does not enforce that the seller
won't preempt; that is enforced by the penalty and a buyer's case over held money, not by the mandate.
The seller's own exit is `delivery_end(cause=payee)`, a dispute filing the seller half journals with
the end and files with the dispute authority; the seller sends no stop or reverse of its own.
Arkhai mediation rules payee-agreed delivery_end under its mapping/time/replay guards; the cause=payee branch is the standard self-penalty (`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`); the terms this change publishes are what that
ruling reads — the penalty, the on-demand returned treatment, the setup charge — and
the display explains them against it (D7). A buyer contesting the account files a case;
mediation triages claims lacking payee agreement or failing its mapping/time/replay guards; matching receipt-backed payer claims rule automatically. There is no compensation enum. Setup-bearing presets wait for foundation 12.1 to vendor the proposed delivery_end signature/concurrence revision and vectors, not another payments wire change; setup-free presets remain independently eligible.
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
not stopped, and can see why no default buyer takes the offer. The diagnostics stay in
the publication cycle's report even when reserved peers publish. Both sides read the
policy from one function, `default_buyer_refusals`: the buyer's side, `buyer_terms.py`
in `kit/settlement-runtime`, composes it with the foundation's authority selection and
refuses before ranking, so seller and buyer explain a refusal the same way. One
run-scoped switch, `--allow-unprotected-terms`, waives these recommendations together —
the missing deadline, the missing penalty and a payee or term-end treatment that is not
returned. It waives nothing the codec, the installed payment capabilities or authority
acceptance refuse, and no profile default sets it.

Resolve seller preferences through override > pool hint > configured default,
keyed per offered preset like its rate. These are seller choices, not a protocol
requirement to price identically. Recommendation: shipped recurring presets have
a payer entitlement with `notice_seconds: 0` — a buyer who stops is charged to the started
period and nothing after, and a seller who wants a tail prices it as a number the buyer sees —
and a setup once part; spot adds a payee entitlement. Omission
never grants the payee an implicit entitlement. The foundation owns validation and
identity inclusion; do not create a second hash rule or require early_termination
on every compute option. Terms injects a preset-helper interface: selected quote/unit,
period/reserve, setup, bounds, adjudication and early-termination declarations in;
a canonical candidate option or a named derivation refusal out. Spot supplies the
hosted helper; generic publication tests use injected helpers. Missing helper omits
the recurring candidate, never reconstructs the mechanism's parameters. Neither archive waits
for the other's execution.

A recurring preset is a structured, mechanism-neutral `recurring` request on a
settlement publication clause; a clause without one publishes a once option. Separate
clauses price the payer-only and payer/payee combinations, and because a clause
resolves whole through override > pool hint > configured default, a preset's notices,
penalty and setup resolve with their own rate and never merge rights across tiers.
Bare-metal pool clauses are `policy_tags.pricing.bare_metal.settlements`: a stated
override replaces that list, which replaces the configured clauses whole; an empty list
withholds every option, and a malformed hint holds the pool instead of falling to a
lower tier's price. The helper returns a unit-bearing reference quote, the parsed
period, the approval window, adjudication and the mechanism's lifecycle capabilities,
then encodes the fully resolved preset. Publication computes the default penalty from
that quote and validates the shared lifecycle terms before it calls the encoder, and
refuses an encoder result that changes the mechanism, asset, period, reserve or
lifecycle, so an encoder can neither replace the rights nor put a horizon into option
identity. Setup support is a capability the helper declares, tied to the vendored
delivery_end revision, never inferred from the presence of setup fields. The payments
kit's helper is installed in both compositions, and with no servicing declaration it
is never asked to encode (D6).

### D4. The terms are the option's `lifecycle`

`early_termination` and `adjudication` are objects under the option's `lifecycle`, beside `price` and `settlement`, and so in the Agreement bytes and the option ID (foundation D5, "The option's shape"). They are the parties' rights after commitment — who may end the deal, on what notice, with what treatment of the period in progress, and who decides a dispute — and become payment facts only when exercised, when the adapter derives stop authorities from the entitlements and the hold from the window; they are owned by the lifecycle codec, not by any settlement mechanism, so they do not sit in the mechanism's own parameters under the mechanism's model. The codec reads both keys by the same names and shapes whatever the settlement schema, and never branches on it or decodes Alkahest arbiter demand trees to read them. A mechanism adapter separately refuses terms it cannot enforce: carrying the keys is not permission to advertise an unsupported Alkahest lifecycle promise. `placement-probe.md` records the earlier experiment of carrying both objects inside the mechanism's parameters; task 1.2's check of the nested shape is a regression, not a decision gate, and it is the replayable `codec_probe.py` and `registry_codec_probe.py`, which exercise the shared codec and the retained registry carrier, in place of a permanent acceptance test.

### D5. Two listing bounds compose at the agreed start

`max_duration_seconds` is the longest deal from its start; `available_until_utc` is
the last possible lease end. Both are listing capacity facts, not option copies or
`listing_resource` fields. Resolve through override > pool hint > configured
default per offering mode. Nonpositive/unset relative bound means no relative
limit; a stated absolute bound is timezone-aware UTC. Malformed bounds hold
derivation with a diagnostic, not a guessed default.

The pool hint is `policy_tags.capacity_bounds.<offering_mode>`, with independent
optional `max_duration_seconds` and `available_until_utc`, which keeps capacity facts
out of rate entries, settlement clauses and physical resource shapes; an unknown mode
name stays opaque. An absolute bound is an aware UTC ISO datetime, or a UTC datetime
from TOML, serialized canonically with `Z`; naive values, epoch numbers and nonzero
offsets are refused, never assigned a timezone. A relative bound is a strict integer:
a nonpositive statement masks lower tiers before it becomes an absent limit, and null
or omission defers to the next tier. Each bound resolves independently. VM keeps its
per-model pricing hint and configured-model defaults as compatibility tiers below the
mode hint: mode hint, legacy model hint, model default, flat default. The pool
contracts own bound reading, validation and tier selection
(`kit/resource-pools-contracts`), and the pool service applies them to document
validation as well as to its HTTP write models.

Storefront storage carries the absolute bound in an optional column. An update
distinguishes omission from explicit null for both bounds, so withdrawing a bound
clears it, and changing or withdrawing one refreshes the capacity/shape identity
without touching accepted Agreements. Publication sends the absolute bound as a
listing-level extra through the registry carrier, not in the option or the listing
resource. Bare metal no longer copies the relative maximum into the resource: rows
that still hold the copy stay readable and public responses omit it. A bare-metal
override's minimum/maximum compatibility is judged against the live projection the
override write already fetches, through the pool-override contribution's
`projection_problems`, because a pool hint can replace the configured maximum and a
corrected hint must not stay refused over stale held tags; publication rechecks on its
held generation with `pool_override_terms_conflict`, and unreadable bounds report
`capacity_bounds_unreadable`.

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
`delivery_deadline_seconds` is the lifecycle term the pool feeds — and the check is
the only place they meet; a buyer that approves at the last permitted instant gets
its period, and no timing the Agreement permits is a seller breach.

Rate billing starts at activation, potentially later than the Agreement start,
while the payments end is absolute: horizon rounding cannot align that end to a
billing boundary. Foundation D5 therefore gives the term end its own
`settles_through`, mapped to the rate part's `end.partialPeriod` with the same
values as stop authorities. Compute presets use `last_boundary` (returned), so
billing never runs past the agreed maximum; the vendored payments contract
expresses that treatment. A seller who configures term-end `started_period`
publishes a charged final partial period, committed in the option, which the
default buyer refuses (D3). Exhaustion
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

Both domains resolve the horizon with the pure `resolve_horizon` in
`kit/settlement-runtime` (`horizon.py`), which takes bounds and minimum terms as data
and knows no compute package or mechanism. The negotiation runtime fixes its
acceptance instant and calls an opaque `resolve_acceptance` domain hook before it
builds or persists any artifact, on all four paths: opening acceptance, the seller's
counter acceptance, buyer acceptance and administrative acceptance. An implicit
recurring `now` has no buyer-signed instant to preserve, so it resolves once to a
whole second before signing. An explicit integer horizon fits a fractional upper bound
without extending it; when the omitted default's limiting bound is fractional the
seller refuses and asks for an explicit shorter horizon, and a fractional bound that
does not limit changes nothing. Publication resolves its reference start to a whole
second the same way and refuses a recurring default whose absolute bound is
fractional. The period, the approval window and the supported treatments reach this
neutral code through `rate_term_projections`, a composition-owned mapping from a
mechanism to a callable over the exact selected option that returns `RateTermTiming`;
a missing projection refuses even where servicing is declared, and both compositions
install the payments kit's. Bare metal prices and admits against a provisional horizon
without rewriting the requested wire, then repeats resolution at final acceptance with
the fixed clock, rebuilds its obligation, service terms and physical duration, and
refuses a changed exact payment. The selected option and the original provision wire
are unchanged in both domains' Agreements.

An unbounded recurring candidate yields no option and a derivation close reason,
not a hold merely for being unbounded; valid reserved candidates remain. Bare
metal's existing positive-bound rule for reserved candidates remains: a reserved-only
pool without a positive relative maximum is held, while a pool offering recurrence
reaches per-option derivation, so an absolute-only horizon publishes recurring options
and omits the reserved ones. A later
listing-date edit never extends an accepted lease. The shared delivery change
uses accepted start plus duration in both domains, not `now`. Here remove VM's
round-zero missing-reserved-duration fallback; delivery owns its resume fallbacks.

### D6. Three doors read one servicing declaration

Composition, not a listing or buyer, declares rate servicing and its contract:
deployed published revision, or `proposed` only in an explicitly opted-in test
lane. No additional minimum-spend primitive gates it.

1. Publication omits recurring candidates if servicing is undeclared, using existing
   no-settlement-option diagnostics if none remain.
2. Acceptance refuses cached recurring selections when servicing is now undeclared,
   using the withdrawn-option/refetch outcome before persisting acceptance.
3. Materialization refuses to derive a rate mandate without the declaration, even
   across an acceptance/restart gap.

Startup additionally refuses to strand accepted rate deals without their
continuation. Disabling offers never disables accepted-deal servicing.
`converge-ongoing-compute-leases` owns startup/continuation wiring; the rate adapter
owns materialization. This change supplies the common declaration contract and
publication/acceptance gates. This plan qualifies those two gates using injected declarations;
spot owns materialization execution/evidence and convergence owns startup/continuation
execution/evidence. Neither consumer's completion gates this change's archive. Rate offers
remain disabled in deployed compositions until their consumer gates pass.

The contract is `RateServicing` in `kit/settlement-runtime` (`rate_servicing.py`): the
revision each installed adapter requires, the composition's current declarations and
an optional explicit proposed-lane identity. Selection needs the exact mechanism and
revision. A proposed declaration must name a stable lane equal to that opt-in, so
neither a proposed flag alone nor a test-mode setting makes it deployable. The required
revision comes from the installed adapter — for payments, the vendored schema's hash —
never from a listing, a buyer or a default. Both storefronts hand their composition's
one selector to publication and negotiation, and the preset request carries the
selected declaration to the encoder. Publication checks recurring clauses and final
option envelopes, so an ordinary builder cannot leak a rate past the clause gate, and
either flat rate marker, `period` or `reserve_ahead_seconds`, requires servicing even
when the other is missing or invalid; that is an admission guard, not a second period
parser. Acceptance checks the selected cached option before any policy or pricing
effect and again while the final artifacts are built, before the runtime persists
acceptance. A withdrawn contract, a revision or lane mismatch included, answers
`settlement_option_withdrawn_refetch` as a 409, and a listing's retained rate terms
never supply a missing declaration. Accepted-deal continuation does not read this
object. Both compositions ship it empty.

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
recovers none of it. Values come from the selected option, not a stored class. The listing's asking rate, `pricing.asking_rate`, keeps its stated unit.
The seller's side of the same display is the default-buyer refusal diagnostic (D3), so
seller and buyer read one policy.

The numbers come from the mechanism, through `MechanismRegistration.present_payment`.
It takes the selected option, an optional requested duration and an optional accepted
quote, and returns the quote, the setup once charge and the initial reserve in the
quote's asset and minor-unit scale; zero says none and null says undetermined, never a
guessed zero. The registry checks the returned billing basis and asset and forbids
changing accepted money, and no neutral buyer code parses a payment field. Before
acceptance the display reads the listing bounds and the requested horizon, and shows an
omitted recurring horizon as awaiting the seller's finite resolution. After acceptance
it reads only the Agreement — selected option, money, start, duration and the resulting
latest end — never a current offer. Selected terms are shown before a fresh negotiation
and the exact accepted terms before a fresh approval, on stderr even in noninteractive
mode, which keeps bare metal's JSON stdout usable. VM's accepted-recovery entry renders
the retained bytes before it dispatches approval effects; bare metal has no separate
reapproval command, and its fresh accepted path renders the same disclosure. An option
with no lifecycle adapter makes no lifecycle promise and is not refused for lacking a
deadline. VM keeps its public price bounds hourly: a flat recurring quote scales by one
period, a reserved quote by the requested span, and shape-priced negotiation still uses
the multiplier codec. Bare metal's CLI has no implicit one-hour default and compares
the accepted amount, asset and billing basis with its exact quote. Its purchase
command is payments-only, so it shows an Alkahest peer's rights without a purchase
stage for one.

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

Neither domain requires minimum spend. Presets default to an honestly named setup
once charge beside the rate. Sellers may price differently or refuse churners,
including by principal blacklist, without claiming resistance to identity rotation.
No new minimum-spend request goes to payments. This change displays setup pricing;
the rate change derives it.

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
- A seller-only started-period refund: only a committed payment term survives an adversarial seller and independent dispute execution.
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

## Evidence

Focused evidence and replay commands for each implemented part are kept outside this
design, under `docs/attachments/negotiate-open-ended-compute-terms/`:
`dependency-contract.md` and `codec-contract.md` (D2a, D4); `price-checkpoint.md`,
`billing-projection-checkpoint.md`, `acceptance-pin-checkpoint.md` and
`reader-guard-checkpoint.md` (D2, D2b); `recurring-publication-checkpoint.md` and
`buyer-rights-checkpoint.md` (D3); `capacity-bounds-checkpoint.md` and
`horizon-acceptance-checkpoint.md` (D5); `servicing-declaration-checkpoint.md` (D6);
`buyer-presentation-checkpoint.md` and `mixed-selection-checkpoint.md` (D7). The
committed probes beside this file replay them. They qualify the terms-owned
publication, acceptance and display seams against injected mechanism ports: none is
hosted rate execution, and they stand in for permanent acceptance tests, which were
not added, by the owner's standing instruction. `tasks.md` records each task's validation and
the end-to-end suites that could not run. `dependency-contracts.md` records the price,
helper, servicing and timing inputs frozen for the rate and continuation changes.

## Design promotion record

Destinations are planned, not claims of implemented behavior.

| Accepted decision | Permanent location |
|---|---|
| D1, D2/D2a/D2b classes, monetary quote unit and acceptance pricing pin | `docs/development/ARCHITECTURE.md`; `openspec/specs/negotiation-protocol/spec.md` |
| D3 penalty preset default (24 periods) and buyer acceptance recommendations; D4 placement result | `openspec/specs/settlement-configuration/spec.md`; foundation-owned lifecycle contract |
| D5 the horizon as the Agreement's, listing bounds and omission | `openspec/specs/negotiation-protocol/spec.md`; `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/architecture.md`; `openspec/specs/resource-pool-management/spec.md` |
| D6 servicing doors | `openspec/specs/settlement-configuration/spec.md`; `openspec/specs/storefront-publication/architecture.md` |
| D7, D8 display and seller-policy distinction | `openspec/specs/buyer-orchestration/spec.md`; `openspec/specs/buyer-orchestration/architecture.md` |
| Goal/dependency currency | `docs/development/ROADMAP.md`; `openspec/changes/README.md` at integration/closeout |
