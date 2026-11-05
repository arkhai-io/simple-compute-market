# Design: keep new deliveries off disabled hosts

## Context

- **What disabling a host does today.** `HostAuthority.disable_host`
  (`provisioning/compute/src/compute_provisioning/hosts/service.py`) clears a
  host's `enabled` flag, described as excluding it from new work. On the delivery
  path only job submission reads the flag: a fulfillment's create passes
  `require_enabled_host=True` (`provisioning/compute/src/compute_provisioning/job_fulfillment.py`),
  and `JobSubmissionService.submit` (`provisioning/compute/src/compute_provisioning/jobs/submission.py`)
  raises `HostDisabledError`; teardown and operator jobs pass. The status
  component's Ansible readiness check, the host listing, and the host-definitions
  export also read the flag, none of them on the delivery path.
- **Admission and placement ignore it.** The ledger's admission filter
  (`_find_candidate` in `kit/site/src/market_site/ledger.py`, serving probe,
  reserve, and `resize_reservation`) checks the declaration's own `enabled`, fit,
  the pool's deliverable offering mode, and the host requirement. The site's
  rebind recheck (`assign_settlement_resource_in_session`) checks the same. The
  scheduler's candidate filter (`kit/fulfillment/src/market_fulfillment/scheduler.py`,
  `_eligible_candidates_in_transaction`) checks the pool, mode, host requirement,
  and fit. None reads a host record. So a claim is admitted and placed on a
  disabled host, its create is refused at dispatch, and the convergence worker,
  which has no attempt ceiling, retries it in `dispatch_pending` until the host is
  re-enabled.
- **A named host with no registration behaves the same.** Job submission raises
  `HostNotFoundError` for it, and the create retries indefinitely. The
  site-capacity requirement "Admission applies the pool provider's host
  requirement" states that admission does not require the named host to be
  registered.
- **The host requirement.** Each fulfillment provider declares whether its
  delivery needs a host; the compute container merges the declarations into a
  provider → bool map, fixed at composition (`container.py`, `host_requirement`),
  and supplies it to the ledger and the scheduler as plain data
  (`kit/resource-pools/src/market_resource_pools/host_requirement.py`). A
  declaration naming no host, in a pool whose provider needs one, is refused by
  admission and placement; it is still projected enabled, and its listing
  published, an accepted residual.
- **Projection.** The resource-pool projection is built from declarations alone
  by `load_capacity_resource_inventory`
  (`provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py`),
  and a declaration naming a disabled or unregistered host projects enabled. The
  capacity-bucket projection (`kit/site/src/market_site/projections.py`) is built
  from `ledger.list_resources()` and skips a member that is not enabled. The
  bare-metal publication view's `available` is the declaration's `enabled` and
  whole-resource availability. Storefronts already skip a member that is not
  enabled (the VM reconciler, shape generation, and cardinality explanations),
  classify a disabled bare-metal resource as withdrawn, close a disabled source's
  listings and reopen them under their original identities when it is re-enabled,
  and refuse, in the seller's inventory guard, a listing whose declaration was
  disabled beneath it.
- **One database.** The `hosts` table, the ledger, and the settlement tables
  share one SQLite database and one `session_factory`. Admission and scheduling
  run under the ledger's serialization lock in a write transaction, and a host
  write is its own write transaction, so a read inside admission cannot interleave
  with a disable.
- **Ownership.** `pools-6-fair-scheduling-policy` also claims this rule, handed
  to it by `project-capacity-resources-without-hosts`; its own design says the
  rule is hard fit and does not wait on its fairness decisions.

## Goals / Non-Goals

**Goals.**

- A declaration in a backed pool whose provider needs a host is offered only when
  it names a registered, enabled host: admission and scheduling treat it as
  eligible, and both projections show it enabled. Otherwise it is neither admitted,
  placed, nor published.
- Disabling a host drains it: nothing new lands on it, and work already assigned
  to it keeps its host.
- The site still owns no host records or connection information.

**Non-Goals.**

- Changing job submission: a create keeps refusing a disabled or unregistered
  host, and teardown and operator jobs keep running against a disabled one.
- Changing what a declaration's own `enabled` means, or disabling declarations
  when their host is disabled.
- Changing storefronts, the projection's wire shape, or the capacity event feed.
- Changing how host inventory enters the registry.
- Fairness or any scheduling policy beyond eligibility.

## Decisions

### D1. This change owns the rule; pools-6 gives it up

This change owns refusing new admission and placement against a host that cannot
take delivery. `pools-6-fair-scheduling-policy`'s proposal bullet, its design
section "Disabled hosts stop new admission and placement, not existing work", and
the sentence in its index row claiming the rule are removed at this change's
closeout, when the transfer takes effect; until then pools-6 is parked, so its
stale claim misdirects no work.

*Rationale.* The rule is a defect fix that depends on none of pools-6's fairness
decisions, which wait on stakeholder input, and pools-6's own design says so.
Keeping this change minimal is the point.

*Rejected.* Folding the rule back into pools-6: the fix would wait on unrelated,
parked decisions, and orphan the host-definitions revisit trigger keyed to this
change. Leaving both changes claiming it: the index, the roadmap, and pools-6
would disagree about the owner. Amending pools-6 in this change's design commit:
possible, but the transfer is real only when this change lands.

### D2. Host eligibility reaches the site and the scheduler through a seam read in the caller's session

The provisioning composition supplies an object the kit layers call inside their
own transaction to learn which hosts take new delivery (its shape is D6). The
ledger and the scheduler receive the same object; the scheduler reads it through
one new operation on its scheduling unit of work. The ledger reads it for
admission and for the offered state every projection is built from (11 F2), so
no projection builder receives the object itself.

*Rationale.* The fact keeps one authority, the host registry, and is read where it
is kept, in the transaction that decides, so no disable can commit between the
read and the decision. Nothing is copied, migrated, or added to a wire. The site
learns only `host_id`s, which it already references, and no connection
information. The shape is the one `CapacityReleaseGuard`, `lease_end_effect`, and
the host pool-change hooks already have: a narrow interface a lower layer defines
without naming the upper one, supplied at composition and consulted in the
caller's session. A composition can supply it only where hosts share the ledger's
database, which holds for every host-delivering provider, since all run inside the
compute provisioning service.

*Rejected.*
- *A site-side copy* (an eligibility column on the declaration, written by a new
  host hook): a second copy of a host fact, a hook on every host write path, a
  migration and backfill, and silent drift wherever a path misses the hook.
- *The calling service reads first and passes the set in:* the read falls outside
  the admission transaction, so a disable can land between read and decision, and
  every caller needs the reader anyway.
- *`kit/site` queries the `hosts` table by name:* the forbidden dependency edge,
  hidden in a string.
- *Disabling the declarations:* excluded by the non-goals; the declaration's
  `enabled` is the operator's statement and the host's state is the host
  authority's.

### D3 and D12. A declaration with no usable host is not offered

Where a declaration's pool is backed and the pool's provider needs a host, the
declaration has a usable host only when it names a host that is registered and
enabled. A declaration without one is not offered:

| Backed pool, provider needs a host | Admission and scheduling | Projection |
|---|---|---|
| Names a registered, enabled host | eligible | as declared |
| Names a disabled host | ineligible | not enabled |
| Names a host with no registration | ineligible | not enabled |
| Names no host | ineligible (unchanged) | not enabled |

The rule does not apply in an unbacked pool, whose listings deliver nothing
through a host and legitimately name none, nor where the pool's provider needs no
host. The requirement that admission not require the named host's registration is
reversed.

*Rationale.* A listing whose delivery has no usable host is the same as a listing
with no host, and neither should appear. A disabled host, a host never registered,
and no host at all leave a backed listing equally undeliverable, and the first two
also leave an admitted deal retrying at dispatch. One predicate, applied at every
layer that decides what is offered, is simpler to specify, test, and explain than
a disabled-only rule with two recorded exceptions. It reverses two earlier
positions on purpose: that a missing host record must not hide a declaration from
the projection, and that a backed declaration naming no host may still be
published.

*Rejected.* Disabled hosts only, with the unregistered and no-host cases recorded
as a roadmap gap: it leaves listings that cannot be delivered, one of them still
producing stuck deals. Hiding the no-host case alone: the unregistered case would
stay admitted and stuck.

### D4. New placement never uses a host that cannot take delivery; an existing assignment keeps its host

Scheduling applies the rule to every candidate, a reservation's own backing
included. A pool-scoped hold whose declaration lost its usable host after
admission is re-placed at scheduling onto another eligible declaration through
the ordinary rebind, or refused as having no eligible resource. A resource-specific
claim, such as bare metal's, naming such a declaration is refused as having no
eligible resource. An assignment already made is returned unchanged on an
equivalent retry: it keeps its host, and its create waits at dispatch, where job
submission refuses it until the host is enabled or registered. Teardown and
operator jobs are unchanged.

*Rationale.* A hold is not a delivery, and scheduling already moves a hold freely
within what its claim permits, so a VM buyer whose hold sat on a disabled host is
delivered elsewhere now rather than waiting. An assignment names a host, and the
host requirement already says an existing assignment keeps the host it was placed
on. Disabling a host then drains it. It is also the smallest change: one filter at
each candidate enumeration, no exception for a reservation's own backing, and no
change to the existing-assignment path.

*Rejected.* Admitted work keeps its host (a reservation's own backing stays a
candidate for it): it needs an exception in both filters and makes a VM deal wait
on a disabled host when another could serve it. Refusing an existing undispatched
assignment too, as a disabled pool does: incomplete without a check at begin or
dispatch, since a storefront that already persisted its schedule begins without
rescheduling, and that is the job-submission change the non-goals exclude; it
would also turn a maintenance window into failed deals for work already placed.

### D5. Publication follows admission: an undeliverable declaration projects as not enabled

In both projections, and in the bare-metal view's `available`, a declaration
without a usable host (D3/D12) projects as not enabled. The projected `enabled`
thus states whether the site offers the declaration: its own `enabled` and a
usable host. The bare-metal view reads `enabled` from the declaration it is
handed, not from the projected entry (`inventory_views.py`), so the provisioning
builder hands it the declaration as the ledger's offered read states it (11 F2);
the view itself is unchanged. The projection reads one host fact, the
deliverable-host set through D2's seam, and still carries no host identifier,
connection address, or tenant-facing address on a generic entry. The operator's
own listing (`GET /api/v1/capacity/resources`) keeps each declaration's stored
`enabled`, and `snapshot()`, the advisory input at negotiation time, follows the
projection.

*Rationale.* A storefront mirrors admission's constraints from its projections only
to avoid committing to what admission will refuse (`ARCHITECTURE.md`, "Deciding
which party is authoritative"), so the projection must state what admission
enforces; projected `enabled` dropped its host term once because admission did not
enforce it, and admission now does. Every storefront already closes a disabled
source's listings, reopens them under their original identities when the source
returns (the derivation identity — pool, resource, shape digest — is untouched),
and refuses such a listing in the inventory guard with the declared-match reason.
So no storefront changes, the wire shape is unchanged, and only site-capacity's
projection requirement is amended.

*Rejected.*
- *Leave publication as it is:* a listing with no usable host is the same as a
  listing with no host, and must not appear; a bare-metal listing for a disabled
  machine would otherwise stay open, pass the inventory guard, and fail every
  reservation.
- *An additive per-member field, such as `host_enabled`:* nothing reads it until
  every consumer learns it, adding a storefront-publication requirement and
  storefront changes across two domains for a distinction no consumer needs.
- *Omitting the declaration from both projections:* hides it from every consumer,
  contradicting "every declaration projects" more deeply than projecting it as not
  enabled does, for no gain.

### D6. The seam and the rule live beside the host requirement

`market_resource_pools/host_requirement.py` gains the seam and one function that
states the whole rule, beside `HostRequirement` and `pool_needs_host`:

```python
class DeliverableHosts(Protocol):
    def deliverable_host_ids(self, db: Session) -> frozenset[str]:
        """Registered, enabled hosts, read in the caller's session."""

def declaration_has_usable_host(
    host_id: str | None,
    provider: str | None,
    backed: bool,
    host_requirement: HostRequirement | None,
    deliverable: frozenset[str] | None,
) -> bool: ...
```

The compute composition implements `DeliverableHosts` over `Host`: the ids of hosts
whose `enabled` is true, so a host with no record never appears. One set is read
per transaction: by admission, by the rebind recheck, by the ledger's offered read
(11 F2), and by the scheduler.

*Rationale.* Every layer applying the rule already imports `market_resource_pools`
for the host requirement, so one module states the whole host rule. A set read once
suits admission, which walks every bucket.

*Rejected.* Placing the seam in `market_site`, beside `CapacityReleaseGuard`: it
would split one rule across two packages. A per-host predicate: one query per
candidate.

### D7. A composition that supplies none applies none

With no host requirement supplied, no host rule applies, as today; API credits
supplies none. With a requirement but no `DeliverableHosts`, a declaration naming a
host is treated as having a usable one, as today. The compute container supplies
both, and a composition test asserts it.

*Rejected.* Refusing construction when a requirement is supplied without the seam:
it would make every ledger and scheduler fixture that supplies a requirement build
a seam, to guard one container a test already covers.

### D8. Where the rule is applied, and how a refusal answers

Each layer applies the rule itself, so none relies on another having refused:

- admission, in `_find_candidate`, serving probe, reserve, and resize: an
  ineligible candidate does not match, and a claim no other candidate satisfies
  receives the ordinary no-capacity answer;
- the site's rebind recheck, `assign_settlement_resource_in_session`:
  `CapacityConflictError`, as its host-requirement check answers;
- the scheduler's candidate filter, on the automatic and explicitly constrained
  paths, before policy selection, rebind, cursor advance, or assignment:
  `NoEligibleSettlementResourceError` (422 `no_eligible_resource`);
- the ledger's offered read (11 F2), from which the capacity-bucket projection,
  `snapshot()`, and the provisioning resource-pool projection builder and the
  domain views it builds are all produced: the member is not enabled.

The scheduler's existing-assignment path is unchanged (D4), including its refusal
of an assignment recorded with no host. Dispatch remains the last check.

Admission and scheduling need no backing of their own: a candidate's pool must
deliver the claim's offering mode, and an unbacked pool delivers nothing. The
ledger's offered read reads no backing either (21 F2): it applies the rule where
the pool declares a deliverable offering mode, the fact admission reads, and a
missing pool, or one whose modes do not parse, is judged to deliver. No projection builder
resolves backing for this rule.

*Rejected.* A distinct refusal reason ("host unavailable"): it would change the
wire and tell a storefront which physical resource backs a claim, which "Capacity
accounting is private to the site authority" forbids.

### D9. A change of host state emits no capacity event

Enabling, disabling, or registering a host emits no capacity delta and advances no
capacity version. Projection revisions and digests are computed on read, so a
storefront sees the change at its next projection poll, and source-publication
reconciliation closes or reopens the listings.

*Rationale.* This follows pool enablement, which also changes what is offered from
outside the ledger and emits no event. It adds no hook to the host authority.

*Rejected.* An enabled-change hook that has the ledger emit a delta from inside each
host write: a new hook on every host write path for a latency gain of one poll
interval.

### D10. Host definitions documents keep retaining the hosts they stop naming

A host definitions document still leaves every registered host it does not name
unchanged. Of the two reasons `bring-host-inventory-under-definition-documents`
gave, hosts registered through the API must coexist with the document, which still
holds; that disabling a host does not keep deliveries off it no longer holds. The
rationale in `openspec/specs/physical-provisioning/architecture.md` is restated on
the remaining reason at closeout, which answers that change's revisit question.

### D11. What disabling a host means

Disabling a host keeps new deliveries off it: no declaration naming it is admitted,
placed, or projected enabled. An assignment already made keeps its host, and its
create waits at dispatch until the host is enabled again. Teardown and operator
jobs run. Enabling the host lifts only that restriction: its declarations are then
offered as any other declaration is, subject to their own `enabled`, their pool,
fit, and availability, and the listings of those offered reopen under their
original identities (11 F3). `physical-provisioning`'s spec states this
beside "Jobs are submitted against a registered host"; `site-capacity` and
`fulfillment` state the rule where admission, projection, and scheduling are
specified. `storefront-publication` needs no delta: its disabled-source close and
reopen rules already cover the result.

A host record still contributes nothing to a projected resource's capacity or
attributes, and is joined to a declaration for its connection only at dispatch;
what admission, scheduling, and projection learn of hosts is the set of ids taking
new delivery. `site-capacity`'s "Projected inventory is internally consistent" and
`physical-provisioning`'s "Host inventory is connection identity" are narrowed to
say so, since both otherwise forbid any host fact from reaching a projection
(11 F1).

### 11 F2. The ledger states each declaration's offered state, and every projection reads it

The ledger gains one read returning every declaration with its offered `enabled`:
its own `enabled` and the usable-host rule (D3/D12), judged with
`declaration_has_usable_host` against the deliverable-host set and whether the
pool delivers an offering mode (21 F2), all read in one transaction. The capacity-bucket
projection and `snapshot()` are built from it, and the compute service passes it,
in place of `list_resources()`, as the provisioning resource-pool builder's input,
so the domain views the builder builds, the bare-metal view's `available` among
them, receive the offered declaration. The administrative listing keeps
`list_resources()` and the stored `enabled`. A pool whose deliverable modes do
not parse, which the service refuses to start with and every write refuses, is
judged to deliver, so the read fails closed for it: the convention
`pool_needs_host` follows for a provider the requirement does not name, the case
a guess would get wrong silently.

*Rationale.* Every projection is a view of the ledger's declarations, and the
ledger already holds the deliverable-host report (D2), the host requirement, and
the deliverable offering modes it reads for admission. One application of the rule, in
the session that reads the rows it judges, leaves one path to every projection's
input, so the bare-metal view cannot drift from the capacity-bucket projection,
and the provisioning builder reads no host.

*Reservation.* The owner would rather a ledger be closer to a raw data structure,
with projection logic kept apart from it. The existing ledger already mixes the
two, and settling that is not this change's work.

*Rejected.* Each builder applies the rule: the ledger for the capacity-bucket
projection and the snapshot, and the provisioning builder by reading the
deliverable set in its pool-context session and overwriting `enabled` on each
declaration before building views. It calls the rule from two places and reads
hosts in a session apart from the declarations, for no gain.

### 21 F1. The ledger's decisions begin their SQLite transaction before they read

Probe, reserve, `resize_reservation`, the own-session `assign_settlement_resource`,
and `list_offered_resources` begin `BEGIN IMMEDIATE` on SQLite, through a
module-private helper in `ledger.py`, after `_expire_stale_holds` (which commits what
it lapses) and before any read the decision rests on. The helper skips a connection
already in a transaction, which has written and so holds the writer slot.

*Rationale.* D2's guarantee, that no disable can commit between the read and the
decision, assumed the Context's "One database" bullet: that admission runs in a write
transaction a host write cannot interleave with. It does not by itself. The
production engine is file-backed, one connection per session, and the SQLite driver
begins a transaction only at the first write, while `HostAuthority`'s writes go
through their own session without the ledger's lock; so the report could be read,
and a disable commit, before admission's first write. The scheduler's unit of work
already issued `BEGIN IMMEDIATE`. The helper is a private copy of `kit/fulfillment`'s,
which `kit/site` may not import. Read paths take the writer slot too, because
`_expire_stale_holds` can write in them; a projection read then waits behind another
writer, within the 30-second busy timeout.

*Evidence.* Library integration on a file-backed database: a report that tries a
write from another connection at each read finds it locked on all five paths, and
again after a lapsed hold's commit, and a write proceeds once a decision ends; each
test failed with the helper disabled, or with reserve's helper moved ahead of the
lapse.

### 21 F2. The offered read judges a pool by its deliverable modes, not its backing

The offered read applies the usable-host rule to a declaration only where its
pool declares a deliverable offering mode; a pool declaring none keeps its
declarations' own `enabled`. The ledger reads no pool's backing.

*Rationale.* `ARCHITECTURE.md` asks that no new site read of pool state be added
while the ledger's dependency on the pool authority stands, and
`inject-site-pool-authority` is to land before any such read. The offered read
needs only to tell an unbacked pool from a backed one, and the pool declarations
already settle that through the fact admission reads: an unbacked pool must
deliver nothing, which their resolution enforces, and admission already judges
unbacked supply by its empty deliverable set rather than by its backing. The
offered read so judges a pool as admission does. A backed pool delivering no mode
may advertise only what it delivers, so nothing of it can be listed or admitted,
and its declarations keeping their own `enabled` offers nothing a storefront could
sell.

*Rejected.* Resolving the pool's backing in the ledger, recorded as a further read
on the divergent edge: a new pool fact the injected pool port would then have to
carry, against the ordering the change index sets. A backing seam supplied by the
composition: another seam for one fact, whose shape the port's design has left
open and would likely redo, while the ledger still reads provider and modes
directly.

## Implementation cadence

One implementation round in one session, covering the seam and rule function
(`kit/resource-pools`), admission, the rebind recheck, the ledger's offered read
and the capacity-bucket projection and snapshot built from it (`kit/site`), the
scheduler filter and its unit-of-work read (`kit/fulfillment`), and the compute
composition's implementation over `Host`, the resource-pool projection builder's
input, and container wiring (`provisioning/compute`),
with their tests; then closeout. The pieces share one predicate and are meaningful
only together.

## Risks / Trade-offs

- **[A storefront advertises a listing between a disable and its next poll]** →
  Admission refuses at once, so the residual is one poll interval of a listing that
  fails reservation in the ordinary capacity class (D9).
- **[Capacity declared before its host is registered no longer sells]** → Intended
  (D3/D12). Definition documents apply hosts before capacity, so the normal order is
  unaffected; an operator registering through the API registers the host first.
  The same holds for tests and end-to-end scenarios: those that declare backed,
  host-requiring capacity naming a host they never register — the bare-metal
  publication and introduction scenarios among them — register the host first,
  as the VM lane's helpers already do.
- **[A projection consumer cannot tell an operator-disabled declaration from one
  without a usable host]** → No consumer needs to; the operator's listing keeps the
  declaration's own `enabled`.
- **[A composition supplies the host requirement without the seam]** → Named hosts
  are then accepted as today (D7); the compute container's composition test catches
  the omission.

## Open Questions

None.
