# Design

## Context and authority

The merged lifecycle design is the frame: commitment ends protocol; later
authority records and kept signed bytes are evidence. Terms retain
early_termination {entitlements, notice_seconds, exposure_seconds, max_term_seconds}
and adjudication. Both are option params (the foundation's negotiated terms, and the terms change's D4); payment
derivation consumes the common codec, not another mechanism-specific copy.

The current kit/arkhai-payments derives a single once part. Its vendored schema
still has mandate-level authorities and HoldUntilStop, not per-part notice
authorities, maxHoldExtension or pendingStop. The revised contract below is an
implementation gate, not a claim about current generated models. The foundation
vendors it once for both changes.

Both compute domains are in scope. API credits stays on once parts. The adapter
is mechanism-owned and stateless; caller journal and continuation state live in
kit/deal-servicing, implemented by
[converge-ongoing-compute-leases](../converge-ongoing-compute-leases/).

## Decisions

### D1. Rate options and presets use common terms and the price accessor

Keep mechanism ID arkhai.payments.v1. Use period (positive fixed-unit ISO duration)
and reserve_ahead_seconds (positive integer) together, or neither. The latter
spelling follows the lifecycle design; no second reserve_ahead alias is introduced.
Convert seconds to wire reserveAhead. Approval expiry uses approval_window; payout
protection uses adjudication, never approval expiry. A rate option requires valid
early_termination and adjudication terms and a finite maximum term.

Read the agreed-price accessor supplied by
[negotiate-open-ended-compute-terms](../negotiate-open-ended-compute-terms/).
For rates its value is the upward-rounded minor-unit charge for one period;
for once-only options it is the term price. The kit never reads the negotiated
scalar directly or reinterprets a basis-point multiplier. Both sides derive the
same parts from the selected immutable option.

Recommendation: expose optional setup_amount as a positive integer minor-unit
string in the option's asset; omission means no setup part. Default presets
populate it from an explicitly configured setup price, and refuse an incomplete
preset rather than inventing an amount. This is an additional once charge, not
max(setup, usage). Sellers may opt out. It is visible before approval and bound
into the option ID. On successfully delivered lawful preemption it remains earned;
failure before delivery is handled by exceptional_end, including the setup part.
This setup refund policy is a preset recommendation, not a payment primitive.

| Preset | Parts | Entitlements |
|---|---|---|
| On-demand | setup once by default + time rate | payer; no payee stop |
| Spot | setup once by default + time rate | payer and payee with priced notice |
| Reserved | once for committed term | existing once semantics |

No class flag is persisted or used for dispatch. One pool may publish on-demand
and spot at different rates. Neither domain has a required minimum spend. Sellers
may price setup differently or refuse churners through negotiation policy.

### D2. Exact per-part mandate derivation

For each rate part derive amount, asset, period, reserveAhead,
end = start_utc + max_term_seconds, hold = {afterStop: dispute_window} and
maxHoldExtension = case_hold_max_seconds. Accepted duration_seconds equals
max_term_seconds; listing bounds already limit that term to
min(max_duration, available_until - start). Starting late never moves the end.

Every part has its own authorities. A rate part has start: [payee]; stop contains
only entitled accounts plus the agreement's dispute authority at zero notice;
reverse contains payee and dispute authority; extend contains only the dispute
authority (also authorizing lift). On-demand has no payee stop. The setup once
part uses the foundation's once derivation, hold and authorities, without rate
start or period arithmetic. Recommendation: order deterministically with setup
when present, then rate.

Each party's stop notice is its committed entitlement's notice_seconds, including
the payer's explicitly priced notice, which may be zero. Exposure is a servicing
budget, not a second hidden charge after notice. Recommendation: default payer
notice to exposure in the preset, with seller override including zero. The adapter
must not add exposure again or overwrite the accepted notice. Keep reserve_ahead_seconds >= exposure_seconds and
the foundation's publication/acceptance budget checks. Reservation ahead funds
service; it is not protection against a dishonest seller and does not replace
payer notice, since unearned reservations return on stop.

The buyer re-derives and checks all parts, order, authorities, notices, holds, end,
cap, asset and amount before approval. Changed listings or configuration cannot
alter an accepted mandate.

### D3. External contract context; one vendoring owner

The revised contract has per-part authorities
{stop: [{account, notice}], reverse, extend, start} (start on rate parts),
maxHoldExtension, optional per-part end, {afterStop: d} holds, start/stop with
optional part, stop with optional at, and extend/lift. Its stop time is
max(at ?? now, now + senderNotice) at authority receipt; never backdated. Earliest
pending stop wins and cannot be withdrawn. The adapter sends explicit part IDs
even where whole-transaction shorthand exists.

Per-part snapshots expose started, stop, pendingStop, extensions and releaseAt,
alongside rate progress and causal sequence. Approval reserves the first batch,
including once parts; no rate accrues before payee start. Periods begin at start.
Exhaustion stops all co-funded parts at funded-through with cause terms; top-up
before then may rescue them. A part's end stops it with cause terms even if no
party acts. Parts independently useful belong in separate transactions.

Each earned amount stays held until its part's stop plus the dispute window.
An accepted case extension covers current and later earnings, capped from each
amount's normal release by maxHoldExtension. Stop does not release money under an
open extension. Partial reverse works before and after stop while money remains
held. Only the dispute authority opens case extensions and applies ruling effects,
then lifts that case's refs.

These are external dependencies, not behavior SCM can implement by asserting it
in its normative spec. The foundation vendors schema/vectors and implements
snapshot-proof verification in round 2. This change gates on that verified
interface before reading any snapshot field; it supplies no second proof verifier.

Outstanding qualification requests: signed snapshot vectors, paired snapshots
before/after start, a mixed once/rate mandate vector, and partial rate reversal
integration traces before and after stop. Missing vectors block the corresponding
conformance claim; double-generated vectors are not published authority evidence.

### D4. Adapter commands and immutable operation descriptors

Extend the hosted payment adapter, not the conditional-escrow port. Lifecycle
submit {negotiation_id, kind, operation_key, at, payload} translates to explicit
per-part events with stable derived keys including operation and part. Outcomes
remain accepted/rejected/pending/unknown; read resolves unknown before another
monetary delta. Same key with different content is a local refusal. Actor
credentials, not possession of a handle, authorize commands.

Provide rate start with provisioned-delivery evidence, entitled stop (seller
notice translates to stop), voluntary partial reverse, and verified state/event
reads. Provision before start, not start on approval or a dispatch intention alone.
The consumer journals start before calling, adopts unknown start from authority
records on recovery, and ends the resource if start fails. Admission/disclosure
races and durable journals belong to convergence, not the adapter.

Export immutable operation descriptors (part, event kind, amount or at,
payload/evidence reference, request identity) and pure target/delta arithmetic.
The caller durably writes each before calling. The adapter has no database or
daemon and imports neither kit/deal-servicing nor either domain.

A transaction_stopped refusal to start signals delivery end, not success.
Repeated stop is already satisfied only when the verified record shows the same
or earlier effective stop. Transport/server errors remain unknown/retryable.
request_id_reused with different bytes and hold_not_reversible require repair.
insufficient_held_funds requires a read of what actually reversed, not inference
of partial success from the code. hold_matured means the target is no longer
locally achievable: surface the shortfall and case path, not an endlessly retried
unsupported refund. No post-release refund command or journal kind is introduced.

### D5. Cumulative targets and half-open period arithmetic

For a started part let S be authority start, P positive period, A per-period
amount and E the end being evaluated. The interval is half-open, [S,E); period k
is [S+kP,S+(k+1)P). A buyer-caused end charges the period iff its start is before E.
A seller-caused end additionally returns the incomplete started period, so a
seller cannot preempt one second into a period and earn it whole. Exactly on a
boundary, no preceding complete period is returned. At E=S nothing is earned.
Buyer notice uses the authority's effective stop, not the buyer's click time.
The terms change discloses this started-period rule before approval as part of
the preset's committed lifecycle semantics; it is not inferred from a mutable
listing or an undocumented operator convention.

Example: S=0, P=60, A=100. At E=60 both keep 100; at E=61 a buyer-caused end keeps
200 and a seller-caused end keeps 100. E=0 keeps zero. Setup charges are separate,
never prorated by the rate helper. Without start, rate earnings are zero and stop
returns reservations; returned reservation is not reversal of earnings.

The cumulative return target per part is verified settled gross less the
permitted charge, clamped at zero. Subtract all confirmed earned-money returns,
including other actors' reversals, and issue only the positive delta. Do not count
unearned reservations returned by stop as earned-money reversals. Qualification
establishes the revised counters/events mapping rather than treating legacy
refunded as a new command. Resolve earlier unknown operations first. A later
target increase produces a new operation only for the difference; prior returns
above target produce neither another refund nor automatic clawback.

For lawful preemption our cooperative seller uses its own reverse authority to
return the started-period delta after effective stop is observable. The seller
half journals this obligation with notice; convergence executes it when due,
including after restart. Reverse need not precede stop: afterStop holds preserve
reversibility. Kept signed notice, option and authority record are evidence if an
adversarial seller does not cooperate.

For an exceptional end or earlier discovered physical end, journal and file
exceptional_end(at) through the dispute adapter. Arkhai mediation realizes the
past instant by stop-now plus reverse; SCM neither backdates stop nor calculates
a ruling's part amounts. The helper is for cooperative correction/qualification;
the authority owns adjudication. Buyer buyer_end(at) and signed end_delivery
acknowledgement are foundation-owned. Financial correction is not a second mutable
end-service instant.

### D6. Seller notice is one command at the authority

Use the foundation's seller-authenticated lifecycle submit route, negotiation-keyed
and administrator-principal authenticated. Admit kind: notice only when the
accepted option has a payee entitlement and its adapter supports rate stops.
Read the Agreement, never today's listing. Persist command identity and the
started-period correction obligation before submission through the seller half's
existing journal seam.

Submit stop now with explicit affected parts and optional future at; earlier
times cannot shorten the authority's notice. Return accepted pending stop/time,
or pending/unknown/rejected. Local acceptance is not authoritative scheduling;
read resolves lost response. Earlier buyer stop wins at the authority and later
repetition cannot postpone it. End service follows the earliest authoritative end.

Recommendation: operator verb deals preempt <negotiation-id> in both storefront
CLIs, forwarding to notice through the typed lifecycle client. Expose optional
--at and stable operation key. Output authority status/time, not an invented local
deadline. No bespoke preemption route is needed. Lifecycle read/list expose
pendingStop during notice. A seller may hint after acting, but push notice and a
live storefront are not safety dependencies.

On-demand refusal points to exceptional_end, the seller's dispute against itself,
not an override stop. The foundation routes VM hosted admin interrupts through
the seller half. Alkahest splitter execution and defects remain outside this work.

### D7. Servicing declarations and identity rotation

Registration declares rate servicing with contract published or proposed.
proposed is accepted only by the explicit lane profile, its configured in-lane
double and test mode; refuse other endpoints and all livemode evidence. Bind the
profile and declared target, not a claimed hostname alone. Rate materialization
refuses without a declaration, even for an already accepted option. The terms
change owns publication/acceptance gates; convergence owns startup/recovery checks
and actual continuation registration. Production published switch-on waits for
hosted deployment of the revision, owned by activation; no horizon gate.

Configuration may list current and retiring service identities with retirement
dates. During overlap an old receipt remains verifiable and a fresh snapshot under
the current identity can re-anchor a running deal. Through the foundation verifier,
the current snapshot attests its embedded old receipt; verify binding to persisted
mandate, parties, mode and sequence. Durably store it as new approval evidence
before removing dependence on the retiring key; keep original signed bytes for
disputes. Stale/rollback snapshots cannot restore a retired trust anchor.

The kit returns re-anchoring evidence; convergence persists it and reports
unanchored deals. Remove a retiring key only after running deals re-anchor or
drain. No per-deal pin survives revocation; livemode changes cannot re-anchor and
require draining. This change owns rotation policy/configuration and the adapter
seam, not cryptographic proof implementation.

### D8. Vectors, qualification and consumer scenarios

Separate published-contract conformance, proposed-contract qualification against
lane doubles, and hosted qualification naming target, revision and readiness.
Keep target identity/mode, hashes and control trace with results. Only the external
service's suite qualifies its ledger and payouts. Examples/fixtures use USD/6;
production reads the Agreement asset.

Unit/vector targets prove derivation, interval edges and exact event bytes.
Kit integration proves retry/unknown resolution and no double return through HTTP
doubles. Application integration proves seller auth, Agreement binding, CLI
delegation and both-domain publication. Smoke is readiness/auth only. E2e proves
cross-service effects, not arithmetic permutations.

After convergence is composed, both lanes exercise buyer stop including priced
notice; spot notice then storefront outage through due time; earlier buyer stop
during notice; exhaustion and maximum term; on-demand payee-stop refusal and
mechanically ruled exceptional end; stop/start race; rotation overlap. Observe
signed authority records plus actual domain capacity/access end. Use deterministic
lane controls, not sleeps. Hosted runs are readiness-gated; missing deployment,
credentials or bare-metal hardware are unmet prerequisites, never qualification
or fallback to another mechanism.

## Rejected alternatives

- Payee-advanced horizon/vouch: a dishonest seller can advance it; the buyer's own stop and case over held money are the guarantee.
- Renewable site deadlines as buyer payment protection: site/storefront are both the seller; activation/renewal policy is a seller-value decision elsewhere.
- Required minimum spend or a service request for it: churn is priced by setup or refused through seller policy.
- An extra once fee labelled a minimum: setup is additive, not usage drawdown.
- Backdated/effective-time payee stop: past ends use the dispute authority's stop-now plus reverse.
- Local notice-stop scheduling: it dies with the storefront; pending stops belong at the authority.
- Payee stop on every on-demand part: it contradicts the absence of a payee entitlement.
- Payer start or start at approval: start is the payee's responsibility after provisioning; an early start is disputable.
- Reverse-before-stop as a safety rule: afterStop holds preserve reversal after stop.
- Unsupported post-stop refund journal: reverse already works after stop while held; paid-out money is outside that primitive.
- Fresh keys with recomputed totals: lost acknowledgements or other actors' returns would pay twice.
- Charging the incomplete started period for seller ends: it rewards preemption just after a boundary.
- Prorating every final period locally: retain the accepted started-period buyer price.
- Separate per-period mechanism/domain adapter: generic parts and authorities serve both domains.
- New preemption route or escrow-keyed admin verb: lifecycle submit is already the authenticated command boundary.
- Pin accepting keys forever or drain all deals on each rotation: bounded overlap and re-anchoring preserve running deals without trusting revoked keys.
- Proposed qualification as live proof: a double cannot establish deployed authority behavior.

## Dependency and ownership gates

The proposal names implementation prerequisites. Mechanics do not depend on
convergence; cross-service scenario execution waits for and gates that consumer's
acceptance, not this prerequisite's archival. This change delivers the scenario
entry points and records consumer-dependent execution as unrun. Convergence consumes the operation/target API rather than copying it, and introduces no vouch,
reverse-before-stop, refund queue or mutable financial end. Snapshot proofs/vectors
come from the foundation; double implementation comes from its owning change.

## Design-stage validation

The repository-pinned OpenSpec 1.14.0 strict validator accepts this change.
make check-change passes comment hygiene, agent skills, task structure and strict
validation. Its remaining failures are the accepted missing foundation-created
deal-lifecycle architecture companion and the two removed change rows still in
the integrator-owned campaign index. The integrator must remove those rows and
redirect their dependencies; this worker does not edit the shared index or roadmap.
No implementation, runtime deployment or product qualification is claimed here.

## Design promotion record

All entries are planned destinations, not claims of implemented current behavior.

| Accepted decision | Permanent location |
|---|---|
| D1–D2 rate derivation, presets and exact check | openspec/specs/settlement-servicing/spec.md; openspec/specs/storefront-publication/spec.md and architecture.md |
| D3 external contract context | openspec/specs/deal-lifecycle/architecture.md, External authorities |
| D4–D5 operations, target and arithmetic | openspec/specs/settlement-servicing/spec.md and architecture.md |
| D6 seller notice and CLI | deal-lifecycle spec.md (foundation-created; [delta](specs/deal-lifecycle/spec.md)) and architecture.md; docs/development/ARCHITECTURE.md, Release |
| D7 declarations and rotation | openspec/specs/settlement-configuration/spec.md; openspec/specs/settlement-servicing/spec.md; docs/development/DEPLOYMENT_AND_CONFIG.md |
| D8 vectors and evidence classes | openspec/specs/test-compatibility/spec.md and architecture.md; kit/arkhai-payments/README.md |
| Adapter/continuation boundary | docs/development/ARCHITECTURE.md, Kit areas and Settlement servicing |
| Campaign and Goal 8 currency | openspec/changes/README.md and docs/development/ROADMAP.md, integrator at design merge and again at closeout |
