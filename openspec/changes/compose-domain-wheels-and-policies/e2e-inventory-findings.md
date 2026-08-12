# E2E inventory failure — root cause, as of run 31434830271

## State

`5 failed, 59 passed, 42 skipped`. All six executor-host stages pass; the six
extra passes are those stages. **No previously-failing scenario became passing**,
so neither the projection fix nor the host-capacity fix addressed the cause.

## The chain, fully traced

    storefront negotiation / admin reserve
      -> capacity.snapshot() / capacity.reserve()
      -> GET /api/v1/capacity/snapshot on the provisioning service   (200 OK)
      -> _capacity_resource_inventory()                              (main.py:165)
      -> load_capacity_resource_inventory(
             session_factory,
             capacity_resources=ledger.list_resources(),             <-- empty
         )
      -> one projected entry per Host row, each correlated against a
         capacity resource matched by host identity

`ledger.list_resources()` returns only `weather-quota`. Confirmed in the compose
log across every run: exactly one `[CAPACITY] Registered resource` line, for the
API-credit quota, and never one for a VM resource.

So `_project_host` is always called with `capacity_resource=None` for `kvm1`. The
projection then carries only host-derived attributes — `vm_host`, `public_host`,
`gpu_count` — and never `region`. `has_matching_inventory_guard` requires the
listing's `region` and `gpu_model` to match, so it cannot.

## Why the two fixes did not help

* **Projection attribute fix** — correct and worth keeping, but it makes the
  *capacity resource's* attributes authoritative, and there is no capacity
  resource for a VM host to draw them from. It will matter the moment one exists.
* **Host capacity fix** — also correct: `kvm1` now has 4 GPUs rather than 1, which
  the `reserve_2x` scenarios need. But the reserve fails before capacity is
  consulted, on the same empty projection.

## The actual gap

Nothing registers VM resources in the site authority's capacity ledger. The
storefront's `admin_import_resources` writes to the storefront's own SQLite; the
site ledger is a separate store, written through
`PUT /api/v1/capacity/resources/{resource_id}`.

The API-credit domain already does this, and is the working precedent:

    domains/apicredits/storefront/src/apicredits_storefront/startup.py:112
      _register_seed_quota() -> SiteCapacityAdminClient.register_resource(...)

Note the direction. `market_site/router.py` calls that endpoint a "compatibility
endpoint for domains that register logical capacity directly", and says "physical
inventory projections are derived from the mounting provisioning service's
authoritative inventory provider". The storefront admin controller agrees:
`_mirror_resources_to_site_authority` is a deliberate no-op whose docstring reads
"storefront admin mutations must not push inventory into the provisioning ledger".

So for physical VM capacity the intended source is the provisioning service's own
inventory provider, not a storefront push. Two shapes follow, and choosing between
them is a design decision, not a bug fix:

1. **Provisioning derives capacity resources from its host rows.** Each registered
   host yields a capacity resource carrying the attributes a consumer matches on.
   Consistent with the stated direction, and it makes `kvm1` sufficient on its
   own — but attributes like `region` are storefront listing data today, not host
   data, so the host registry would have to carry them.
2. **The e2e scenarios register capacity resources explicitly**, as the API-credit
   domain does, through `SiteCapacityAdminClient` in the executor-host stage. Small
   and local, uses an endpoint that exists and is exercised, and keeps the seeded
   attributes with the scenario that declares them. But it uses the path the
   router calls a compatibility endpoint.

(2) is the smaller interim step and fits the anti-sleep, explicit-setup shape the
scenarios already use. (1) is what POOLS-9 is presumably for.

## Corrected sizing: neither option is right, and the fix is smaller than both

Two facts settle it.

**Provisioning cannot supply `region`.** There is no `region` column anywhere in
its DB models, and POOLS-9's own non-goals say why: `region`, `gpu_model` and
`sla` are "storefront-owned per `ARCHITECTURE.md`'s authority boundaries; this
change retires physical authority, not per-pool rows." Deriving these from host
inventory is not a small slice of POOLS-9 — it is against POOLS-9.

**The guard reads the wrong shape.** It skips any row whose `state` is not
`"available"`:

    if (row.get("state") or "").strip() != "available":
        continue

The site projection emits no `state` key at all. Its keys are `enabled`,
`available`, `capacity`, `attributes`, `resource_id`, `pool_id`, `resource_type`,
`resource_subtype`, and the executor fields. The storefront's *local* resource
table does have a `state` column.

So the guard was written against local rows and is now fed projected ones, and
every projected row is skipped before its attributes are ever examined. Fixing
the attributes could not have helped, and neither could registering capacity
resources — the rows would still have been discarded on the first condition.

That reframes the failure: not missing inventory, but a consumer reading a
projection with a local table's schema. Which is the class of defect `pools-8`
created by flipping `use_site_projection_for_listings` without retiring the local
path — the flip landed, and not every consumer moved with it.

## The shape of a minimal fix

The guard answers "is there available capacity matching this listing?" from two
authorities owning different halves:

* physical availability and capacity — the site projection, via its own
  vocabulary (`enabled`, `available`, `capacity`)
* commercial attributes — `region`, `gpu_model`, `sla` — storefront-owned

So it should read availability from the projection in the projection's terms, and
match commercial attributes against storefront-owned state rather than expecting
them in a physical projection.

Sizing, for the decision: POOLS-9 is 40 open tasks across 7 sections and none of
them is this. The guard fix touches `has_matching_inventory_guard`, the
`_default_seller_policy_inputs` snapshot feeding it, and their tests. It needs
none of the commercial override write path, the `compute_allocations` retirement,
or the CSV import retirement.

Worth checking while there: whether any other consumer of the projection still
reads it with the local table's schema. The same flip would have left them too.

## Which change owns this

`negotiation-capacity-feasibility-probe` — unstarted, 18 tasks — and its `Why`
names this exact defect:

> the seller's only shape check (`has_matching_inventory_guard`) compares `region`
> and `gpu_model` by equality [against] the advisory projection

Its design lists `has_matching_inventory_guard` as reading "an advisory snapshot
and compares two categorical fields", and replaces that with `probe()` — which
"runs the same matching logic used by `reserve()` and returns the match payload
without writing. It is the non-consuming twin of the admission path, not an
approximation of it."

That sidesteps both halves of today's failure rather than patching them. The guard
stops guessing at a projection's schema — no `state` key to get wrong — and stops
comparing commercial fields itself, because the authority does the matching. And
the plumbing already exists: `probe` is on `kit/site`, `SiteCapacityClient`, and
the aggregate client, and `vm_job_spec_service` already calls it in the
fulfillment path. Nothing calls it during negotiation.

## Where region and gpu_model are going

Confirmed against the active changes, and it matters because it rules out fixing
the guard by teaching it where to read each field today:

* **`region`** — `capacity-shape-envelope` and `pools-9` both treat it as
  pool-level commercial metadata. `pools-9` explicitly refuses to retire it from
  `compute_capacity_pools`: "Commercial state is storefront-owned."
* **`gpu_model`** — `structured-capacity-requirements` moves it into a
  family-grouped nested shape, `gpu: {count, model}`, flattened by a shared
  utility into the existing `dimensions`/`attributes` split. Its proposal
  anticipates exactly this interim: "POOLS-8's own inventory work landing before
  this change is implemented (e.g. projecting GPU model) uses the already-
  flattened form (`attributes["gpu_model"]`), forward-compatible with this
  change's eventual nested shape without needing migration."

So `attributes["gpu_model"]` is the sanctioned interim form, and any fix should
use it rather than inventing a shape. `region` should not migrate at all.

## What the e2e scenarios would have to set up

If the guard moves to `probe()`, the scenario's setup requirement changes shape.
It would no longer need commercial attributes to reach the site authority — the
probe asks the authority whether a claim is servable, and the authority matches on
what it owns. What the scenarios must then guarantee is that the site has capacity
for the claim: the executor host, already covered by the stage added here, plus
whatever the claim's quantitative dimensions require.

That is worth confirming against `probe`'s actual matching before committing to
it, because it decides whether any further admin endpoint is needed. If `probe`
matches on attributes the provisioning service does not hold, the same wall
returns one layer in.

## Correction: the host fallback is the designed path, and it works

`capacity-resource-administration`'s `Why` (36 tasks, unstarted) describes this
exact gap and says the fallback is intended:

> a host with no matching capacity resource projects `capacity` as
> `{"gpu_count": host.gpu_count}`, `resource_id` as the host name, and
> `resource_type` as `compute.gpu`. **That works, and it is why a host-seeded
> deployment publishes and sells today.**

So "nothing registers VM capacity resources" is not the defect — it is the
supported state, and `_project_host`'s `capacity_resource=None` branch is the
designed path for a GPU-count-only deployment. That change exists to add the
missing operator surface for *multi-dimensional* capacity, not to make GPU-count
capacity work.

Which returns the diagnosis to the guard, and narrows it to one line. The
projection is correct and populated; the guard discards every row of it because
it filters on a `state` key the projection has never emitted.

## What remains unverified, and it is the thing to check next

Whether `probe()` would clear it. `probe` matches
`resource.attributes.get(key) == value` against the site **ledger**
(`_find_candidate` queries `CapacityBucket`), while the host-derived projection is
a separate read path (`load_capacity_resource_inventory`). If the ledger holds no
VM buckets — and nothing derives buckets from hosts — then `probe` reports
unservable for the same underlying reason, one layer in.

That decides whether `negotiation-capacity-feasibility-probe` can be pulled
forward as the fix or whether it depends on `capacity-resource-administration`
first. The check is small: whether `_find_candidate` reads the same host-derived
inventory the snapshot does, or only the `CapacityBucket` table.

If it reads only buckets, the interim fix is the guard's `state` filter, not the
probe.

## Settled: the five failures are two distinct causes

`_find_candidate` queries `CapacityBucket` only, never the host-derived
projection. `probe()` and `reserve()` both go through it. `register_resource` is
the only thing that creates a bucket, and nothing calls it for VM resources.

That splits the failures cleanly:

| Failures | Path | Cause |
|---|---|---|
| B4, both `05a_evaluate_negotiate` | `capacity.snapshot()` -> `has_matching_inventory_guard` | the guard filters on a `state` key the projection does not emit |
| both `test_02_reserve_2x` | `capacity.reserve()` -> `_find_candidate` -> `CapacityBucket` | no VM bucket exists, because nothing registers a VM capacity resource |

They are not the same bug and they do not have the same fix.

**The three negotiation failures** are the one-line guard fix. The projection is
populated and correct; the guard reads it with the local table's schema.

**The two reserve failures** need a VM capacity resource in the ledger. This is
also why pulling `negotiation-capacity-feasibility-probe` forward would not help:
`probe` reads buckets, so moving the guard onto it would convert the three
negotiation failures into the same bucket failure the reserves already hit.

## Recommended split

1. **Now, in this branch:** fix the guard's `state` filter. Small, owned by no
   other change, and clears three of five. Use `attributes["gpu_model"]` as
   `structured-capacity-requirements` sanctions, and read availability in the
   projection's own vocabulary (`enabled`, `available`, `capacity`) rather than a
   `state` string.
2. **Also now, if the e2e scenarios are to pass:** register a VM capacity resource
   for the executor host, from the scenario's own setup stage via
   `SiteCapacityAdminClient` — the path `apicredits_storefront/startup.py` already
   uses. This is scenario setup, not product change, and it belongs in the
   executor-host stage beside the host registration already there.
3. **Not now:** `capacity-resource-administration` for the operator-facing
   multi-dimensional path, and `negotiation-capacity-feasibility-probe` for moving
   the guard onto `probe`. The second should land after the first, or it inherits
   the bucket gap.

Step 2 is the layer this branch keeps discovering: what the e2e stack must set up
for the system to work. It is not a workaround for a missing product feature —
`capacity-resource-administration` says a host-seeded deployment sells today via
the projection, and the ledger is a separate concern that a deployment registering
capacity would populate itself.

## What is verified

* `POST /api/v1/admin/capacity/projections/refresh` works — six calls, every site
  reporting `resource_pool: loaded` and `capacity_bucket: loaded`
* the executor host is registered with 4 GPUs before any scenario reserves
* the projection preserves declared attributes when a capacity resource exists
  (six unit tests, mutation-verified)

## What is not

That any VM capacity resource has ever existed in the site ledger. Until one does,
the projection has nothing to correlate and no amount of host or attribute work
changes the outcome.

---

# Correction, 2026-08-11 (run after 31434830271: `9 failed, 55 passed, 42 skipped`)

Two conclusions above are wrong, and one recommendation was applied in a shape that
introduced five new failures. Recorded here rather than by editing the text above, so the
reasoning that led to each is preserved.

## The traced chain is wrong at one hop

The chain above puts `_capacity_resource_inventory()` (`main.py:165`) under
`GET /api/v1/capacity/snapshot`. That path does not exist. In `make_capacity_router`,
`get_resource_inventory` is passed only into `SiteProjectionService`, which uses it for
`resource_pools()` and nothing else; `capacity_buckets()` reads
`ledger.list_resources()`. The `/snapshot` route calls `ledger.snapshot()` directly, which
is `list_resources()` filtered to enabled rows — one `_resource_payload` per
`CapacityBucket`.

`_resource_payload` **does** emit a `state` key, `"available"` or `"leased"`.

So the guard never received projection rows. It received bucket rows carrying exactly the
key it filtered on, and the list was empty. The `state`-filter diagnosis, and the
"consumer reading a projection with a local table's schema" framing built on it, do not
hold.

## Therefore the five failures were one cause, not two

The "Settled" table above splits them by path. Both paths read `CapacityBucket`:
`snapshot()` for the guard, `_find_candidate` for reserve. With no VM bucket in the ledger
the guard saw an empty list and the reserve found no candidate. One cause, one fix.

The current run confirms it. The `_row_is_available` rewrite landed, and the negotiation
failures persist in exactly the scenarios that still declare no capacity resource
(`RTX 5080` in `test_full_deal`, `RTX 4090` in `test_buy_oneshot_buyer_cli`), while the
H200 scenarios that now declare one get past the guard. That rewrite is defensible if
projection rows ever feed the guard — its own docstring shows the author believed they
did — but it fixed something that was not the cause, which is why no previously-failing
scenario became passing.

## "Nothing registers VM capacity resources by design" is exact for publishing and wrong
for selling

The quoted passage from `capacity-resource-administration` is accurate, and the
host-derived fallback genuinely is the designed path — for the **resource-pool
projection**, which is what listing derivation reads. It produces no `CapacityBucket`, and
`register_resource` is the only thing that does. Since `probe`, `reserve`, and the
negotiation guard's `snapshot()` all read buckets, a host-seeded deployment can publish
listings it cannot sell against. "That works, and it is why a host-seeded deployment
publishes and sells today" is precise about the first verb and not the second.

## `region` stays storefront-owned, and that does not block declaring it

`pools-9`'s non-goal is about *ownership* and stands. It does not prevent an operator
declaring `region` as a matchable attribute on a capacity declaration: the site ledger
stores `attributes` as an opaque mapping it never interprets, and a claim speaks the site's
resource-domain vocabulary by design. Declaring it is what step 2 above recommended and
what Section 11 does. The real consequence to hold onto is that `region` then exists in two
places — storefront commercial state and a site attribute — and the site cannot detect
drift between them.

## Step 2 was applied in a shape that sells hardware twice

`register_e2e_capacity` landed, and the fungible scenario used it to declare
`compute-e2e-fungible-a` and `-b` **both** on `vm_host=kvm1` — two four-GPU declarations on
a host with four physical GPUs. `load_capacity_resource_inventory` refuses two declarations
correlating to one host, so every subsequent `GET /site-resource-pools` returned 500 for
both storefronts for the rest of the run, which is the five new failures. The guard is
correct; a fungible pool is two hosts, not two declarations on one. Section 11 fixes the
setup, and `capacity-resource-administration` §4b moves the refusal to write time so one bad
declaration cannot take a site's projection down again.

---

# Run 31478292008 — `1 failed, 66 passed, 39 skipped`

Section 11's setup model holds. Every executor-host stage, both `05a`s, the fungible
reserve, and `test_02_admin_reserve_2x` are green. The compose logs contain no 500,
no `several capacity resources`, no `KeyError`, and no `'resource_pool': 'invalid'`.

The one remaining failure, `b4`, now gets much further: it negotiates (round 0 counter,
round 1 accept), agrees at 8500, creates the escrow, settles, and fails while polling
provisioning. Cause traced in the compose logs to
`AttributeError: 'ProgrammableMockAnsibleService' object has no attribute
'reserved_var_keys'` on `POST /api/v1/fulfillment/begin`, rendered to the buyer as
`Provisioning failed: Internal Server Error`.

That is a pre-existing divergence between the mock Ansible service and the service it
substitutes, not a capacity defect — `reserved_var_keys` was added to the real service
without the mock following, and no run had reached `begin_fulfillment` before now to
notice. Owned by section 12 of this change's plan.

Worth recording as a pattern, because this is the third instance in three runs: a test
double that does not match the real thing hides the defect until an outer layer reaches
it. `fake_site.py` returned reservation fields the real router strips; the provisioning
integration `db_engine` seeded a pool without the provider config the migration gives it;
`MockAnsibleService` lacked a method the real service has. Each was invisible to every
suite and visible only to the nightly e2e.

---

# Run 31479739305 — `2 failed, 66 passed, 38 skipped`

`b4` passes. The buy scenario now discovers, negotiates to agreement at 8500, creates the
escrow, settles, and provisions to `ready` — the first end-to-end VM deal this campaign has
produced. Section 12's mock fix was the last thing in its way.

Two failures remain and they are different in kind.

**`b5` — mine.** It asserts the listing closes while capacity is held and found it open.
Six of the nine seeded resources declare one sellable unit; the setup helper declared four
for every scenario, so a 1x reserve left three available and the 1x listing never closed.
Fixed in section 13.1 by making sellable units a required per-scenario argument, separate
from the host's hardware count.

**`test_04` — unattributed.** The release response reported no reopened listings because
the capacity-delta subscriber had already reopened them 24ms earlier, on a delta belonging
to a *different* resource, while the dynamic resource still held two of its four units. Two
readings fit the same evidence — a reopen that is not recomputed per resource, or the
release-path twin of the race `reserve_capacity` already unions around — and section 13.1
changes the delta's shape enough for the next run to separate them. Left open deliberately.

The pattern from the previous three runs did not recur: no test double diverged from the
real thing this time. What replaced it is subtler and worth naming for the next reader —
a helper-wide default standing in for a value only the caller knows. `sellable_units=4`
was wrong for six of nine scenarios and invisible until a scenario asserted on the one
behaviour that reads it.

---

# Run 31481250887 — `1 failed, 67 passed, 38 skipped`

`test_04` passes. Neither reading of that race needed a product fix: 13.1's correction to
the declared units changed the delta's shape and the inline release now reports its own
effect. Recorded because the alternative — patching the reopen path on a guess — was the
tempting move and would have been wrong.

`b5` fails one line further on, and it is the same defect class as the reserve response:
`DealLease.refresh` read `resource_id` from a reservation payload that has never carried
that key. The reservation exposes `settlement_resource_id`, set when scheduling binds a
concrete resource; `resource_id` was always `None`. The assertion had simply never run,
because `b4` failed in every previous run of this campaign.

Chasing that found the larger problem. `require_state(deal_state, ...,
"_evaluate_negotiate_passed")` gates stage 05b of both full-deal scenarios, and **nothing
ever set that field**. Every stage from 05b to the end — negotiation, escrow, settlement,
provisioning, lease registration, teardown — has been skipping. That is most of the 38
skips, and it is why `09c`, which asserts the same lease shape `b5` just failed on, never
executed to report it.

The pattern worth carrying forward: a required-state gate that no stage satisfies is
invisible in a green summary, because pytest reports a skip as neither failure nor pass.
`require_state` was introduced to make a scenario name its own dependencies — which it does
— but nothing checks that a declared dependency is ever produced. A test that asserts a
state is set, or a suite-level check that every `require_state` key is written somewhere,
would have caught this at introduction.

---

# Run 31482372498 — `4 failed, 74 passed, 28 skipped`

The stage-gate fix worked: seven more tests pass and ten fewer skip, and the newly
executing stages immediately found three defects. All four failures are first
executions, not regressions.

**`settlement_resource_id` null after scheduling.** `PhysicalSettlementScheduler`
rebound capacity only when the selected resource differed from the reservation's
existing debit, so the ordinary case — one candidate, already debited there — recorded
nothing on the reservation while `schedule_assignment` durably recorded it on the
settlement record. Two places carrying the same fact, disagreeing. The ledger's
assignment already handles the equality case cheaply, so the call is unconditional now.

**`fulfillment_id` missing from a typed client model.** The server returns it and
documents it as the field to prefer; `storefront_client.SettleStatusResponse` declared
`fulfillment_uid` instead and dropped `fulfillment_id` into `extra`. Stage 08b is the
first caller ever to ask. Note these are two genuinely different identities — the
durable fulfillment aggregate and the on-chain settlement claim — and one escrow row
carries both.

**The reopen race, finally attributed.** Two runs ago this looked like the release
path racing the delta subscriber. With timings it is something else: a reconciliation
for capacity version 5 reopened listings that a version-7 reservation had just closed,
and a version-7 pass closed them again 300ms later. Reopening on a stale availability
view over-advertises; closing on one is conservative. Filed as
`monotonic-listing-reconciliation`.

Worth recording that the earlier guess would have been wrong. Both readings offered in
run 31479739305 were plausible and neither was correct, and the fix that "would have
worked" — unioning the release response with listings reopened since a snapshot — would
have masked a defect that lets a storefront advertise capacity it cannot serve.

---

# Run 31483777656 — `3 failed, 79 passed, 24 skipped`

Five more passing, four fewer skipped. Both `09a` failures are the first execution of the
stage that drives provisioning to completion, and they found an operator control that has
never worked in any deployment: `POST /api/v1/system/fulfillment-convergence/run-cycle`
answers `503 fulfillment_convergence_watchdog not initialised`, because the container's
`_system_service` provider never passed the watchdog it builds two lines away.
`ARCHITECTURE.md` documents this control as available and requires a manual cycle to
invoke the same production handler; it had no handler at all.

The provisioning integration fixture built `SystemService` without it too — the fourth
test double this campaign that looked like production and wasn't (`fake_site`'s reserve
response, `db_engine`'s default pool, `MockAnsibleService`'s method surface, now this).
Fixed both, and added a unit test on the provider function itself, because a provider that
drops an argument fails nowhere at import time.

The third failure is `monotonic-listing-reconciliation` again, in the fungible pool this
time, and it adds two facts to that change: a *registration* delta triggers a reopen pass
(`register_resource` emits a `released` kind for a new resource), and an inline reserve
reported closing two listings that a read immediately afterwards observed open — so write
ordering between the subscriber and the inline close is not settled by their log order,
and a freshness gate alone may not be the whole fix. Every derived-listing status
assertion in that scenario now polls for the converged state rather than only the one that
failed first; the reserve responses' own `closed_listing_ids` remain strictly asserted.

---

# Methodology change, 2026-08-11

The four listing-status assertions in the dynamic-listing scenario have been through three
shapes in this campaign, and the third is the one that holds.

They began as a single sample taken immediately after a reserve, which raced the
storefront's one-second capacity poller and failed roughly half the time. They were then
made to poll until the state settled, which passed — and was wrong: it is the sleep
`docs/development/TESTING.md` forbids, it cannot prove ordering even when green, and it
would have hidden the reopen defect rather than surfacing it. They are now asserted twice
around one deliberate advance, against a storefront paused for the whole module.

The middle step is the one worth remembering. It was introduced during implementation
rather than designed, it made the suite green, and the greenness is precisely what would
have let it become the pattern. A tolerance that makes a race pass is not a fix for the
race; it is a way of agreeing not to look at it.

The instrument now exists to look at it: with the poller halted,
`monotonic-listing-reconciliation` either reproduces on a named advance or does not
reproduce at all, and that is the next question to answer.

---

# Run 31493466153 — the stack never came up

No pytest summary because no test ran. `alice-storefront` exited 3 during
`compose up --wait`:

```
TypeError: run_storefront_startup_steps() got an unexpected keyword argument 'task_logger'
```

Self-inflicted, and instructive about where this repository's coverage ends. Routing the
five loop starts through a new registry meant renaming their `logger=` keyword to
`task_logger=`; the rename was applied across `startup.py` and caught a sixth call — the
step runner itself, which takes `logger=`. Every suite passed, because `_startup_tasks`
runs only inside a live application lifespan and nothing below the end-to-end level
executes it. The first signal was a container exit code.

A unit test now walks `startup.py` for every call to the step runner and the loop
registry and validates each keyword against the real signature, and it fails when the
defect is reintroduced. Worth noting the first version of that test did not: it inspected
the `_start_*` helper functions, which is where the rename was *correct*, and passed
cleanly against the live defect. A guard written from the shape of the fix rather than
from the shape of the failure proves nothing, and the only way to know which one you have
written is to reintroduce the defect and watch the test go red.

---

# Run 31495188400 — `2 failed, 84 passed, 21 skipped`

The stack came up and the suite got further than it ever has: 84 passing, 21 skipped.
Both prior fixes are confirmed working — `settlement_resource_id` now reads
`compute-e2e-deal-001` on the lease, and the dynamic-listing scenario's pause-and-advance
stages pass.

**`09c` — a legacy field on the durable path.** The stage asserted
`lease["create_job_id"]`, described as "a tracked Ansible create job". That field is only
ever written by a caller registering a lease with an Ansible job id; a deal that went
through the durable fulfillment path has none, by exactly the rule that keeps
`provisioning_job_id` empty on settle status. The third instance of this shape in this
campaign, after `resource_id` and `fulfillment_id`: a scenario asserting on the identity
the old path produced, reached for the first time now that the flow runs to completion.
Both full-deal variants now assert the durable identity instead.

**`09b` (buyer CLI) — `monotonic-listing-reconciliation`, in an unconverted scenario.**
The listing was closed at 13:18:23 and reopened at 13:18:26 by a reconciliation for
`compute-e2e-deal-001` while its capacity was still held, then closed again at 13:18:29.
The same flap, in a scenario that does not pause the storefront — only the
dynamic-listing scenario has been converted so far.

That is the useful signal from this run: the two scenarios that pause do not exhibit the
flap and the ones that do not pause still do. The conversion works; it just has not been
applied to the rest of the suite yet.

---

# Run 31499398440 — `4 failed, 85 passed, 18 skipped`

One more passing, three fewer skipped, and the interruption/teardown stages ran for the
first time in this campaign. Three of the four failures are one cause.

**`10a`, and `11a`/`11b` cascading from it.** The admin interrupt endpoint answers
`409 Deal is not marked interruptible/splitter-backed`. The scenario's offer does declare
`"interruptible": True` — but `ComputeResource` has no such field, pydantic drops unknown
keys by default, and so the stored `offer_resource` never carries it. The word
`interruptible` does not appear anywhere in the run's compose logs.

`_deal_is_interruptible` then falls through to its second test, whether the buyer's escrow
proposal is splitter-gated, which a plain MockERC20 escrow is not. So the guard is
unsatisfiable for every deal this suite creates, and `11a`/`11b` never get to run.

This is a real gap, not a scenario mistake: an admin control gates on an offer attribute
the offer schema cannot express. Three shapes of fix, and the choice is a product decision
rather than a test one:

1. `ComputeResource` gains `interruptible: bool = False`. Interruptibility is a commercial
   property of the offer — spot versus on-demand — and a buyer arguably needs to see it
   before agreeing, which argues for a first-class field. It changes the published offer
   wire shape.
2. The guard reads a provider tag under `attributes["tag.*"]`. No wire change, but the
   model's own docstring says tags are opaque to policy and matched by equality, and this
   value is load-bearing for a lifecycle control — the wrong home for it.
3. The scenario makes its deals splitter-gated so the existing second test passes. Keeps
   production untouched, and leaves the first test dead code that no deal can satisfy.

**`09b` (buyer CLI)** is `monotonic-listing-reconciliation` again, in a scenario not yet
converted to pause-and-advance. Unchanged from the previous run and expected until 4.2b
lands.

Worth noting what this run confirms about the campaign's shape. Every fix has moved the
failure further down the same flow rather than sideways: capacity setup, then the mock's
method surface, then placement identity, then the stage gate, then wiring, then lease
identity, and now an offer attribute that cannot be expressed. Each was invisible until
the flow reached it, and each was a real defect rather than a test artefact.

## Teardown now triggers on expiry, not interruption

The `10a` stages in both full-deal scenarios back-date the lease instead of posting an
interrupt. Two reasons, and the second is the stronger one.

The interrupt guard is unsatisfiable (see above), so the stages could not pass as written.
But the guard is not really what was wrong. Lease expiry is how a lease ends in
production; interruption is an operator escape hatch for capacity sold as preemptible.
Driving the main teardown path with the escape hatch meant the ordinary path — the one
every real deal takes — had no coverage at all, and `DealLease.backdate`, written for
exactly this and documented in the class docstring as how the full-deal scenarios drive
expiry, had never been called by anything.

Everything after `10a` is unchanged: `10b` still runs one explicit `check_leases` cycle,
the `vm_remove` mock rule still holds the provider at its gate, and `11a`/`11b` still
assert convergence. They key off the lease view and the gate rather than off the interrupt
response, which is why swapping the trigger was a local change.

The interrupt control keeps its own defect, now owned by
`declare-interruptible-on-a-compute-offer`, along with an end-to-end scenario dedicated to
it. That is the right place for it: one scenario proving the escape hatch, rather than two
scenarios using the escape hatch to prove something else.

---

# Run 31539745808 — `3 failed, 80 passed, 24 skipped`

`10a` passes: the lease back-dates and the watchdog picks it up. All three failures are
one cause, and the cause is mine.

`_process_releasing_reservation` computes `past_grace = now >= lease_end + grace_seconds`
with a 300s grace, and marks `release_failed` the moment grace elapses with `vm_remove`
unfinished. Back-dating two hours put the lease past grace before the release even began,
so the first watchdog cycle dispatched the removal and timed it out in the same pass:

```
[LEASE_LIFECYCLE] Release failed for reservation 4502647a...:
  vm_remove_timeout vm_remove did not complete before watchdog grace period elapsed
[LEASE_LIFECYCLE] Cycle: checked=1 released=0 release_failed=1 skipped=0
```

The back-date is bounded on both sides and I only reasoned about one: the lease must be
past its end for the watchdog to act, and must *not* be past grace, because 11a and 11b
deliberately hold `vm_remove` at a mock gate. One minute expires the lease and leaves
about four for the gated stages. The constant now says both bounds.

`11b` follows from `10b`. `05a` in the buyer-CLI scenario is the more interesting cascade:
the failed release never returned the capacity, and both full-deal scenarios declared the
same `compute-e2e-deal-001`, so the second scenario's inventory guard found nothing
available and vetoed at round 0. The buyer-CLI scenario now declares
`compute-e2e-deal-cli-001` on its own host.

That is the same lesson as the shared `kvm1` executor from the start of this campaign, in
a different field: two scenarios sharing an identity makes one scenario's failure look
like a defect in the other, and the second failure is the one that gets debugged. Per
scenario, per resource, per host.

---

# Run 31578351290 — `3 failed, 88 passed, 16 skipped`

Best yet: 88 passing, 16 skipped, and the grace-window fix worked — `10a` and `11a` pass
and the release job is submitted rather than timed out. All three remaining failures point
at one fixture, and it is a teardown that is no longer only a teardown.

`release_reserved_resources` is a module-scoped autouse fixture that calls
`POST /api/v1/admin/portfolio/release-reservations` — a *fleet-wide* release of every held
reservation on the storefront. Its docstring explains itself as a workaround: "mocked
provisioning never expires the lease, so the resource stays in reserved state forever…
this fixture is the test-only equivalent for the short-circuited mock flow."

That premise is now false. Stage 10a expires the lease deliberately and 10b drives the
watchdog through it, so the mock flow does expire leases — the scenarios stopped being
short-circuited when teardown moved onto the production path.

The run shows four fleet-wide releases, and two land badly:

- `08:30:56` — a release names `ledger:default:bcc1010d…`, the `test_full_deal` lease,
  in the same second the lease lifecycle submits its release job. `10b` then reads no
  `release_job_id` on the lease and fails; `11b` follows.
- `08:31:01` fulfillment for the buyer-CLI deal, then a release at line 1745, then `09c`
  at line 1943 finds no reservation carrying a `lease_end_utc` at all — the reservation it
  needs was released between its registration and its assertion.

So the fixture now races the very lifecycle it was written to substitute for, and because
it is fleet-wide and autouse it can clear another scenario's reservation as easily as its
own. It should be scoped to the reservations its own module created, or removed in favour
of the expiry path the scenarios now drive — but which, and whether any scenario still
needs the workaround, wants deciding rather than guessing. Two prior loops in this campaign
were lost to fixing a symptom whose cause was elsewhere, and this is the same shape: the
failing assertions are in `10b`, `11b`, and `09c`, and none of them is where the problem
is.

## The fleet-wide release fixture is gone

Removed rather than scoped. Both halves of its stated premise were false by the time it
failed: leases expire on the production path now, and every scenario declares its own
resource, so the starvation it was written to prevent cannot happen between scenarios.

What it leaves behind is worth stating plainly, because the fixture was load-bearing for
something real once. Scenarios that hold capacity and never release it — the one-shot buy,
multi-registry, and the settlement variants — now finish with their capacity still held.
That is correct within a run, since each holds only its own resource. It does mean a repeat
run against a long-lived stack would find that capacity gone, and the right home for that
is the stack's reset, not a test teardown that can reach across scenarios.

The pattern this closes, three instances in: a shared executor host, then a shared resource
id, then a shared release. Each made one scenario's behaviour depend on another's, and each
time the failure surfaced in the scenario that was not at fault. Per scenario, per
resource, per host, and no fixture that acts on anything it did not create.

---

# Run 31579815786 — `4 failed, 91 passed, 12 skipped`

91 passing, 12 skipped. Removing the fleet-wide release worked: `09c` passes in both
scenarios, and no reservation is cleared out from under another module. The four remaining
failures are two causes, symmetric across the two full-deal scenarios, and both are in the
scenarios rather than the product.

**`10b` — reading a field the lease contract does not have.** `DealLease.refresh` mapped
`fulfillment_id` from `lease["release_job_id"]`. `LeaseResponse` exposes
`vm_remove_job_id`; it has never had `release_job_id`. The ledger writes the release job id
to *both* columns — `_sync_release_job_fields` sets `release_job_id` and, for VM executors,
`vm_remove_job_id` — but only the vm-flavoured name is on the lease contract, so the view
read `None` however healthy the release was. The logs show the release job submitted
normally (`019ff529-…`), and `11b`'s own failure output prints that same id as the
fulfillment id, which is what settles it: the release existed and the reader was wrong.

Fourth instance of this shape in the campaign, after `resource_id`, `fulfillment_id`, and
`create_job_id`: a scenario reading an identity under a name the contract does not use.
Each was invisible until the flow reached it. Now falls back to the reservation row's
`release_job_id`, so a non-VM executor populating only that column still resolves.

**`11b` — asserting one step early.** After the `vm_remove` gate is released, nothing has
yet looked at the resulting job. A lease cycle polls it and finishes the release, and only
a finished release lets convergence record the fulfillment as torn down. The stage called
`run_fulfillment_convergence_cycle` first and asserted `torn_down`, observing
`tearing_down` — the correct state, read before the step that advances it. The two calls are
now in that order.

Worth noting this one is a consequence of the teardown trigger moving to lease expiry. Under
the old interrupt path the storefront had already begun teardown before the stage ran, so
the ordering happened to be satisfied. The stage was always relying on something it did not
state.

---

# Run 31581689519 — `2 failed, 93 passed, 12 skipped`

93 passing. `10b` passes in both scenarios: reading `vm_remove_job_id` was the right fix.
Only `11b` remains, and my previous change to it was wrong in an instructive way.

The reorder moved the lease cycle ahead of convergence, and the cycle reported
`{checked: 0, released: 0, release_failed: 0, skipped: 1}` — the releasing reservation was
processed and its release job was not yet succeeded. So both two-call orderings have now
been observed failing, each one step short of the state it asserted:

- convergence, then lease cycle → fulfillment still `tearing_down`
- lease cycle, then convergence → release job unfinished, cycle reports `skipped`

The reason is that three parties hand off and none of them looks twice.
`provisioning_test_client.drain` waits on the **Ansible** job queue, which is where
`vm_remove` runs; the release job the lease cycle polls is a fulfillment aggregate, not an
Ansible job — the ids in the logs are UUIDv7 fulfillment ids, not queue job ids. So
convergence must first notice the Ansible job finished and advance the release fulfillment;
the lease cycle then sees that fulfillment succeed, finishes the release and returns the
units; a second convergence records `torn_down`.

The stage now performs all three advances and asserts only afterwards. Asserting between
them is what produced two runs of near-misses, and in both cases the product was doing
exactly the right thing one step later.

The correction I would make to my own earlier reasoning: when a stage fails by one step, the
useful question is not "which order is right" but "how many parties are involved". I
answered the first question twice and got it wrong both times, because the answer to the
second is three.

---

# Run 31586372700 — `2 failed, 89 passed, 16 skipped`

`11b` still reports `{checked: 0, released: 0, release_failed: 0, skipped: 1}` with three
advances, so my inference last run was wrong too. I have now guessed twice at this stage and
been wrong twice, so this entry records the traced chain instead of a third guess.

What is now established by reading the code rather than inferring from failure shapes:

- The lease cycle's release job is not a queue job. `ReleaseJobDispatcher.get_job` routes by
  executor kind to the VM adapter's release port, which maps the *fulfillment's* state:
  `torn_down` → `succeeded`, `teardown_failed` → `failed`, anything else → `running`.
- So `check_leases` can only ever return `released` once the fulfillment is already
  `torn_down`. The lease cycle is downstream of convergence, not a peer of it — my
  "three parties handing off" description had the topology right and the reason wrong.
- Convergence reaches `torn_down` only through `_converge_teardown_record`, which polls the
  provider status recorded under `teardown_provider_metadata` and returns early while that
  status is `pending`.

That narrows the question to one thing, and it is a product question rather than a stage
ordering one: **after `vm_remove` completes, does the teardown's provider status ever become
`succeeded` under the mock profile?** `drain` returning successfully means every Ansible job
reached a terminal state, so the removal itself finished. If convergence still sees
`pending`, the candidates are that `teardown_provider_metadata` was never recorded at
dispatch, or that it was recorded in a shape `_provider_status` cannot resolve — in which
case `_log_retry("teardown status", …)` will have logged it, and that log line is the next
thing to read.

No stage change is worth making until that is answered. Two runs have been spent moving
assertions around a stage whose blocking condition is upstream of every assertion in it.

The correction to carry forward: `11b`'s failures were legible as an ordering problem for
two runs because reordering changed *which* assertion failed. A stage that fails differently
when reordered is not thereby an ordering problem — it can equally be one blocked precondition
observed from two angles, and distinguishing those requires tracing the dependency rather
than permuting the calls.

---

# Run 31589320954 — `2 failed, 93 passed, 12 skipped`

The claim-lease fix worked. `11b` now gets past everything it has failed on for five runs:
convergence records `torn_down`, the lease cycle returns the units, the release stage event
arrives, the resource reads unconsumed, and re-reserving it succeeds. Both scenarios fail on
the last line of the stage instead:

```
POST /api/v1/admin/portfolio/resources/compute-e2e-deal-001/release-reservation
  → 404 {"detail":"Not Found"}
```

That is FastAPI's unmatched-route 404, not a handler's. **No storefront implements that
route.** `StorefrontClient.admin_release_one_reservation` has always posted to it, and its
docstring describes behaviour it has never had — "idempotent on already-available rows,
404 if the row doesn't exist" — which is exactly the misreading the response invites. The
surgical release it promises does exist, as `PATCH /portfolio/resources/{id}` with
`state=available`; the fleet-wide endpoint's own docstring points there.

Fifth instance in this campaign of a typed client and its server disagreeing, after
`resource_id`, `fulfillment_id`, `create_job_id`, and `release_job_id`. The first four were
field names; this one is a whole route. All five were invisible until a scenario reached
them, and all five read as product defects at first glance.

The stage now uses PATCH. The client method is annotated rather than deleted — it is public
API and a method that names its own absence is more useful to an outside caller than an
import error — and whether the route should exist server-side is left open, since the
capability is already reachable.

---

# Run 31591230862 — `95 passed, 12 skipped, 0 failed`

Green. The full VM end-to-end suite passes for the first time in this campaign, including
the complete deal lifecycle: discovery, negotiation to agreement, escrow, settlement,
provisioning to `ready`, lease expiry, gated teardown, release, and capacity reuse.

The twelve skips are not incidental and should not be read as "green enough". Every one is
in `test_multi_registry`, and every one is downstream of a single fixture:

```
alice_agent_id → pytest.skip("Alice has no live agent_id — the alice-storefront
                              container hasn't completed on-chain registration yet")
```

Alice's container starts, resolves its database, and polls capacity — its log lines stop
early at 11:22:08 while the run continues for minutes afterwards — and never registers on
chain. So the entire Alice half of the multi-registry scenario has never executed: her
health, her registry reachability, her strategy, her inventory seeding, her publication,
her presence in registry A and absence from registry B, the fan-in that proves two unique
listings, the dead-registry resilience case, and all three independent-negotiation stages.

That is the same shape as the `_evaluate_negotiate_passed` gate found earlier in this
campaign: a scenario that skips its own subject reports as neither pass nor failure, so a
green summary conceals it. The difference is that this gate is *satisfiable* — it depends on
a container completing registration rather than on a field nothing sets — so the harness
guard added for that defect does not catch it, correctly: the state is produced, just not by
Alice.

What the skips are protecting is real. A scenario that asserted against an unregistered
Alice would fail confusingly, and skipping is better than that. What is missing is anything
that notices the skip is permanent. Nothing distinguishes "Alice is slow to register on this
run" from "Alice has never registered on any run", and only the second is true.

## Pause-and-advance extended to the remaining scenarios

Four scenarios join the dynamic-listing one in pausing the storefront at a named stage and
advancing deliberately. Every listing-status assertion in them now advances the capacity
poller first, which removes the last places `monotonic-listing-reconciliation` could show up
as an intermittent failure rather than a reproducible one.

Two decisions worth recording rather than burying.

`test_non_erc20_settlement` is excluded. It is written as parametrized module-level
functions, not staged classes, so it has no readiness stage to pause in; adding one would
restructure the scenario for a benefit it does not need, since it makes no listing-status
assertion. Excluded deliberately rather than overlooked.

And pausing costs something. The green run shows Bob's claims engine completing three full
claim cycles — submitted, collectable, collected — purely because a timer fired during the
scenarios. No stage asserted on any of it, so nothing fails, but the suite stops exercising
a path it was exercising by accident. The right response is not to leave the loops running:
it is to advance the claims engine explicitly and assert what it did, which turns an
accident into coverage. Left as an open task rather than done here, because asserting on
claim *collection* would depend on on-chain conditions the scenario does not control, and
choosing what to assert deserves more than a passing decision.

---

# Run 31593556775 — `3 failed, 71 passed, 37 skipped`

A regression, and mine. Pausing each deal scenario at its readiness stage broke the deals:

```
POST /api/v1/negotiate/new → 503
  {"error":"paused","reason":"global",
   "hint":"Storefront or listing is paused; use admin API to advance or resume"}
```

Pause has always meant "refuse new negotiations" — that was its entire meaning before this
work extended it to the timer loops. So a scenario cannot hold the pause across the step
that agrees the deal, and three scenarios that must negotiate were paused before doing so.
71 passing against 95 is the cost, and the 37 skips are the downstream stages of the three
that failed.

The dynamic-listing scenario worked from the start because it never negotiates: it reserves
capacity through the admin API. That is why the pattern looked general when it was not, and
it is the kind of difference worth checking before generalising from one scenario to five.

The fix is placement. Each deal scenario now pauses immediately before the assertion that
needs determinism — after agreement and settlement — rather than at its readiness stage. The
determinism those stages need is only about what reconciliation does once capacity is held,
so nothing is lost by pausing later. `test_multi_registry` loses its pause entirely: it
makes no listing-status assertion, so it had nothing to gain and a negotiation to lose.

The design question this exposes is worth raising rather than working around. "Paused" now
carries two meanings — refuse new negotiations, and halt timer-driven work — and a caller
who wants the second without the first has no way to ask. The scenarios can live with the
conflation by pausing late, but an operator who wants to stop background writes while
continuing to trade cannot. Splitting the two, or naming the loop control separately, is a
product decision for the owner of
`storefront-lifecycle-pause-and-advance` rather than something to settle in a test.

---

# Run 31606573720 — `2 failed, 86 passed, 22 skipped`

The split works. All three deal scenarios now hold their loops idle from the readiness
stage while negotiating, agreeing, and settling normally — trading pause and loop pause are
genuinely independent in a live stack, which is what the split was for.

Both failures are one mistake of mine, and it is the mistake pause-and-advance is supposed
to make impossible:

```python
listing = storefront_admin_client.get_listing(...)   # captured here
advance_storefront(..., "capacity-events")           # reconciled after
assert listing.status == "closed"                    # asserts the older row
```

I inserted the advance immediately before the *assertion* rather than before the *fetch*, so
the row was captured before the reconcile it was meant to observe. The compose log settles
it: exactly one `stale_compute_listings_closed` fired all run, for `compute-e2e-buy-001` —
the buy scenario, where the advance happens to precede its fetch and which passed. No close
for `compute-e2e-deal-001` because nothing asked, and no stale read either; the deal
scenarios simply looked too early.

Worth stating what this run proves rather than only what it cost. Under the old timer-driven
arrangement this same ordering bug would have passed most of the time, because the poller
would have closed the listing within a second either way, and it would have failed
occasionally and looked like `monotonic-listing-reconciliation`. Deterministic advance turned
a latent test bug into a repeatable failure with a one-line cause. That is the trade the
methodology makes: fewer intermittent failures, and no forgiveness for reading state at the
wrong moment.

Audited the other five advance sites — every one already reads after advancing.
