# Design

## Context

The foundation defines per-part authorities, afterStop holds, case extensions,
self-penalty dispute filings/rulings, and the payment/dispute adapters. The spot change supplies
rate mechanics beyond `charged`, setup parts, presets and option publication; servicing
supplies end service's rate-part integration and the consolidated matrix. Those can be
qualified in-lane before the hosted services execute them. A schema publication is not
proof that the target serves it.

Goal 8's MVP changes land first, and this design builds on what they leave:

- `switch-on-hosted-per-period-vm` declares per-period servicing in the VM production
  composition with the declared treatments `[charged]`, after confirming with the
  payments service's maintainers which revision the hosted targets run and recording
  live evidence of the on-demand baseline, the buyer's stop, funds running out and spot
  preemption. It prepares the hosted target through existing setup tooling and runs its
  readiness check, and it records the declaration's rollback.
- Arkhai operators are the MVP's dispute authority. They act through the dispute
  account's stop entry and the payments service's reversal, under a published policy
  stating key retention, continuity and case handling, following runbooks in
  `docs/operator-handbook.md`.
- `serve-running-rate-deals-on-vm` composes VM rate servicing, startup coherence and
  withdrawal, and qualifies the MVP's four VM lane rows against both doubles.
- The MVP's default buyer (`offer-per-period-vm-terms`) accepts a charged final period
  everywhere. The full product's default buyer (`negotiate-open-ended-compute-terms`)
  refuses charged treatment on a seller's preemption and at the term end, accepts it on
  its own stop, and displays a premature-stop penalty without requiring one.

## Goals / Non-goals

Extend production servicing to bare metal and to the `returned` and `prorated`
treatments against the deployed hosted revision, replace operator-handled disputes
with mechanical rulings where the mediation revision supports them, preserve
fail-closed publication/acceptance/materialization for every undeclared treatment, and
record live evidence without relabelling double qualification. This change adds no
payment primitive and changes no accepted deal's authority or terms.

## Decisions

### D1. Hosted contract capability gate and dispute qualification

The gate is the hosted deployment executing what the MVP does not use: `returned` and
`prorated` on every stop entry and at the term end, the dispute authority's stop entry
with `chosen` treatment (where the MVP shipped its fixed-`charged` fallback), hold
extension and lifting on rate parts, and partial reversal after a stop. Verify payee-only
start after lease activation on rate parts, authority-hosted pending notices,
per-stopper treatment, afterStop holds, partial reversal before/after stop and case
extend/lift. SCM started_period/last_boundary/stop map to charged/returned/prorated.

Each composition's servicing declaration lists the treatments it has qualified, and
publication, acceptance and materialization read that list; a term whose treatment is
not declared fails closed. The VM declaration `[charged]` that
`switch-on-hosted-per-period-vm` ships is current state, not completion. This change
extends the VM list to `returned` and `prorated` and declares bare metal's list once the
hosted target executes them. The shipped presets move the payee entitlement and the
term end to `last_boundary` once `returned` is declared, so a default buyer, which
refuses charged treatment on a seller's preemption and at the term end, can take
on-demand and spot. Closeout requires an
unconfigured buyer taking on-demand and spot live under the shipped presets, with a live
preemption returning the unstarted remainder. Absolute term ends have their own
partialPeriod without rounding; exhaustion is period-boundary aligned.

Requalify foundation's delivery_end dispute intent, mediation request vocabulary
and published mapping. The seller half files with the Agreement dispute authority,
journaled with the end, never future-dated. Pre-start failure journals immediately
and files at Agreement start. Seller sends no stop/reverse for this path.
Arkhai mediation's mechanical delivery-end rule is payee agreement under the foundation's guards; its cause=payee branch is the standard self-penalty
(`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`), requalified here against the hosted authority step by step and never
restated; seller exit requires that complete dispute-recorded package, not direct
partial restitution, and the authority records disputes to act on bad sellers,
including bans. Where mechanical rulings go live they replace the operator procedures
the MVP's runbooks describe for the same cases; filings outside the mechanical guards
stay with operators.

Seller stop entries exist only for entitlements such as spot notice; spot emergency
exit files delivery_end. No seller PT0S/returned restitution entry, implicit
favourable-stop permission, payee notice waiver, payer early release or several-
stop-entries dependency remains. On-demand non-preemption is remedied by buyer case
over held money plus the premature-stop penalty, not by mandate enforcement. The buyer's end and its
`delivery_end` case are requalified exactly as the foundation states them (`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-buyers-end`).

A deployment must demonstrate semantics, not merely advertise a version. The vendored
schema and vectors (`kit/arkhai-payments/schema/SOURCE.md`) already include signed
before/after-start snapshots and partial reversals while running and after stop, and no
unpublished payments candidate exists; re-vendor only if the producer publishes a newer
revision, through the existing SOURCE record. Mismatch between the hosted target and the
vendored revision leaves the extended declaration off; do not adapt away notice,
authority, required returned treatment or holds. Evidence is lane-double evidence or
live evidence, as test-compatibility defines them; only a hosted target yields live
evidence. Periods are earned at period end or part stop, not start; setup releases one
dispute window after the later of the Agreement start and approval. No minimum-spend or
backdated payee-stop gate is added.

### D2. Verify double and consumer before extending the production declaration

First run the vendored vectors against the in-lane double for the treatments and
operations beyond the MVP's. Then run both compute lanes with the real adapters against
that double, including its mediation peer. Report divergences against their owning
code/change and repair before activation. Lane runs are labelled lane-double evidence
and never authorize a production declaration on their own.

### D3. Verify the owned target, then extend the declaration

`switch-on-hosted-per-period-vm` prepares the hosted test target and its readiness
check. This change extends that preparation to bare-metal capacity and personas and to
the hosted mediation authority: the operator identifies the bare-metal service identity
and mode, buyer payer and seller payee personas, credentials by environment-variable
name, and the Agreement's configured dispute authority. Confirm selectors address the
intended target before seeding. Public evidence uses public-safe target aliases and
revision identifiers from the vendored SOURCE record, never internal endpoints, account
identifiers, credentials or raw private logs. Use existing deployment/setup tooling, not
a second service stack. Readiness passes before a deal scenario runs.

The live fixture must have known isolated funding and capacity, use the real
payment and dispute adapters, and support cleanup of created deals/resources. Run
held-money and case effects against the configured agreement authority. Mediation
is an internal product prerequisite, not a request for another payments capability.
Missing credentials or an unavailable target block the live checks; they are not
passing double evidence.

The MVP's published dispute-authority policy states key retention, continuity, case
dismissal and hand rulings for operators. This change extends it to the mechanical
rulings: repeated/concurrent-case and dismissal policy, plus key-retention and
origin-continuity through deal life, window and open cases, for the hosted mediation
authority. Missing these blocks activation. No response bound is asked of the authority: a binding one would end unruled cases in default judgements against someone, and an unbounded one is no bound; a seller mistreated by its chosen authority picks another for its next deals. The authority may publish an advisory expected time to rule, which qualification records as advisory if present and as absent otherwise, and the terms display shows the same.

The arkhai.mediation.v1 contract, delivery_end revision included, is published and vendored by the foundation (its `kit/arkhai-mediation/schema/SOURCE.md` identifies the revision by content); the hosted development service still runs an older revision. Live claim qualification and setup-bearing presets wait for the deployed authorities to run the vendored revision, not for another payments wire change.

After hosted checks pass, the VM composition's declared treatments gain `returned` and
`prorated`, and the bare-metal composition declares its list. The same declaration is
checked at publication, acceptance and materialization. Do not change service
identity/mode or redirect accepted deals as part of extending it; any required
coordinated cutover follows existing drain/recovery rules. Convergence owns startup
coherence and continued servicing after withdrawal; activation consumes and requalifies
that contract, not another copy of its implementation. Accepted deals recover forward
from kept records and operation keys, never by mechanism priority fallback.

### D4. Completion and evidence

Both VM and bare-metal double-backed lanes re-run convergence's consolidated
rate-servicing matrix, including the MVP's four VM rows, spot's prepared maximum-term and
on-demand emergency entry points, and declaration coverage. Convergence owns matrix
qualification; this change requalifies it against the deployed revision. Lane
interruptions use pause/resume, with durable production-application restart proved
separately at integration level. Lane clocks move together through the storefront and
doubles' perceived-clock fixture. These runs are lane-double evidence, not live
evidence. Hosted runs exercise, beyond the MVP's live rows, the payment-boundary
transitions with real authority responses: bare-metal complete deals, payer stop with
priced notice and hint (delivery continues until effective stop), per-stopper
`returned`/`prorated` partial-period billing, a preemption returning the unstarted
remainder, setup once, seller notice surviving storefront absence, seller delivery_end
filing and payee-signed delivery_end rule with cause-specific remedies, payee-signed
delivery_end or human triage with signed acknowledgement, case extension/lift and partial
reverse after stop, including restart and lost-response recovery where the target's
supported test controls allow it.

The buyer's independent recovery is live evidence of its own, five observations each
a blocker if unrun: a payer stop with the storefront stopped, not flagged absent; a
case filed from the exact accepted Agreement and the buyer's kept evidence with
nothing retrieved from the seller; a restart after an unknown stop result that reuses
the original operation key and opens no second stop; a seller that never files its
exceptional end, remedied by the buyer's stop and case alone (convergence row 12); a
seller's `available` recorded in time with nothing reachable, weighed as its assertion
against the buyer's kept observation (row 12b); and
a case accepted over money already paid out, reported `not_held` per part and shown
as such (row 13). An accepted case is not recoverable money; the authority's per-part
answer is what the buyer sees.

The buyer's end runs live exactly as the foundation's "The buyer's end" states it,
with the storefront's signed receipt kept as evidence. Where a seller enables
convergence's funding timer, verify at funding expiry that the payment read comes first:
renewal replaces timer, verified exhaustion is an authority end, and only
unreachable/unverifiable evidence permits bare-timer end and later self-penalty filing.

For nonzero notice, end_delivery is explicit end-now or outage fallback, not normal
follow-up to payer stop. Operator VM emergency files delivery_end in on-demand
and spot; entitled spot notice remains a separate path. Observe qualifying payee
mechanical ruling through mediation's PT0S/chosen entry and verify no seller stop/
reverse before filing. Setup-part and earlier-evidence checks observe authority
rulings and safe dispute-adapter revision/prior-ruling mapping, not local monetary
arithmetic. Runnable doubles qualify lanes; kit tests use the kit-owned clock-
injected authority engine directly, without tooling dependency, and the HTTP
double wraps the same engine.

Live reports name the observed authority effects, physical recovery, evidence
kept and remaining cases/holds separately. Do not claim a race/outage was tested
live if it was only controlled in the double; report each row's provenance and
unrun cause. Goal 8's completion requires both-domain live complete deals, the hosted
payment/dispute acceptance matrix, and an unconfigured buyer — one that changed no
acceptance setting — taking on-demand and spot live under the shipped presets, with a
live preemption returning the unstarted remainder. An unavailable required live scenario
is a blocker, not a caveat that closes the change; the MVP's `[charged]` VM declaration
is recorded as current state.

## Rejected alternatives

- Await a billing horizon or vouch: buyer safety is its own stop and dispute over held earnings, not seller liveness.
- Await minimum spend: setup once parts and seller negotiation policy cover the chosen product posture.
- Await a backdated payee stop or separate post-release refund: dispute-authority stop now plus partial reverse under held money supplies the self-penalty package.
- Seller-direct exceptional-end correction or a compound payments termination: the first leaves a partial package and no dispute record; foundation records the second as deferred until hosted bonds and dispute-authority recording are designed.
- Enable from a published schema alone: the selected hosted deployment may still implement the older contract.
- Label both double-backed lanes live after vendoring: conformance does not prove hosted deployment behavior.
- Remove servicing when withdrawing publication: existing commitments still need end work and evidence retention.
- Close Goal 8 on the MVP's `[charged]` declaration: a seller's preemption then charges the whole started period, which the default buyer refuses.

## Dependency and execution gates

Internal gates are `switch-on-hosted-per-period-vm`, spot mechanics/publication,
servicing, discovery and the delivery-deadline change, whose pool deadline the full
product publishes and whose site enforcement of the accepted value is part of what this
change qualifies. Scenario tooling comes from the payment/mediation double.
The external gate is the hosted payments execution in D1 and the hosted mediation
service running the vendored delivery_end revision; no several-stop-entries dependency
remains. Mediation self-penalty and receipt-backed delivery_end or triage mapping
are internal prerequisites, not extra payments primitives.
Implementation tasks distinguish the actual prepared target and readiness from
these task-required environments; no ignored worktree-only setup is sufficient.

## Permanent documentation destinations

D1/D3: settlement-configuration spec and architecture companion,
`docs/development/DEPLOYMENT_AND_CONFIG.md`, and ARCHITECTURE's settlement servicing;
the mechanical rulings replacing operator procedures in `docs/operator-handbook.md` and
`openspec/specs/deal-lifecycle/architecture.md`.
D2/D4: test-compatibility spec and architecture companion. At closeout the Goal 8
row records deployment-qualified enablement and its live evidence; the campaign
index records the external gate resolved. No duplicate diagram promotion occurs.
