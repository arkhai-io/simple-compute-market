# Design: resolve the correctness gaps left in compute delivery

## Context

Goal 1's five remaining correctness gaps are taken together (the proposal). Reading
the code against the proposal changed two of them.

**Item 1 does not occur as stated.** A relayed create does point the host's
buyer-facing client at the relay its port was leased on: `relay-proxy`'s
`add.yml` includes `relay-client` first, whose `client_config.py prepare` writes
`serverAddr`, `serverPort` and `auth.token` from the job's `frp_server_addr` and
restarts `frpc-buyers` when they change; the job's relay is resolved from the
lease (`relays/execution.py`), and the lease is taken on the relay of the
declaration's pool. A host has at most one capacity declaration
(`CapacityBucket.host_id` is unique, `kit/site/src/market_site/db.py`), so every
delivery on a host is in one pool and leased on one relay, whose pool reference
cannot change while it holds a lease (`check_pool_relay_change`), and the
declaration cannot move to another pool while a reservation holds capacity
against it (`_refuse_reassignment_under_obligation`, `kit/site/src/market_site/ledger.py`).
A host's own
pool is placement intent that nothing admitting, scheduling, dispatching or
selling reads (`ARCHITECTURE.md`, "Resource pools"). What remains are three rules
that read the host's placement where the relay that matters is the declaration's
pool's: the management-route rule, which claims only the obvious case, and the
host pool-change hook and the drain, which only err toward caution.

**Item 2 is not reachable through today's callers.** The allocator's only callers
are the two plans inside `begin_fulfillment`, and acceptance locks the settlement
row `FOR UPDATE` before preparing, so a concurrent retry of one reservation reaches
the allocator only after the first acceptance committed its lease, which the
allocator's fresh owner lookup finds. The allocator's own gap — its owner lookup
precedes its relay lock — is real but needs a caller that does not hold the
settlement lock. The reachable sibling is in acceptance: `FulfillmentTransaction.accept`
reads the row unlocked, and `accept_fulfillment`'s locked select returns that same
identity-mapped object unrefreshed (SQLAlchemy refreshes it only under
`populate_existing`), so a retry that waited on the lock judges a stale
`fulfillment_id is None` and accepts again under a new fulfillment ID. The shipped
provisioning chart runs SQLite in one process, where the acceptance block holds no
`await` and two acceptances cannot overlap, and no lane runs PostgreSQL.

**Item 5 has a lease half.** The release status port reports `teardown_failed` as
failed, and the lease goes to `release_failed` at once, where it waits for an
operator's retry-release. Independently, the lease's stalled-teardown timeout
(`lease_watchdog_grace_period_seconds`, 300 by default) marks `release_failed` any
teardown still `tearing_down` after the grace, which a teardown job's own retries
(backing off 60, 120 and 240 seconds) exceed: a teardown that succeeds on a retry
reaches `torn_down` while its lease waits for an operator. The lease's
`release_job_id` holds the fulfillment ID, not a job's, so a new teardown job
identity does not touch it.

Items 3 and 4 are as the proposal states them.

The deployed release is `marketplace-v0.3.0` (`git log --tags --no-walk
--decorate`). Its job engine records `execution_handle` exactly as today, only once
`start_playbook` has returned, so a job it failed with no handle may still have
spawned its playbook: when the handle's commit fails after the spawn, the engine's
catch-all marks the job failed while the playbook runs (26 F1). Its version-1
`ssh` hosts left leases `release_failed` whose teardowns never started, though
nothing on their job records proves it.

## Goals / Non-Goals

**Goals**

- Every relayed delivery's relay is the one its host's client dials, and tests hold
  the two facts that make it so.
- A concurrent equivalent retry of one acceptance or one owner's allocation gets
  the first one's fulfillment or lease, never a second fulfillment ID or a false
  exhaustion.
- A bare-metal end under a delivery conflict is guarded by a test and stated by a
  scenario, the reads after it reporting the ending, the result read answering the
  recorded result while any lease ends; `converge_teardown` is gone.
- A storefront that started before its registry offers payments without a
  restart, and says why while it cannot.
- A teardown whose execution is recorded as never started recovers without an
  operator, within a bound; one whose execution started, or whose start nothing
  proves, keeps today's rule.

**Non-Goals**

- A placement rule for capacity declarations, or any change to which relay a
  delivery is leased on (D1).
- A PostgreSQL test lane (Open Questions).
- Reading registry recommendations again after a successful read (D6).
- Rerunning a teardown whose execution started, a cancelled one, or one finished
  before this change recorded starts — `marketplace-v0.3.0`'s version-1 leftovers
  among them (D4, 26 F1).
- The operator event for a spent rerun bound or a lease failed for
  `teardown_timeout`, which `report-provisioning-failures-to-operators` owns.

## Decisions

### D1 — Item 1 is corrected and guarded, not fixed by a new rule

A relayed delivery's port is leased on the relay of its capacity declaration's
pool, whatever pool, if any, its host is placed in, and the job adding its proxy
points the host's buyer-facing client at that relay before it adds the proxy. That
is the system's rule already; this change states it as a `physical-provisioning`
requirement and holds it with two tests. The rule rests on three facts: a host has
at most one capacity declaration, a pool's relay reference cannot change while it
holds a lease (`check_pool_relay_change`), and the site refuses to move a
declaration to another pool while a reservation holds capacity against it
(`_refuse_reassignment_under_obligation`); a later change relaxing any of them must
answer for the rule (11 F9).

- a static test of the family roles: a proxy add includes the client baseline
  synchronization from the job's relay address, port and token;
- a compute-provisioning integration test: a host placed in a pool on relay R2, or
  unplaced, whose declaration sits in a pool on R1, is leased a port on R1 and
  dispatched with R1's relay reference; and a declaration holding a lease is
  refused a move to a pool on another relay.

The corrected account goes to `physical-provisioning`'s companion, and the
roadmap's gap closes. The management-route rule keeps reading the host's pool: it
claims only the obvious case, since any admission-enforcing relay refuses a
management proxy. The host pool-change hook and the drain keep reading placement
too; they only refuse or withhold more than necessary.

*Rejected.* Dropping the item with no test, which leaves the two facts unguarded,
so a later change to the relay roles or the declaration's uniqueness could create
the defect unnoticed. Extending the management-route rule to the declaration's
pool, which needs either a relay seam into the site's declaration writes, in the
area `inject-site-pool-authority` is reshaping, or a refusal at purchase time, to
widen a check that never claimed completeness. A placement rule (a declaration
naming a placed host sits on its host's pool's relay), which constrains operators
to fix no buyer-visible defect and reaches into `kit/site`. Leasing on the host's
relay, which makes placement decide delivery and gives an unplaced host no relay.
Making the host's pool authoritative for its declarations, which contradicts "a
declaration names its own pool".

### D2 — Concurrent retries return the first acceptance and the owner's lease

Two small fixes, each proven by a deterministic test on SQLite.

**The allocator.** `allocate_in_session` looks up the owner's active lease after it
takes the relay row's lock and before it refuses a missing or disabled relay, so a
claim that waited on the lock sees a lease committed meanwhile, and an owner
already holding a lease on a draining relay still receives it (11 F8). On any `IntegrityError` it reads the owner's active lease
again and returns it when one now exists — the case of a concurrent claim on
another relay, which the relay lock does not serialize — and moves to the next port
only otherwise. `RelayWindowExhaustedError` therefore means the window is full. The
two constraints are told apart by re-reading state, not by a dialect's constraint
name, so the rule is the same on SQLite and PostgreSQL. Tests: the statement order
rendered for the PostgreSQL dialect (owner lookup after `relays … FOR UPDATE`), as
the existing relay-lock test does; a test-only allocator subclass whose first
owner lookup misses, standing for a lookup taken before another claim committed,
which must return the existing lease; and the existing drain scenario, an owner
holding a lease on a disabled relay receiving it.

**Acceptance.** `accept_fulfillment`'s locked select takes `populate_existing`, as
the allocator's relay read already does, so an equivalent retry that waited on the
row lock judges the committed row and returns the first acceptance's fulfillment
without accepting, preparing or persisting again. Test: session 2 loads the row,
session 1 accepts and commits, session 2 accepts and receives session 1's
fulfillment ID. `FulfillmentTransaction.accept` drops its unlocked pre-read and
`FulfillmentAcceptanceDecision` drops `newly_accepted`, which that read fed and no
caller reads, so nothing in acceptance is judged from a read taken before the lock
(11 F7); the kit takes a minor bump for the removed field. This is a defect found
during the change, outside item 2's stated scope, recorded in the task notes.

Neither fix changes a wire form, a stored record, or a configuration key.

*Rejected.* Dropping the item, which leaves the allocator's stated idempotence
wrong under a lock-free caller and the reachable stale read unowned. The allocator
alone, which closes the named gap and leaves its reachable sibling. A PostgreSQL
lane, which is new test infrastructure out of proportion here (Open Questions).

### D3 — A lease waits while its fulfillment still has something to try

The release status port reports a `teardown_failed` aggregate whose rerun is
pending (D5) as tearing down, and reports it failed only when none is pending: its
execution started, its job was cancelled, reruns are disabled, or they are spent.
The lease therefore stays `releasing` until the aggregate settles — `torn_down`
releases it, a `teardown_failed` with no rerun pending sends it to
`release_failed` — or the grace below passes, and `release_failed` means only that
an operator must act.

The stalled-teardown timeout stays the backstop (11 F6).
`lease_watchdog_grace_period_seconds` keeps its meaning: a lease still `releasing`
past it, timed from when it entered `releasing`, goes to `release_failed` with
`teardown_timeout`, whether its teardown is in progress or a rerun is pending. Its
default rises from 300 to 3600 seconds, in the service's settings and in both
charts' values, sized for the teardowns a deployment is expected to run, not for
the longest the settings allow (26 F2). A job whose execution never started fails
at once, without retries — a refusal before the spawn fails the job outright — so
at the defaults a teardown's waits are the reruns' spacing of 60, 120 and 240
seconds and the backoff of the one job whose execution starts, 60, 120 and 240
seconds again: 14 minutes together, leaving about 46 minutes for that job's
playbook runs. A teardown that succeeds on a job retry or a rerun within that no
longer strands its lease, and every stuck release — a status read that keeps
raising, a teardown whose job vanished, a hung convergence — still reaches an
operator within the hour.

A teardown whose attempts run longer — each may run to `ansible_timeout_seconds`,
1800 by default, so four of them can take over two hours — is timed out like any
stuck release. Its lease goes to `release_failed` with `teardown_timeout`, and
since an operator's retry-release re-observes the same aggregate, a teardown that
has since reached `torn_down` is released by that one call. Raising the default to
cover the worst case the settings allow, about 8040 seconds, would hold every stuck
release from an operator for two and a half hours to spare a call for teardowns
no deployment is expected to run. An operator who raises `teardown_rerun_limit`,
the job retries or `ansible_timeout_seconds`, or whose teardowns run longer,
raises the grace with them; a deployment that pinned 300 strands teardowns that
succeed on a retry until it raises it, as the handbook's upgrade step says. The
operator event for `teardown_timeout` is
`report-provisioning-failures-to-operators`'s.

`relay_grant_expiry_grace_seconds` stays 3600. Its sizing rule is restated over the
teardown still due rather than over the watchdog grace, and over the same expected
teardown the watchdog grace is sized for: the reruns' spacing for
`teardown_rerun_limit` reruns, a teardown job's retries with their backoff, and
the runs a teardown is expected to take, so a grant does not expire while a
working teardown is still due. Past the watchdog grace no teardown is due: the
lease is `release_failed` and an operator acts. Raising the grant grace to cover
the watchdog grace instead would hold every released port in quarantine for up to
two hours after its lease's end, for no failure it prevents.

The version-1 leftovers of `marketplace-v0.3.0` are not rerun: their jobs finished
before starts were recorded, so nothing proves their playbooks never ran (D4,
26 F1). Their leases stay `release_failed`, and the operator handbook's upgrade
step for them — remove the workload by hand, then force-release — stands.

*Rejected.* Re-observing `release_failed` leases automatically, which would make
`release_failed` mean "failed so far", so an operator verifying hosts could not
tell which leases are theirs. Leaving the lease side unchanged, which keeps an
operator call for every recovered teardown and leaves the timeout stranding
successful ones. A one-time sweep re-requesting release for the upgrade's
leftovers, which is recovery machinery for teardowns nothing proves never started
(26 F1).
Keeping a state-changing timeout timed from the current teardown job, which keeps a
clock that can still be wrong. Turning the timeout into a counted diagnostic that
changes no state, which leaves a hung teardown invisible: the count has no surface
an operator reads (11 F6). Keeping the grace as a diagnostic threshold beside a
second, derived bound that changes state, which keeps two clocks. Surfacing the
count on `check-leases` with no state change, a passive signal for a case where an
operator must act. Raising the grace and the grant grace above the worst case the
settings allow, about 9000 seconds, which delays every stuck release's operator by
two and a half hours and lengthens a released port's quarantine (26 F2).

### D4 — A job records that its execution is starting before it starts

`JobRun` gains `report_starting()`, which an executor calls immediately before it
starts anything that can act on the host — the Ansible executor before spawning
the playbook. The job engine commits the instant to a new nullable
`execution_started_at` column there; if the commit fails, the callback raises and
nothing is spawned. Three rules complete it (11 F10):

- The callback raises unless the job is still `running`, so a job cancelled
  between its claim and its start spawns nothing; the attempt fails through the
  engine's internal-error path, which leaves a cancelled job cancelled. This is
  unlike `report_handle`, which returns quietly on a cancelled job because its
  playbook already runs.
- A later attempt keeps the first recorded instant: the instant answers whether
  execution ever started. A retry never clears it, as it never clears
  `execution_handle`.
- The instant comes from the process's time source, as `created_at` does.

A job's execution never started when the job is `failed`, not `cancelled`, records
neither `execution_started_at` nor `execution_handle`, and records `finished_at`
(D5). The last condition tells the two eras apart (26 F1): an engine that records
starts stamps `finished_at` on every terminal transition, and no older engine runs
against the migrated database, so a terminal job with no `finished_at` was finished
before starts were recorded — every `marketplace-v0.3.0` job among them. Such a job
is never classified as never started: its engine spawned the playbook before it
recorded the handle, so a missing handle proves nothing. A started job keeps
today's rule, and a recorded start without a handle counts as started, so the
instant between spawning a playbook and recording its handle can never be read as
"never started". The mock runner goes through the same executor, so the lanes
record the start too.

The job read, `JobStatusResponse`, gains an optional `execution_started_at`, null
for a job not started or recorded before the column, and an optional
`finished_at` (D5), null for a job not finished or recorded before that column; a
client reading a service that does not report them reads null. Both columns are
one additive migration in compute provisioning, and the contracts package takes a
minor bump.

*Rejected.* The missing handle as it stands, which leaves the window after
spawning, where a failed handle write makes a running playbook read as never
started and a rerun would race it — for a job recorded before the column as for
any other, so the handle cannot classify old jobs either (26 F1). Classifying old
handleless jobs by their recorded error, rerunning only those whose message proves
a refusal before the spawn, such as `marketplace-v0.3.0`'s version-1 connection
refusal, which ties the predicate to one past release's free-text wording, where a
wrong match is an unsafe rerun. A provisional handle written before spawning, which
hands the runner a handle with no process to cancel and gives the column two
meanings.

### D5 — A rerun is a new job under a key derived from the jobs already bound

`dispatch_teardown` adopts the reservation's latest teardown job, unless that job's
execution never started (D4) and a rerun is ready; then it submits rerun *n* under
the contract key `"{reservation}:teardown:rerun-{n}"`, where *n* counts the
teardown jobs already bound to the reservation. The first teardown keeps
`"{reservation}:teardown"`. The frozen `prepared_teardown_operation` and its
parameters are reused, so a later pool edit never rewrites an accepted operation;
the relay's address and token and the host's connection are read at execution, as
for every job. A crash between submitting and recording finds the new job as the
latest and adopts it; concurrent dispatches collapse on the job identity's unique
index. The aggregate's `teardown_provider_metadata` names the latest job as
`teardown_job_id` and `current_job_id`; `create_job_id` and the lease's
`release_job_id` are unchanged.

Rerun *n* is ready once the previous teardown job has been finished for the job
retry policy's `delay_seconds(n − 1)`, up to `teardown_rerun_limit` reruns: a new
compute provisioning setting, default 3, where 0 disables reruns and a negative
value is refused at startup. A job's finish is recorded (11 F2): a new nullable
`finished_at` column, which the engine's `_transition` stamps from the process's
time source on every terminal status, in the same additive migration as
`execution_started_at`. A job finished before the column reads null, and is never
rerun: D4 does not classify it as never started (26 F1).
`updated_at` is not used: it takes the database's clock, which tests cannot drive,
and any later write moves it.

One predicate in `compute_provisioning`, beside `compensable`, decides, answering
`not_rerunnable` (started, cancelled, finished before starts were recorded, or
reruns disabled), `waiting(until)`,
`ready(n)`, or `spent(n)`. `dispatch_teardown` acts on `ready`; the release status
port reports `waiting` and `ready` as tearing down and the others as failed, its
message saying the execution never started and how many reruns were spent; the
operator event `report-provisioning-failures-to-operators` adds reads `spent`.

The predicate reads the reservation's teardown jobs through one engine-internal
read (11 F5): unpaginated, filtered to the reservation's jobs under the teardown
action, returning a compute-owned record per job — its status, whether its
execution is recorded as never started (D4), its `finished_at`, and its creation
order. The provider's
`JobReader` gains it, and the status port takes the same read. The engine's
paginated listing is not used: it returns the create job beside the teardowns, as
wire views carrying no action kind, handle or finish. The wire view gains only
`execution_started_at` and `finished_at` (D4); the release status's message,
saying the execution never started and how many reruns were spent, is the
operator's account of a never-started teardown, so the view carries no derived
flag. "Lease release delegates to durable fulfillment teardown" is modified to
admit the predicate as the release status's one source beyond the aggregate, as
`compensable` already reads the job-backed provider's metadata (11 F4); the
release adapter still submits and polls no provider job.

Convergence is unchanged. `FulfillmentConvergenceWatchdog`, provider-neutral in
the compute provisioning service, requeues every `teardown_failed` row as now, and
what a requeued dispatch submits is the provider's.

*Rejected.* Carrying the attempt in the prepared operation, which changes a
persisted envelope under a frozen schema version and teaches the
provider-neutral convergence about reruns. A random job per rerun, which loses
dispatch's crash safety. Reusing `default_max_retries` as the bound, which ties two
meanings to one key, or a constant an operator facing a long transient outage
cannot raise. Timing reruns from `updated_at`, which no test can drive, or not
spacing them at all, which spends the bound in a few convergence cycles on an
outage that would have cleared (11 F2). Serving the predicate from the paginated
listing, or widening the wire view with the action kind and a derived started
flag for data only the predicate needs (11 F5). Having the provider record the
predicate's outcome on the aggregate so the status port stays aggregate-only, which
needs a field on `extra="forbid"` metadata and a rule for when it goes stale
(11 F4).

### D6 — A storefront reads again a registry it could not read

`RegistryDisputePolicy` keeps, for each registry, whether its last descriptor read
succeeded and when it last failed. Each storefront's publication cycle, at its
`compose` stage, reads again every registry whose last read failed, so the first
publication after the registry answers carries the payments option. A successful
read is kept until the storefront restarts, as today, so a healthy registry is not
read again (26 F3). Today's one read, `MultiRegistryClient.get_descriptors` in
`core/storefront`, reads every configured registry, so it gains an optional
selection of the registries to read: an additive parameter, absent meaning every
registry as now, and a minor bump of the core storefront package. The policy's
re-read passes the registries whose last read failed.

While a registry is unread and `use_registry_dispute_authorities` is true, the
readiness of each mechanism whose options name a dispute authority reports it in
its `public_details`, under `dispute_authorities_unread`: each unread registry and
when its read last failed. It is a report, not a readiness blocker (11 F1): a
mechanism with any blocker is unready, and publication suppresses every option of
an unready mechanism, so a blocker would stop the options a seller's local
`[[Dispute]]` entries compose today while a registry is down, and its kind would
decide whether an open listing is closed or held. Readiness, publication and open
listings are therefore unchanged by an unread registry. The policy exposes its
unread registries; each storefront passes them into the mechanism readiness
resources under `dispute_authorities_unread`, as other readiness resources are
passed. `settlement status` shows them; `/health` does not depend on them.

The detail is each mechanism's own (26 F3). `SettlementConfigurationRegistry`
refuses a public detail its mechanism's registration does not allowlist, and keeps
public details mechanism-owned, so each mechanism whose options name a dispute
authority allowlists `dispute_authorities_unread` and its preflight copies it from
its resources, as Alkahest's preflight copies `chain_probe`: Alkahest
(`kit/alkahest`), whose allowlist gains the key, and Arkhai Payments
(`kit/arkhai-payments`), whose preflight reads its resources for the first time and
whose allowlist, empty today, gains it. Each kit takes a minor bump. Tests: the
policy's re-read after a multi-registry read in which one registry failed reads
only that registry; each of the two mechanisms reports an unread registry in its
public details, with no blocker, and passes the registry's validation.

Item 4's defect is a storefront relying on registry recommendations alone: one
whose local entries name no authority its options can use. A storefront with local
entries publishes their options while its registry is unread, today and after this
change.

*Rejected.* Reading every registry again periodically, which no one needs while
registries do not change recommendations at runtime (Open Questions) and which
raises whether a dropped recommendation republishes open listings. Refusing
readiness until read, which still needs the re-read to ever become ready and takes
a storefront serving existing buyers out of service whenever its registry is down.
A readiness blocker on every mechanism whose options name an authority, which
suppresses local-authority options while a registry is down (11 F1). A
`reachability` blocker only where no authority is available without the registry,
holding open listings meanwhile, which adds a publication behaviour to two
specifications for a report D6 needs only to show. Reading every registry again
each cycle while any is unread, adopting only the failed ones' results, which
spares the core read its selection but reads healthy registries again (26 F3).
Reporting the unread registries at the composition level — a detail the runtime
adds to mechanisms' readiness outside their allowlists, or a field of
`settlement status` outside every mechanism's readiness — which spares the two
mechanism kits but weakens the rule that public details are mechanism-owned, or
changes the status representation (26 F3).

### D7 — A compensating teardown reruns by the same rule

A compensating teardown is the domain's ordinary teardown, dispatched through the
same `dispatch_teardown`, so D5's rule applies to it unchanged, and its failure
keeps `create_compensation` as before. Every domain's teardown is already required
to be safe after a partial create. The handbook's note on creates that failed on a
version-1 host stands: their compensating teardowns finished before starts were
recorded, so they are not rerun (D4, 26 F1).

*Rejected.* Excluding compensations, a special case on a failure reason inside a
compute predicate that no risk calls for.

### D8 — The rule that a fulfillment's teardown is one job is restated in `physical-provisioning`

`physical-provisioning` gains "A teardown that never started is run again under a
new job identity, within a bound" (D5, D7) and "A job records that its execution
is starting before it starts" (D4). "An undelivered lease is released by what its
fulfillment proves" is modified for D3, as are the release-failure scenarios of
"Allocation-backed lease release" and "Site-backed release lifecycle", which now
hold for a failure no rerun will retry, and "Lease release delegates to durable
fulfillment teardown", whose release status reads the rerun predicate beside the
aggregate (D5, 11 F4). "Lease release and fulfillment teardown
have separate retry ownership" keeps its rule — the lease never creates a teardown
— and its scenario states that a rerun is the provider's, under the same
`fulfillment_id`. Closeout rewrites the companion's "Proof-driven release", whose
sentence that only VM-backed reservations read the aggregate is also out of date,
and `ARCHITECTURE.md`'s "Release". The `fulfillment` specification takes nothing for
item 5: its convergence already retries without a ceiling.

*Rejected.* Restating the rule in the `fulfillment` specification, which would
make the provider-neutral kit describe one provider's job identities.

### D9 — Item 3 is two requirements' scenarios, a test, a fix to the result read, and a deletion

A delivery conflict is a disagreement about a live delivery: the storefront compares
the recorded result with the delivery the site reports only while the site reports
the fulfillment `active` (`BareMetalFulfillmentService.status`), as the requirement's
"for an active bare-metal fulfillment" already states. An ending lease has no live
delivery to disagree about.

`storefront-publication`'s "A bare-metal delivery that conflicts with its recorded
result is refused" therefore gains, beside its refusal of the reads, that a buyer's
end is not refused for the conflict, terminates the lease through the lifecycle
`end`, and leaves the recorded result standing, and that once the lease is ending the
buyer's reads report the ending as for any ended lease, not the conflict. Its scenario
"A buyer ends a deal while the site reports a different delivery" states it: after the
end, the status read reports the lease ending, the result read answers the recorded
result, and the access read is refused as outside an active lease, none of them
answering `delivery_conflict`. A buyer under a conflict thus sees its lease end
through the status read, as every buyer does (the bare-metal lanes assert `released`
there).

The result read answered "not ready" while a lease was `terminating`, the state
`apply_end` records once it has terminated the lease and before the site reports a
teardown state, though the recorded result and receipt stood before and after: the
result route's admitted states predate `terminating` and were not extended when it
was added. The route admits `terminating`, and still answers "not ready" while no
result or receipt is recorded, so a lease ended before delivery reads as before.
`storefront-publication` gains "A bare-metal result read answers the recorded result
while its lease ends", a requirement of its own since it holds for every ending
lease, not only one under a conflict. Against `marketplace-v0.3.0` a 409 becomes a
200 carrying the recorded result, within the bare-metal storefront's minor bump this
change already takes. This is a defect found during the change, recorded in the task
notes.

Tests, application integration through the storefront's typed clients in
`test_http_settlement.py`: `test_a_delivery_other_than_the_recorded_result_is_a_conflict`
extended to the end and the three reads after it; a delivered deal whose lease is
`terminating`, the provisioning double still reporting the fulfillment `active` after
`terminate_lease`, read as its recorded result; and a lease ended before delivery,
read as not ready. `BareMetalFulfillmentService.converge_teardown` is deleted.

*Rejected.* A test with no scenario, which would guard a behaviour no requirement
states. The reads still answering `delivery_conflict` after the end, which needs the
storefront to keep a conflict past the live delivery it was judged against — a stored
mark on its lifecycle row, a migration, and a behaviour change for a state no
requirement motivates — and leaves a buyer under a conflict unable to see its lease
end through the status read. Dropping the after-end clause, which leaves the reads
after an end unstated, the gap D9 closes. Recording the result read as an unowned gap
rather than fixing it, which leaves "the reads report the ending" false for one read
and costs a later change a design, review and closeout for one admitted state.

### D10 — One round of three sessions

The change is implemented in one round of three sessions before one
implementation review. Each session owns its own files but one: sessions 1 and 2
both change the `compute_provisioning` package, which takes one version bump per
change, so session 1 owns the `compute_provisioning` and contracts bumps, any
dependents' lower bounds, and the lock refresh, and the plan makes session 2's
section depend on session 1's (11 F11). Session 3's packages are its own.

1. Item 5 (D3, D4, D5, D7, D8): the job engine's two columns and their migration,
   `report_starting`, the contract fields, the internal teardown-job read, the
   rerun predicate, provider dispatch, the status port and lease lifecycle,
   `teardown_rerun_limit`, the watchdog grace's default in the settings and both
   charts, the e2e helper's comment on the grace, the package bumps, and the
   operator handbook.
2. Items 1 and 2 (D1, D2): the relay guard tests, the allocator, and
   `kit/fulfillment`'s acceptance.
3. Items 3 and 4 (D6, D9): the core storefront package's selective descriptor
   read, the storefront kit, the Alkahest and Arkhai Payments mechanisms' public
   detail, the three storefronts, those packages' bumps, and the bare-metal test
   and deletion (26 F3).

The delta specifications are written whole at design, so no session edits a shared
specification file.

Session 3 stopped in item 3, which returned to design (D9). A fresh session, in the
same round, completes item 3 as D9 now gives it, in the bare-metal storefront, which
section 7's bump already covers; the round's implementation review and validation
follow it.

*Rejected.* Two rounds reviewing item 5 alone first, which the owner judged not
worth the extra round. One session for everything, which serializes independent
work. A second round for item 3's remainder alone, a review boundary for a few lines
in one package already bumped.

## Implementation cadence

One round of three sessions, as D10 gives it: session 1 implements item 5 (D3,
D4, D5, D7, D8); session 2 items 1 and 2 (D1, D2); session 3 items 3 and 4 (D6,
D9). After item 3's return to design, a fresh session in the same round completes
item 3 as D9 restates it (the result read during `terminating`, the extended
conflict test and its sibling cases, and the deletion already made). One
implementation review follows the round, then closeout.

## Risks / Trade-offs

- **A stuck release waits up to the grace before an operator sees it** (D3). A
  hung convergence, a vanished job or a status read that keeps raising holds its
  lease `releasing` for up to 3600 seconds by default, where 300 held it before;
  it then reaches `release_failed` with `teardown_timeout`. The durable operator
  event waits on `report-provisioning-failures-to-operators`.
- **A deployment that pinned the grace at 300 still strands teardowns that succeed
  on a retry** (D3), until it raises it, as the handbook's upgrade step says.
- **A teardown whose runs take longer than about 46 minutes in all is timed out**
  (D3, 26 F2). Its lease reaches `release_failed` with `teardown_timeout`, and an
  operator's retry-release releases it once its aggregate is `torn_down`. A
  deployment whose teardowns run that long raises the grace.
- **`marketplace-v0.3.0`'s version-1 leftovers stay manual** (D4, 26 F1). Nothing
  on their jobs proves their playbooks never ran, so they are not rerun, and the
  handbook's steps for them — remove the workload, then force-release — stand.
- **A persistent pre-start cause spends the rerun bound in about seven minutes**
  (D5). That is intended: a persistent cause should reach an operator quickly; an
  operator facing a longer transient outage raises `teardown_rerun_limit`.
- **The PostgreSQL behaviour of D2 is proven by statement order and simulated
  interleavings, not by a PostgreSQL run** (Open Questions).
- **The three sessions share one review** (D10), so item 5, the only part with a
  migration and a lifecycle change, is reviewed beside four unrelated fixes.

## Open Questions

- **A PostgreSQL proof of D2.** Both fixes are proven on SQLite. Revisit when a
  change moves compute provisioning onto PostgreSQL or adds a PostgreSQL test
  lane: it runs the two concurrent retries for real.
- **Registry recommendations changing at runtime.** A storefront keeps a successful
  read until it restarts (D6). Revisit when the first registry changes its
  recommended dispute authorities while storefronts run, such as rotating an
  authority: periodic reads, and whether a dropped recommendation republishes open
  listings, are designed then.
