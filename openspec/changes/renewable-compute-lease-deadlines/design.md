# Design — compute lease delivery deadlines

## Context

`kit/site` owns the capacity reservation and agreed lease window. Its commit is
idempotent, truncation only moves the end earlier, and admission accounts the full
agreed window. `list_lease_due` currently selects leased rows by `lease_end_utc`;
compute's lease lifecycle begins release and performs provider work outside the
ledger transaction. API credits commits quota holds with no lease end.

A storefront that dies before delivery can therefore hold compute capacity until
the maximum term. A delivery deadline on the unactivated lease closes that gap, and
the same number is the buyer's term. After activation, storefront liveness remains
the seller's risk: an operating resource is not reclaimed simply because storefront
bookkeeping has stopped. The activation phase and transition the deadline is written
against are `activate-compute-leases-at-the-site`'s, which lands first and reads no pool policy; this
change writes the deadline at commit and expires the lease that never activates.

The lifecycle frame is `agreed-evidence-and-early-termination`: commitment makes
the agreement binding; end service realizes the earliest final request, and money
moves only at the payment and dispute authorities. A site's signed statement is
kept evidence, not a new authority record. These authority boundaries and the
deadline-only scope are settled.

## Goals / Non-Goals

**Goals:** bound capacity held between site commit and delivery; make activation
and expiry race safely; keep payment classifications out of the site; leave old
leases and API-credit quota holds unchanged.

**Non-goals:** the activation phase, transition and typed contract (`activate-compute-leases-at-the-site`), renewal of active leases, lease extension, payment
or refund operations, and delivery caller wiring.
This is a recommended cooperative seller implementation, not a protocol requirement
that a buyer may assume an arbitrary seller obeys.

## Decisions

### D1. The deadline written at commit

The nullable `renew_by_utc` and `renewal_phase` columns, the `active` phase and the
activation transition are `activate-compute-leases-at-the-site`'s (its D1). This change writes
`awaiting_activation` and the deadline into them at commit; activation, as that change
defines it, replaces the deadline with the agreed end.

- On first commit with a resolved delivery deadline, record `awaiting_activation` and
  `renew_by_utc = max(committed_at_utc, lease_start_utc) + delivery_deadline_seconds`,
  where `delivery_deadline_seconds` is the deal's accepted value, supplied with the
  commit as a fact of the deal like its window, and the pool's current effective value
  is its ceiling: the site refuses a commit whose accepted deadline exceeds what the
  pool now grants, or that carries one where the pool now enforces none, since the
  seller cannot ask its site for more time than the site gives — a refusal that
  delivery classifies as seller failure before dispatch: no provisioning occurs, and the
  reservation the storefront already holds is released through the foundation's
  no-dispatch path (unify D5), not by the site on refusal. A pool
  lengthened after acceptance changes nothing for the deal; a pool shortened below an
  accepted deal's value refuses that deal rather than reclaiming it early, and the
  listing republishes with the new value. A commit carrying no accepted deadline (a
  buyer that opted out of the term) takes the pool's current policy as the site's own
  capacity safeguard. `committed_at_utc` is the deal's commitment instant the storefront
  supplies with the commit — the payment authority's record of the buyer's approval on a hosted
  deal, the mechanism's commitment act otherwise. The site refuses an anchor after its
  own clock and can verify nothing else about it: it knows no payment mechanism, so the
  anchor is the storefront's word. The site's deadline is therefore the seller's own
  capacity safeguard — it reclaims a lease its storefront never activated — and not the
  buyer's guarantee of the accepted deadline; a storefront that sits on an approved deal
  and supplies a later anchor lengthens its physical deadline, not its promise. The
  buyer's deadline is judged by the dispute authority from the payment authority's own
  approval record and the Agreement, and the storefront's journaled commit, with the
  anchor it supplied, is evidence against it where the two disagree.
  This protects a forward reservation without expiring it before its admitted start;
  unify defers dispatch/activation/access until that start (no early lead time).
- Commit retried in either phase leaves the original deadline and phase unchanged;
  activation (`activate-compute-leases-at-the-site` D1) replaces the deadline, earlier or later,
  with the reservation's current `lease_end_utc`.
- Truncation caps a non-null deadline to the new end. The due instant is the earlier
  of the agreed end and a non-null deadline. After activation those instants coincide.
- Admission always accounts against the agreed window. The earlier activation
  deadline does not free capacity for a future reservation before release succeeds.
- A pool resolving no delivery deadline records neither field; its leases continue
  to expire only at their end, and activation leaves them as the activation change
  says. This is not a billing classification. **Recommendation:** a pool resolving a delivery deadline requires a
  finite end at commit; unsupported open-ended use is refused rather than creating
  an unbounded activation.

`unify-compute-delivery-path` orders activation with its delivery and
access-disclosure gates for every caller and recovery path, and wires every caller
before this change's switch is enabled.

### D2. Expiry claims the deadline and phase it read

The due query returns the agreed end, deadline and phase that made the row due,
plus whether the cause is activation lapse or ordinary term end. Before a teardown
side effect, expiry conditionally claims `state == leased` and exact equality of
that observed tuple inside the ledger's serialized transaction. If activation or
truncation changed the tuple, the claim fails with no event, outbox item or provider
call; the next pass reevaluates. A matching claim begins `releasing`; activation
then cannot undo it. No database lock spans a provider call.

**The deadline is enforced by the claim, not by the clock.** Activation after an
elapsed deadline is allowed while the row remains unclaimed; it is a capacity fact
and not delivery — the lifecycle classifies a deal whose buyer could not use the
resource by the accepted deadline as non-delivery whatever the site's phase, and
starts no new billing on it (foundation D8). Refusing it merely
because a watchdog poll has not happened would turn poll latency into an eviction.
The agreed end remains an independent bound, so activation never extends service
past it. On a tie between activation deadline and term end, report ordinary term
end (recommendation: it avoids attributing an unavoidable term end to failed delivery).

The claim condition supplements the existing release guard: it does not permit
freeing capacity while a create is in flight or teardown is unproven. It must be
carried through direct release, deferred release and failure paths, not checked
only after a provider action.

### D3. Provider-declared delivery deadline, read through the pool port

`delivery_deadline_seconds` is a Resource Pool policy tag: the seconds after
max(commitment instant, lease start) within which the site activates the lease, the site's reclaim rule for a lease never activated. It is
also the buyer's term: the storefront publishes the pool's effective value as the
option's `lifecycle.delivery_deadline_seconds` (foundation D5), under the same name,
and the site enforces exactly what was accepted, bounded by its own current policy
(D1), from an anchor it cannot verify. The site's deadline is the seller's safeguard
against its own storefront's absence; the promise the buyer read is checked by the
dispute authority against the payment authority's approval record, which the buyer
holds. It is not money or a minimum spend. The two
readings of the tag — publication's and commit's — can differ when an operator edits
it between them; the accepted value wins where the pool still grants it, and the
commit is refused where it does not, so no deal is silently given more time than it
promised or less than it was promised.
Each provider declares, as plain composition-supplied data, whether it supports
a delivery deadline and its default. Compute providers `vm.ansible` and
`bare_metal.ansible` declare one; the API-credits provider declares none.

**Recommendation:** initial defaults are 1800 seconds for VM and 7200 seconds for
bare metal, reflecting different provisioning paths. They are operator-tunable
recommendations, not protocol bounds or a claimed measured SLA. Packaged compute
seed pools state those defaults. A later default edit does not reset deadlines
on committed leases.

**Recommended validation:** a supporting provider's pool may override the default
with a positive integer number of seconds. Absence means use the provider default, not disable protection;
zero, negatives, booleans, fractional values and null are refused at create,
replace, patch and document import. A provider declaring none resolves no delivery deadline
and refuses an explicit override. Validation-only and applying writes agree and
imports remain atomic. Commit snapshots the resolved duration into its deadline;
later pool edits do not alter existing leases.

**Recommendation (unify 02 F4):** add the explicit compute-composition setting
`activation_deadlines_enabled`, default false. Provider support/defaults and pool
validation remain declared even while disabled; an invalid override never becomes
valid because the switch is off. The injected pool-facts port resolves no effective
delivery deadline while disabled, so new leases retain null deadline/phase. This is an
operator composition setting, not a pool tag or caller-supplied commit flag. Enabling
applies only to new commits; disabling does not clear deadlines already snapshotted.

The session-scoped pool-facts port from `inject-site-pool-authority` supplies the
effective delivery deadline in the commit transaction. The site does not import the pool
authority or infer a provider from a domain or billing kind. API-credit quota holds
therefore receive no deadline by the same generic rule, with no site exemption.
If the dependency stalls, reconsider the port contract with its owner; passing a
storefront-selected delivery deadline is not an authorized fallback. The storefront
supplies the anchor instant, a fact of the deal like the window; the duration is the
pool's alone, and publication reads it through the same port.

A delivery-deadline overrun enters ordinary guarded release. The storefront supplies
classified failure evidence to the foundation's single end-plus-optional-filing
operation. The foundation owns cause classification and the financial intent's
fixed timing basis. Consume D8's pre-start exception (journal now, act at accepted
start), never a future-dated command. The final owner supersession restores
exceptional_end as the seller's dispute-adapter filing, journaled with the end;
the seller sends no stop/reverse. Mediation alone mechanically rules its standard-
or-stronger self-penalty request, not buyer_end, which goes to human triage. The site
computes no financial instant/amount and its report is not a refund prerequisite.
The caller supplies verified buyer/ruling/payment evidence for classification;
term clock or payee stop alone does not erase established non-delivery. Rate billing
starts after ready evidence and activation in unify; the deadline authorizes no billing.

### D4. Renewal and renewal-lapse policy are deferred seller options

**Revisit condition:** a site operator separate from the storefront operator needs
to bound its exposure to an absent storefront. This is the seller's choice about
its hardware, not a buyer, payment-authority or dispute-authority requirement.
No renewal API, renewal timer or lapse-policy tag ships in the present change.

Retained option for that future design:

- An active lease may carry an independent renewable deadline, separate from the
  agreed end. Renewal from `leased` / `active` moves it later only, never beyond
  that end; it is refused after release is claimed. A stale renewal cannot shorten
  or resurrect a lease. Admission still uses the full agreed window.
- Expiry compares the observed deadline and phase as in D2. An elapsed but unclaimed
  deadline may be renewed. Activation and renewal remain distinct transitions;
  a future activation target would need its own explicit design, never a payment
  fact inferred from this option.
- A site-selected pool policy could be `reclaim` (release on lapse), bounded
  `grace` (release later, with the duration and effective deadline visible), or
  `continue` (serve to the agreed end). A site-wide default and any maximum grace
  are choices for that future design. The site need not know why renewal lapsed.
- The view and physical-end record would expose the deadline, phase, policy and
  cause `renewal_lapsed`. They would remain evidence, never a billing stop.

**Cost of active reclaim:** `reclaim` can destroy a working VM merely because the
storefront crashed. Billing does not stop on site silence or on that reclaim.
Honest recovery files `exceptional_end(at)` at the physical end through the dispute
adapter: mediation rules the self-penalty, including the premature-stop penalty
capped by earned amounts still held after refunds; bond award is reserved for hosted bonds, even though the original failure was only bookkeeping.
`grace` only delays that cost; `continue` leaves unpaid-service exposure with the
seller until the agreed end or a recovered end-service action. None is a buyer
guarantee. Renewal must be justified by a separate operator's concrete needs before
this trade-off is reintroduced.

### D5. Lease-end intent evidence

The foundation supplies the signed `lease_ended` record and durable outbox; this
change adds `activation_deadline_lapsed`. The record carries the reservation/deal
correlation, the claimed deadline and phase, and the base report's intended effective end instant.
The report is recorded before teardown: it is not proof of physical completion.
Proven guarded release remains a separate completion fact, including on failures. The deadline is the reason release was claimed,
not a fabricated instant of proven VM teardown. A term end that wins the due
comparison keeps its ordinary cause. Retrying the event preserves its identity
and signed content; the evidence store keeps the original bytes.

The site and compute lease views (`activate-compute-leases-at-the-site` D2) already expose
`renew_by_utc`, `renewal_phase` and the active instant; this change adds nothing to
them and exposes no renewal-lapse policy, because none is implemented. End service may consume the site's report as a local final request
with actor, cause and source; the payment/dispute adapters still own all financial
actions. This cause does not require an event before the seller files for failed
delivery. Delivery admission must also honor an expiry claim that wins activation.

## Rejected alternatives

- Billing horizon or payee-advanced vouch — protects only an honest crashed seller,
  not a dishonest seller; the buyer's own stop and disputes over held money suffice.
- Funded-horizon activation or active renewal now — conflates the seller's internal
  lease policy with payment; activate every deal to its agreed end and defer renewal.
- Site-event-triggered refund — the foundation classifies delivery failure and
  supplies a valid command instant, with the buyer's case as backstop; reports are evidence.
- Seller-direct exceptional-end correction or backdated payee stop — the seller
  files a dispute, not its own stop/reverse, and mediation alone applies the standard
  self-penalty (`openspec/changes/agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`).
- Compound payment termination authority — deferred until hosted bonds are designed;
  foundation records this alternative and its required dispute-authority recording,
  not a new site capability.
- Minimum-spend requirement — churn is the seller's pricing/acceptance choice;
  a setup `once` part is the recommended default, not a site delivery-deadline rule.
- A seller-internal deadline the buyer never reads (this design's first form, replaced
  2026-10-29) — a buyer could not tell a short horizon from an undeliverable one, and a
  seller activating late inside a long term had not failed; the pool's tag is now the
  value the option publishes, under one name, and the deadline's anchor is the deal's
  commitment instant rather than the storefront's own commit time.
- Storefront-local scheduled stop — authority-hosted pending stops survive a dead
  storefront; the site deadline schedules neither notice nor billing.
- One monotonic deadline from commit — activation may need to move the provisional
  deadline earlier or later to the agreed end; only later renewals would be monotonic.
- Deadline as a movable agreed end, or a separate cap over it — changes admission
  meaning and requires extension; keep the agreed end and provisional deadline distinct.
- Open-ended compute commit with eventual storefront truncation — a dead storefront
  leaves capacity unbounded; a finite agreed end remains required for these pools.
- Provider calls under a row lock — release orchestration keeps external calls
  outside transactions; compare-and-set claims provide the race boundary.
- Clock-only activation refusal — makes watchdog latency evict a resource whose
  expiry has not been claimed; claim order decides.
- Shipping the activation transition in this change (its first form, split
  2026-10-29) — the transition reads no pool and four changes need it before the
  pool-authority port lands; it is `activate-compute-leases-at-the-site` and this change
  depends on it.
- Commercial flag on commit — the provider/pool delivery deadline is sufficient and leaves
  the site independent of billing shape.
- Site-wide delivery deadline, reuse of hold TTL, or no deadline until billing starts —
  ignores provider differences or leaves the commit-to-delivery gap unbounded.
- Storefront-selected grace as buyer protection — no seller-local lapse policy
  supplies an authority-backed billing guarantee; the whole renewal policy is deferred.

## Implementation cadence and gates

One site-focused implementation round after `inject-site-pool-authority` and
`activate-compute-leases-at-the-site`: delivery-deadline validation/provider declarations, the
commit snapshot, conditional expiry and the lapse cause. Reservation acknowledgement-gap qualification consumes only
`capacity-reservation-lifecycle-hardening`'s negotiation-keyed exact-request
reservation-idempotency slice, not its whole implementation or archive; site-local
activation work can proceed before that integration gate. Event integration waits for `agreed-evidence-and-early-termination`'s signed
record/outbox. `unify-compute-delivery-path` lands before this change and has wired
every caller through the activation change's contract, so this change owns its own
enablement: it ships `activation_deadlines_enabled` false, qualifies every already
wired commit and recovery caller in explicitly enabled owned lanes, then changes the
repository composition default; hosted operators independently confirm readiness. Public evidence records
readiness and public release versions, not hosted target identifiers.
New storefronts treat verified null-phase legacy leases as already active/no-op;
absence of an activation route is tolerated only with a verified legacy view.
A protected/unknown phase without activation support is repair-required. Existing
null-phase leases remain unchanged when enabling. Site-only evidence never enables
protection or proves campaign readiness. This avoids a whole-change dependency cycle.

## Coordinated first-review triage

The unify review's 01 F3 / 02 F1 are resolved by reservation-only activation and
explicit truncation/lost-acknowledgement scenarios. Its 01 F4 / 02 F2 are resolved
by the max(commitment,start) deadline anchor, zero early-dispatch lead time at the
caller, and foundation-owned valid pre-start command journaling (act at accepted start). Its 02 F4 is
resolved by the off-by-default composition switch and unify-owned final enablement.
The owner additionally fixes the distinction between site end intent and proven
physical completion (D-G), and activation-before-billing order (D-F). These are
coordinated design edits, not evidence that caller or site code is implemented.
That review requested a coordinated re-check before advancement; the focused
cross-change re-check below resolves it. The review/triage records live with unify,
which owns those findings.

## Coordinated second-review triage

Unify 04 F9 splits enablement into owned-lane qualification with the switch on and
only then unify's repository composition-default edit. Renewable's introduced default
remains false; its resource-pool requirement is amended by unify after qualification.
Unify 03 F2 / 04 F8 strengthens the hardening slice to normalized exact-request/state
reconciliation; expired unresolved reserve effects cannot silently create a hold.
The final owner decision supersedes E-A/E-C/E-E as amended and the restitution-entry/
favourable-stop notes: activation lapse is evidence for journaled exceptional_end
filing through the dispute adapter, not seller payment self-correction. Mediation
alone mechanically rules the standard-or-stronger seller self-penalty. No site payment
logic or new buyer guarantee is introduced. "Won't preempt" is enforced by remedy
over held money plus the premature-stop penalty, not the mandate. end_delivery has no at and gives signed
receipt evidence only; the buyer half owns payment-stop retry while billing continues
until it lands, with optional buyer_end human triage. Restitution stop entries,
notice waiver/early release and multiple-stop-entry gates were removed; seller stops
are entitlements only, and a spot seller's emergency exit is a filing. The focused
cross-change re-check leaves implementation ready subject to the recorded section gates.

## Open questions

None in the active scope. Default values, strict override validation, finite-end
refusal, tie attribution, forward-start anchor and off-by-default composition
switch above are recommendations supplied by this design;
implementation re-verifies them against
the landed dependency interfaces. D4's policy choices remain explicitly deferred.

## Permanent documentation destinations

| Accepted decision | Destination |
|---|---|
| D1, D2 deadline, claim and admission | `openspec/specs/site-capacity/spec.md` and `openspec/specs/site-capacity/architecture.md`; capacity reservation in `docs/development/ARCHITECTURE.md` |
| D3 | `openspec/specs/resource-pool-management/spec.md`; pool policy configuration in `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D5 watchdog/event | `openspec/specs/physical-provisioning/spec.md`; recovery workers in `docs/development/ARCHITECTURE.md` |
| D4 deferred renewal | Remains in this change; not promoted as current behavior |

Directory naming: `renewable-compute-lease-deadlines` stays the campaign identifier
while the active proposal is the delivery deadline alone; a rename would touch every
sibling without changing the acceptance boundary.
