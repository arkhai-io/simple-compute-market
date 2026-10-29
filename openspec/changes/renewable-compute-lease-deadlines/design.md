# Design — compute lease activation deadlines

## Context

`kit/site` owns the capacity reservation and agreed lease window. Its commit is
idempotent, truncation only moves the end earlier, and admission accounts the full
agreed window. `list_lease_due` currently selects leased rows by `lease_end_utc`;
compute's lease lifecycle begins release and performs provider work outside the
ledger transaction. API credits commits quota holds with no lease end.

A storefront that dies before delivery can therefore hold compute capacity until
the maximum term. An activation deadline closes that seller-internal gap. After
activation, storefront liveness remains the seller's risk: an operating resource
is not reclaimed simply because storefront bookkeeping has stopped.

The lifecycle frame is `agreed-evidence-and-early-termination`: commitment makes
the agreement binding; end service realizes the earliest final request, and money
moves only at the payment and dispute authorities. A site's signed statement is
kept evidence, not a new authority record. These authority boundaries and the
activation-only scope are settled.

## Goals / Non-Goals

**Goals:** bound capacity held between site commit and delivery; make activation
and expiry race safely; keep payment classifications out of the site; leave old
leases and API-credit quota holds unchanged.

**Non-goals:** renewal of active leases, lease extension, payment
or refund operations, buyer-facing provisioning promises, and delivery caller wiring.
This is a recommended cooperative seller implementation, not a protocol requirement
that a buyer may assume an arbitrary seller obeys.

## Decisions

### D1. A lease deadline beside the agreed end, with an activation phase

Keep the original design's nullable `renew_by_utc` and `renewal_phase` fields.
The names do not imply an active renewal operation: only activation ships here.
`lease_end_utc` keeps meaning the agreed end and moves only through truncation.

- On first commit with a resolved allowance, record `awaiting_activation` and
  `renew_by_utc = max(commit_time, lease_start_utc) + provisioning_allowance_seconds`.
  This protects a forward reservation without expiring it before its admitted start;
  unify defers dispatch/activation/access until that start (no early lead time).
- Activation is one conditional transition from `leased` and
  `awaiting_activation` to `active`. It replaces the deadline, earlier or later,
  with the reservation's current `lease_end_utc`. **Every deal activates to that
  end**, including reserved, on-demand, spot and Alkahest. The request names the reservation, not a payment fact or target time.
- Activation retried in `leased` / `active` returns the current lease unchanged.
  Commit retried in either phase likewise leaves the original deadline and phase
  unchanged. Activation from `releasing`, terminal, failed-release or operator-owned
  states is refused without a write: it cannot resurrect a lease.
- Truncation caps a non-null deadline to the new end. The due instant is the earlier
  of the agreed end and a non-null deadline. After activation those instants coincide.
- Admission always accounts against the agreed window. The earlier activation
  deadline does not free capacity for a future reservation before release succeeds.
- Migration leaves both fields null on existing leases. A pool resolving no
  allowance records neither field; its leases continue to expire only at their end.
  An activation call on such a lease returns it unchanged. This is not a billing
  classification. **Recommendation:** a pool resolving an allowance requires a
  finite end at commit; unsupported open-ended use is refused rather than creating
  an unbounded activation.

The phase is not a reservation state. `awaiting_activation` avoids reviving the
retired `provisioning` state. Fulfillment's active instant remains the site fact
recorded when the resource becomes usable; activation does not move that instant
on retry. `unify-compute-delivery-path` orders activation with its delivery and
access-disclosure gates for every caller and recovery path.

### D2. Expiry claims the deadline and phase it read

The due query returns the agreed end, deadline and phase that made the row due,
plus whether the cause is activation lapse or ordinary term end. Before a teardown
side effect, expiry conditionally claims `state == leased` and exact equality of
that observed tuple inside the ledger's serialized transaction. If activation or
truncation changed the tuple, the claim fails with no event, outbox item or provider
call; the next pass reevaluates. A matching claim begins `releasing`; activation
then cannot undo it. No database lock spans a provider call.

**The deadline is enforced by the claim, not by the clock.** Activation after an
elapsed deadline is allowed while the row remains unclaimed. Refusing it merely
because a watchdog poll has not happened would turn poll latency into an eviction.
The agreed end remains an independent bound, so activation never extends service
past it. On a tie between activation deadline and term end, report ordinary term
end (recommendation: it avoids attributing an unavoidable term end to failed delivery).

The claim condition supplements the existing release guard: it does not permit
freeing capacity while a create is in flight or teardown is unproven. It must be
carried through direct release, deferred release and failure paths, not checked
only after a provider action.

### D3. Provider-declared provisioning allowance, read through the pool port

`provisioning_allowance_seconds` is a Resource Pool policy tag: allowance after
max(commit time, lease start) to activation, not money, minimum spend, a listing term or a buyer SLA.
Each provider declares, as plain composition-supplied data, whether it supports
an allowance and its default. Compute providers `vm.ansible` and
`bare_metal.ansible` declare one; the API-credits provider declares none.

**Recommendation:** initial defaults are 1800 seconds for VM and 7200 seconds for
bare metal, reflecting different provisioning paths. They are operator-tunable
recommendations, not protocol bounds or a claimed measured SLA. Packaged compute
seed pools state those defaults. A later default edit does not reset deadlines
on committed leases.

**Recommended validation:** a supporting provider's pool may override the default
with a positive integer number of seconds. Absence means use the provider default, not disable protection;
zero, negatives, booleans, fractional values and null are refused at create,
replace, patch and document import. A provider declaring none resolves no allowance
and refuses an explicit override. Validation-only and applying writes agree and
imports remain atomic. Commit snapshots the resolved duration into its deadline;
later pool edits do not alter existing leases.

**Recommendation (unify 02 F4):** add the explicit compute-composition setting
`activation_deadlines_enabled`, default false. Provider support/defaults and pool
validation remain declared even while disabled; an invalid override never becomes
valid because the switch is off. The injected pool-facts port resolves no effective
allowance while disabled, so new leases retain null deadline/phase. This is an
operator composition setting, not a pool tag or caller-supplied commit flag. Enabling
applies only to new commits; disabling does not clear deadlines already snapshotted.

The session-scoped pool-facts port from `inject-site-pool-authority` supplies the
effective allowance in the commit transaction. The site does not import the pool
authority or infer a provider from a domain or billing kind. API-credit quota holds
therefore receive no deadline by the same generic rule, with no site exemption.
If the dependency stalls, reconsider the port contract with its owner; passing a
storefront-selected allowance is not an authorized fallback.

An allowance overrun enters ordinary guarded release. The storefront supplies
classified failure evidence to the foundation's single end-plus-optional-self-correction
operation. The foundation owns cause classification and the financial intent's
fixed timing basis. Consume D8's pre-start exception (journal now, act at accepted
start), never a future-dated command. E-C makes exceptional_end a seller payment-
adapter self-correction, not a dispute or mechanical mediation ruling. The site
computes no financial instant/amount and its report is not a refund prerequisite.
The caller supplies verified buyer/ruling/payment evidence for classification;
term clock or payee stop alone does not erase established non-delivery. Rate billing
starts after ready evidence and activation in unify; allowance authorizes no billing.

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
Honest recovery is `exceptional_end(at)` at the physical end: a self-penalty, including
awarding any bond in full, even though the original failure was only bookkeeping.
`grace` only delays that cost; `continue` leaves unpaid-service exposure with the
seller until the agreed end or a recovered end-service action. None is a buyer
guarantee. Renewal must be justified by a separate operator's concrete needs before
this trade-off is reintroduced.

### D5. Lease-end intent evidence and lease inspection

The foundation supplies the signed `lease_ended` record and durable outbox; this
change adds `activation_deadline_lapsed`. The record carries the reservation/deal
correlation, the claimed deadline and phase, and the base report's intended effective end instant.
The report is recorded before teardown: it is not proof of physical completion.
Proven guarded release remains a separate completion fact, including on failures. The deadline is the reason release was claimed,
not a fabricated instant of proven VM teardown. A term end that wins the due
comparison keeps its ordinary cause. Retrying the event preserves its identity
and signed content; the evidence store keeps the original bytes.

The site and compute lease views expose `renew_by_utc`, `renewal_phase`
and the existing active instant. No renewal-lapse policy is exposed because none
is implemented. End service may consume the site's report as a local final request
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
- Backdated/effective-time payee stop — stops are never backdated; the seller's
  payment adapter stops now with partialPeriod returned and reverses held earnings
  since at as self-correction, separate from a buyer's dispute.
- Minimum-spend requirement — churn is the seller's pricing/acceptance choice;
  a setup `once` part is the recommended default, not a site allowance rule.
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
- Commercial flag on commit — the provider/pool allowance is sufficient and leaves
  the site independent of billing shape.
- Site-wide allowance, reuse of hold TTL, or no deadline until billing starts —
  ignores provider differences or leaves the commit-to-delivery gap unbounded.
- Storefront-selected grace as buyer protection — no seller-local lapse policy
  supplies an authority-backed billing guarantee; the whole renewal policy is deferred.

## Implementation cadence and gates

One site-focused implementation round after `inject-site-pool-authority`: schema,
allowance validation/provider declarations, activation, conditional expiry and typed
views. Reservation acknowledgement-gap qualification consumes only
`capacity-reservation-lifecycle-hardening`'s negotiation-keyed exact-request
reservation-idempotency slice, not its whole implementation or archive; site-local
activation work can proceed before that integration gate. Event integration waits for `agreed-evidence-and-early-termination`'s signed
record/outbox. `unify-compute-delivery-path` then wires activation and supplies the
cross-service delivery evidence. No dependency on a rate-part contract revision is introduced. Renewable ships `activation_deadlines_enabled`
false. Unify owns enablement after compatible storefronts deploy first, the updated
site deploys with protection off, and every commit/recovery caller is qualified
in explicitly enabled owned lanes. Unify then changes the repository composition
default; hosted operators independently confirm readiness. Public evidence records
readiness and public release versions, not hosted target identifiers.
New storefronts treat verified null-phase legacy leases as already active/no-op;
absence of an activation route is tolerated only with a verified legacy view.
A protected/unknown phase without activation support is repair-required. Existing
null-phase leases remain unchanged when enabling. Site-only evidence never enables
protection or proves campaign readiness. This avoids a whole-change dependency cycle.

## Coordinated first-review triage

The unify review's 01 F3 / 02 F1 are resolved by reservation-only activation and
explicit truncation/lost-acknowledgement scenarios. Its 01 F4 / 02 F2 are resolved
by the max(commit,start) deadline anchor, zero early-dispatch lead time at the
caller, and foundation-owned valid pre-start command journaling (act at accepted start). Its 02 F4 is
resolved by the off-by-default composition switch and unify-owned final enablement.
The owner additionally fixes the distinction between site end intent and proven
physical completion (D-G), and activation-before-billing order (D-F). These are
coordinated design edits, not evidence that caller or site code is implemented.
Recommend another design review of the coordinated contracts before planning;
keep this change in design. The review/triage records live with unify, which owns
those findings.

## Coordinated second-review triage

Unify 04 F9 splits enablement into owned-lane qualification with the switch on and
only then unify's repository composition-default edit. Renewable's introduced default
remains false; its resource-pool requirement is amended by unify after qualification.
Unify 03 F2 / 04 F8 strengthens the hardening slice to normalized exact-request/state
reconciliation; expired unresolved reserve effects cannot silently create a hold.
E-C removes any seller dispute/mechanical-ruling dependency: activation lapse remains
site evidence passed to the seller payment-adapter self-correction. No site payment
logic or new buyer guarantee is introduced. Keep in design for the coordinated review.

## Open questions

None in the active scope. Default values, strict override validation, finite-end
refusal, tie attribution, forward-start anchor and off-by-default composition
switch above are recommendations supplied by this design;
implementation re-verifies them against
the landed dependency interfaces. D4's policy choices remain explicitly deferred.

## Permanent documentation destinations

| Accepted decision | Destination |
|---|---|
| D1, D2 | `openspec/specs/site-capacity/spec.md` and `openspec/specs/site-capacity/architecture.md`; capacity reservation in `docs/development/ARCHITECTURE.md` |
| D3 | `openspec/specs/resource-pool-management/spec.md`; pool policy configuration in `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D5 watchdog/event | `openspec/specs/physical-provisioning/spec.md`; recovery workers in `docs/development/ARCHITECTURE.md` |
| D5 typed activation/view | `openspec/specs/compute-provisioning-contract/spec.md` |
| D4 deferred renewal | Remains in this change; not promoted as current behavior |

Directory naming recommendation: retain `renewable-compute-lease-deadlines` as the
stable campaign identifier while naming the active proposal activation-only. A
rename would require edits to sibling changes and campaign documents without
changing the acceptance boundary.
