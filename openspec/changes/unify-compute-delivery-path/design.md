# Design — one compute delivery path

## Context

VM and bare metal currently commit, dispatch and disclose through different paths.
Bare metal commits from now; VM recovery substitutes 3600 seconds twice, and
vm_fulfillment_service._parse_start_utc substitutes now for missing start and accepts
legacy minute-format timing. The accepted Agreement, not those fallbacks, owns the
window. Exact normalized requests and recorded resource identities remain recovery
inputs; legacy minute-format persisted timestamps remain readable, not a reason to
guess a new Agreement start.

Provisioning owns physical fulfillment and live results. Core forms
StorefrontFulfillmentContext and invokes the domain hook, validating its returned
identity. The shared path runs inside that hook, never beside or instead of it.
Payment settle and Alkahest's ready continuation reach the same hook. This change
does not replace settlement-stage evidence validation.

The foundation owns end service and its durable admission/end-plus-filing operations.
These are dependency contracts, not implemented capabilities on this branch.

## Goals / Non-Goals

One compute-family delivery implementation, immutable Agreement windows, activation
before billing and availability, stable effect recovery, classified end handoff,
and no credential replay after a locally admitted end.

No second end service, payment journal, dispute policy, billing horizon, renewal,
Alkahest dispute adapter, or broader obligation-discovery/evidence extraction.

## Decisions

### D1. A separate compute-family delivery distribution and one record

**Recommendation (02 F5/F11/F12):** create the library distribution
provisioning/compute/delivery, source compute_delivery, rather than add commercial
orchestration to arkhai-compute-provisioning. It depends on compute contracts/client
interfaces and neutral lifecycle libraries, not storefronts or deployed services.
Teach scripts/architecture.py the normal compute-family provisioning subtree
classification and register that convention in docs/development/ARCHITECTURE.toml;
do not add an override that closeout cannot discharge.
This avoids adding servicing/persistence dependencies to the site service's install.
The vocabulary-only domains/compute and neutral kit/fulfillment remain unsuitable.

The neutral authorization/effect protocols, phase vocabulary and opaque evidence
envelope belong in kit/deal-lifecycle; the foundation owns that shared port slice.
An envelope carries identity, digest, kind/version and a domain payload. Generic
servicing does not interpret compute payloads; a compute-scoped adapter validates
ready evidence and is injected by composition. No upward family import is required.

Each domain fulfillment hook delegates to this path through
StorefrontFulfillmentPorts. Core's identity validation remains in force.
Available maps to fulfilled; pending, persistence retry and repair-required map to
deferred (repair-required is operator-visible, never an automatic retry that invents
terms). A terminal result maps to failed only after the D5 handoff is durable.
Mechanism-specific evidence/claim continuations remain outside the shared path.

One negotiation-keyed record in the storefront database holds accepted window/site,
reservation/fulfillment IDs, decisions, intents, acknowledgements and checkpoints.
It holds no credentials, payment balances, final-request log or financial end.
End service owns the revision-bearing admission port and single end-plus-optional-
self-filing operation from agreed-evidence-and-early-termination. Delivery consumes
those operations in the same storefront transaction for admission/CAS; no transaction
spans remote I/O and neither owner imports the other's concrete repository.

**Recommendation (01 F6 / 02 F9): additive projection cutover.** Introduce the shared
record additively. Keep immutable evidence/exact requests and real Alkahest state in
their owners; make old VM delivery-progress rows read-only projections, not writers.
Under one migration transaction adopt negotiation, accepted digest/window, reservation
and fulfillment identities after authoritative reconciliation: held/committed -> exact
commit intent; dispatched -> dispatched; provider-ready -> ready evidence only.
Never infer activation, billing start or availability from old credentials or a
physical active flag. Revalidate live readiness, activation and admission before
availability. Ambiguous/missing/conflicting evidence stays repair-required and keeps
its resource. Already-disclosed access is not retroactively revoked by this migration.

Enable live result reads for adopted resources before deleting all stored access
material, including authenticated response bodies. Switch every foreground/recovery
writer together and record a minimum writer/schema version; old binaries refuse
startup after cutover. Downgrade requires a reviewed forward repair or explicit
development reset, never a silent return to old writers. This supersedes VM's
blanket reset-only delivery-schema rule, not its fail-closed evidence validation.

### D2. The Agreement window survives every retry

Commit lease_start_utc = Agreement.start_utc and lease_end_utc = start + duration,
at settlement, under the same reservation identity on every attempt. Terms owns
max_term_seconds == duration_seconds and whole-period maximums, not delivery.
No now/missing-duration fallback and no replacement resource on ambiguous old timing.
Late settlement shortens service, never shifts the absolute end.

**Recommendation (02 F2):** keep forward reservations, with zero early-provisioning
lead time in this plan: dispatch, activation, billing start and disclosure occur no
earlier than Agreement.start_utc. Before then, a committed deal is deferred with a
durable wake time and rechecks admission on wake. This avoids using hardware outside
the admission window; a future nonzero lead time would need explicitly accounted
capacity, not just a timer. Renewable anchors the provisional deadline at
max(commit_time, lease_start_utc) + allowance. Available never means early access.
Settlement after the end enters D5, without guessing which party caused lateness.

Reservation acknowledgement-gap recovery consumes the negotiation-keyed exact-request
idempotency slice of capacity-reservation-lifecycle-hardening. It is a section-1/2
implementation gate, not a dependency on that change's entire hardening scope.
Reserve, commit, schedule and begin all resolve the same authoritative identity.

### D3. Pure authorization and a separate billing-start effect

authorize_delivery(deal, phase) is a decision, not a payment mutation. Phases are
commit, dispatch, start and disclose. Each attempt durably records allow/refuse/
pending, reason, operation ID and evidence references before use. Start means
permission to attempt billing start, not the start effect itself. Unknown authority
outcomes stay pending. The prepaid hook performs no additional financial action;
it does not bypass selected-stage typed/versioned commitment evidence validation.

Every protected transition, activation included, rechecks foundation admission
and its revision; a financial allow never overrides a local due end.
D7 reuses that port for subsequent credential reads.

After ready evidence and activation, invoke start_billing(effect_id, evidence)
separately. The path persists one stable effect intent/key before calling.
Rate servicing implements it through the seller half/payment adapter under the
supplied key, derives per-part keys deterministically, and resolves unknown outcomes
without allocating another start identity. Its existing effect journal is a replay
implementation of this intent, not an independently keyed delivery decision.
Prepaid start_billing is a no-op and creates no artificial once-part start.

The family supplies commitment and fulfillment identities plus validated ready-
evidence digest/envelope, never access secrets. Converge owns rate authorization,
authority start/stop/pending-stop interpretation and the start-port implementation;
spot-deals owns adapter/part translation. Their requirements are referenced, not
copied here. Neither a funded horizon nor a payee vouch is required.
A remote authority read and local admission are not globally atomic.

### D4. Acknowledged checkpoints and recoverable effect intents

| Checkpoint | Meaning / recovery |
|---|---|
| authorized | commit decision and exact commit intent durable; resolve same reserve/commit |
| dispatched | fulfillment dispatch acknowledged; query/adopt the recorded fulfillment |
| activated | validated provider readiness and site activation acknowledged; preserve any earlier end |
| started | billing-start effect acknowledged (verified authority record for rate; no-op for prepaid) |
| available | disclose authorization and readiness durable; no buyer read required |
| converged | selected stage's required evidence/readiness/claim-binding continuation acknowledged, or explicitly no continuation for that stage |

Order: commit gate/commit; wait until start; dispatch gate/dispatch/ready; local
admission/activate; start gate/start_billing; disclose gate/available; converged.
The old ambiguous delivery active name is retired; physical active and site
renewal_phase active remain their owners' distinct facts. Converged does not wait
for unrelated collection/payout or move claims-engine submission into delivery.
Access uses available/converged and D7, not convergence alone.

Persist intents before remote reserve, commit, dispatch, activation and billing
calls. Acknowledgements advance checkpoints. Recovery checks authority state under
the same keys and repeats admission at every gap. Required writes defer effects;
bookkeeping alone never abandons a running resource. Local claim expiry permits
recovery, not duplication. This change recovers each checkpoint effect.
Kit-owned listing/fulfillment lifecycles owns obligation discovery and terminal
driving across mechanisms, and consumes this path rather than reimplementing it.

### D5. Classified delivery-end handoff, never a refund implementation

Supply cause, actor, source, accepted start, observed failure time, identities and
evidence to the foundation's single end-plus-optional-self-filing operation.
That owner selects/records the earliest final request and journals filing atomically.
Delivery neither writes a second end log nor computes amounts or payment corrections.

| Observed cause before availability | Earlier controlling end | Caller handoff |
|---|---|---|
| Buyer end_delivery, entitled authority stop, terms end, or ruling | Same or earlier lawful request | Reuse/request end only; no seller self-penalty merely because not yet available |
| Seller-side provisioning failure, terminal start refusal, activation lapse | No lawful end preceding failure | Seller-failure classification with evidence for exceptional_end |
| Seller failure discovered after an already controlling lawful end | Earlier buyer/terms/ruling request | Preserve attribution; do not manufacture a second undelivered penalty |
| Settlement observed after the window with no prior end/failure record | No independently established prior cause | Request end at term; supply never-delivered evidence for cooperative self-filing, not a guessed buyer-fault exemption |

**Recommendation (01 F4 / 02 F2/F8):** for genuinely never-delivered failure the
foundation uses at = min(Agreement.start_utc, failure_observed_at). Persist that
instant with the failure; retry does not recompute now. Before a future start this
is a valid immediate intent and returns the entire unserved term/setup share; after
start it preserves the original start basis. Delivery supplies both instants rather
than silently clamping authority commands. Foundation/dispute policy owns that mapping.
A prior term end does not erase an already established seller non-delivery obligation.
Reject an unsupported assertion of buyer-caused lateness as a reason to keep payment:
only authority records and kept signed bytes establish buyer actions.

No-dispatch proof permits end service's release without teardown; dispatched work
is adopted and ended, not replaced. The site report is end intent/evidence, not proof
of hardware release. Proven release is a separate completion fact. Physical recovery
does not wait for authorities. The dispute authority, not this path, applies any
stop/reversal under held money. Setup ends at activation under the foundation;
its unserved-share rule is not delivery arithmetic.

An Alkahest deal with no adapter reports unsupported self-filing and retains its
existing recovery/reclaim semantics; no fictitious authority success is reported.
After availability, foundation's actual service-end rule applies instead.
Cooperative seller filing is not a guarantee about arbitrary sellers.

### D6. Reservation-only activation before billing

Activate after provider-ready evidence, no earlier than Agreement start, and before
billing start and availability. The request names only the reservation.
Validate the site's returned end against the immutable commit end or a verified
earlier end recorded by end service. An unexplained mismatch is repair-required;
a valid earlier truncation is adopted, never extended to the original Agreement end.
The active instant is the site's fact. Journal/retry unknown acknowledgements under
the same identity; expiry claimed first refuses activation and enters D5.
A truncation before activation or between a lost acknowledgement and retry must
survive unchanged. Never activate to a funded horizon.

**Recommendation (02 F4): staged enablement.** Renewable ships the explicit compute
composition safeguard switch off, while provider support/default validation remains.
This change owns enablement only after every storefront/recovery caller is deployed.
Deploy compatible storefronts first, then the updated site with the switch off;
qualify callers, then enable for new commits. Existing null-phase leases stay null.

For a verified legacy null-phase leased view, activation is a no-op; an absent
activation route is tolerated only with that verified legacy view/capability.
An awaiting-activation lease with no route, unknown phase, unverified legacy
assumption, or an end mismatch is deferred repair-required. Never guess that an
unreachable activation endpoint succeeded. This permits rolling deployment without
unactivated delivered leases being reclaimed. Site-only evidence cannot enable it.
Renewal remains a deferred seller-side option, not buyer protection.

### D7. Live credential reads, including authenticated replay

VM settle/settle-status remains its buyer access surface: fetch live through the
shared guard while preserving the existing response model. Bare metal's access/
result surface uses the same guard. VM buyer's hosted path and core buyer's
orchestrator continue polling the typed settle-status contract; no new endpoint,
CLI or persisted-credential fallback is introduced. Coordinate client changes with
buyers-use-the-storefront-client if that change lands first.

Require available/converged, start reached and foundation's local time/revision
admission. Fetch provider credentials outside the transaction, then recheck the
revision and due end before signing/authorizing the response. Discard fetched bytes
if an end wins. Physical termination revokes previously disclosed material.

Both VM seller_auth and bare-metal response_auth must exempt credential-capable
settle/status/access/result responses from retained response bodies. Retain the
request digest/identity needed to reject changed requests, and response signing;
exact retry re-enters the read/guard and may now be refused. Existing cached access
bodies are purged at cutover; no credentials appear in replay storage, decisions,
logs or projections. Replay of mutation acknowledgements is otherwise unchanged.
Coordinate this narrow policy with redesign-authenticated-requests; do not wait on
that whole redesign or weaken changed-request rejection.

No payment snapshot on each read. Local authorization, not receipt of in-flight
bytes or an absolute remote-stop access bound, is the guarantee. Watch turns remote
authority stops into local ends. Foundation supplies ordering, not another cache.

## Ownership and dependency gates

- Foundation: neutral delivery ports/evidence envelope, revision-bearing admission,
  one end-plus-filing operation and cause/timing semantics. No local substitutes.
- Renewable: activation/conditional expiry/report extension; transitively requires
  inject-site-pool-authority. This change owns final deployed safeguard enablement.
- Capacity-reservation-lifecycle-hardening: negotiation-keyed reserve replay slice.
- Converge and spot-deals: rate decisions/effects/adapters. Prepaid implementation
  need not wait for rate qualification; publication stays fail-closed until composed.
- Add-arkhai-payments-lane-double: HTTP lane qualification in tasks 3.3/4.3/4.4.
  Library integration uses in-process contract fakes from the same vectors, not a
  tooling dependency.
- Kit-owned listing/fulfillment: broader convergence discovery/terminal driving,
  dependent on this path for protected-effect recovery and access retirement.

## Rejected alternatives

- Provisioning base-kit placement: unnecessary lifecycle/persistence install weight.
- Start hidden in authorization or before activation: ambiguous keys and avoidable
  billing-before-expiry races; start is a separately keyed post-activation effect.
- Early dispatch without accounted lead-time capacity: can exceed the agreed window.
- Restoring the original end on activation: resurrects an earlier admitted end.
- Self-penalty for every refused transition: conflates lawful ends with seller failure.
- A buyer-fault guess for late settlement: no authority-backed evidence supports it.
- Billing horizons, local notice schedulers, direct refunds and a second end journal:
  contradict the authority boundary. Authority stops/holds/cases protect buyers.
- Retained credential-response replay: bypasses local admission after an end.

## Open questions

No unowned design choice in this change. Recommendations above are the defaults
supplied under owner delegation. Reverify exact neutral-port names and schema
bindings when the foundation lands; a missing port remains a gate, not license to
implement it twice. Obtain another design review before planning because placement,
cutover, timing and effect ordering changed materially.

## Design promotion record

Planned, not current-state documentation:

| Accepted decision | Permanent destination |
|---|---|
| D1 distribution, neutral protocol boundary, core hook | docs/development/ARCHITECTURE.md (Family kits, Fulfillment), ARCHITECTURE.toml; compute-delivery architecture |
| D1 additive adoption, credential retirement, downgrade refusal | vm-storefront-fulfillment spec/architecture; compute-delivery spec/architecture |
| D2 windows and future starts; D3 ports; D4 checkpoints/recovery | compute-delivery spec/architecture; fulfillment architecture (boundary only) |
| D5 caller classification | compute-delivery spec/architecture; reference deal-lifecycle policy |
| D6 activation/enablement; D7 access and replay | compute-delivery spec/architecture; vm-storefront-fulfillment; docs/development/DEPLOYMENT_AND_CONFIG.md; ARCHITECTURE.md authority/results sections |
| Capability index | openspec/specs/README.md adds compute-delivery |
| Goal/campaign currency | ROADMAP.md Goal 8 and missing-start-at-commit row; changes/README.md dependency/status rows |
