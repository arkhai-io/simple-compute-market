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
bookkeeping has stopped.

The lifecycle frame is `agreed-evidence-and-early-termination`: commitment makes
the agreement binding; end service realizes the earliest final request, and money
moves only at the payment and dispute authorities. A site's signed statement is
kept evidence, not a new authority record. These authority boundaries and the
deadline-only scope are settled.

### What the landed code provides

- **Activation.** `activate-compute-leases-at-the-site` added one nullable
  `activated_at_utc` (`kit/site/src/market_site/db.py`), written once by
  `activate_lease` from the site's clock on a `leased` reservation with a lease end
  (`kit/site/src/market_site/ledger.py`). Whether a lease is activated is derived from
  it and stored nowhere else; activation changes no state, window or admission. The
  instant shows on the site's reservation view and on the compute contract's
  `LeaseView`. There is no compatibility path for a site without activation. The site
  schema is `kit/site/src/market_site/migrations.py`, which both the compute
  provisioning service and the API-credits service apply.
- **Delivery.** `unify-compute-delivery-path` commits every compute deal through the
  storefront's capacity effects (`CapacityEffects.commit`,
  `kit/capacity-publication/src/market_capacity_publication/capacity.py`) from
  `domains/compute/delivery/src/compute_delivery/path.py`, with the Agreement's window
  and no deadline or anchor. A site refusal of the commit after reservation is recorded
  as seller failure before dispatch, with the reservation released through end
  service's no-dispatch path (`openspec/specs/compute-delivery/spec.md`). A refused
  activation on a lease the site reports releasing or released is already handed to end
  service as `activation_lapse`.
- **The storefront's deadline.** The servicing journal records the deal's commitment
  instant and accepted `delivery_deadline_seconds` and classifies a missed deadline as
  non-delivery at min(term end, max(start, commitment) + deadline)
  (`kit/deal-servicing/src/market_deal_servicing/journal.py`).
- **The MVP's stopgap.** Goal 8's MVP publishes the deadline the seller's payments
  clause configures (`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`,
  which requires one on every compute option), and `offer-per-period-vm-terms` amends
  `deal-lifecycle` to call it seller-configured and storefront-enforced. That parameter
  is a lifecycle key owned by a settlement mechanism's model, which `deal-lifecycle`
  forbids. No site enforces a deadline.
- **Pool facts.** `kit/site` still imports `kit/resource-pools` directly;
  `inject-site-pool-authority` replaces that edge with a session-scoped port. The
  site's pool projection already carries each pool's `policy_tags`
  (`kit/site/src/market_site/projections.py`).

## Goals / Non-Goals

**Goals:** bound capacity held between site commit and delivery; make activation
and expiry race safely; publish the pool's deadline as the buyer's term and retire the
seller-configured stopgap; keep payment classifications out of the site; leave old
leases and API-credit quota holds unchanged.

**Non-goals:** the activation instant, transition and typed views
(`activate-compute-leases-at-the-site`), renewal of active leases, lease extension,
payment or refund operations, and delivery caller wiring.
This is a recommended cooperative seller implementation, not a protocol requirement
that a buyer may assume an arbitrary seller obeys.

## Decisions

### D1. The deadline written at commit

This change adds its own nullable activation-deadline column to the shared site schema
(its name is open below), applied by both hosting services; existing rows stay null.
It adds no phase column: an unactivated lease is one whose `activated_at_utc` is null.

- On first commit with a resolved delivery deadline, record the deadline
  max(committed_at_utc, lease_start_utc) + delivery_deadline_seconds,
  where `delivery_deadline_seconds` is the deal's accepted value, supplied with the
  commit as a fact of the deal like its window, and the pool's current effective value
  is its ceiling: the site refuses a commit whose accepted deadline exceeds what the
  pool now grants, or that carries one where the pool now enforces none, since the
  seller cannot ask its site for more time than the site gives — a refusal that
  delivery classifies as seller failure before dispatch: no provisioning occurs, and the
  reservation the storefront already holds is released through the foundation's
  no-dispatch path, not by the site on refusal. A pool
  lengthened after acceptance changes nothing for the deal; a pool shortened below an
  accepted deal's value refuses that deal rather than reclaiming it early, and the
  listing republishes with the new value. A commit carrying no accepted deadline (a
  buyer that opted out of the term) takes the pool's current policy as the site's own
  capacity safeguard. `committed_at_utc` is the deal's commitment instant the storefront
  supplies with the commit — the same instant its servicing journal records, which is
  the payment authority's record of the buyer's approval on a hosted deal and the
  mechanism's commitment act otherwise — so the site and the storefront compute the
  same deadline. The site refuses an anchor after its
  own clock and can verify nothing else about it: it knows no payment mechanism, so the
  anchor is the storefront's word. The site's deadline is therefore the seller's own
  capacity safeguard — it reclaims a lease its storefront never activated — and not the
  buyer's guarantee of the accepted deadline; a storefront that sits on an approved deal
  and supplies a later anchor lengthens its physical deadline, not its promise. The
  buyer's deadline is judged by the dispute authority from the payment authority's own
  approval record and the Agreement, and the storefront's journaled commit, with the
  anchor it supplied, is evidence against it where the two disagree.
  This protects a forward reservation without expiring it before its admitted start;
  delivery defers dispatch/activation/access until that start (no early lead time).
- Commit retried leaves the original deadline unchanged, whatever the pool now says.
- The due instant of an unactivated lease is the earlier of its agreed end and a
  non-null deadline; an activated lease is due at its agreed end. Activation writes
  only `activated_at_utc`, as the activation contract states; the deadline stays
  recorded as evidence of what was committed. Truncation moves only the agreed end, and
  the due instant follows from it, so no copied deadline needs capping.
- Admission always accounts against the agreed window. The earlier activation
  deadline does not free capacity for a future reservation before release succeeds.
- A pool resolving no delivery deadline records no deadline; its leases continue
  to expire only at their end. This is not a billing classification. **Recommendation:** a pool resolving a delivery deadline requires a
  finite end at commit; unsupported open-ended use is refused rather than creating
  an unbounded activation.

### D2. Expiry claims the deadline and activation it read

The due query returns the agreed end, deadline and whether `activated_at_utc` was null
when the row became due, plus whether the cause is activation lapse or ordinary term
end. Before a teardown side effect, expiry conditionally claims `state == leased` and
exact equality of that observed tuple inside the ledger's serialized transaction. If
activation or truncation changed the tuple, the claim fails with no event, outbox item
or provider call; the next pass reevaluates. A matching claim begins `releasing`;
activation then cannot undo it, since activation is refused from `releasing`. No
database lock spans a provider call.

**The deadline is enforced by the claim, not by the clock.** Activation after an
elapsed deadline is allowed while the row remains unclaimed; it is a capacity fact
and not delivery — the lifecycle classifies a deal whose buyer could not use the
resource by the accepted deadline as non-delivery whatever the site records, and
starts no new billing on it (foundation D8). Refusing it merely
because a watchdog poll has not happened would turn poll latency into an eviction.
The agreed end remains an independent bound, so activation never extends service
past it. On a tie between activation deadline and term end, report ordinary term
end (recommendation: it avoids attributing an unavoidable term end to failed delivery).

The claim condition supplements the existing release guard: it does not permit
freeing capacity while a create is in flight or teardown is unproven. It must be
carried through direct release, deferred release and failure paths, not checked
only after a provider action.

### D3. Provider-declared delivery deadline: the pool's term, published and enforced

`delivery_deadline_seconds` is a Resource Pool policy tag: the seconds after
max(commitment instant, lease start) within which the site activates the lease, the site's reclaim rule for a lease never activated. It is
also the buyer's term: the storefront reads the pool's effective value from the site's
pool projection at publication and publishes it as the option's
`lifecycle.delivery_deadline_seconds` (foundation D5), under the same name. The
accepted value travels with the commit, and the site enforces exactly what was
accepted, bounded by its own current policy (D1), from an anchor it cannot verify. The
site's deadline is the seller's safeguard against its own storefront's absence; the
promise the buyer read is checked by the dispute authority against the payment
authority's approval record, which the buyer holds. It is not money or a minimum spend.
The two readings of the tag — publication's and commit's — can differ when an operator
edits it between them; the accepted value wins where the pool still grants it, and the
commit is refused where it does not, so no deal is silently given more time than it
promised or less than it was promised.

The value the MVP publishes from the seller's payments clause is a stopgap this change
retires. Publication switches to the pool's value, `deal-lifecycle` is re-amended from
the MVP's "seller-configured, storefront-enforced" wording to the pool's term enforced
by the site, and the payments clause's `delivery_deadline_seconds` parameter is removed,
so no settlement mechanism's model owns a lifecycle key. The storefront journal keeps
classifying a missed accepted deadline as non-delivery; the site adds capacity reclaim
when the storefront is absent.

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

**Recommendation:** add the explicit compute-composition setting
`activation_deadlines_enabled`, default false. Provider support/defaults and pool
validation remain declared even while disabled; an invalid override never becomes
valid because the switch is off. The injected pool-facts port resolves no effective
delivery deadline while disabled, so new leases retain a null deadline. This is an
operator composition setting, not a pool tag or caller-supplied commit flag. Enabling
applies only to new commits; disabling does not clear deadlines already snapshotted.

The session-scoped pool-facts port from `inject-site-pool-authority` supplies the
effective delivery deadline in the commit transaction. The site does not import the pool
authority or infer a provider from a domain or billing kind. API-credit quota holds
therefore receive no deadline by the same generic rule, with no site exemption.
If the dependency stalls, reconsider the port contract with its owner; passing a
storefront-selected delivery deadline is not an authorized fallback. The storefront
supplies the anchor instant, a fact of the deal like the window, and the accepted value
it published; the duration's ceiling is the pool's alone.

A delivery-deadline overrun enters ordinary guarded release. The storefront supplies
classified failure evidence to the foundation's single end-plus-optional-filing
operation, through the delivery path's existing `activation_lapse` hand-off. The
foundation owns cause classification and the financial intent's fixed timing basis.
Consume D8's pre-start exception (journal now, act at accepted start), never a
future-dated command. delivery_end is the seller's dispute-adapter filing, journaled
with the end; the seller sends no stop/reverse. Mediation alone mechanically rules its
standard-delivery_end claim with payee agreement and mapping/time/replay guards;
receipt-backed payer claims qualify too. The site computes no financial instant/amount
and its report is not a refund prerequisite. The caller supplies verified
buyer/ruling/payment evidence for classification; term clock or payee stop alone does
not erase established non-delivery. Rate billing starts after ready evidence and
activation; the deadline authorizes no billing.

### D4. Renewal and renewal-lapse policy are deferred seller options

**Revisit condition:** a site operator separate from the storefront operator needs
to bound its exposure to an absent storefront. This is the seller's choice about
its hardware, not a buyer, payment-authority or dispute-authority requirement.
No renewal API, renewal timer or lapse-policy tag ships in the present change.

Retained option for that future design:

- An active lease may carry an independent renewable deadline, separate from the
  agreed end and from this change's activation deadline. Renewal moves it later only,
  never beyond that end; it is refused after release is claimed. A stale renewal
  cannot shorten or resurrect a lease. Admission still uses the full agreed window.
- Expiry compares the observed tuple as in D2. An elapsed but unclaimed
  deadline may be renewed. Activation and renewal remain distinct transitions;
  a future activation target would need its own explicit design, never a payment
  fact inferred from this option.
- A site-selected pool policy could be `reclaim` (release on lapse), bounded
  `grace` (release later, with the duration and effective deadline visible), or
  `continue` (serve to the agreed end). A site-wide default and any maximum grace
  are choices for that future design. The site need not know why renewal lapsed.
- The view and physical-end record would expose the deadline, policy and
  cause `renewal_lapsed`. They would remain evidence, never a billing stop.

**Cost of active reclaim:** `reclaim` can destroy a working VM merely because the
storefront crashed. Billing does not stop on site silence or on that reclaim.
Honest recovery files `delivery_end(cause=payee)` at the physical end through the dispute
adapter: mediation rules the self-penalty, including the premature-stop penalty
capped by earned amounts still held after refunds; bond award is reserved for hosted bonds, even though the original failure was only bookkeeping.
`grace` only delays that cost; `continue` leaves unpaid-service exposure with the
seller until the agreed end or a recovered end-service action. None is a buyer
guarantee. Renewal must be justified by a separate operator's concrete needs before
this trade-off is reintroduced.

### D5. Lease-end intent evidence

The foundation supplies the signed `lease_ended` record and durable outbox; this
change adds `activation_deadline_lapsed`, which the record's cause set already admits
without a contract change. The record carries the reservation/deal correlation, the
claimed deadline and the base report's intended effective end instant.
The report is recorded before teardown: it is not proof of physical completion.
Proven guarded release remains a separate completion fact, including on failures. The deadline is the reason release was claimed,
not a fabricated instant of proven VM teardown. A term end that wins the due
comparison keeps its ordinary cause. Retrying the event preserves its identity
and signed content; the evidence store keeps the original bytes.

The site's reservation view and the compute contract's `LeaseView` already expose
`activated_at_utc`; this change adds the activation deadline to both and exposes no
renewal-lapse policy, because none is implemented. End service may consume the site's report as a local final request
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
  self-penalty (`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md#the-standard-self-penalty`).
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
- The seller-configured payments-clause value as the permanent source (the MVP's
  stopgap) — it puts a lifecycle key in a settlement mechanism's model, which
  `deal-lifecycle` forbids, and lets the published term drift from the capacity policy
  the site enforces.
- Storefront-local scheduled stop — authority-hosted pending stops survive a dead
  storefront; the site deadline schedules neither notice nor billing.
- A stored activation phase beside `activated_at_utc` — the activation contract derives
  the phase from the instant and stores it nowhere else.
- Deadline as a movable agreed end, or a separate cap over it — changes admission
  meaning and requires extension; keep the agreed end and provisional deadline distinct.
- Open-ended compute commit with eventual storefront truncation — a dead storefront
  leaves capacity unbounded; a finite agreed end remains required for these pools.
- Provider calls under a row lock — release orchestration keeps external calls
  outside transactions; compare-and-set claims provide the race boundary.
- Clock-only activation refusal — makes watchdog latency evict a resource whose
  expiry has not been claimed; claim order decides.
- Shipping the activation transition in this change (its first form, split
  2026-10-29) — the transition reads no pool and four changes needed it before the
  pool-authority port; it is `activate-compute-leases-at-the-site`, now landed.
- Commercial flag on commit — the provider/pool delivery deadline is sufficient and leaves
  the site independent of billing shape.
- Site-wide delivery deadline, reuse of hold TTL, or no deadline until billing starts —
  ignores provider differences or leaves the commit-to-delivery gap unbounded.
- Storefront-selected grace as buyer protection — no seller-local lapse policy
  supplies an authority-backed billing guarantee; the whole renewal policy is deferred.

## Implementation cadence and gates

One site-focused implementation round after `inject-site-pool-authority`:
delivery-deadline validation/provider declarations, the commit snapshot, conditional
expiry and the lapse cause. Then the storefront round: the publication read, the commit
carrying the accepted value and anchor, the stopgap's retirement and the
`deal-lifecycle` re-amendment. Every commit and recovery caller is already wired, so
this change owns its own enablement: it ships `activation_deadlines_enabled` false,
qualifies every wired commit and recovery caller in explicitly enabled owned lanes,
then changes the repository composition default; hosted operators independently
confirm readiness. Public evidence records readiness and public release versions, not
hosted target identifiers. Existing null-deadline leases remain unchanged when enabling.
Site-only evidence never enables protection or proves campaign readiness.

## Review history

The coordinated unify reviews settled reservation-only activation, the
max(commitment, start) anchor with zero early-dispatch lead time, foundation-owned
pre-start journaling, the off-by-default switch with owned-lane qualification before
the default changes, the distinction between site end intent and proven physical
completion, and activation before billing. The final owner decision made activation
lapse evidence for a journaled delivery_end filing through the dispute adapter, not
seller payment self-correction; seller stops are entitlements only. The records live
with `unify-compute-delivery-path`.

## Open questions

- **The activation-deadline column's name.** The landed schema has only
  `activated_at_utc`; this change adds one nullable column for the deadline, and its
  name is for the design session.
- **Which specification owns the enablement switch.** The delta states the
  `activation_deadlines_enabled` requirement under `resource-pool-management`; it
  governs the site's commit rather than pool administration, and may belong under
  `site-capacity` instead.

Default values, strict override validation, finite-end refusal, tie attribution,
forward-start anchor and off-by-default composition switch above are recommendations
supplied by this design; implementation re-verifies them against the landed
dependency interfaces. D4's policy choices remain explicitly deferred.

## Permanent documentation destinations

| Accepted decision | Destination |
|---|---|
| D1, D2 deadline, claim and admission | `openspec/specs/site-capacity/spec.md` and `openspec/specs/site-capacity/architecture.md`; capacity reservation in `docs/development/ARCHITECTURE.md` |
| D3 declaration and validation | `openspec/specs/resource-pool-management/spec.md`; pool policy configuration in `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D3 publication, restored source and retired clause parameter | `openspec/specs/storefront-publication/spec.md`, `openspec/specs/deal-lifecycle/spec.md`, `openspec/specs/settlement-configuration/spec.md` |
| D3 retired abandoned-lease runbook | `docs/operator-handbook.md` |
| D5 watchdog/event | `openspec/specs/physical-provisioning/spec.md`; recovery workers in `docs/development/ARCHITECTURE.md` |
| D4 deferred renewal | Remains in this change; not promoted as current behavior |

Directory naming: `renewable-compute-lease-deadlines` stays the campaign identifier
while the active proposal is the delivery deadline alone; a rename would touch every
sibling without changing the acceptance boundary.
