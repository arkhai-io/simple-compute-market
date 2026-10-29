# Design

## Context

`agreed-evidence-and-early-termination` defines the post-commitment lifecycle: final
requests, end service, kept evidence, lifecycle commands, `watch` and its cursors, the
seller's self-penalty filing and the buyer's delivery end. `spot-deals-through-arkhai-payments`
defines rate parts: the mandate, period arithmetic, partial-period terms, publication
and the seller's notice command. `unify-compute-delivery-path` defines the one delivery
state machine both compute domains compose. This change is rate-part servicing inside
end service: the storefront work that keeps a running rate deal's physical state,
authority records and journaled effects converged after commitment, in both compute
compositions. It is not a second lifecycle.

Today a storefront verifies approval before delivery and then stops watching: nothing
converges rate funding, authority stops and physical effects while a deal runs. The
protocol ends at commitment; everything after is lifecycle and evidence. The storefront
and the site are one seller from the buyer's perspective, and the buyer's guarantees
rest on authority records and kept signed bytes, never on the seller's cooperation.

## Goals and non-goals

Both compute compositions converge after commitment, report physical and financial
work separately, and recover durable effects across restart and authority outages.

No payment ledger, site renewal protocol, local payment-stop scheduler or minimum
spend is introduced. Spot owns rate mechanics, mandates, period arithmetic,
partial-period terms, publication and the online notice command. Unify owns the
delivery state machine. Activation owns hosted enablement.

## Decisions

### D1. Ownership and dependencies

`kit/deal-servicing` owns the storefront end-service loop, its observation state, the
evidence and effect journal, the domain-neutral physical ports, and the consumption of
the foundation's delivery authorization protocol — its phases and decisions. It
imports no mechanism kit, no dispute kit and no compute specialization. The compute
specialization imports the protocol; each composition injects its concrete payment
and dispute adapters and its domain ports for lease admission, activation and release.

This change depends on three changes as wholes. The foundation supplies the lifecycle
contracts. Spot supplies the rate mechanics: the hosted adapter's `authorize` and
`start_billing`, the partial-period mapping, the holds and rotation re-anchoring.
`unify-compute-delivery-path` lands first and supplies the delivery path, the hook
seam, lease activation and the undelivered handoff; this change implements the rate
hook and servicing against that path and owns the whole rate qualification matrix,
including the two rows that exercise the delivery path under a rate hook (scenarios 4
and 8 below). Scenario execution also needs the runnable payment and mediation
doubles from `add-arkhai-payments-lane-double`.

Where this change and the foundation modify the same requirement, the foundation
archives first. The seller-list requirement keeps the foundation's bounded page,
continuation token, identity, extension and state clauses and adds diagnostics. The
settlement retry requirement keeps idempotent completion, re-drive and retrieve
semantics and adds only the neutral lifecycle-journal allowance. Spot does not replace
either requirement, and no foundation requirement is promoted twice.

### D2. Durable state, completion and diagnostics

Per deal, the kit persists the commitment and Agreement binding, the domain operation
and lease identity, the verified record cursors, the funding observation and timer,
the selected earliest final request, the immutable operation descriptors, rotation and
re-anchoring status, and the completion history. Exact evidence bytes live in the
foundation's evidence store. End-service behaviour is specified in `deal-lifecycle`,
not as a second contract in `settlement-servicing`.

**Physical completion** requires authenticated proof of capacity release — the
capacity-released callback, or a verified terminal lease or fulfillment release read —
or proof that nothing was dispatched, or a labelled, authenticated manual
acknowledgement. Unknown dispatch is adopted and ended first. A signed `lease_ended`
is end intent and attribution evidence, not proven teardown: an initial report or a
`release_failed` report leaves physical completion false. An earlier end never
resurrects a resource.

**Financial completion** is revision-scoped: every required part has a verified
authority stop or end (payout is not required), every end-related case and ruling
effect is resolved, and no operation is pending or unknown. An unstarted rate part
needs a verified stop or end too; a once part uses its own term end or an earlier
authority stop. A dispute-window hold still running is not unfinished end work, and
filing acceptance alone does not complete anything. The end revision names the
selected earliest request and the relevant cases and ruling revisions; new earlier
evidence or a relevant case change reopens financial work without deleting history.
Once-only deals use the same facts and are financially complete when no end-related
authority work remains. Watches and retention continue after both facts are set.

The seller's lifecycle `read` and `list` expose both facts with their evidence
references, the end revision, the age of each gap, pending case and operation
references, repair reasons, and the principal, reason and operation of any manual
recovery. They also show pending self-penalty cases, billing that continues after a
delivery end (a buyer's stop not yet landed included), running rate deals awaiting
re-anchoring, and once-only deals that depend on a retiring key, labelled "must
drain". A deal is *running* or *unstarted* until a final request is due, *ending*
while either completion fact is false, and *ended* when both are true. A permanent
refusal or a missing required credential or evidence shows *repair required* while
both facts are preserved. The buyer's read keeps its foundation-owned delivery and
evidence projection and shows none of the administrator diagnostics.

Manual recovery is the seller `submit` kind `acknowledge_physical_recovery`,
authorized to the storefront administrator only. Its payload binds the deal, the
resource or end revision and a reason, under a stable operation key; reuse of the key
with changed content is rejected. It is dispatched locally to end service, not to
either authority adapter; its `at` is the observed recovery instant, never future;
its accepted result names the immutable local audit record and the updated physical
fact, not an authority record; an unknown transport outcome resolves by seller read
and same-key retry. It records audited physical evidence only, never money and never
site-signed evidence. The contracts and typed client expose this local result beside
authority-command outcomes.

Revision history is retained. The kit warns on a physical gap beyond the configured
watchdog-plus-teardown budget and on authority work beyond one retry budget, and
surfaces permanent refusals at once. Budgets derive from measured domain latency.
Warnings never stop servicing, never call a priced notice gap an overcharge, and
never claim that reserve-ahead caps buyer billing after an unnoticed end.

### D3. Two queues, one registered step

One end-service loop is registered with the storefront loop controller. Its step runs
the physical work, then bounded authority work with its own error handling, then a
second physical pass for ends that became due. Pausing pauses that loop; stepping runs
all three passes. An authority failure cannot prevent physical work, the second pass
included; a physical failure cannot prevent authority work. Cursor-after-journal and
same-key resolution of unknown outcomes are the foundation's rules, reused here.

The authority queue consumes verified records, refreshes funding timers and drives
journaled commands. An entitled stop stays pending until its authority effective time;
observing it does not stop anything. A verified funded-through value is a replaceable
timer, never a speculative lease truncation, and funding can advance it. At expiry the
loop reads the payment authority before ending: a verified renewal replaces the timer,
and a verified exhaustion stop is an authority final request with no classification.
Only an unreachable or unverifiable authority produces a bare-timer final request and
the pending classification of D5. The read is bounded, so an outage does not block
physical work; a top-up within one polling interval is not seller fault when the
authority can verify it. Missing pre-start funding is not exhaustion. No site deadline
follows funding.

### D4. Adapter-based admission, and activation before billing

The neutral kit asks the injected payment adapter for a deal-level
`authorize(phase, evidence)` decision and never interprets hosted per-part snapshot
fields. The foundation's payment protocol owns that operation and
`start_billing(operation_key, activated_delivery_evidence)`; spot implements the rate
checks, and a once-only adapter returns allow and a no-op. Publication and acceptance
fail closed when the installed adapter cannot supply the required contract.

Authorization before commit, dispatch and disclosure checks verified authority
evidence, the reservation and any effective or pending stop through that adapter. The
lease is provisioned and activated — to the Agreement's end, or to a verified earlier
end recorded by end service — *before* the rate `start` is issued, and `start` is an
effect, not an authorization step. A future entitled stop preserves service until its
earlier end; an unexplained mismatch or a failed activation suppresses `start`. A lost
activation acknowledgement is resolved by re-reading and re-admitting, so a truncation
between activation and the retry is preserved. End service alone journals the
immutable billing-start key and the activated-delivery evidence before any I/O;
unify's delivery checkpoint stores a reference to that journal, not a second start
intent. An unknown `start` is resolved by read and same-key retry before disclosure. A
start refusal supplies classified undelivered evidence through unify to the
foundation's timing policy; the rate hook does not choose the correction instant.

Unify and the foundation own local dispatch and disclosure serialization and physical
revocation; the rate hook consumes those guarantees. A healthy remote stop still has a
polling, watchdog and teardown observation window, not instantaneous revocation. Each
party has one `notice_seconds` on its stop entitlement. Measured servicing latency and
reserve-ahead sizing are the seller's capacity-risk choices, not codec gates and not
buyer charges. With the storefront absent, service may run to the maximum lease end;
an activation deadline protects the seller's capacity, not the buyer's money.

### D5. Classified ends, held money and revised remedies

The foundation's D8 owns the closed cause classification, its timing, and the end and
filing journal; this change adds one source, the funding timer. After the expiry read
of D3 fails at *T*, the final request is recorded atomically with a pending filing
classification in the same journal. A later verified exhaustion stop at or before *T*
discharges it; billing that continued beyond *T* resolves it into the fixed
`exceptional_end(T)` filing intent; inconclusive evidence leaves it pending. The same
atomic resolution covers earlier evidence that arrives after an end. There is no
synthetic final request and no second journal, and physical work never waits for a
classification.

The seller half files `exceptional_end(at)` with the Agreement's dispute authority
through the dispute adapter, journaled with the end. It is never future-dated: a
pre-start failure journals immediately and files at the Agreement start. The seller
sends no stop or reverse of its own for a self-penalty. The dispute adapter maps the
intent to its interface's request; the foundation supplies `exceptional_end` among its
intents together with mediation's request vocabulary and published mapping.

Arkhai mediation's only mechanical ruling is a payee-filed self-penalty request at
least as strong as the standard request. Through its own stop entry,
`{account, notice: PT0S, partialPeriod: "chosen"}`, the standard request stops rate
parts now with returned treatment, reverses rate earnings since `at`, reverses each
once part's unserved share by time, and then reverses
`min(premature_stop_penalty, earned amounts still held)` to the payer across parts in
mandate order. Bond award stays reserved for hosted bonds. An entitled notice pays no
penalty; a spot emergency pays it. A person applies the same capped remedy to a buyer's
case alleging an unentitled seller end. On-demand always returns the partial period —
that is its contract. Setup is returned in full when the seller never delivers and
not at all once it has; a buyer's stop before activation leaves it with the seller. Every other request, `buyer_end` included, goes
to human triage. The authority never reconciles direct seller restitution, because
there is none.

A self-penalty is one package — stop, refunds and bond — and a partial direct path
would still need a dispute. The authority records disputes so it can act on bad
sellers, banning included. Seller stop entries therefore exist only for entitlements,
such as spot's notice entry; a spot emergency files `exceptional_end`, not a
notice-only fallback or an immediate seller stop. On-demand's promise not to preempt
is remedied by the premature-stop penalty and a buyer's case over held money, not
enforced by the mandate; the seller's own exit is the mechanically ruled self-penalty.

Earlier evidence creates revision-bound dispute work; an append is not an amendment.
Unknown original filings and ruling effects are resolved before any revised request is
submitted. The dispute adapter's qualified revision mapping is consumed as is: read
the existing cases and prior ruling effects, use a supported revision or linked-case
path, and net prior authority-applied reversals and bond awards without duplication.
No local monetary delta and no seller payment correction is introduced. If the adapter
cannot demonstrate a safe revision mapping, the deal shows repair required and its
financial work stays unresolved. The foundation owns this contract, mediation owns the
ruling mapping, and this change qualifies their composition.

Partial-period pricing, stop-entry notices and term-end treatment are payment terms
owned by the foundation and spot. Holds and case extensions are authoritative only
when verified at the payment authority. Both authorities down leaves durable
unresolved work, not a recovery deadline. A malicious seller may bill until the buyer's
stop, exhaustion or the maximum term; held earnings and timely buyer action at the
agreed dispute authority protect recovery. These limits are promoted to the
deal-lifecycle architecture companion.

### D6. Commands and recovery

The buyer flow is the foundation's and spot's; this change exercises it. The buyer
half stops at the payment authority first and sends a hint; with a nonzero notice,
service continues until `watch` observes the effective stop. If the payment authority
is unreachable, the buyer half journals its stop and retries it under the same key,
and billing runs until the stop lands. `end_delivery` is the explicit end-now-regardless
command: it carries no `at`, and the storefront signs its own receipt time as evidence.
The storefront has no authority to stop billing for the buyer and journals no
cooperative payment stop. The exact signed request, receipt and site reports are kept
through the foundation's ingestion and read. The buyer may additionally file
`buyer_end(at)` with that evidence; it is human-triaged and realized as the payer's own
stop at `at` with the payer's notice and treatment, never ruled mechanically. The case
carries the exact Agreement, verified against the mandate's deal hash, and needs no
payment attachment. No payee notice waiver and no payer early release is assumed.

Operator recovery is stateless and runs through the injected adapters from a
caller-retained command file. A seller-authenticated, read-only export of the
foundation's evidence store supplies the exact Agreement, the commitment and mandate,
the authority bindings, the original filing identities, the signed evidence and the
known case and effect references; the seller lifecycle contracts, client and CLI own
the export, which carries no private keys, and it is produced and retained outside the
stopped storefront. Missing required bytes refuse recovery rather than reconstructing
an Agreement or allocating a replacement key.

Before any I/O the runner durably writes an immutable operation envelope: the key, the
fixed kind, time and payload, the commitment and authority binding, the principal and
reason, the evidence digests and references, and the exact adapter command and request
descriptors. Replay reads first and retries identical descriptors; it never issues
`exceptional_end(now)` or a new key. Results are exported separately, so an
interruption before the export is recoverable. For a self-penalty the descriptors
target the dispute adapter only; an entitled notice targets the payment adapter only.

Before filing, the runner and online replay read the dispute record and adopt an
equivalent existing payee-filed case under the original semantic filing identity,
which binds the commitment, the Agreement's dispute authority, the cause and end
revision and the fixed request; distinct caller keys never create duplicate cases for
one intent. A preflight read alone cannot close a concurrent-writer race, so the
adapter must prove same-intent resolution and same-key retry, or refuse the filing with
repair required. A different or earlier basis uses D5's revision mapping. On restart,
`watch` discovers operator cases and ruling effects and reconciles the journaled
obligations. Because the seller never applies partial restitution before filing, no
seller stop or reverse needs reconciling. Manual physical acknowledgement goes only
through the online administrator `submit` of D2. No offline storefront writer and no
second payment implementation exists.

### D7. Restart, declarations and activation

Restart recovers journaled effects and cursors, not historical approval or lease
status alone. During an identity overlap the loop requests spot's fresh verified
snapshot for each running rate deal, persists the exact re-anchoring evidence before
dependence on the old key is retired, and reports unanchored deals as repair reasons
before retirement; once-only deals are inventoried as "must drain". Spot owns the
cryptographic and rotation policy; this change owns the durable consumption and the
seller read and list status.

Publication, acceptance and materialization require the servicing declaration. A
storefront that starts holding accepted rate deals with no loop composed refuses to
start, as incoherent state; a dependency outage alone is recoverable, never a refusal.
Withdrawing the declaration disables new deals only, and existing commitments keep
their servicing and evidence. Servicing against the proposed contract is lane-only.
Production activation verifies the hosted per-part, notice and hold revision and
support for the stop terms actually offered through its own deployment gate; a
permitted charged/charged subset need not wait for returned or prorated support.

## Scenarios and evidence

This change owns the rate-servicing lane matrix. It executes spot's prepared entry
points — the maximum term and the on-demand and spot emergency self-penalty filings
included — and spot records preparation, not qualification. Unify owns once-only
activation expiry and the delivery-path seam; rows 4 and 8, which exercise that path
under a rate hook, are this change's.

| # | Scenario | Required observation |
|---|---|---|
| 0 | On-demand baseline | setup once + rate, provision/activate/start/disclose, priced payer stop + hint, both facts |
| 1 | Buyer end with payments down | pre/during/post dispatch, receipt-timed end_delivery evidence, buyer-half same-key stop retry with billing until it lands; buyer_end triage and both-down replay |
| 2 | Site withdraws with storefront absent | buyer independent stop/case; late report, classified seller self-penalty filing; release proven separately |
| 3 | Interrupted authority effects | same case/effect-key resolution, partial reverse after stop; earlier evidence during partial correction or append/close race remains unresolved until verified revision effects |
| 4 | Stop between start and disclosure | activate/start/disclose races in both domains; no start before activation or duplicate start key across crashes; local admission blocks disclosure; measured remote observation windows |
| 5 | Rate deal activation deadline expires | no-dispatch proof or adoption/release; exceptional_end at start, setup entirely returned |
| 6 | Funding expiry and last-poll top-up | read before end; reachable renewal replaces timer and verified exhaustion is an authority end; only outage/unverifiable state ends on bare timer, with hidden top-up requiring later self-penalty filing |
| 7 | Spot notice then earlier payer stop | authority hosts pending stop during absence; earliest wins, authority partial-period terms |
| 8 | Activated but never disclosed | post-activation start refusal and started-but-undisclosed failure in both domains; no start before activation or duplicate start key across crashes; classified exceptional_end filing at deal start, buyer-case backstop |
| 9 | Maximum term | absolute authority end with its own partialPeriod, including late start and a mid-period end; physical recovery, no exceptional_end |
| 10 | Seller emergency | on-demand and spot file exceptional_end; mediation mechanically rules only qualifying payee self-penalty through its chosen entry; seller sends no stop/reverse; on-demand emergency pays premature_stop_penalty capped by earned amounts still held after refunds in mandate order, shown at both ends of the cap: late in a deal, the stated amount; minutes after activation with the started period returned, the setup charge alone, and zero with no setup charge; entitled spot notice pays none |
| 11 | Identity rotation overlap | old receipt verified during overlap, current snapshot re-anchors the running rate deal before retirement, exact old bytes retained; once-only dependencies drain; revoked/stale anchors and livemode changes refused |
| 12 | Seller never files | an unentitled end the storefront never reports and never files; the buyer's own stop and a case filed from the exact accepted Agreement and kept evidence alone, with the storefront absent throughout, are the whole remedy; the ruling rests on the buyer's record |
| 13 | Case over paid-out money | a case filed after a part has paid out is accepted, reports `not_held` per part with the reason, may still end delivery, and moves no paid-out money; the buyer display shows per-part `held` / `not_held`, never a pending refund |

The nine diagram pairs under `diagrams/` illustrate cases 0–8; cases 9–13 extend the
matrix without duplicating diagrams.

A lane interruption is a loop pause and resume, not evidence of process restart.
Durable restart is proved by production-application integration tests that rebuild
against the same database in both domains; the bare-metal lane keeps its permanent
no-restart contract. Lost-response replay in a lane proves cross-service effect
convergence only.

Each run is recorded under the lane double's evidence classes by name —
*Qualification against the published contract*, *Qualification against a proposed
contract*, and *Live evidence* — whose definitions are that change's D6. Rows 7 and 9
record the buyer's explicit non-default `started_period` acceptance for interim
charged terms; default-policy refusal and returned-capable acceptance are observed
separately once the returned-capable revision is vendored. Spot owns identity
re-anchoring policy and evidence production; row 11 qualifies its overlap and recovery
behaviour in both lanes.

Cross-service lane scenarios use real UTC time, short fixture periods and deadlines,
and bounded readiness and event waits through the existing controls. They consume the
tooling's typed due-work barriers, with per-authority watermarks, pending effects and
blocked dependencies; future work stays pending and a blocked effect never counts as
completion. The doubles run in wall-clock mode and their injected clocks are never
jumped ahead of storefront or site time; fixture validation bounds clock skew and wait
budgets and fails setup when clocks disagree; no site clock-injection surface is added.
Library integration keeps deterministic injected clocks for expiry and race
permutations; lanes qualify the network transitions only and never duplicate
arithmetic coverage. Kits use the single clock-injected payments authority engine in
`kit/arkhai-payments`' fixtures directly; the HTTP doubles wrap that engine with
controls and the mediation composition. No kit depends on runnable tooling.

## Rejected alternatives and accepted limitations

Rejected: a seller-advanced horizon or vouch; locally scheduled payment stops; a
required minimum spend; backdated stops; mandatory reverse-before-stop; a parallel
financial-end log; one completion fact; end intent as release proof; seller-direct
exceptional-end payment correction; mechanical `buyer_end` rulings; append as
amendment; an offline second database writer. None strengthens the buyer's
authority-backed guarantees.

Outside scope: periodic collection, pooled funding, liability ledgers, push
observation and lease top-up. Seller-side site renewal is optional capacity policy.

Accepted: buyer recovery requires kept evidence and action within dispute protection;
no seller cooperation and no instant adjudication is promised.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D3, D7 composition ownership | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` |
| D2–D6 end-service contracts and guarantee limits | the `deal-lifecycle` spec and architecture companion, which the foundation's closeout creates |
| The adapter-mediated journal exception to retryable settlement | `openspec/specs/settlement-servicing/spec.md`; adapter decisions remain mechanism-owned continuation |
| Scenario boundaries | `openspec/specs/test-compatibility/spec.md` |
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
- Goal 8 round-5 triage: `unify-compute-delivery-path` is a whole-change dependency
  and rows 4 and 8 are this change's; the option's shape is `price`, `settlement` and
  `lifecycle` (foundation D5).
- Owner direction, 2026-10-29: the seller's exceptional end is a dispute filing with
  no seller stop or reverse; `buyer_end` is a buyer-filed, person-ruled case; the
  storefront signs receipt evidence only.

Next: design review of the reconciled change; its triage amends the drafted plan.
