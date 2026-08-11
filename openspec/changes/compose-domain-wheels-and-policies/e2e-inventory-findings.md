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
