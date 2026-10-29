# Design

## Context

The foundation defines per-part authorities, afterStop holds, case extensions,
stop-now plus reversal, and the payment/dispute adapters. The spot change supplies
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

### D1. Hosted contract and gated multi-entry support

The gate is the hosted deployment of the payments revision with per-part
authorities and hold extensions, including support for every offered stop term.
Every required returned/prorated entry needs partialPeriod support, including
on-demand seller restitution; negotiated charged/charged terms do not remove that
gate. Spot's interim notice-only configuration cannot claim immediate restitution. Verify the vendored contract: payee-only start after lease activation on rate parts, stop authority
notices hosted as pending stops, per-stopper started-period treatment, afterStop
dispute-window holds, partial reverse before and after stop, and per-case extend/lift.
Payments knows accounts and mandate authorizations, not buyer/seller roles or
implicit beneficial actions. SCM derives a buyer-visible stop entry on every part,
`{account: seller, notice: PT0S, partialPeriod: returned}`. SCM exceptional_end is
implemented as `stop {part}` under that entry plus `reverse {part, amount}` under
existing reverse authority: rate earnings since at, once unserved shares and any
full bond award. No exceptional-end kind/field exists in payments; no dispute filing
or mechanical ruling is involved. No payee notice waiver or payer early release
is assumed. Dispute authority actions still require its own entries.

On-demand gives the seller only the immediate entry. Its non-preemption promise
is not mandate-enforced; buyer case over held money and the bond supplies the remedy.
Spot requires both seller notice and immediate entries, hence several stop entries
per account per part: an unscheduled, gated payments dependency. Until supported,
spot immediate stop is unavailable and emergency exit waits out its notice unless
the owner decides otherwise. Activation cannot label that fallback immediate
restitution or enable the gated capability without published and hosted evidence.

A deployment must demonstrate those semantics, not merely advertise a version.
The vendored snapshot schema/proof and vectors are checked through the existing
SOURCE record. Reuse foundation vendoring when current. If the hosted deployment
differs from the published revision, record the mismatch and leave the declaration
off. Do not silently adapt away authority, notice, partialPeriod or hold requirements.
SCM started_period/last_boundary/stop map to charged/returned/prorated respectively.
Unsupported offered terms fail closed. Until the partialPeriod revision is
vendored, spot offers only charged on both sides, never a corrective storefront
refund. That supported negotiated charged/charged subset may activate if all required
entries and other gates pass
and the buyer explicitly accepts started_period for payee and charged term ends.
Negotiated spot seller-stop treatment remains separate from SCM's explicit
PT0S/returned restitution entry; the latter cannot be assumed while multi-entry
support is gated. On-demand's required returned entry is not waived by interim
charged negotiated terms. Client
presets prefer payer charged/payee returned, and default buyers refuse payee or
term-end treatment other than last_boundary. Each absolute term end has its own
partialPeriod, without term rounding; exhaustion is period-boundary aligned.
The dispute authority's stop entry uses chosen and each human ruling supplies
treatment. buyer_end preserves the payer's priced notice and partialPeriod;
mediation has no mechanical rulings. Cases carry the exact Agreement verified
against the mandate's deal hash, not a required attachment.
Periods are earned at period end or part stop, not period start. Verify setup once
ends at activation, releases one dispute window later, and self-penalty returns
all before delivery and none after delivery.

There is no true-minimum-spend gate or backdated/effective-time payee-stop gate. Producer-published signed snapshot, before/after-start and partial-reversal vectors
before/after stop are blockers to *Qualification against the published contract*.
Absent any, pinned kit-owned candidate bytes support only *Qualification against a
proposed contract*, never a relabelled double trace. *Live evidence* additionally
requires the hosted checks. These three classes are defined only by the lane-double
change's D6; snapshot proof or vector gaps cannot be waived by activation.

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
explicit-entry seller stop/reverse correction, human-triaged buyer_end with signed acknowledgement, case
extension/lift and partial reverse after stop, including restart and lost-response
recovery where the target's supported test controls allow it.

On end_delivery the storefront signs receipt time (no buyer at) and journals its
cooperative stop with buyer treatment at receipt plus payer notice and payer
partialPeriod only where an entry authorizes that dispute-free storefront action,
including journaling through outage. No notice waiver; otherwise the buyer half
must stop payments. Verify this separately from
the buyer's stop-first path and human buyer_end case. At funding expiry verify the
payment read: renewal replaces the timer, exhaustion is an authority end, only
unreachable/unverifiable evidence permits a bare-timer end and later correction.

For nonzero notice, end_delivery is explicit end-now or the unreachable-payment
authority fallback, not the normal immediate follow-up to payer stop. Operator
VM interrupt uses seller notice for spot while multi-entry support is gated;
on-demand uses its explicit PT0S/returned entry and existing reverse authority.
Setup-part and earlier-evidence checks must observe authority-calculated remedies,
not local end-correction arithmetic. Runnable doubles qualify lanes; kit tests keep
the kit-owned clock-injected authority engine directly and no tooling dependency;
the HTTP double wraps that same engine.

Live reports name the observed authority effects, physical recovery, evidence
kept and remaining cases/holds separately. Do not claim a race/outage was tested
live if it was only controlled in the double; report each row's provenance and
unrun cause. The goal's activation acceptance requires both-domain live complete
deals and the hosted payment/dispute acceptance matrix; an unavailable required
live scenario is a blocker, not a caveat that closes the change.

## Rejected alternatives

- Await a billing horizon or vouch: buyer safety is its own stop and dispute over held earnings, not seller liveness.
- Await minimum spend: setup once parts and seller negotiation policy cover the chosen product posture.
- Await a backdated payee stop or separate post-release refund: stop now plus partial reverse under afterStop holds and extensions supplies correction.
- Enable from a published schema alone: the selected hosted deployment may still implement the older contract.
- Label both double-backed lanes live after vendoring: conformance does not prove hosted deployment behavior.
- Remove servicing when withdrawing publication: existing commitments still need end work and evidence retention.

## Dependency and execution gates

Internal gates are the foundation, spot mechanics/publication, servicing and
discovery changes. Scenario tooling comes from the payment/mediation double.
External gates are the hosted revision and, for spot immediate seller restitution,
the unscheduled multi-entry support in D1. Until supported, spot emergency uses
seller notice; do not claim immediate stop. Activation must not wait on the
superseded settle or publish/preempt change directories.
Implementation tasks distinguish the actual prepared target and readiness from
these task-required environments; no ignored worktree-only setup is sufficient.

## Permanent documentation destinations

D1/D3: settlement-configuration spec and architecture companion,
`docs/development/DEPLOYMENT_AND_CONFIG.md`, and ARCHITECTURE's settlement servicing.
D2/D4: test-compatibility spec and architecture companion. At closeout the Goal 8
row records deployment-qualified enablement and its live evidence; the campaign
index records the external gate resolved. No duplicate diagram promotion occurs.
