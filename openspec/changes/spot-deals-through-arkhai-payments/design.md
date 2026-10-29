# Design

## Context and authority

The merged lifecycle design is the frame: commitment ends protocol; later
authority records and kept signed bytes are evidence. Terms retain
early_termination {version, entitlements, max_term_seconds}
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
same parts from the selected immutable option and the rate structure bound by
signed acceptance. Never pass today's listing or a registry cache to recovery's
accessor. The accepted-rate carrier/digest chosen by negotiation-driven-capacity-resize
2.1a is an input gate; without resolvable bound pricing, refuse materialization.

Recommendation: expose optional setup_amount as a positive integer minor-unit
string in the option's asset; omission means no setup part. Default presets
populate it from an explicitly configured setup price, and refuse an incomplete
preset rather than inventing an amount. This is an additional once charge, not
max(setup, usage). Sellers may opt out. It is visible before approval and bound
into the option ID. On successfully delivered lawful preemption it remains earned;
failure before delivery is handled by exceptional_end, including the setup part.
The setup part's end is activation (provisioning), not the maximum compute term;
it pays out one dispute window after activation. The standard self-penalty returns
all setup for an undelivered deal and none once delivered. This requires an
expressible activation anchor in the vendored contract; no local refund substitutes
for it. The foundation owns that contract/mediation gate.

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
end instant = start_utc + max_term_seconds with its own partialPeriod,
hold = {afterStop: dispute_window} and
maxHoldExtension = case_hold_max_seconds. Accepted duration_seconds equals
max_term_seconds; listing bounds already limit that term to
min(max_duration, available_until - start). Starting late never extends that bound.
Recommendation (01 F4): rate publication/acceptance requires whole-second
Agreement start timestamps under the integer-second payment wire. Preserve signed
Agreement bytes; reject fractional rate starts instead of silently rounding them
up past capacity bounds. Existing once-only fractional timestamp handling remains
unchanged.

Term end has its own partialPeriod payment term, independent of the stoppers'
entries. Compute presets use returned at that immutable end, so late start cannot
bill a period beyond the agreed maximum: S=10, P=60, end=120 charges [10,70),
returns the incomplete [70,130) period, and still ends delivery at 120. Do not
round maximum terms down or move the absolute end. Exhaustion needs no separate
partial-period policy: fundedThrough is a period boundary under reserve-ahead.

Recommendation: bind end_partial_period explicitly in the rate option params,
using charged/returned/prorated, and map it to the payment end's partialPeriod.
The intended preset is returned. Until the end field is vendored, publish spot
and on-demand rate options only with an explicit charged end treatment if that
is the vendored contract's actual semantics. Disclose the final partial-period
charge before acceptance; never silently downgrade returned to charged.
Publication and acceptance fail closed on an unexpressible end treatment or
an incompatible dispute-authority policy. Contract/schema vectors gate the exact
wire representation; SCM implements no compensating refund.

The foundation owns per-part authority derivation from the common codec. This
change adds the rate-specific start permission, period, reservation and end fields:
start is payee-only; on-demand grants no payee stop. Stop entries carry the entitled
party's notice_seconds and the partialPeriod mapped from settles_through (D5).
The dispute authority's stop has zero notice; it alone extends/lifts holds. Reverse
permissions remain payee and dispute authority. Setup uses the foundation's once
permissions and activation end, without rate start or period arithmetic.
Recommendation: deterministic ordering is setup when present, then rate.

There is one notice per party, the accepted entitlement's notice_seconds. The
codec has no exposure_seconds or stop+exposure value. Seller polling/watchdog/
teardown budgets remain local operational recommendations, not another payment
term or hidden tail. Reserve-ahead funds service until exhaustion; it does not
replace the priced payer notice, since unearned reservations return on stop.

The buyer re-derives and checks all parts, order, authorities, notices, holds, end,
cap, asset and amount before approval. Changed listings or configuration cannot
alter an accepted mandate.

### D3. External contract context; one vendoring owner

The revised contract has per-part authorities
{stop: [{account, notice, partialPeriod}], reverse, extend, start} (start on rate
parts). Until partialPeriod is vendored, only its expressible charged semantics
may be offered; D5 defines that fail-closed interim. Other fields include
maxHoldExtension, optional per-part end with partialPeriod, {afterStop: d} holds,
start/stop with optional part, stop with optional at, and extend/lift. Its stop time is
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
integration traces before and after stop, and reservation/charge behavior where a
late rate start approaches the absolute term bound. Missing vectors block the corresponding
conformance claim; double-generated vectors are not published authority evidence.

### D4. Adapter commands and immutable operation descriptors

Extend the hosted payment adapter, not the conditional-escrow port. Lifecycle
submit {negotiation_id, kind, operation_key, at, payload} translates to explicit
per-part events with stable derived keys including operation and part. Outcomes
remain accepted/rejected/pending/unknown; read resolves unknown before another
monetary delta. Same key with different content is a local refusal. Actor
credentials, not possession of a handle, authorize commands.

Provide rate start with activated-delivery evidence, entitled stop (seller
notice translates to stop), voluntary partial reverse, and verified state/event
reads. Activation precedes rate start: start is an effect after activation, not
an authorization step before it. Recommendation (02 F7): the neutral
ActivatedDeliveryRef contains the
negotiation, commitment, reservation and fulfillment identities, the site's
verified activation record reference/instant and a provisioning-ready evidence
digest, without credentials. The shared delivery path produces it; convergence
journals and passes it through the adapter protocol. Missing, malformed or
mismatched references refuse start before an authority call.
The consumer journals start before calling, adopts unknown start from authority
records on recovery, and ends the resource if start fails. Admission/disclosure
races and durable journals belong to convergence, not the adapter.

Export immutable operation descriptors (part, event kind, amount or at,
payload/evidence reference, request identity). No end-pricing target/delta API
or started-period correction journal is exported.
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

### D5. Started-period treatment is enforced by the payment authority

The common codec's entitlement settles_through maps one-to-one to the stop entry:

| SCM value | Payment partialPeriod | In-progress period |
|---|---|---|
| started_period | charged | Charged in full |
| last_boundary | returned | Billing ends at the last boundary |
| stop | prorated | Billed to effective stop time |

The payments service computes this price, not SCM. Client preset recommendations
are payer started_period and payee last_boundary; a dispute authority may require
returned on seller stops under its published compute policy. Until that contract
revision is vendored, publication and acceptance refuse every unexpressible value.
The interim spot preset explicitly commits started_period on both entitlements;
it does not promise a seller-period return. D2's recommended interim rate presets
also explicitly bind a charged end; the intended compute term-end treatment is
returned once expressible. Unsupported authority policy also
fails closed. No storefront refund restores a missing payment term.

For authority start S and period P, periods are half-open [S+kP,S+(k+1)P).
At E=S, nothing is earned. With S=0, P=60, A=100, E=60 charges 100 for all
three treatments; at E=61 charged keeps 200, returned keeps 100, and prorated
bills to 61 using the published contract's minor-unit rounding. Qualification
gates on that rounding vector rather than SCM inventing one. Without start,
earnings are zero and returned reservations are not earned-money reversals.
Buyer notice uses effective stop, not click time.

Verified stop records determine treatment:

| Winning record | Treatment |
|---|---|
| Payer or payee stop | That authority entry's partialPeriod |
| Exhaustion (terms) | fundedThrough boundary; no partial period |
| Absolute part end (terms) | The end's own partialPeriod; compute preset returned, recommended interim charged |
| Dispute-authority stop/effects | Authority ruling only; no SCM compensating correction |
| Superseded or equal-time competing request | Use the authority's recorded winning stop and entry; never local arrival order |
| Unknown cause or ambiguous winning entry | Surface unsupported/unknown state; no inferred monetary action |

A maximum end may cut a period after late activation; its committed end treatment
prices that period without moving or exceeding the accepted capacity bound. A pending
seller stop creates no later refund obligation; if a payer stop wins, only its
committed treatment applies. Independent discounts and ruling penalties remain
separate effects; SCM neither absorbs them into end pricing nor computes a
cumulative target. Removing that target also removes the cross-actor read/compute/
reverse race, not merely its duplicate-retry symptom.

Exceptional ends or earlier physical ends use journaled exceptional_end(at)
through the dispute adapter. The authority realizes past ends with stop-now plus
reverse; SCM does not compute ruling amounts, backdate stops or maintain a second
financial end. Existing voluntary reverse commands remain, but are not automatic
end corrections.

### D6. Seller notice is one command at the authority

Use the foundation's seller-authenticated lifecycle submit route, negotiation-keyed
and administrator-principal authenticated. Admit kind: notice only when the
accepted option has a payee entitlement and its adapter supports rate stops.
Read the Agreement, never today's listing. Preserve stable command identity and
unknown-outcome recovery through the foundation command contract. There is no
seller-command correction journal: authority-hosted pending stop and partialPeriod
are sufficient even if the storefront never resumes.

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
not an override stop. The foundation-owned VM admin interrupt route submits
notice when the accepted option grants payee entitlement; it files exceptional_end
only otherwise. Alkahest splitter execution and defects remain outside this work.

### D6a. Rate buyer-end re-drive preserves priced notice

This change owns the rate re-drive deferred by foundation task 7.5, in the neutral
buyer half and both domains' canonical end verbs. Normal buyer end submits stop
at the payment authority and sends hint; for nonzero payer notice it does not send
end_delivery. Delivery continues until watch observes effective stop and end
service acts. Hint/read failure never changes the authority stop outcome. Zero
notice may use the same flow. Explicit end-now-regardless sends end_delivery after
stop and discloses that service is surrendered before paid notice expires.

If the payment authority cannot be reached, retain the foundation's end_delivery
plus buyer_end(at) case path and kept signed acknowledgement. Both-authorities-down
recovery remains the foundation journal/retry path. This is not a new peer route
or a change to the immediate-only end_delivery contract. Terms owns displaying
normal stop versus immediate surrender.

### D7. Servicing declarations and identity rotation

The terms change owns the declaration contract, publication/acceptance doors and
proposed-profile validation. This change consumes that validated contract at
materialization and refuses absent declarations even for accepted-but-unmaterialized
work. Convergence owns rate startup/recovery and continuation registration;
activation owns published production switch-on after hosted deployment. Disabling
new publication must not abandon already materialized deals. No horizon gate.

Configuration may list current and retiring service identities with retirement
dates. During overlap an old receipt remains verifiable and a fresh snapshot under
the current identity can re-anchor a running deal. Through the foundation verifier,
the current snapshot attests its embedded old receipt; verify binding to persisted
mandate, parties, mode and sequence. Durably store it as new approval evidence
before removing dependence on the retiring key; keep original signed bytes for
disputes. Stale/rollback snapshots cannot restore a retired trust anchor.

The kit returns rate-deal re-anchoring evidence; convergence persists it and reports
unanchored rate deals. Recommendation: scope re-anchoring here to rate deals.
Once-only hosted deals are included in the retiring-key dependency inventory but
must drain before removal; durable once-only re-anchoring is deferred, not silently
assigned to a rate-only consumer. Remove a retiring key only after running deals re-anchor or
drain. No per-deal pin survives revocation; livemode changes cannot re-anchor and
require draining. This change owns rotation policy/configuration and the adapter
seam, not cryptographic proof implementation.

### D8. Vectors, qualification and consumer scenarios

Separate published-contract conformance, proposed-contract qualification against
lane doubles, and hosted qualification naming target, revision and readiness.
Keep target identity/mode, hashes and control trace with results. Only the external
service's suite qualifies its ledger and payouts. Examples/fixtures use USD/6;
production reads the Agreement asset.

Unit/vector targets prove derivation, partialPeriod edges and exact event bytes.
Kit library integration uses in-process fakes generated from the same contract
vectors to prove retry/unknown resolution; kits do not depend on runnable tooling.
HTTP doubles serve lane/e2e qualification. Application integration proves seller
auth, Agreement binding, CLI delegation and both-domain preset integration. Smoke is readiness/auth only. E2e proves
cross-service effects, not arithmetic permutations.

Convergence owns the cross-service requirements, runnable scenarios and execution
matrix; none is promoted here while unrun. Physical completion evidence must prove
release and access closure, not merely the site's lease_ended intent report. This change supplies adapter/CLI seams
and focused evidence only. Planned scenario ownership is explicit below; selectors
are to be delivered in the existing compute-lane scenario harness by the executor.

| Scenario / planned selector | Entry surface | Executor | Evidence class |
|---|---|---|---|
| buyer_notice | canonical buyer end | convergence, both lanes | proposed lane |
| notice_outage | deals preempt + outage control | convergence, both lanes | proposed lane |
| earlier_buyer_stop | preempt then buyer end | convergence, both lanes | proposed lane |
| exhaustion / maximum_term | clock/funding controls | convergence, both lanes | proposed lane |
| on_demand_exceptional_end | refused notice then self-filing | convergence, both lanes | proposed lane |
| stop_start_race | activation/start controls | convergence, both lanes | proposed lane |
| rotation_overlap | identity control + restart | convergence, both lanes | proposed lane |
| hosted_four_path | buyer stop, seller notice, exhaustion, self-filing | activation, both lanes | hosted, readiness-gated |

Published vectors qualify derivation/contract use here; proposed lanes never prove
hosted internals. Hosted prerequisites are reported before scenario execution.

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
- Storefront cumulative-target end refunds: they bind only a cooperative seller, race independent authority rulings, and absorb unrelated discounts.
- Boundary-aligned seller notices as a substitute for partialPeriod: they change the offered notice and cannot encode arbitrary committed started-period treatment.
- Local final-period pricing: the payment term and authority decide it, including the explicitly charged interim seller preset.
- Separate per-period mechanism/domain adapter: generic parts and authorities serve both domains.
- New preemption route or escrow-keyed admin verb: lifecycle submit is already the authenticated command boundary.
- Pin accepting keys forever or drain all deals on each rotation: bounded overlap and re-anchoring preserve running deals without trusting revoked keys.
- Proposed qualification as live proof: a double cannot establish deployed authority behavior.

## Dependency and ownership gates

Section-level gates, not whole-change archival cycles:

- Foundation codec/authority derivation, vendoring and verified snapshots gate rate
  derivation/reads; its round-2 proof implementation is not duplicated.
- Terms accessor, accepted pricing carrier (resize 2.1a), bounds and declaration
  contract gate sections 2–3. Terms alone owns generic publication emission;
  this change supplies its rate/setup preset helper and materialization door.
- In-process contract fakes gate kit library integration; runnable lane doubles gate
  only lane evidence, not pure derivation. No kit imports the double tooling.
- Convergence consumes these mechanics and owns funding timers, persisted rate
  re-anchoring and the complete lane matrix. Its archival is not a prerequisite
  here. Activation owns hosted four-path execution, not this change.

First use before convergence uses lane-only approval/command fixtures: delivery
must fail closed without the rate hook. It proves pending authority stop, not a
working delivered spot lease. Production rate publication stays dark until its
servicing doors are composed; this fixture is not production enablement.

## Design-stage validation

Both bunx @fission-ai/openspec@1.14.0 validate and the installed openspec validate
accept this change under --strict, without long-requirement warnings.
make check-change passes five of six checks; documentation citations report only
the accepted missing foundation-created openspec/specs/deal-lifecycle/architecture.md
(two citations, in this design and proposal). git diff --check is clean.
Shared index/roadmap edits are reported to the integrator, not made here.
No implementation, runtime deployment or product qualification is claimed.

## Design promotion record

All entries are planned destinations, not claims of implemented current behavior.

| Accepted decision | Permanent location |
|---|---|
| D1–D2 rate derivation, presets and exact check | openspec/specs/settlement-servicing/spec.md; openspec/specs/storefront-publication/spec.md and architecture.md |
| D3 external contract context | openspec/specs/deal-lifecycle/architecture.md, External authorities |
| D4–D5 operation identity and authority-enforced partialPeriod | openspec/specs/settlement-servicing/spec.md and architecture.md |
| D6–D6a seller notice, buyer rate-end re-drive and CLI | deal-lifecycle spec.md (foundation-created; [delta](specs/deal-lifecycle/spec.md)) and architecture.md; docs/development/ARCHITECTURE.md, Release |
| D7 declarations and rotation | openspec/specs/settlement-configuration/spec.md; openspec/specs/settlement-servicing/spec.md; docs/development/DEPLOYMENT_AND_CONFIG.md |
| D8 vectors and evidence classes | openspec/specs/test-compatibility/spec.md and architecture.md; kit/arkhai-payments/README.md |
| Adapter/continuation boundary | docs/development/ARCHITECTURE.md, Kit areas and Settlement servicing |
| Campaign and Goal 8 currency | openspec/changes/README.md and docs/development/ROADMAP.md, integrator at design merge and again at closeout |
