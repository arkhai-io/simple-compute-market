# Design

## Context

The foundation defines per-part authorities, afterStop holds, case extensions,
self-penalty dispute filings/rulings, and the payment/dispute adapters. The spot change supplies
rate mechanics, presets and option publication; servicing supplies end service's
rate-part integration. Those can be qualified in-lane before the required hosted
payments revision is deployed. A schema publication is not proof that the target
serves it. No claim is made here that any target is already prepared or ready.

## Goals / Non-goals

Enable both compute compositions against the deployed hosted revision, preserve
fail-closed publication/acceptance/materialization until then, and record live
evidence without relabelling double qualification. This change adds no payment
primitive and changes no accepted deal's authority or terms.

## Decisions

### D1. Hosted contract capability gate and dispute qualification

The gate is hosted deployment of the payments revision with per-part authorities,
hold extensions and every required stop term. Verify payee-only start after lease
activation on rate parts, authority-hosted pending notices, per-stopper treatment,
afterStop holds, partial reversal before/after stop and case extend/lift. Unsupported
terms fail closed; SCM started_period/last_boundary/stop map to charged/returned/
prorated. An interim spot charged/charged subset may activate only if every other
gate passes and the buyer explicitly accepts started_period for payee and charged
term ends. Default buyers still prefer payer charged/payee returned and refuse
payee or term-end treatment other than last_boundary. Absolute term ends have their
own partialPeriod without rounding; exhaustion is period-boundary aligned.

Requalify foundation's exceptional_end dispute intent, mediation request vocabulary
and published mapping. The seller half files with the Agreement dispute authority,
journaled with the end, never future-dated. Pre-start failure journals immediately
and files at Agreement start. Seller sends no stop/reverse for this path.
Arkhai mediation's only mechanical ruling is a payee-filed self-penalty request at
least as strong as standard. Through mediation's own
`{account, notice: PT0S, partialPeriod: "chosen"}` stop entry, standard ruling stops
rates now returned, reverses earnings since at, reverses once unserved shares by
time, then reverses min(premature_stop_penalty, earned amounts still held) to the
payer across parts in mandate order. Bond award stays reserved for hosted bonds. On-demand always returns the
partial period: that is the on-demand contract. Setup is owed from approval; it returns
in full if the seller never delivers and not at all once it has. Seller exit requires this
complete dispute-recorded package, not direct partial restitution. The authority
also records disputes to act on bad sellers, including bans.

Seller stop entries exist only for entitlements such as spot notice; spot emergency
exit files exceptional_end. No seller PT0S/returned restitution entry, implicit
favourable-stop permission, payee notice waiver, payer early release or several-
stop-entries dependency remains. On-demand non-preemption is remedied by buyer case
over held money plus the premature-stop penalty, not by mandate enforcement. buyer_end is buyer-filed
and human-triaged, realized as payer stop at at with payer notice and partialPeriod;
there is no mechanical buyer_end ruling. Cases carry exact Agreement verified
against mandate deal hash, not a required payment attachment. The storefront signs
end_delivery receipt evidence only; the buyer half alone stops payments and keeps
same-key retry during outage, with billing until that stop lands.

A deployment must demonstrate semantics, not merely advertise a version. Check
vendored schema/proof/vectors through the existing SOURCE record and reuse current
foundation vendoring. Mismatch leaves the declaration off; do not adapt away
notice, authority, required returned treatment or holds. Producer-published signed
snapshot, before/after-start and partial-reversal before/after-stop vectors block
Qualification against the published contract if absent. Pinned candidate bytes
permit only Qualification against a proposed contract; Live evidence additionally
requires hosted observations. Lane-double D6 owns those definitions. Periods are
earned at period end or part stop, not start; setup releases one dispute window
after the later of the Agreement start and approval. No minimum-spend or backdated payee-stop gate is added.

### D2. Verify double and consumer before the production declaration

First run published vectors against the in-lane double. Then run both compute
lanes with the real adapters against that double, including its mediation peer,
under the published contract. Report divergences against their owning code/change
and repair before activation. Proposed-contract qualification remains distinct and
lane-only while still useful for future contract work; it never authorizes a
production declaration.

**Recommendation supplied here:** retain explicit proposed/published provenance in
the evidence format even once the proposed runtime extension becomes redundant;
remove the runtime extension only when all currently required scenarios pass the
published contract. This preserves honest historical evidence without keeping a
needless alternate production path.

### D3. Verify the owned target, then flip the declaration

The operator identifies the intended hosted test deployment, its revision,
service/receipt identity and mode, buyer payer and seller payee personas,
credentials by environment-variable name, and the Agreement's configured dispute
authority. Confirm selectors address the intended target before seeding. Public
evidence uses public-safe target aliases and revision identifiers from the
vendored SOURCE record, never internal endpoints, account identifiers, credentials
or raw private logs. Use existing deployment/setup tooling, not a second service
stack. Readiness passes before a deal scenario runs.

The live fixture must have known isolated funding and capacity, use the real
payment and dispute adapters, and support cleanup of created deals/resources. Run
held-money and case effects against the configured agreement authority. Mediation
is an internal product prerequisite, not a request for another payments capability.
Missing credentials or an unavailable target block the live checks; they are not
passing double evidence.

The hosted dispute authority is qualified against the foundation's published
description (D13), not only against its vectors: its policy on repeated and
concurrent cases on one agreement and on closing a case nobody advances, and its
key-retention and origin-continuity commitment for the life of a deal plus its
dispute window and open cases, must be published. An authority whose description
lacks either blocks activation however its doubles behave: the architecture rests
on this authority's fairness and continuity, and the code neither limits filings
nor follows a rotated key.

After hosted checks pass, both production compositions declare servicing against
the published revision. The same declaration is checked at publication, acceptance
and materialization. Do not change service identity/mode or redirect accepted
deals as part of flipping it; any required coordinated cutover follows existing
drain/recovery rules. Convergence owns startup coherence and continued servicing
after withdrawal; activation consumes and requalifies that contract, not another
copy of its implementation. Accepted
deals recover forward from kept records and operation keys, never by mechanism
priority fallback.

### D4. Completion and evidence

Both VM and bare-metal double-backed lanes re-run convergence's consolidated
rate-servicing matrix (including spot's prepared maximum-term and on-demand
emergency entry points), plus option-gating coverage. Convergence owns matrix
qualification; this change requalifies it against the deployed published revision.
Lane interruptions use pause/resume, with durable production-application restart
proved separately at integration level. Cross-service doubles use coherent real
UTC time, not isolated clock jumps. These runs
are published-contract qualification, not live evidence. Hosted runs exercise the
same payment-boundary transitions with real authority responses: activation then start,
payer stop with priced notice and hint (delivery continues until effective stop),
per-stopper partial-period billing, seller notice surviving storefront absence, exhaustion,
seller exceptional_end filing and sole mechanical payee self-penalty, human-triaged buyer_end with signed acknowledgement, case
extension/lift and partial reverse after stop, including restart and lost-response
recovery where the target's supported test controls allow it.

end_delivery carries no at; the storefront signs receipt time and retains exact
signed request/receipt as evidence, with no authority to stop billing for the buyer.
The buyer half stops at payments first. During outage it journals/retries that stop
under the same key; billing runs until landing. An additional buyer_end case goes
to human triage with exact Agreement and signed evidence; no mechanical buyer_end
ruling or cooperative seller stop exists. At funding expiry verify payment read:
renewal replaces timer, verified exhaustion is an authority end, and only
unreachable/unverifiable evidence permits bare-timer end and later self-penalty filing.

For nonzero notice, end_delivery is explicit end-now or outage fallback, not normal
follow-up to payer stop. Operator VM emergency files exceptional_end in on-demand
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
unrun cause. The goal's activation acceptance requires both-domain live complete
deals and the hosted payment/dispute acceptance matrix; an unavailable required
live scenario is a blocker, not a caveat that closes the change.

## Rejected alternatives

- Await a billing horizon or vouch: buyer safety is its own stop and dispute over held earnings, not seller liveness.
- Await minimum spend: setup once parts and seller negotiation policy cover the chosen product posture.
- Await a backdated payee stop or separate post-release refund: dispute-authority stop now plus partial reverse under held money supplies the self-penalty package.
- Seller-direct exceptional-end correction or a compound payments termination: the first leaves a partial package and no dispute record; foundation records the second as deferred until hosted bonds and dispute-authority recording are designed.
- Enable from a published schema alone: the selected hosted deployment may still implement the older contract.
- Label both double-backed lanes live after vendoring: conformance does not prove hosted deployment behavior.
- Remove servicing when withdrawing publication: existing commitments still need end work and evidence retention.

## Dependency and execution gates

Internal gates are the foundation, spot mechanics/publication, servicing and
discovery changes. Scenario tooling comes from the payment/mediation double.
The external payments capability gate is the hosted revision in D1; no several-
stop-entries dependency remains. Mediation self-penalty and human buyer_end mapping
are internal prerequisites, not extra payments primitives. Activation must not wait on the
superseded settle or publish/preempt change directories.
Implementation tasks distinguish the actual prepared target and readiness from
these task-required environments; no ignored worktree-only setup is sufficient.

## Permanent documentation destinations

D1/D3: settlement-configuration spec and architecture companion,
`docs/development/DEPLOYMENT_AND_CONFIG.md`, and ARCHITECTURE's settlement servicing.
D2/D4: test-compatibility spec and architecture companion. At closeout the Goal 8
row records deployment-qualified enablement and its live evidence; the campaign
index records the external gate resolved. No duplicate diagram promotion occurs.
