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
