# Design

## Context and authority

This is rate-part servicing inside the foundation's end service, not a second
lifecycle. `agreed-evidence-and-early-termination` owns final requests, evidence,
commands, watch/cursors, self-filing and buyer delivery ends. The protocol ends at
commitment; subsequent records are lifecycle and evidence. The storefront and site
are one seller from the buyer's perspective. Buyer guarantees rest on authority
records and kept signed bytes, never the seller's cooperation.

Current storefronts verify approval before delivery but do not continuously
converge rate funding, authority stops and physical effects. This design proposes
that integration; it makes no current-runtime or hosted-readiness claim.

## Goals and non-goals

Both compute compositions converge after commitment, report physical and financial
work separately, and recover durable effects across restart and authority outages.
No payment ledger, horizon/vouch, site renewal protocol, local payment-stop
scheduler or minimum spend is introduced. Spot owns rate mechanics, mandates,
period arithmetic, partial-period terms, publication and online notice commands.
Unify owns the one delivery state machine. Activation owns hosted enablement.

## Decisions

### D1. Ownership and section-level gates

**Recommendation supplied here (external F4):** `kit/deal-servicing` owns the storefront end-service loop, observation state,
evidence/journal, domain-neutral physical ports, and delivery authorization
protocol (phase and allow/refuse/pending decision with reason/evidence references).
It imports no mechanism kit, dispute kit or compute specialization. The compute
specialization imports this protocol; compositions inject concrete adapters and
domain lease/admission/activation/release ports.

Implementation gates are foundation lifecycle contracts and spot rate mechanics.
The dependency on `unify-compute-delivery-path` is **section-level**, not its archive:
unify tasks 1–3 supply the path, hook seam, activation and undelivered handoff;
converge tasks 1–3 supply the rate hook and servicing; unify's rate qualification
(task 4.4) and converge task 4 then use those implementations. Neither change waits
for the other's archive to implement its prerequisite section. Reverify shared
contracts at the delivered revisions before each handoff. Scenario execution also
requires the doubles' runnable payment/mediation sections, not their consumer
qualification or archive. Request these edges in the campaign index Notes rather
than keeping whole-change dependencies that form a cycle.

### D2. Durable state, completion and diagnostics

Persist commitment/Agreement binding, domain operation/lease identity, verified
record cursors, funding observation/timer, selected earliest final request,
immutable operation descriptors and completion history. Keep exact evidence bytes
in the foundation's evidence store. End-service behavior belongs to `deal-lifecycle`,
not a second contract in `settlement-servicing`.

Physical completion requires authenticated proof of capacity release (the existing
capacity-released callback or verified terminal lease/fulfillment release read),
proof of no dispatch, or a labelled authenticated manual acknowledgement. Unknown
dispatch is adopted and ended first. A signed `lease_ended` is end intent and
attribution evidence, not proven teardown: initial and `release_failed` reports
leave physical completion false. An earlier end never resurrects a resource.

Financial completion is revision-scoped: all required parts are terminal, all
end-related case effects/corrections are resolved, and no operation is pending or
unknown. Filing acceptance alone is insufficient. The end revision identifies the
selected earliest request and the set of relevant cases/ruling revisions; new
earlier evidence or relevant case changes reopen financial work without deleting
history. Once-only deals use the same facts and are financially complete when no
end-related authority work remains. Watches/retention continue after both facts.

**Recommendation supplied here (external F5):** extend seller lifecycle `read`/`list`: both facts and their evidence references,
end revision, gap ages, pending case/operation references, repair reasons, and
manual principal/reason/operation provenance. Running/unstarted remain until a
final request is due; ending means at least one completion fact is false; ended
requires both true. Permanent refusal or missing required evidence/credential
shows repair required while preserving both facts. Buyer reads retain their
foundation-owned delivery/evidence projection, not administrator-only diagnostics.

Manual recovery is seller `submit` kind `acknowledge_physical_recovery`, authorized
only to the storefront administrator. Its payload binds the deal, resource/end
revision and reason, with a stable operation key; changed key reuse is rejected.
It records audited physical evidence only, never money or site-signed evidence.

**Recommendations supplied here:** retain revision history; warn on a physical
gap beyond the configured watchdog-plus-teardown budget, and on authority work
beyond one retry budget, surfacing permanent refusals immediately. Budgets derive
from measured domain latency. Warnings never stop servicing or call a priced
notice gap an overcharge. Seller diagnostics never claim reserve-ahead caps buyer
billing after an unnoticed end.

### D3. Two queues, one registered step

**Recommendation supplied here (external F16):** register one end-service loop with the storefront loop controller. One step runs
physical work, bounded authority work with independent error handling, then a
second physical pass for newly due ends. Pausing pauses that loop; stepping runs
all three passes. Authority failures cannot prevent physical work, including the
second pass; physical failure cannot prevent authority work. Reuse the foundation's
cursor-after-journal and same-key unknown-outcome recovery rather than respecify it.

The authority queue consumes verified records, refreshes funding timers and drives
journaled commands. An entitled stop remains pending until its authority effective
time; it is not an immediate stop on observation. A verified funded-through value
is a replaceable timer, never a speculative lease truncation. Funding can advance
it; expiry creates a final request and the pending classification obligation in
D5. Missing pre-start funding is not exhaustion. No site deadline follows funding.

### D4. Adapter-based admission and activation before billing

**Recommendation supplied here (external F4):** the neutral kit asks the injected payment adapter for a deal-level
`authorize(phase, evidence)` decision, never interprets hosted per-part snapshot
fields. The foundation payment protocol owns that operation and
`start_billing(activated_delivery_evidence)`; spot implements rate checks and
once-only adapters return allow/no-op. Publication/acceptance must fail closed if
the installed adapter cannot supply the required contract.

Authorization before commit/dispatch/disclosure checks verified authority evidence,
reservation and effective/pending stops through that adapter. Provision and activate
the lease to the Agreement's end **before** issuing rate start as an effect, not an
authorization step. End service alone journals the immutable billing-start key and
activated-delivery evidence before I/O; unify's delivery checkpoint stores a
reference, not a second start intent. Resolve unknown start by read/same-key retry
before disclosure. Start refusal uses unify's undelivered handoff at deal start.

Unify/foundation own local dispatch/disclosure serialization and physical revocation.
This hook consumes those guarantees rather than repeating them. A healthy remote
stop still has a polling/watchdog/teardown observation window, not instantaneous
revocation. `exposure_seconds` and `stop+exposure` are retired: each party has one
`notice_seconds` on its stop entitlement. Measured servicing latency and
reserve-ahead sizing are seller capacity-risk recommendations, not codec gates or
extra buyer charges. With storefront absent, service may run to the maximum lease
end; an optional activation deadline protects seller capacity, not buyer money.

### D5. Classified ends, held money and revised remedies

Keep earnings under the agreed afterStop hold and accepted case extensions. Only
verified payment records establish protection, not filing acceptance. Stops are
never backdated. **Recommendation supplied here (external F2):** consume a closed source-classified
self-filing contract, to be reconciled in the foundation owner requirement:

| Final-request cause | Seller action |
|---|---|
| Verified authority stop (including exhaustion, maximum term, entitled notice), ruling, or buyer end_delivery | No exceptional_end for that request |
| Unentitled site withdrawal, failed/never-started delivery, operator emergency without entitlement | Journal exceptional_end with final request; undelivered uses deal start |
| Funding-timer expiry without current authority evidence | Journal pending classification with the end; read before deciding |

A site report caused by an already requested entitled/buyer end is correlated to
that request, not treated as a new seller fault. For timer expiry at T, a verified
exhaustion stop at/before T discharges the classification without filing. If billing
continued past T (for example a top-up hidden by outage), journal exceptional_end(T)
under a stable key. If the record cannot decide, keep the obligation unresolved
and financial completion false. Physical work never waits for that read. An
operator with payee entitlement submits authority notice, not exceptional_end;
without entitlement it uses the self-penalty path.

An evidence append does not amend an intent or promise re-ruling. Earlier evidence
can be appended for retention, but neither acknowledgement nor skipped-closed
append satisfies a revised remedy. Resolve unknown original effects first. Unless
a verified authority contract explicitly supports amendment/re-ruling covering the
new revision, file a new revision-bound exceptional_end with prior case/effect
records and earlier signed evidence, regardless of whether the old case is open.
Track both cases; unresolved prior effects and append/close races cannot disappear
from completion. The authority determines and nets further effects against prior
returns and bond awards. Contract/vector reverification must establish that
repeated filings do not double-apply a whole-deal penalty; otherwise expose repair
required, not a locally computed ruling or a fabricated completion.

**Recommendation supplied here:** retain authority adjudication for revised ends,
not voluntary cumulative-target end refunds. Partial-period treatment is a payment
term per stopper: SCM started_period ↔ charged, last_boundary ↔ returned, stop ↔
prorated. The payments service computes it, with no storefront corrective reverse.
SCM presets prefer payer charged/payee returned; until expressible by the vendored
contract only charged/charged spot terms ship, and unsupported terms fail closed.
Exhaustion and part end are charged; spot owns whole-period maximum-term rounding.
Setup once ends at activation, pays one dispute window later, and self-penalty
returns all when undelivered and none once delivered. These are adapter/authority
contracts consumed here, not local financial arithmetic.

The honest residual is not reserve-ahead after an unnoticed end. A malicious seller
may bill until buyer stop takes effect, exhaustion or maximum term. Held earnings
and timely buyer action at the agreed dispute authority protect recovery. Both
authorities down leaves durable unresolved work, not a promised recovery deadline.
Promote these limits to the deal-lifecycle architecture; buyer disclosure is terms-owned.

### D6. Commands and recovery

Exercise the foundation/spot buyer flow, do not reimplement it. With nonzero payer
notice the buyer stops at the payment authority and sends a hint; service continues
until watch observes the effective stop. `end_delivery` is explicit end-now-regardless
and the unreachable-payment-authority path with buyer_end(at) evidence. Keep exact
site reports and signed acknowledgements through foundation ingestion/read.

**Recommendation supplied here:** replace the nonexistent offline database-writer
composition with stateless operator authority commands. Domain CLI compositions
inject payment/dispute adapters into a kit/deal-servicing recovery command runner.
It takes a kept commitment/case bundle, the seller credentials bound to its original
authorities, a caller-retained operation key, administrator identity and reason.
It submits entitled notice or exceptional_end directly, prints/exports exact signed
results, and uses authority read/same-key retry after unknown outcome. It does not
open/write storefront persistence. On restart ordinary watch observes seller stops
and cases and journals their effects. Manual physical acknowledgement alone goes
through the online administrator-authenticated seller submit described in D2.
No separate payment implementation or competing database writer is built.

### D7. Restart, declarations and activation

Restart recovers journaled effects/cursors and spot's identity re-anchoring, not
historical approval or lease status alone. Publication, acceptance and materialization
require servicing declarations. Startup with accepted rate deals but no loop is
refused as incoherent; dependency outages alone are recoverable, not refusal.
Withdrawal disables new deals only. Existing commitments keep servicing/evidence.
Proposed-contract servicing is lane-only. Production activation verifies the hosted
per-part/notice/hold revision and support for the stop terms actually offered
through its own deployment gate; a permitted charged/charged subset need not wait
for returned/prorated support.

## Scenarios and evidence

This change is the single owner of the rate-servicing lane matrix. Execute spot's
prepared entry points, including maximum term and on-demand payee-stop refusal
followed by exceptional_end; spot records preparation, not duplicate qualification.
Unify owns once-only activation expiry and the path seam; its consumer-dependent
rate qualification uses this matrix after the section handoff in D1.

| # | Scenario | Required observation |
|---|---|---|
| 0 | On-demand baseline | setup once + rate, provision/activate/start/disclose, priced payer stop + hint, both facts |
| 1 | Buyer end with payments down | pre/during/post dispatch, end_delivery acknowledgement, buyer_end; both-down replay |
| 2 | Site withdraws with storefront absent | buyer independent stop/case; late report, classified seller filing; release proven separately |
| 3 | Interrupted case effects | same case/key resolution, partial reverse after stop; earlier evidence during partial application or append/close race leads to revision filing |
| 4 | Stop between start and disclosure | local admission blocks disclosure; measured remote observation windows |
| 5 | Rate deal activation deadline expires | no-dispatch proof or adoption/release; exceptional_end at start, setup entirely returned |
| 6 | Funds exhausted / timer expiry during outage | renewable timer; exhaustion no filing; hidden top-up leads to self-filing after verified read |
| 7 | Spot notice then earlier payer stop | authority hosts pending stop during absence; earliest wins, authority partial-period terms |
| 8 | Activated and started but never disclosed | disclosure fails, self-filing at deal start, buyer-case backstop |
| 9 | Maximum term | authority end at whole-period bound; physical recovery, no exceptional_end |
| 10 | On-demand seller emergency | payee stop refused, exceptional_end accepted; no invented entitlement |

The nine diagram pairs illustrate cases 0–8; cases 9–10 extend the qualification
matrix without duplicating diagrams. **Recommendation supplied here (Sol F3):**
lane interruptions are loop pause/resume, not process restart evidence. Durable restart proof belongs to production-application
integration tests rebuilding against the same database in both domains; retain the
permanent bare-metal lane no-restart contract. Lost-response replay in lanes proves
cross-service effect convergence only.

**Recommendation supplied here:** cross-service lane scenarios use real UTC time,
short fixture periods/deadlines and bounded readiness/event waits through existing
controls. Doubles run wall-clock mode here; do not jump their injected clocks ahead
of storefront/site time. Fixture validation bounds clock skew and wait budgets and
fails setup if clocks disagree. No site clock-injection surface is added. Library
integration keeps deterministic injected clocks for expiry/race permutations; lanes
only qualify the network transitions, never duplicate arithmetic coverage. Kits use
contract-vector in-process fakes, not runnable tooling dependencies.

## Rejected alternatives and accepted limitations

Reject seller horizon/vouch, locally scheduled payment stops, required minimum
spend, backdated stops, mandatory reverse-before-stop, a parallel financial-end log,
one completion fact, end-intent as release proof, append-as-amendment, and an offline
second database writer. None strengthens buyer authority-backed guarantees.
Periodic collection, pooled funding, liability ledgers, push observation and lease
top-up are outside scope. Seller site renewal is optional capacity policy. Buyer
recovery requires kept evidence and action within dispute protection; no seller
cooperation or instant adjudication is promised.

## Permanent documentation destinations

D1/D3/D7 composition ownership goes to market-composition and repository ARCHITECTURE.
D2–D6 end-service contracts and guarantee limits go to deal-lifecycle spec/architecture.
The adapter-mediated journal exception to retryable settlement goes to
settlement-servicing; adapter decisions remain mechanism-owned continuation.
Scenario boundaries go to test-compatibility; diagram pairs to
`docs/development/diagrams/`. Tasks record exact promotion destinations. No permanent
document is changed while this remains design-stage work.
