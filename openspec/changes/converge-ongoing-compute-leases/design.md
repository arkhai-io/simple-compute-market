# Design

## Context

The landed `deal-lifecycle` specification defines the post-commitment lifecycle:
final requests, end service, kept evidence, lifecycle commands, `watch` and its
cursors, cause classification with its pending slot, the seller's self-penalty
filing and the buyer's delivery end. The landed `compute-delivery` specification
defines the one delivery path both compute domains compose: activation before
billing start, end service's one billing-start intent and the classified
undelivered hand-off. The landed lane-double requirements in `test-compatibility`
supply the payments and mediation doubles, their typed controls and their
perceived clocks.

The archived `spot-deals-through-arkhai-payments` supplies the mechanics in both
compute domains: rate and setup mandate derivation with every `partialPeriod`
treatment and the dispute entry's `chosen` stop, one payments transaction adapter
with the rate `authorize` and start, verified rate observations, the seller's
notice through `deals preempt`, the buyer's canonical `end` and opt-in watchdog,
end service's refusal to commit a rate deal it cannot service (its D12–D14), and a
receipt key change as a drained cutover with no re-anchoring (its D17, D21). The
archived `negotiate-open-ended-compute-terms` supplies the terms, the servicing
declaration as a list of qualified treatments, the shipped presets — the buyer's
stop `charged`, a seller's preemption and the term end `returned` — and the default
buyer's refusals with a waiver each.

Goal 8's MVP changes land before this change. `serve-running-rate-deals` lifts
end service's refusal and composes rate servicing in both compute storefronts:
rate start through the shared delivery path, stop-cause classification, the
physical fact and the meaning of *ended*, one operator signal, startup coherence
and withdrawal, restart recovery with each domain's production-application
rebuild, a kit-owned per-deal step order both storefront cycles call with each
step's failure isolated (which also fixes bare metal's cycle, where a physical
failure skips its filing dispatch), loop registration through `kit/storefront`,
the keying of a refused rate deal's next commit, the buyer watchdog's
delivered-deal cases, and the baseline forms of rows 0, 6, 7 and 9 in both lanes.
`drive-the-storefront-clock-in-lanes` gives both storefronts a perceived clock the
lane moves with the doubles'.

This change is the rest of rate-part servicing inside end service: the work that
keeps a running rate deal's physical state, authority records and journaled
effects converged in both compute compositions when sellers fail, authorities are
down or evidence arrives late. It is not a second lifecycle. The storefront and
the site are one seller from the buyer's perspective, and the buyer's guarantees
rest on authority records and kept signed bytes, never on the seller's
cooperation.

## Goals and non-goals

Both compute compositions converge after commitment, report physical and financial
work separately, and recover durable effects across restart and authority outages.

No payment ledger, site renewal protocol, local payment-stop scheduler or minimum
spend is introduced, and no rotation work: a receipt key change is a drained
cutover (spot D17, D21). The archived spot change owns rate mechanics, mandates,
period arithmetic and partial-period terms; the archived terms change owns
publication and buyer acceptance policy, as landed in their specifications. Compute delivery owns the delivery
state machine. Activation owns hosted enablement of the full product.

## Decisions

### D1. Ownership and dependencies

`kit/deal-servicing` owns the storefront end-service loop, its observation state,
the evidence and effect journal, the domain-neutral physical ports, and the
consumption of the delivery authorization protocol. It imports no mechanism kit,
no dispute kit and no compute specialization. Each composition injects its
concrete payment and dispute adapters and its domain ports for lease admission,
activation and release.

This change depends on `serve-running-rate-deals`, which brings the MVP set;
the mechanics it needs are the archived spot change's and are landed. It owns the
rest of the rate qualification matrix, including the two rows that exercise the
delivery path under a rate hook (scenarios 4 and 8 below).

The seller-list requirement keeps the landed bounded page, continuation token,
identity, extension and state clauses and adds diagnostics. The settlement retry
requirement's lifecycle-journal allowance is `serve-running-rate-deals`'s; no
requirement is promoted twice.

### D2. Durable state, completion and diagnostics

Per deal, the kit persists the commitment and Agreement binding, the domain
operation and lease identity, the verified record cursors, the selected earliest
final request, the immutable operation descriptors, the completion history and, when the seller enables it (D3), the funding
observation and timer. Exact evidence bytes live in the foundation's evidence
store.

*Ended* has the meaning `serve-running-rate-deals` defines: physically
released, every part stopped or ended at the authority as verified, and no open
end-related case. This change refines the two facts under that meaning; it does
not change it.

**Physical completion** requires authenticated proof of capacity release — the
capacity-released callback, or a verified terminal lease or fulfillment release
read — or proof that nothing was dispatched, or a labelled, authenticated manual
acknowledgement. Unknown dispatch is adopted and ended first. A signed
`lease_ended` is end intent and attribution evidence, not proven teardown: an
initial report or a `release_failed` report leaves physical completion false. An
earlier end never resurrects a resource. The MVP records the release proof; this
change adds the manual acknowledgement.

**Financial completion** is revision-scoped: every required part has a verified
authority stop or end (payout is not required), every end-related case and ruling
effect is resolved, and no operation is pending or unknown. An unstarted rate part
needs a verified stop or end too; a once part uses its own term end or an earlier
authority stop. A dispute-window hold still running is not unfinished end work,
and filing acceptance alone does not complete anything. The end revision names the
selected earliest request and the relevant cases and ruling revisions; new earlier
evidence or a relevant case change reopens financial work without deleting
history. Once-only deals use the same facts. Watches and retention continue after
both facts are set.

The seller's lifecycle `read` and `list` expose both facts with their evidence
references, the end revision, the age of each gap, pending case and operation
references, repair reasons, and the principal, reason and operation of any manual
recovery. They also show pending self-penalty cases, billing that continues after
a delivery end (a buyer's stop not yet landed included, which the MVP shows as
*ending* with reason "rate still running"). A deal is *running* or *unstarted* until a final request is due, *ending*
while either fact is false, and *ended* when both are true. A permanent refusal or
a missing required credential or evidence shows *repair required* while both facts
are preserved. The buyer's read keeps its landed delivery and evidence projection
and shows none of the administrator diagnostics.

Manual recovery is the seller `submit` kind `acknowledge_physical_recovery`,
authorized to the storefront administrator only. Its payload binds the deal, the
resource or end revision and a reason, under a stable operation key; reuse of the
key with changed content is rejected. It is dispatched locally to end service, not
to either authority adapter; its `at` is the observed recovery instant, never
future; its accepted result names the immutable local audit record and the updated
physical fact, not an authority record; an unknown transport outcome resolves by
seller read and same-key retry. It records audited physical evidence only, never
money and never site-signed evidence.

Revision history is retained. The kit warns on a physical gap beyond the
configured watchdog-plus-teardown budget and on authority work beyond one retry
budget, and surfaces permanent refusals at once. Budgets derive from measured
domain latency. Warnings never stop servicing, never call a priced notice gap an
overcharge, and never claim that reserve-ahead caps buyer billing after an
unnoticed end.

> **Stale (spot D17, D21).** This decision also persisted rotation and
> re-anchoring status per deal, and listed running rate deals awaiting
> re-anchoring and once-only deals depending on a retiring key as "must drain".
> A receipt key change is now a drained cutover with no re-anchoring, and
> convergence takes on no rotation work; the operator finds open payment deals
> through the existing seller read and list (spot D20).

### D3. One kit loop with whole-page passes, and the opt-in funding timer

One end-service loop in `kit/deal-servicing` replaces the two storefront cycles,
registered through `kit/storefront`'s loop controller and built on the per-deal
step-order helper the MVP introduces. Its step runs the physical work for every
deal on the page, then bounded authority work with its own error handling, then a
second physical pass for ends that became due. Each composition supplies its own
recovery steps (site-report and respondent recovery) to the loop rather than
running a cycle of its own. Pausing pauses that loop; stepping runs all three
passes. An authority failure cannot prevent physical work, the second pass
included; a physical failure cannot prevent authority work. Cursor-after-journal
and same-key resolution of unknown outcomes are the foundation's rules.

The authority queue consumes verified records and drives journaled commands. An
entitled stop stays pending until its authority effective time; observing it does
not stop anything.

By default the authority's recorded stops — funding exhaustion, the term end, a
notice taking effect, the buyer's stop and the dispute authority's stop — are the
only end source for a running rate, as in the MVP. A seller may enable a funding
timer in its composition to limit its exposure while the payments service is
unreachable. With it enabled, a verified funded-through value is a replaceable
timer, never a speculative lease truncation, and funding can advance it. At expiry
the loop reads the payment authority before ending: a verified renewal replaces
the timer, and a verified exhaustion stop is an authority final request with no
classification. Only an unreachable or unverifiable authority produces a
bare-timer final request and the pending classification of D5. The read is
bounded, so an outage does not block physical work; a top-up within one polling
interval is not seller fault when the authority can verify it. Missing pre-start
funding is not exhaustion. No site deadline follows funding.

### D4. Adapter-based admission, and activation before billing

The landed `deal-lifecycle` and `compute-delivery` requirements already state the
protocol: the neutral kit asks the injected payment adapter for
`authorize(phase, evidence)` and `start_billing(operation_key, evidence)`, the
lease is activated before billing starts, end service alone journals the
billing-start key, and a refused or failed start enters the undelivered hand-off.
`serve-running-rate-deals` binds the rate adapter in both domains and lifts end
service's commit refusal. This change qualifies both domains under the rate hook
in rows 4 and 8.

> **Stale.** This decision bound the rate adapter in bare metal; with
> `serve-running-rate-deals` covering both compute domains, that binding is its
> (moved with tasks 1.3 and 3.1).

A healthy remote stop still has a polling, watchdog and teardown observation
window, not instantaneous revocation. Each party has one `notice_seconds` on its
stop entitlement. Measured servicing latency and reserve-ahead sizing are the
seller's capacity-risk choices, not codec gates and not buyer charges. With the
storefront absent, service may run to the maximum lease end; an activation
deadline protects the seller's capacity, not the buyer's money.

### D5. Classified ends, held money and revised remedies

The landed cause classification owns its timing and the end and filing journal;
this change adds one source, the opt-in funding timer. After the expiry read of D3
fails at *T*, the final request is recorded atomically with a pending filing
classification in the same journal. A later verified exhaustion stop at or before
*T* discharges it; billing that continued beyond *T* resolves it into the fixed
`delivery_end(cause=payee)` filing intent; inconclusive evidence leaves it
pending. The same atomic resolution covers earlier evidence that arrives after an
end. There is no synthetic final request and no second journal, and physical work
never waits for a classification.

The seller half files `delivery_end(cause=payee)` with the Agreement's dispute
authority through the dispute adapter, journaled with the end. It is never
future-dated: a pre-start failure journals immediately and files at the Agreement
start. The seller sends no stop or reverse of its own for a self-penalty.

Arkhai mediation's mechanical delivery-end rule is payee agreement under the
foundation's guards; its cause=payee branch is the standard self-penalty
(`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`).
Which claims rule mechanically, under which guards, and what each cause's ruling
does are the foundation's statements and are not restated here; this change
proves their consequences — a buyer-filed claim the payee signed, a receipt-backed
payer claim, a contested one left to a person, and the self-penalty's financial
effects — in rows 1, 5, 8, 10 and 12. The mediation double executes only a
ruling's `reverse` today, so this change adds execution of its `stop` and
`penalty` effects, proven by the double's suite, before those rows run. The
storefront ends delivery on a ruling's delivery end whatever its applied state,
so a row that holds a ruling at its gate steps no storefront servicing while the
ruling waits there.

A self-penalty is one package — stop, refunds and bond — and a partial direct path
would still need a dispute. Seller stop entries therefore exist only for
entitlements, such as spot's notice entry; a spot emergency files `delivery_end`,
not a notice-only fallback or an immediate seller stop. On-demand's promise not to
preempt is remedied by the premature-stop penalty and a buyer's case over held
money, not enforced by the mandate; the seller's own exit is the mechanically
ruled self-penalty.

Earlier evidence creates revision-bound dispute work; an append is not an
amendment. Unknown original filings and ruling effects are resolved before any
revised request is submitted. The dispute adapter's qualified revision mapping is
consumed as is: read the existing cases and prior ruling effects, use a supported
revision or linked-case path, and net prior authority-applied reversals and bond
awards without duplication. No local monetary delta and no seller payment
correction is introduced. If the adapter cannot demonstrate a safe revision
mapping, the deal shows repair required and its financial work stays unresolved.

Partial-period pricing, stop-entry notices and term-end treatment are payment
terms owned by spot and the terms change. Holds and case extensions are
authoritative only when verified at the payment authority. Both authorities down
leaves durable unresolved work, not a recovery deadline. A malicious seller may
bill until the buyer's stop, exhaustion or the maximum term; held earnings and
timely buyer action at the agreed dispute authority protect recovery.

### D6. Commands and recovery

The buyer flow is the foundation's and the MVP's; this change exercises it. The
buyer half stops at the payment authority first and sends a hint; with a nonzero
notice, service continues until `watch` observes the effective stop. If the
payment authority is unreachable, the buyer half journals its stop and retries it
under the same key, and billing runs until the stop lands. `end_delivery` is the
explicit end-now-regardless command: it carries no `at`, and the storefront signs
its own receipt time as evidence. The storefront has no authority to stop billing
for the buyer and journals no cooperative payment stop. The buyer's
`delivery_end(cause=payer)` case is the foundation's
(`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-buyers-end`);
this change proves it in row 1 and assumes no payee notice waiver and no payer
early release.

Operator recovery is stateless and runs through the injected adapters from a
caller-retained command file. A seller-authenticated, read-only export of the
foundation's evidence store supplies the exact Agreement, the commitment and
mandate, the authority bindings, the original filing identities, the signed
evidence and the known case and effect references; the seller lifecycle
contracts, client and CLI own the export, which carries no private keys, and it is
produced and retained outside the stopped storefront. Missing required bytes
refuse recovery rather than reconstructing an Agreement or allocating a
replacement key.

Before any I/O the runner durably writes an immutable operation envelope: the
key, the fixed kind, time and payload, the commitment and authority binding, the
principal and reason, the evidence digests and references, and the exact adapter
command and request descriptors. Replay reads first and retries identical
descriptors; it never issues `delivery_end(cause=payee)` or a new key. Results are
exported separately, so an interruption before the export is recoverable. For a
self-penalty the descriptors target the dispute adapter only; an entitled notice
targets the payment adapter only.

Before filing, the runner and online replay read the dispute record and adopt an
equivalent existing payee-filed case under the original semantic filing identity.
A preflight read alone cannot close a concurrent-writer race, so the adapter must
prove same-intent resolution and same-key retry, or refuse the filing with repair
required. On restart, `watch` discovers operator cases and ruling effects and
reconciles the journaled obligations. Manual physical acknowledgement goes only
through the online administrator `submit` of D2. No offline storefront writer and
no second payment implementation exists.

### D7. Restart, rotation and declarations

Restart recovers journaled effects and cursors, not historical approval or lease
status alone; each domain's production-application rebuild over the same database
is `serve-running-rate-deals`', and this change extends it to the journaled
filings, revisions and recovery envelopes it adds.

> **Stale (spot D17, D21).** The rest of this paragraph is withdrawn: a receipt
> key change is a drained cutover, nothing re-anchors a running deal, and
> convergence takes on no rotation work. Re-anchoring across a key change is an
> unowned gap in `docs/development/ROADMAP.md`'s Goal 8, with the design to resume
> from recorded in spot's D17. The withdrawn text: During a payments identity overlap the loop requests spot's fresh
> verified snapshot for each running rate deal, persists the exact re-anchoring
> evidence before dependence on the old key is retired, and reports unanchored deals
> as repair reasons before retirement; once-only deals are inventoried as "must
> drain". Spot owns the cryptographic and rotation policy, informed by the payments
> service's key-retention commitment; this change owns the durable consumption and
> the seller read and list status. Until it lands, the MVP's operating rule is to
> drain running deals before the signing key retires.

> **Stale.** Startup coherence and declaration withdrawal in both domains are now
> `serve-running-rate-deals`' (task 3.5 moved). The text it replaces: Startup
> coherence and declaration withdrawal in VM are the MVP's. This change gives bare
> metal the same: a storefront holding accepted rate deals with no rate
> adapter composed refuses to start, as incoherent state; a dependency outage alone
> is recoverable, never a refusal; withdrawing the declaration disables new deals
> only, and existing commitments keep their servicing and evidence. Per-period
> servicing is declared on in lanes and off elsewhere until a hosted switch-on
> qualifies it.

## Scenarios and evidence

This change owns the rest of the rate-servicing lane matrix. It executes spot's
prepared entry points — the maximum term and the on-demand and spot emergency
self-penalty filings included — and spot records preparation, not qualification.
Compute delivery owns once-only activation expiry; rows 4 and 8, which exercise
the delivery path under a rate hook, are this change's.

`serve-running-rate-deals` qualifies the baseline forms of rows 0, 6, 7 and 9
in both lanes, on the shipped presets with default buyers: the physical fact and
*ended*, and no funding timer. For those rows this change runs only the variants
the MVP leaves (the "Residual" column, both lanes; the MVP's design names exactly
which it runs, and this column follows it at this change's design review). Every
other row runs in both lanes.

| # | Scenario | Required observation | Residual |
|---|---|---|---|
| 0 | On-demand baseline | setup once + rate, provision/activate/start/disclose, priced payer stop + hint, both facts | a VM seller-enabled setup part unless the MVP runs it; the revision-scoped financial fact |
| 1 | Buyer end with payments down | pre/during/post dispatch, receipt-timed end_delivery evidence, buyer-half same-key stop retry with billing until it lands; receipt concurrence, unsigned-case triage and both-down replay | — |
| 2 | Site withdraws with storefront absent | buyer independent stop/case; late report, classified seller self-penalty filing; release proven separately | — |
| 3 | Interrupted authority effects | same case/effect-key resolution, partial reverse after stop; earlier evidence during partial correction or append/close race remains unresolved until verified revision effects | — |
| 4 | Stop between start and disclosure | activate/start/disclose races in both domains; no start before activation or duplicate start key across crashes; local admission blocks disclosure; measured remote observation windows | — |
| 5 | Rate deal activation deadline expires | no-dispatch proof or adoption/release; delivery_end at start, setup entirely returned | — |
| 6 | Funding exhaustion | verified exhaustion stop ends delivery at its effective time; with the seller's timer enabled, read before end — reachable renewal replaces the timer, verified exhaustion is an authority end, and only outage/unverifiable state ends on the bare timer, with a hidden top-up requiring a later self-penalty filing | the timer variants |
| 7 | Spot notice then earlier payer stop | authority hosts pending stop during absence; earliest wins, authority partial-period terms | the earlier payer stop |
| 8 | Activated but never disclosed | post-activation start refusal and started-but-undisclosed failure in both domains; no start before activation or duplicate start key across crashes; classified delivery_end filing at deal start, buyer-case backstop; the deadline variants, both orders: `start` not yet sent at the deadline, refused, no rate started; and `start` accepted by the authority before the deadline with `available` never recorded — seconds before, and thirty periods before with no setup and no penalty — the start standing as history, non-delivery established at the deadline, `delivery_end(cause=payee)` and the ruling returning every period the rate earned, the buyer's net charge zero | — |
| 9 | Maximum term | absolute authority end with its own partialPeriod, including late start and a mid-period end; physical recovery, no delivery_end | late start; mid-period end |
| 10 | Seller emergency | the on-demand notice refused at `deals preempt`, naming `delivery_end`, before the filing; on-demand and spot file delivery_end; mediation mechanically rules payee-agreed delivery_end with mapping/time/replay guards through its chosen entry; seller sends no stop/reverse; on-demand emergency pays premature_stop_penalty capped by earned amounts still held after refunds in mandate order, shown at both ends of the cap: late in a deal, the stated amount; minutes after activation with the started period returned, the setup charge alone, and zero with no setup charge; entitled spot notice pays none | — |
| 11 | Identity rotation overlap — **withdrawn** (spot D17, D21: a key change is a drained cutover; spot's running-storefront cutover proof is its own) | old receipt verified during overlap, current snapshot re-anchors the running rate deal before retirement, exact old bytes retained; once-only dependencies drain; revoked/stale anchors and livemode changes refused | — |
| 12 | Seller never files | an unentitled end the storefront never reports and never files; the buyer's own stop and a case filed from the exact accepted Agreement and kept evidence alone, with the storefront absent throughout, are the whole remedy; the ruling rests on the buyer's record | — |
| 12a | Late anchor | the storefront commits with a later, non-future anchor than the approval the payment authority recorded; the site enforces the longer physical deadline; the buyer's case from its kept approval record is ruled non-delivery at the accepted deadline regardless | — |
| 12b | Asserted availability | the storefront records `available` before the deadline with nothing reachable behind it; the buyer's case carries its own kept observation of failure; the seller's record is weighed as its assertion, not conclusive, and the ruling rests on the classes together | — |
| 13 | Case over paid-out money | a case filed after a part has paid out is accepted, reports `not_held` per part with the reason, may still end delivery, and moves no paid-out money; the buyer display shows per-part `held` / `not_held`, never a pending refund | — |

The nine diagram pairs under `diagrams/` illustrate cases 0–8; cases 9–13 extend
the matrix without duplicating diagrams. Row 12a needs the site's delivery
deadline from `renewable-compute-lease-deadlines`.

A lane interruption is a loop pause and resume, not evidence of process restart.
Durable restart is proved by production-application integration tests that
rebuild against the same database in both domains; the bare-metal lane keeps its
permanent no-restart contract. Lost-response replay in a lane proves cross-service
effect convergence only.

Each run is labelled under `test-compatibility`'s two labels: lane-double evidence
with each double's installed contract hashes, never live evidence; only a hosted
target yields live evidence. Rows 7 and 9 run on the shipped presets — a seller's
preemption and the term end `returned` — with default buyers; there are no interim
charged terms, since the vendored contract expresses `returned`. A `charged`
variant, where one is run, is a separate observation that waives each charged term
by name (`--allow-charged-preemption`, `--allow-charged-term-end`).

> **Stale (spot D17, D21).** This paragraph also said spot owns identity
> re-anchoring policy and evidence production and that row 11 qualifies its
> overlap and recovery in both lanes; row 11 is withdrawn.

Lane scenarios follow `docs/development/TESTING.md`'s discipline: a row waits
only for an effect its own request caused or for an instant the Agreement fixes,
and a behaviour defined by time elapsing is driven by moving every perceived clock
together through the lane's joint clock fixture — both doubles' and the
storefront's, both storefronts through `drive-the-storefront-clock-in-lanes` —
whose finaliser resets them
whatever the module's outcome. Library integration keeps deterministic injected
clocks for expiry and race permutations; lanes qualify the network transitions
only and never duplicate arithmetic coverage. Kits use the single clock-injected
payments authority engine in `kit/arkhai-payments`' fixtures directly; the HTTP
doubles wrap that engine with controls and the mediation composition. No kit
depends on runnable tooling.

## Rejected alternatives and accepted limitations

Rejected: a seller-advanced horizon or vouch; locally scheduled payment stops; a
required minimum spend; backdated stops; mandatory reverse-before-stop; a parallel
financial-end log; one completion fact; end intent as release proof; seller-direct
exceptional-end payment correction; a ruling SCM infers from silence or
manufactures; append as amendment; an offline second database writer; a funding
timer every storefront must run. None strengthens the buyer's authority-backed
guarantees.

Outside scope: periodic collection, pooled funding, liability ledgers, push
observation and lease top-up. Seller-side site renewal is optional capacity
policy.

Accepted: buyer recovery requires kept evidence and action within dispute
protection; no seller cooperation and no instant adjudication is promised. With
the funding timer disabled, a seller serves at its own risk while the payments
service is unreachable; the exhaustion stop's effective time, not the time the
storefront observes it, bounds what the buyer pays.

## Open questions

- **The site's clock.** Whether a row whose storefront step follows a clock
  advance also needs the site's perceived clock depends on whether the site judges
  a truncation instant or a lease end against its own wall clock; the answer
  `drive-the-storefront-clock-in-lanes`'s design records decides whether this
  change also takes the site's share of the lane-wide perceived clock.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D3, D7 composition ownership | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` |
| D2–D6 end-service contracts and guarantee limits | `openspec/specs/deal-lifecycle/spec.md` and `openspec/specs/deal-lifecycle/architecture.md` |
| D3 the opt-in funding timer setting | `openspec/specs/deal-lifecycle/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Scenario boundaries, lane time and the mediation double's ruling effects | `openspec/specs/test-compatibility/spec.md` |
| Diagram pairs | `docs/development/diagrams/` |

Tasks record the exact promotion destinations. No permanent document changes while
this remains design-stage work.

## Status

Reconciled onto the foundation on 2026-10-29 from the Goal 8 design groomed on
2026-10-28, which this change absorbs as rate servicing inside end service.

- External review F4 and F16: `kit/deal-servicing` ownership (D1) and the single
  three-pass loop (D3).
- External review F5: completion facts and diagnostics on the seller's read and list
  (D2).
- External review F2: the rate consumer's mapping onto the foundation's closed
  classification (D5).
- Reviews 03 F1 and 04 F6/F12: stateless operator recovery, the read-only evidence
  export, the immutable envelope, shared filing identities and dispute-record adoption
  (D6).
- Review Sol F3: lane pause/resume is not restart evidence; durable restart is
  integration-level (Scenarios and evidence).
- Goal 8 round-5 triage: rows 4 and 8 are this change's; the option's shape is
  `price`, `settlement` and `lifecycle` (foundation D5).
- Owner direction, 2026-10-29: the seller's exceptional end is a dispute filing with
  no seller stop or reverse; `delivery_end` is one claim for either filer, mechanical
  with payee agreement and guards, otherwise triaged; the storefront signs receipt
  evidence only.
- Goal 8 rescope, 2026-11-10: rescoped onto the MVP set. The funding timer returns
  as a seller opt-in (D3); the MVP's per-deal helper precedes the one kit loop
  (D3); *ended* keeps the MVP's meaning (D2); rotation overlap stays (D7); rows 7
  and 9 record the shipped buyer policy; the bare-metal storefront clock and the
  mediation double's `stop` and `penalty` effects are this change's; evidence is
  labelled lane-double or live; lane time follows `TESTING.md`. Reverified against
  the code the foundation, compute delivery and the lane doubles left.

- Goal 8 replan, 2026-11-16, after the terms and spot changes archived: the MVP
  servicing change, now `serve-running-rate-deals`, covers both compute domains,
  so bare metal's rate composition, rate start binding, stop-cause classification,
  startup coherence and withdrawal, restart rebuild and baseline lane rows moved
  there (tasks 1.3, 2.3's classifier, 3.1, 3.5), with the keying of a refused rate
  deal's next commit (spot D14) and the buyer watchdog's delivered-deal cases that
  the campaign index had assigned here; bare metal's storefront clock moved to
  `drive-the-storefront-clock-in-lanes` (task 4.1a). Rotation work is withdrawn
  (spot D17, D21): D2's re-anchoring status, D7's overlap paragraph, task 3.5's
  re-anchoring, the deal-lifecycle rotation requirement and row 11, each marked
  stale. Rows 7 and 9 run on the shipped `returned` presets with default buyers,
  a `charged` variant a separate waived observation; runs carry the two labels,
  lane-double evidence and live evidence; row 10 observes the on-demand notice
  refused naming `delivery_end`. Task 1.2 is answered from the archived spot
  change. The owner dispositions D1/E1, D2, D7, D8, D9, D11 and D12 recorded in the
  2026-11-10 rescope concern the terms and spot documents and are settled by what
  landed. Of those owner dispositions, D3 (opt-in timer), D4 (one kit loop after the MVP's helper), D6 (the
  MVP's meaning of *ended*) and D14's clock (now the clock change's) stand here.

Next: design review of the rescoped change, reverified against the code the
archived spot and terms changes left; its triage amends the drafted plan.
