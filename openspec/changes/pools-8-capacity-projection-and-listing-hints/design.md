## Context

The site authority now publishes two independent projections: `site_resource_pools` for host/resource facts and `site_capacity_buckets` for grouped advisory capacity. Each has revision/digest identity. VM storefront startup loads and polls both into atomic in-memory caches with stale retention. No production publication or claim-building reader consumes those caches yet; accepted identities are not durable across restart (accepted by design as of 2026-08-03 — see "Section 2 revised decision," below — rather than a gap this change closes); and pool labels/provider/enabled/policy tags are absent from the resource projection.

Storefront `resources` and capacity-pool tables still combine commercial metadata with locally authored physical identity. Wholesale replacement would remove pricing, settlement, and operator state that the site authority does not own.

### Local physical-authority inventory (task 1.4, first pass — 2026-08-03)

All raw SQL, defined in `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py` (table DDL) and `.../utils/migrations.py` (additive tables):

| Table | Owner module | Kind |
|---|---|---|
| `resources` | `sqlite_client.py` | Physical identity + commercial fields, combined (target of this change's mapping split); live-read by `domains/vms/listings/reconciler.py` for capacity-driven listing derivation/reconciliation |
| `hosts` | `sqlite_client.py` | Physical identity (operator-declared host capacity, checked by `resource_capacity_validator.py`) |
| `resource_transition_events` | `sqlite_client.py` | Physical authority — audit trail for `resources` mutations, admin-only writer, no other reader |
| `compute_allocations` | `sqlite_client.py` | Operational bookkeeping, unrelated to `SiteAllocation`/`CapacityReservation` (POOLS-7 `design.md` item 1 already confirmed this table is out of that change's scope; carried forward here rather than re-litigated) |
| `derived_compute_listings` | `sqlite_client.py` | Commercial (published listing state); read/written by `reconciler.py`, `admin_controller.py`, `cli_publish.py` |
| `derived_bare_metal_listings` | `sqlite_client.py` | Commercial (published listing state) |
| `compute_capacity_pools` | `migrations.py` | Commercial pool concept, auto-derived side effect of `upsert_resource`; **correction (2026-08-03, Section 5 design): live-read by `domains/vms/listings/reconciler.available_compute_slices`, not orphaned — see below** |
| `compute_pool_members` | `migrations.py` | Commercial-pool membership referencing physical identity, same auto-derived/unread status as `compute_capacity_pools` |

Writers found so far:
- `domains/vms/listings/host_csv_importer.py`, `domains/vms/listings/resource_csv_importer.py` — CSV import into `hosts`/`resources`.
- `SQLiteClient.upsert_resource` — programmatic upsert into `resources`, gated by `resource_capacity_validator.py` (best-effort host-capacity check against `hosts`; passes through resources with no `vm_host` or an unregistered one).
- `domains/vms/listings/reconciler.py`'s `record_derived_listing`/`mark_derived_listings_closed`/`mark_derived_listings_open`/`reopen_local_derived_listing` — writers of `derived_compute_listings`, called from `admin_controller.py`, `cli_publish.py`, and the reconciliation path below.

Readers found so far:
- `controllers/admin_controller.py` — operator-facing CRUD/listing across `resources`/`hosts`/`derived_compute_listings`.
- `services/system_service.py` — status/diagnostic reads (e.g. `resource_count`).
- `services/resource_capacity_validator.py` — reads `hosts` only, to gate `upsert_resource`.
- **`domains/vms/listings/reconciler.py` is the real, central reader of `resources` and `derived_compute_listings` for capacity-driven listing derivation and reconciliation** — `available_compute_slices` queries `resources` directly (raw `SELECT ... FROM resources`) to compute open slices; `stale_open_listing_ids`/`closed_available_listing_ids` join `resources`/`derived_compute_listings` against caller-supplied `member_availability` to decide what to close/reopen. This corrects the earlier hedge in this section's prior pass, which suspected listing derivation might not read `resources` live — it does, through this module, not through `listing_service.create_listing` or `vm_job_spec_service.compute_capacity_claim_from_order`.
- `domains/vms/storefront/src/market_storefront/services/capacity_client.py` is the current production trigger for that reconciliation: `_make_listing_reconcile_subscriber`/`capacity_events_poller_loop` subscribe to the site authority's legacy `CapacityDelta` event feed, build `member_availability` via `member_availability_view`, and call `close_stale_compute_listings_after_capacity_change`/`reopen_available_compute_listings_after_capacity_change` (in `publication_service.py`, which delegates the actual table reads to `reconciler.py`). This is the delta-event mechanism, not the POOLS-7 `site_resource_pools`/`site_capacity_buckets` pull projections — confirming, not contradicting, this document's Context claim that no production reader yet consumes the new projections. Section 4's mapping/reconciliation work will need to either replace this subscriber's data source or run alongside it during migration; deciding which is a Section 4 planning question, not resolved here.
- `services/vm_job_spec_service.py`'s `compute_capacity_claim_from_order` builds Capacity Reservation claims from `pool_id`/`resource_id` already stored on the buyer's order/negotiation record — it does not re-query `resources` at claim time. Confirms claim construction is decoupled from the local physical tables at the point of use, even though listing *derivation* (above) is not.
- `services/listing_service.py`'s `create_listing` (the operator/API-driven listing path) takes seller-supplied `offer_resource` (including `pool_id`/`resource_id`) directly from the request body and writes only to the generic, domain-neutral `listings` table (`upsert_listing`, defined in `core_storefront`) — it does not read `resources`/`hosts`/`derived_compute_listings` at all. **Correction (2026-08-03, Section 4 design): this is not a second, independent listing-creation path.** `cli_publish.py`'s `_publish_offer` calls this exact same `/listings/create` endpoint (sourcing its arguments from `available_compute_slices` instead of a human), then separately records a `derived_compute_listings` mapping row — one creation mechanism, one automated caller of it plus a bookkeeping step. See "Section 4 design," below, for the corrected picture and why it matters for the mapping-table decision.

**Closing the remaining open items:**
- `resource_transition_events`: an append-only audit log of direct-set mutations applied to a `resources` row (`SQLiteClient.apply_resource_transition`), written only from `admin_controller.py`. Classification: **physical authority** — provenance/audit trail for the same locally-authored resource state `resources` itself holds, not commercial. No other reader found.
- `compute_capacity_pools`/`compute_pool_members`: schema only in `migrations.py`; the only writer is `SQLiteClient._sync_compute_pool_for_resource`, an internal side effect that every `upsert_resource` call triggers automatically to maintain a derived per-pool GPU-count aggregate. **Correction (2026-08-03, Section 5 design): these tables are live-read, not orphaned.** The original inventory pass searched only `domains/vms/storefront/src` and missed `domains/vms/listings/reconciler.py` (a sibling package) — its `available_compute_slices`, the function `cli_publish.py` calls to compute publication candidates, directly `JOIN`s `compute_capacity_pools`/`compute_pool_members` and is the primary live path whenever those tables exist (which `migrations.py` ensures unconditionally, so its `resources`-only fallback branch is effectively dead code in any migrated deployment). Classification stands as **commercial pool concept** (fields are `seller_id`/`pricing_policy_id`/`escrow_policy_id`/`allocation_policy`/`min_price`/`token`/`accepted_escrows` — exactly the storefront commercial capacity-pool object this change's own non-goal warns must not be conflated with a provisioning-side Resource Pool), but **not** a retirement candidate — see "Section 5 design," below, for why this table is exactly where the currently-implicit pooled-vs-specific-resource publication distinction lives today, and what `listing_mode` needs to formalize about it.
- Migration readers: `migrations.py` only creates schema for these tables additively; no migration performs a data backfill by reading `resources`/`hosts`/`derived_compute_listings`. Closed — nothing further to trace here.
- e2e readers: no `e2e-tests` file references these table names directly; e2e coverage exercises them only indirectly through HTTP admin/listing endpoints, which are already covered by the `admin_controller.py` inventory above. Closed.

Task 1.4 is now materially complete. **Update (2026-08-03, Section 5 design):** the one flagged soft spot resolved itself, in the opposite direction from what was expected — `compute_capacity_pools`/`compute_pool_members` are not unread; the original pass simply hadn't searched `domains/vms/listings/` yet. See the corrected classification above and "Section 5 design," below. This is a good illustration of why that soft spot was flagged rather than silently trusted.



## Goals / Non-Goals

**Goals:**
- Surface per-site/family projection load state for operator visibility, without durable persistence (revised 2026-08-03 — see "Section 2 revised decision"; originally scoped as persisting complete generations per trusted site).
- Map provisioning identity into storefront-owned commercial publication without conflating authorities.
- Consume mapped identity for listings and Capacity Reservation claims.
- Add additive, advisory, domain-owned listing and hold hints.
- Remove only local physical-authority state proven superseded.

**Non-Goals:**
- Make projections authoritative for admission or assignment.
- Rebuild existing producer/cache behavior.
- Equate Resource Pools with storefront commercial pools.
- Put domain enum values in `kit/resource-pools` or `kit/site`.

## Decisions

### Persist configured sites and projection families independently — SUPERSEDED

**Superseded 2026-08-03 (see "Section 2 revised decision" below); kept for history, not current design.**

~~Storefront persistence records each operator-trusted `site_id` binding separately from remote payloads. For each `(site_id, projection_kind)`, it stores the accepted revision, digest, fetched/stale metadata, and one complete generation. Replacement is transactional per family; failure retains the previous generation as stale and never writes an empty projection.~~

~~A restart loads durable generations before polling. Revision sequences are authority-local and projection-family-local; comparing revisions across sites or families is invalid.~~

### Section 2 revised decision: no durable projection persistence (2026-08-03)

Discussion (recorded here rather than only in chat, per this repository's discuss-phase convention) found the original persistence layer was solving a restart-time gap — a configured site being unreachable at the exact moment the storefront process (re)starts — that has no current production consumer to protect: Section 1's inventory confirmed nothing in production yet reads `site_projection_cache.py`'s caches (live listing reconciliation still goes through the legacy `CapacityDelta`/`reconciler.py` path). The one concrete operational case identified — the e2e/Helm deployment, where the site (provisioning service) and the storefront boot together in one chart and the storefront may start before its one configured site is reachable — is fully covered by retry-until-success plus observable status, not persisted state, since e2e has exactly one site (global and per-site readiness coincide there) and there is nothing yet depending on serving degraded data across the gap.

**Accepted design:**
- No new tables, no migrations, no `ProjectionCache` seeded-constructor changes. `ProjectionCache`/`site_projection_cache.py` keep their current shape.
- `site_projection_poller_loop` already retries indefinitely on failure (existing code, unchanged) — this alone satisfies "keep trying until the site comes up."
- Surface per-`(site_id, projection_kind)` load state (`ProjectionState`: `not_loaded`/`loaded`/`stale`/`unavailable`/`invalid`) on the storefront's existing operator status surface (`system_service.get_health`/`/api/v1/system/status`), following the same pattern that surface already uses for `resource_count` (`storefront-publication`'s existing "Operator-visible acceptance state" requirement: distinguish diagnosable states, report rather than silently block). A Helm readiness probe or the e2e harness can poll this status and wait, without the storefront itself needing to invent blocking/gating behavior.
- Load-state reporting is **per site**, not global: one site failing to load must not report the whole storefront as broadly degraded when other configured sites (and their listings) are fine. For a single-site deployment (e2e today), per-site and global readiness happen to coincide, which is exactly the case that motivated this discussion.
- Downstream consumers (whichever Section 4 introduces) MUST treat `not_loaded`/`invalid`/`unavailable` as "unknown, do not treat as zero capacity" — the same "ignorance ≠ zero" principle `site-capacity/spec.md` already states normatively for the legacy reconciliation path ("Site authority is unavailable" requirement). This is a requirement on Section 4's design, recorded here so it isn't lost before that section is planned, not new work for Section 2 itself.

**Related finding, not itself Section 2 scope:** POOLS-7's task 2.3 flagged "storefront-side connection-to-site identity, currently held only in process-local aggregation state" as a durability gap to "complete or relocate ... with the durable storefront persistence work in ... POOLS-8." Investigating what that in-memory state actually is: `core_storefront.aggregation.AggregateCapacityClient._reservation_sites` (`capacity_reservation_id → site name`), whose own docstring already states it is "[a] cache, not a ledger: misses (process restart) fall back to asking every site, and the answer is re-learned." This is a different piece of state than the projection cache (this section's original subject), and it already has exactly the same soft-state, retry-on-miss design this section now adopts for projections — it does not need new persistence either, by its own existing design. This suggests POOLS-7 task 2.3's relocation note may already be satisfied as written, not merely deferred; closing it out is a small documentation task (confirm the fallback path is actually exercised/tested, then promote this as the accepted resolution in `site-capacity/spec.md` or `storefront-publication/spec.md`), not new implementation. Recorded here so it isn't lost; not yet added to this change's task list pending confirmation it belongs in this change rather than being closed directly against POOLS-7.

### Keep projection identity separate from commercial inventory

A mapping layer relates projected `(site_id, pool_id, resource_id?)` identity to storefront-owned publication records containing pricing, settlement mechanisms, seller policy, and listing history. Site projection refresh updates physical facts and availability inputs; it does not overwrite commercial policy.

The mapping must define missing, disabled, moved, and conflicting identities. Disappearing physical support closes or suppresses derived listings but does not erase agreement history.

### Route pinned claims directly

Listings derived from one site carry an internal trusted mapping to that site and projected pool/resource identity. Claim construction uses the mapping and routes reservation to the producing authority. It does not broadcast a pinned state-changing request across sites. Public listing payloads expose only intended market identity/labels, not authority credentials or URLs.

### Extend resource projection with pool metadata

The resource-pool projection adds the minimum normalized metadata required by publication: pool label, enabled state, provider/mechanism reference where safe, and opaque `policy_tags`. Any payload change advances that projection's revision/digest. Credentials and provider secrets are never projected.

A separate pool-metadata projection was considered but rejected for the first implementation because publication needs an atomic view of member identity and pool hints. If payload size or update frequency later warrants separation, it requires its own independent identity and cache.

### Keep hints advisory and domain-owned

`kit/resource-pools` defines only stable key names:

- `listing_mode`
- `max_reservation_hold_seconds`

Each domain validates values and applies defaults. VM and bare metal may distinguish pooled versus specific-resource publication; API credits may use quota/key semantics. Unknown or invalid values produce an operator-visible explanation and fall back to the domain's structural default.

A cooperating storefront caps its requested hold TTL to the nonnegative operator preference and its own policy. The site ledger continues enforcing only the actual caller-supplied TTL and does not treat the tag as authority.

### Retire local physical state reader by reader

Before removing any table or field, inventory publication, claim construction, negotiation, pricing, admin, recovery, migration, and e2e readers. Remove `resource_capacity_validator.py` only after its local physical-inventory input has no caller. Preserve commercial metadata and transition/idempotency state even if stored in an existing table.

### Share contracts, not domain semantics

Core storefront may own schema-opaque projection persistence and reconciliation ports. Domain packages own projection-to-listing interpretation and hint enums. Site/resource-pool kits do not import storefront or domain code.

## Risks / Trade-offs

- **[Projection data becomes stale]** → Retain last complete generation in memory with explicit freshness state, surface per-site/family load state on the operator status endpoint, and require live admission for every reservation regardless of cached projection state (2026-08-03: no durable persistence layer — see "Section 2 revised decision"; this risk is bounded by projections never being admission-authoritative, not by restart survival).
- **[Mapping duplicates identity]** → Store references and commercial overlays, not an independently authored physical truth.
- **[Pool metadata leaks secrets]** → Project allowlisted normalized fields only and test payload redaction.
- **[Pinned site is unavailable]** → Report/retry that authority; do not silently reserve elsewhere under the same listing.
- **[Local inventory removal breaks operator workflows]** → Gate each deletion on reader inventory, migration, and focused compatibility evidence.

## Migration Plan

1. Surface per-site/family projection load state on the operator status endpoint without changing current publication (2026-08-03: replaces the originally planned durable configured-site/projection-generation tables — see "Section 2 revised decision"; no schema change in this step).
2. Extend producer payloads additively and load old payloads with absent optional metadata.
3. Backfill commercial mappings from current listings/local inventory where identity is unambiguous; quarantine ambiguous rows.
4. Switch publication and claim construction behind observable comparison/feature controls.
5. Remove proven-superseded physical-authority writers/readers only after parity and restart tests.

Rollback restores the previous publication/claim reader while retaining additive projection tables. Listings created from mappings retain enough provenance to close safely; no migration deletes agreement history.

## Resolved Questions (design review, 2026-08-03)

- **Are Resource Pool IDs globally generated after POOLS-7 identity cleanup, or must every persistent/publication reference remain explicitly site-scoped?** Resolved: `pool_id` is NOT globally unique and was never made so. `kit/resource-pools/src/market_resource_pools/db.py`'s `ResourcePool.id` docstring is explicit that it is an "operator-chosen slug (e.g. 'hetzner-eu-central')... [n]ot a UUID," and that cross-site pool ownership is deliberately left to the storefront rather than encoded in the identifier, because one provisioning-service database is one site and every row in it already implicitly belongs to that site. POOLS-7's early planning text (`pools-7-storefront-fulfillment-cutover/design.md`, "Final planning decisions") proposed globally unique identifiers across the board, but the identifiers that actually shipped as globally unique opaque values are `capacity_reservation_id`, `fulfillment_id`, `provisioned_resource_id`, and `settlement_resource_id` — not `pool_id`, which was deliberately kept as a human-legible, site-local slug. Two different sites may coincidentally reuse the same `pool_id` string with no relationship to each other.

  Consequence for this change: every durable storefront record this change introduces that keys off a projected pool or resource (the commercial mapping table, and any cached reference used for direct claim routing) MUST key on the explicit `(site_id, pool_id)` pair — or `(site_id, pool_id, resource_id)` where a resource-level identity is also involved — never on `pool_id` alone. `storefront-publication`'s existing "Trusted provisioning-site identity" requirement (a storefront binds each provisioning connection to an operator-configured `site_id` and never accepts a counterparty-asserted one) is the trust boundary that makes this safe: the storefront supplies `site_id`, the projection supplies `pool_id`/`resource_id`, and only their pairing is a stable identity.

## Section 2 design discussion (opened 2026-08-03) — CONCLUDED

**Conclusion (2026-08-03): superseded by "Section 2 revised decision" above.** The persistence layer this discussion was designing (questions A–D and the worked seeding example) is not being built — see the revised decision for why. Kept below as the record of alternatives considered, per this repository's discuss-phase convention of recording unresolved alternatives rather than deleting them once a different path is chosen; nothing below should be read as current design.

Grounded against the actual current implementation, not just the prior "Persist configured sites and projection families independently" decision's prose:

- **Current in-memory shape.** `core_storefront.site_projections.ProjectionCache` (generic, `core/storefront/`) is the only cache implementation and is used only by the VM storefront's `market_storefront.services.site_projection_cache` today (bare-metal has no consumer yet — confirmed by grep, so changing `ProjectionCache` itself has a small, known blast radius). It is entirely process-local: `_caches: dict[str, SiteProjectionCaches]` is a module global rebuilt from scratch by `load_site_projections()` on every startup, which immediately does a **blocking live fetch** (`await asyncio.gather(caches.resource_pools.load(), caches.capacity_buckets.load())`) before the storefront can serve from it — there is no seeded/stale-from-disk state today, exactly as this document's Context section already claimed.
- **Where `site_id` actually comes from today.** `market_storefront.services.capacity_client._capacity_settings()` reads `[capacity.sites]` (name → authority URL) from `settings.toml`/dynaconf at call time. This mapping is already durable — it survives restart via the operator's own config file, independent of any storefront database. This matters for schema scope, below.

**Decision A — one table, no separate `configured_sites`.** Accepted (2026-08-03): `site_projection_generations(site_id, projection_kind, revision, digest, value_json, fetched_at)` is the only new table. "Is this site currently trusted" is answered by live `[capacity.sites]` config, never a persisted flag. If site-level metadata is needed later (the discussed example: a per-site public key for authenticating to that site), it gets added as a column on whichever table already carries `site_id` at the time it's actually needed — not pre-built now. Note the one real tradeoff of collapsing to a single table: any such future site-level column would be duplicated across a site's two `projection_kind` rows (`resource_pool` and `capacity_bucket`), since `projection_kind` is part of the key. That duplication is acceptable for slow-changing operator config data (a public key changes rarely, if ever, relative to projection generations), and is deliberately deferred rather than solved speculatively — consistent with not building a table before there's a concrete column to put in it.

**Decision B — stale/error state is not persisted.** Accepted (2026-08-03), and confirmed forward-compatible: this project's own roadmap includes replacing the polling mechanism with a provisioning-service-initiated push in a later change, and keeping `state`/`last_error` as pure runtime fields (not durable schema) means the persistence layer here is written against "the last accepted generation and when it was fetched," a concept push delivery will also produce, not against polling-specific mechanics that a push replacement would otherwise need to unwind from the schema.

**Question C — seeding `ProjectionCache`, worked example.**

To be precise about what is and is not seeded: **site URLs are never persisted or seeded from the database.** Per Decision A, `site_id → authority URL` continues to be resolved fresh from live `[capacity.sites]` config on every process start, exactly as `_capacity_settings()` does today — that part of `load_site_projections()` does not change. What gets seeded is the *projection payload* for a site the storefront already has both a live config entry and a previously-accepted generation for: the list of resource-pool/capacity-bucket rows, plus the revision/digest identity, so the cache isn't empty while waiting for the first live poll to complete.

Today (`core/storefront/src/core_storefront/site_projections.py`):

```python
class ProjectionCache(Generic[T]):
    def __init__(
        self,
        client: ProjectionClient[T],
        *,
        validate: Callable[[T], None] | None = None,
    ) -> None:
        self._client = client
        self._validate = validate or (lambda _: None)
        self._identity: ProjectionIdentity | None = None
        self._value: T | None = None
        self._state = ProjectionState.not_loaded
        self._last_error: str | None = None
        self._refresh_lock = asyncio.Lock()
```

Proposed addition — an optional `seed`, defaulting to today's behavior when omitted:

```python
    def __init__(
        self,
        client: ProjectionClient[T],
        *,
        validate: Callable[[T], None] | None = None,
        seed: tuple[ProjectionIdentity, T] | None = None,
    ) -> None:
        self._client = client
        self._validate = validate or (lambda _: None)
        if seed is not None:
            self._identity, self._value = seed
            # A seeded generation is durable data from a prior process
            # lifetime, not a live confirmation — it must never be
            # presented as `loaded` until this process's own poll/refresh
            # confirms or replaces it.
            self._state = ProjectionState.stale
        else:
            self._identity = None
            self._value = None
            self._state = ProjectionState.not_loaded
        self._last_error: str | None = None
        self._refresh_lock = asyncio.Lock()
```

Today (`domains/vms/storefront/src/market_storefront/services/site_projection_cache.py`), URL/site discovery and cache construction happen together, with an unconditional blocking live fetch before anything is usable:

```python
async def load_site_projections() -> None:
    aggregate = build_capacity_client(lambda: get_sqlite_client())
    remotes = remote_site_clients(aggregate)  # site_id -> RemoteCapacityClient, from live config
    replacements: dict[str, SiteProjectionCaches] = {}
    for site, remote in remotes.items():
        caches = SiteProjectionCaches(
            resource_pools=ProjectionCache(_RemoteProjectionClient(remote, "resource_pool")),
            capacity_buckets=ProjectionCache(_RemoteProjectionClient(remote, "capacity_bucket")),
        )
        await asyncio.gather(caches.resource_pools.load(), caches.capacity_buckets.load())
        ...
```

Proposed — URL/site discovery is unchanged (still `remote_site_clients(aggregate)` off live config); only the `ProjectionCache` construction step changes to read a persisted generation, if any, before the live fetch:

```python
async def load_site_projections() -> None:
    aggregate = build_capacity_client(lambda: get_sqlite_client())
    remotes = remote_site_clients(aggregate)  # unchanged: site_id -> URL, from live config
    repo = get_sqlite_client()  # same DB handle; new repository methods, not a new client
    replacements: dict[str, SiteProjectionCaches] = {}
    for site, remote in remotes.items():
        caches = SiteProjectionCaches(
            resource_pools=ProjectionCache(
                _RemoteProjectionClient(remote, "resource_pool"),
                seed=await repo.load_site_projection_generation(site, "resource_pool"),
            ),
            capacity_buckets=ProjectionCache(
                _RemoteProjectionClient(remote, "capacity_bucket"),
                seed=await repo.load_site_projection_generation(site, "capacity_bucket"),
            ),
        )
        # No longer blocks on a live fetch: a seeded cache is already
        # `stale`-but-usable. The existing poll/refresh cycle (unchanged)
        # confirms or replaces it; task 2.2's persistence hook lives inside
        # `refresh(force=True)`'s existing success path, not here.
        replacements[site] = caches
    _caches.clear()
    _caches.update(replacements)
    asyncio.create_task(_confirm_seeded_generations(replacements))
```

where `repo.load_site_projection_generation(site_id, projection_kind) -> tuple[ProjectionIdentity, list[dict]] | None` returns `None` for a site with no persisted row yet (first-ever startup for that site), which `ProjectionCache.__init__` already treats as "no seed" via the same `seed=None` path used today. The `_confirm_seeded_generations` background kickoff (replacing the old blocking `asyncio.gather(...load())`) is sketched here for shape only — its exact form is Section 2 planning, not resolved in this discussion.

**Question D — raw SQL vs. SQLAlchemy, reviewed.**

This is a real, consistent split by *tier*, not incomplete migration within one package. Evidence against the "older code" theory:
- Zero SQLAlchemy usage anywhere in `core/storefront/src` or `domains/vms/storefront/src` (confirmed by search) — every storefront table, old and recently-added alike (e.g. `compute_capacity_pools`, added well after `kit/resource-pools` existed), uses the same raw-`sqlite3` + hand-rolled `Migration(id, apply)` engine.
- `core_storefront.sqlite_migrations.Migration`/`apply_schema_migrations` is feature-equivalent to `provisioning/compute/service/db/migrations.py`'s `Migration(id, apply)` engine — same shape (id-keyed idempotent migrations, a `schema_migrations` tracking table) — reinforcing that this was built deliberately to the same standard, not left behind.
- `core_storefront/sqlite_client.py`'s own docstring: "Hoisted from `market_storefront.utils.sqlite_client` when the API-credits domain became the second composition root" — an active extraction refactor, not untouched legacy code.

Pros of the storefront tier's raw-SQL convention, for this specific table:
- Zero new dependency in a tier that has none today; sqlite3 is stdlib.
- No sync/async friction: storefront code is `async def` throughout over stdlib `sqlite3`, whereas SQLAlchemy's async support needs an async driver (`aiosqlite`) plus `greenlet`, a second access pattern with no other user in this tier.
- One table, no joins, no relationships to model — the ORM's main value (declarative relationships, query building across mapped classes) isn't needed here.
- Matches every other table already in this file — lower cognitive load for whoever next touches `market_storefront`.

Cons:
- No declarative schema-as-code / weaker type safety than a mapped class.
- SQL literals inline, same as the rest of the file (accepted local style, not a new cost this change introduces).

Why `kit/site`/`kit/resource-pools`/`provisioning/compute/service` use SQLAlchemy, and why that reason doesn't transfer here: multiple independently-versioned *kit packages* (site, resource-pools, fulfillment) are composed into **one shared database** inside the provisioning service via declarative `Base.metadata.create_all` composition (`kit/resource-pools/src/market_resource_pools/db.py`'s own docstring names this pattern explicitly). SQLAlchemy's cross-package declarative composition is what makes that sharing tractable. This table has no such cross-package sharing need — it lives entirely inside the VM storefront's own database, which nothing else composes into.

**Recommendation:** match the storefront tier's existing raw-SQL convention for `site_projection_generations`, specifically because this table's home (VM storefront) has a consistent, actively-maintained convention with no cross-package composition need — not as a general "raw SQL over SQLAlchemy" preference outside that context. If a later table in this same change needs cross-package sharing the way the provisioning tier does, that would be a reason to reopen this, but nothing identified so far in Section 2 or Section 4 requires it.



**Proposed startup sequencing for task 2.3** (pending confirmation of A–C above): `load_site_projections()` changes from "build caches, then immediately live-fetch" to (1) read live `[capacity.sites]` config, (2) for each configured site, read any persisted `(site_id, projection_kind)` generation and construct `ProjectionCache` seeded stale via question C's mechanism (or `not_loaded` if no persisted row exists — first-ever startup for that site), so the storefront can begin serving from a stale-but-non-empty cache immediately without waiting on a network round trip, then (3) kick off the existing poll/refresh cycle, which will confirm-and-promote-to-`loaded` or replace-and-persist as today's `poll_once()`/`refresh()` already do, with one addition: a successful `refresh(force=True)` must now also write the new generation to disk transactionally (task 2.2), not just update the in-memory dataclass fields.



## Section 3 design (opened 2026-08-03)

Grounded against `kit/site/src/market_site/projections.py`, `kit/resource-pools/src/market_resource_pools/{db,pools}.py`, and the Ansible provider config path (`compute_provisioning_service/db/models.py`'s `AnsiblePoolConfig`, `vm_provisioning_adapter/services/ansible_pool_config_handler.py`).

### Mechanism

`resource_pool_projection()` currently groups resources by `pool_id` with zero pool-level fields — only per-resource facts. The accepted "Extend resource projection with pool metadata" decision (already in this document) said *what* to add; this is the *how*:

- `resource_pool_projection(resources, *, pool_metadata: Mapping[str, Mapping[str, Any]] | None = None)` gains an optional parameter: `pool_id -> {label, enabled, mechanism, policy_tags, vm_size_defaults}`, supplied by the mounting service (the provisioning service composes it from its own `ResourcePool`/`AnsiblePoolConfig` tables — `kit/site` never queries them directly, staying duck-typed against a plain dict, consistent with the existing `resource_inventory` callable pattern this function already uses).
- Each pool's projected row gains a `pool_metadata` key holding only the allowlisted fields present in the supplied mapping. A pool absent from `pool_metadata` (older producer, or the mounting service not yet composing a directory) is projected with inventory only — additive and backward-compatible by construction, closing task 3.3 without extra logic.
- `SiteProjectionService` gains an optional `pool_directory: Callable[[], Mapping[str, Mapping[str, Any]]] | None` constructor parameter, called once per `resource_pools()` invocation alongside the existing `resource_inventory` callable — same shape, same lifecycle.
- Any change to the supplied pool metadata changes the projection's canonical digest exactly like a resource change does today (`canonical_digest` already hashes the complete row structure) — task 3.2's revision-advancement requirement falls out of the existing digest mechanism for free, no new logic needed.

### Resolving the open question: provider identity, direct or reduced?

This was an open question in this document before Section 1/2's review. Resolved by inspection: `ResourcePool.provider` (`kit/resource-pools/pools.py`) is already a coarse, non-sensitive *kind* string ("Fulfillment provider kind, e.g. 'ansible'") — not a URL, credential, or anything provider-instance-specific. The actual sensitive material lives in `ResourcePool.provider_config` (a separate column, containing e.g. `playbook_path`/`extra_vars`, potentially carrying operator secrets), which is never read by this projection at all. So there is nothing to reduce: project `provider` directly, under the field name `mechanism` (matching task 3.1's own wording and avoiding the word "provider," which this codebase otherwise uses for the thing that owns `provider_config`/credentials — a naming distinction worth keeping deliberately, not just cosmetically).

### Task 3.5's actual prerequisite: `AnsiblePoolConfig` doesn't persist VM size defaults yet

Confirmed in the Section 1 review pass: `default_vm_ram`/`default_vm_vcpus`/`default_vm_disk_size` exist only on the fulfillment-time pydantic model and are unreachable — the pool admin API rejects any attempt to set them today. Before anything can be projected, this needs:

1. **Schema:** three nullable columns on `ansible_pool_configs` (`default_vm_ram INTEGER`, `default_vm_vcpus INTEGER`, `default_vm_disk_size VARCHAR`), added via an additive `_add_column_if_missing`-style migration matching the existing pattern in `provisioning/compute/service/db/migrations.py` (e.g. `_migrate_ansible_jobs_contract_fields`). NULL on an existing row means "this pool contributes nothing at that fallback tier," identical to today's behavior.
2. **Handler wiring:** `AnsiblePoolConfigHandler._FIELDS` gains the three keys; `validate_config_problems` gains validation (positive integer for RAM/vCPUs, non-empty string for disk size, all three independently optional/nullable); `read_config`/`replace_config` read and write them alongside the existing three fields.
3. Only after (1)–(2) exist is there anything for the provisioning service's pool-directory composer to read and hand to the projection.

This is real schema/admin-API-surface work, not just a projection change — worth calling out explicitly since it's a bigger unit than the rest of Section 3 and touches a live operator-facing contract (pool create/replace/patch would newly accept these fields).

### Resolved: `pool_views`, mirroring the existing `publication_views` precedent (2026-08-03)

Confirmed against `resource_pool_projection`'s own existing code, not a new pattern: at the resource level, `publication_views` is already a generic `dict[str, Any]` that `kit/site` passes through completely uninterpreted (`projected["publication_views"] = dict(resource.get("publication_views") or {})`), while the actual domain-shaped content under a versioned key like `"bare_metal.v1"` is built by `bare_metal_provisioning_adapter.runtime.project_bare_metal_resource` — a function that lives in the bare-metal *domain* package, not in `kit/site` or the generic `compute_provisioning_service`, which only calls out to it. This is exactly the "kit provides a generic delegate shape, the domain layer supplies the coupling" pattern already established elsewhere in this codebase (also visible in `resource-pool-management`'s `requirement_delegate`, resolved through the VM adapter's own allowlisted registry rather than being known to any generic kit).

Applying the same shape at the pool level: `pool_metadata` gains a generic `pool_views: dict[str, Any]` field (name deliberately distinct from `publication_views` — this is provider/negotiation-time sizing data, not buyer-facing listing content, so reusing the same word would be misleading even though the mechanism is identical), and the VM-specific payload goes under a versioned key, e.g. `pool_views["vm.ansible_pool_defaults.v1"] = {"default_vm_ram": ..., "default_vm_vcpus": ..., "default_vm_disk_size": ...}`. The shaping function (analogous to `project_bare_metal_resource`) lives in `vm_provisioning_adapter`'s own runtime module, not in `compute_provisioning_service`'s pool-directory composer directly — the composer only calls out to it, exactly matching how `_bare_metal_publication_view` calls `project_bare_metal_resource` today rather than building the bare-metal shape inline. `kit/site` never sees `default_vm_ram` or any other VM-shaped name; it only ever sees `pool_views: dict[str, Any]`, structurally identical treatment to `policy_tags` and `publication_views`. `mechanism`/`label`/`enabled`/`policy_tags` remain flat, top-level, and genuinely domain-neutral — only the VM-specific sizing data moves into the versioned nested view.

This changes task 3.5's shape from "project `vm_size_defaults`" to "project `pool_views`, with the VM-domain adapter supplying the `vm.ansible_pool_defaults.v1` view content" — same underlying data, correctly layered.

## Section 4 design (opened 2026-08-03)

Grounded against `domains/vms/listings/reconciler.py`, `domains/vms/storefront/src/market_storefront/cli_publish.py`, `domains/vms/storefront/src/market_storefront/services/listing_service.py`, and `core_storefront.aggregation.AggregateCapacityClient`.

### Correction to Section 1's framing: one listing-creation path, not two

Section 1's inventory described `listing_service.create_listing` (operator/API-driven) and the CLI/reconciler-derived flow as two independent listing-creation paths. Tracing `cli_publish.py`'s `_publish_offer` more closely: it calls the storefront's own `/listings/create` HTTP endpoint — the exact same `listing_service.create_listing` code path a human operator's request would hit — then `_record_published_vm_listing` calls `reconciler.record_derived_listing` afterward to record a mapping row. There is one listing-creation mechanism; the CLI path is an automated *caller* of it (sourcing `offer`/`pool_id`/`resource_id` from `available_compute_slices` instead of a human typing them), plus an extra bookkeeping step. Worth correcting explicitly since it changes how much new machinery Section 4 actually needs.

### Resolving open question B: `derived_compute_listings` is already most of the commercial mapping table

`derived_compute_listings`' actual schema (`listing_id, pool_id, resource_id, gpu_count, status, derivation_key, last_reconciled_at`) carries no pricing/settlement/policy fields at all — those already live entirely on the generic `listings` table, addressed by `listing_id`. So this table is not a competing commercial-metadata store; it is already, structurally, exactly the "(pool_id, resource_id?) → storefront-owned record" mapping this document's existing "Keep projection identity separate from commercial inventory" decision calls for — just missing `site_id` and sourced from the wrong place. Resolved: **extend this table, do not build a new one**, matching the same "extend what's already indexed by the right key rather than adding a parallel table" preference from Section 2's decision A. Concretely:

- Add `site_id` to `derived_compute_listings` (and `derived_bare_metal_listings`, for Section 4.5's bare-metal parity — same schema shape, same gap).
- Fix `derivation_key`'s construction (`reconciler.listing_pool_key`/`listing_resource_key`, currently `f(pool_id_or_resource_id, gpu_count)` with no site component) to include `site_id`. **This closes a real, confirmed latent bug, not just a hygiene nicety:** since `pool_id` is only site-locally unique (task 1.3's resolution), two different sites naming a pool the same thing today collide under the same `derivation_key`, and the `ON CONFLICT(derivation_key) DO UPDATE` in `record_derived_listing` would silently let one site's row overwrite the other's mapping.
- Redirect `available_compute_slices`' capacity computation (`reconciler.py`, currently `SELECT ... FROM resources` against the local table) to read from `site_resource_pools`/`site_capacity_buckets` via `site_projection_cache.py` instead. This is the actual substance of tasks 4.3/4.4 — the mapping table's *shape* barely changes, but its *population source* does.
- Reconciliation's close/reopen logic (`stale_open_listing_ids`/`closed_available_listing_ids`, already keyed against caller-supplied `member_availability`) does not need to be rebuilt — only what feeds `member_availability` changes, from `capacity_client.py`'s legacy `CapacityDelta` subscription to something reading the projection caches. Whether that's a full replacement or a parallel path during migration is a task-4.3-level sequencing decision, not resolved here.

### A confirmed correctness gap that motivates "Route pinned claims directly"

This document's existing decision says pinned claim construction "does not broadcast a pinned state-changing request across sites" — investigating whether today's code already violates this, concretely: `AggregateCapacityClient.reserve()` (`core_storefront/aggregation.py`) has no way to target one specific site for a *fresh* reservation. It calls `self._placement(self.site_names, snapshots, claim=claim)` and tries each site returned, in placement order, until one admits — `_route_order`'s owning-site-first behavior only applies to a reservation that already has a learned `capacity_reservation_id`, which doesn't exist yet at `reserve()` time. So a listing whose offer was derived from one specific site's pool `"gpu-pool"` has nothing today stopping the aggregator from also trying a *different* site against the same bare claim `{"pool_id": "gpu-pool", ...}` if placement policy tries that site — and if that other site coincidentally also has a pool named `"gpu-pool"` (a real possibility, since pool_id is only site-locally unique per task 1.3), it would attempt to admit the reservation against the wrong physical pool entirely, silently. This is not hypothetical: it's the direct, confirmed consequence of combining (a) non-globally-unique `pool_id` with (b) today's placement-based fan-out having no concept of a claim being pinned to a specific site.

### Resolved: Option 1, split into private methods (2026-08-03) -- corrected 2026-08-03 (Section 5, Q3)

**Correction:** the original version of this decision conditioned site-pinning on a claim being resource-pinned ("listings with a known pinned origin"). That conflated two different things. Per Section 5's Q3: the storefront commits to a *site* at reservation time; the *provisioning service* commits to a physical resource at scheduling time. Site identity comes from the mapping table (`derived_compute_listings.site_id`) and is known for **every** listing derived from a projection -- fungible or resource-pinned alike -- because every `ResourcePool` lives on exactly one site. Resource-level selection within that site is the site's own concern (its ledger's admission match, or its later `schedule_resource` fulfillment step), never the storefront's. So `site=` must be supplied whenever a mapping entry exists, regardless of `listing_mode`; the fan-out path is only for listings with **no** mapping entry at all (pre-migration or otherwise not derived from a projection).

This also drove a rename: the original sketch called these `_reserve_pinned`/`_reserve_placed`, which collides with Section 5's `listing_mode` also wanting the word "pinned" for its resource-level concept. Renamed to name what's actually being decided at each layer -- **site** selection here, **resource** selection at Section 5's layer -- rather than reusing "pinned" for both and relying on context to disambiguate.

```python
async def reserve(
    self,
    *,
    claim: Mapping[str, Any] | None = None,
    deal_ref: Mapping[str, Any] | None = None,
    ttl_seconds: float | None = None,
    lease_start_utc: str | None = None,
    lease_duration_seconds: int | None = None,
    site: str | None = None,
) -> dict[str, Any] | None:
    """Route to one site in placement order; fall back on refusal.

    ``site``, when supplied, targets exactly that site: no placement
    fan-out, no fallback to another site on refusal. Required whenever
    the claim comes from a listing with a known site mapping -- fungible
    or resource-pinned alike, since pool_id is only site-locally unique
    and falling back to another site on refusal could otherwise admit
    against a same-named pool on the wrong site. Which physical resource
    within that site satisfies the claim is the site's own decision
    (its ledger's admission match at reserve time, or its fulfillment
    provider's placement at schedule time) -- never decided here.
    """
    if site is not None:
        return await self._reserve_at_site(
            site, claim=claim, deal_ref=deal_ref, ttl_seconds=ttl_seconds,
            lease_start_utc=lease_start_utc, lease_duration_seconds=lease_duration_seconds,
        )
    return await self._reserve_by_placement(
        claim=claim, deal_ref=deal_ref, ttl_seconds=ttl_seconds,
        lease_start_utc=lease_start_utc, lease_duration_seconds=lease_duration_seconds,
    )

async def _reserve_at_site(
    self,
    site: str,
    *,
    claim: Mapping[str, Any] | None,
    deal_ref: Mapping[str, Any] | None,
    ttl_seconds: float | None,
    lease_start_utc: str | None,
    lease_duration_seconds: int | None,
) -> dict[str, Any] | None:
    """Reserve at exactly one named site; no fan-out, no fallback on refusal."""
    if site not in self._sites:
        raise ValueError(f"unknown or unconfigured site {site!r}")
    reserved = await self._sites[site].reserve(
        claim=claim, deal_ref=deal_ref, ttl_seconds=ttl_seconds,
        lease_start_utc=lease_start_utc, lease_duration_seconds=lease_duration_seconds,
    )
    if reserved is None:
        return None
    capacity_reservation_id = reserved.get("capacity_reservation_id")
    if capacity_reservation_id:
        self._reservation_sites[str(capacity_reservation_id)] = site
    return _tagged(site, reserved)

async def _reserve_by_placement(
    self,
    *,
    claim: Mapping[str, Any] | None,
    deal_ref: Mapping[str, Any] | None,
    ttl_seconds: float | None,
    lease_start_utc: str | None,
    lease_duration_seconds: int | None,
) -> dict[str, Any] | None:
    """Try each site in placement order; fall back to the next on refusal.

    Only for listings with no site mapping at all. Unchanged from today's
    `reserve()` body.
    """
    snapshots = await self._snapshots()
    for name in self._placement(self.site_names, snapshots, claim=claim):
        try:
            reserved = await self._sites[name].reserve(
                claim=claim, deal_ref=deal_ref, ttl_seconds=ttl_seconds,
                lease_start_utc=lease_start_utc, lease_duration_seconds=lease_duration_seconds,
            )
        except Exception as exc:
            logger.warning(
                "[AGGREGATOR] reserve at site %r failed, trying next: %s", name, exc,
            )
            continue
        if reserved is None:
            continue
        capacity_reservation_id = reserved.get("capacity_reservation_id")
        if capacity_reservation_id:
            self._reservation_sites[str(capacity_reservation_id)] = name
        return _tagged(name, reserved)
    return None
```

**Also resolved while sketching this:** `site_id` must not ride inside `claim`/`required_attributes`, and must not be added to `ComputeResource`/`offer_resource` at all. That model is the public, buyer-negotiated offer; its only free-form extension point (`attributes["tag.*"]`) is explicitly documented as buyer-visible and matched by the negotiation policy, and this document's existing "Route pinned claims directly" decision already requires that "public listing payloads expose only intended market identity/labels, not authority credentials or URLs" -- `site_id` is exactly the kind of internal routing fact that must stay out of the public offer. Instead, the caller (`vm_fulfillment_service._reserve_capacity_for_obligation`) looks `site_id` up from `derived_compute_listings` by `listing_id` (a new small lookup helper, e.g. `lookup_derived_listing_site`) immediately before calling `reserve(..., site=site_id)`; `None` for a listing with no mapping entry falls through to `_reserve_by_placement` exactly as today. `compute_capacity_claim_from_order`/`_REQUIRED_COMPUTE_KEYS` need no change.

### Task 4.6 is largely satisfied by construction, needs a proof not a redesign

"Prove projections never participate in live admission" holds automatically as long as `reserve()` still always calls the real site's live `/capacity/reserve` endpoint for the actual admission decision — the mapping/projection layer only ever decides *which site* to call and *what claim* to send, never substitutes a cached availability check for the live call. Section 4's job here is a test proving no shortcut path exists (e.g. a mis-implemented "resource clearly available per last projection, skip live check" optimization), not new design.

## Section 5 design (opened 2026-08-03)

Grounded against `domains/vms/listings/reconciler.py`'s `available_compute_slices`, `domains/vms/storefront/src/market_storefront/utils/sync_negotiation.py`, and `domains/apicredits`.

### What `listing_mode` actually needs to formalize

`available_compute_slices` already makes a pooled-vs-specific-resource publication decision today — it's just implicit and storefront-local rather than an explicit, projected operator policy. Its live path (`compute_capacity_pools JOIN compute_pool_members`, confirmed live above) groups resources by `pool_id`; a pool with `member_count == 1` gets `single_resource_id` set (effectively "specific resource" mode), one with more members stays fungible/pooled. What decides membership is `attrs.get("pool_id")` on each locally-upserted resource — an artifact of CSV import/`upsert_resource`, not a declared policy from the site authority. `listing_mode` (`ResourcePool.policy_tags`, projected via Section 3's `pool_metadata`) replaces this emergent behavior with an explicit, site-authority-owned decision the VM domain resolves, e.g.:

```python
# domains/vms/listings/ (new, small resolver module)
from typing import Literal

VmListingMode = Literal["pooled", "specific_resource"]
_DEFAULT_VM_LISTING_MODE: VmListingMode = "pooled"  # matches today's structural
                                                      # default when member_count > 1,
                                                      # the overwhelmingly common case

def resolve_vm_listing_mode(policy_tags: Mapping[str, Any]) -> tuple[VmListingMode, str | None]:
    """Return (mode, explanation). explanation is None unless the raw tag
    was present but unrecognized, in which case the structural default is
    used and the explanation is operator-visible (e.g. surfaced on the
    pool's admin status), matching this document's existing
    "Keep hints advisory and domain-owned" decision.
    """
    raw = raw_listing_mode(policy_tags)  # kit/resource-pools.hints
    if raw is None:
        return _DEFAULT_VM_LISTING_MODE, None
    if raw in ("pooled", "specific_resource"):
        return raw, None  # type: ignore[return-value]
    return _DEFAULT_VM_LISTING_MODE, f"unrecognized listing_mode {raw!r}, using {_DEFAULT_VM_LISTING_MODE!r}"
```

Once Section 4's mapping work redirects `available_compute_slices` to read the projection instead of local `compute_pool_members`, this resolver's output replaces the `member_count == 1` heuristic directly.

### Bare metal: structurally trivial, still needs the resolver for symmetry

`derived_bare_metal_listings` (`listing_id, machine_id, physical_host_id, status, derivation_key`) has no pooled concept at all — bare-metal listings are inherently one machine each. A bare-metal `resolve_listing_mode` is a one-line structural default (`"specific_resource"`, always) with the same unrecognized-value-explanation shape as VM's, satisfying task 5.2's symmetry requirement without meaningful new logic. Not worth more design time than this.

### Task 5.3, resolved by investigation: apicredits has nothing to resolve against yet

`domains/apicredits` exists and its provisioning-service side (`keys_service.py`) does use `market_site.ledger.CapacityLedgerService` directly — but confirmed by search, nothing in `domains/apicredits` imports `market_resource_pools` at all. It has no `ResourcePool`/`policy_tags` concept in its model — API credits are keys/quota against the base ledger, not GPU-style pools. So there is no `policy_tags` for an apicredits `listing_mode` resolver to read in the first place; task 5.3's own condition ("only if a concrete publication consumer exists") isn't met, for a more precise reason than "no domain exists" — a domain exists, it just doesn't participate in the resource-pool projection this hint rides on. Confirmed deferral, not an assumption.

### Task 5.4: where the hold-TTL cap actually goes

`sync_negotiation.py`'s acceptance-hold placement reads one global, storefront-operator-configured `hold_ttl_seconds` from settings and applies it uniformly to every hold, regardless of which pool the claim is for:

```python
ttl = float(getattr(getattr(_settings, "capacity", None), "hold_ttl_seconds", 0) or 0)
if ttl <= 0:
    return
...
claim = compute_capacity_claim_from_order(order_dict)
capacity = build_capacity_client(lambda: sqlite_client)
held = await capacity.reserve(
    claim=claim or None,
    deal_ref={"listing_id": listing_id, "negotiation_id": negotiation_id},
    ttl_seconds=ttl,
    lease_start_utc=requested_start_utc,
    lease_duration_seconds=requested_duration_seconds,
)
```

Task 5.4 caps this per-pool: look up the claim's pool's `policy_tags` (via the same `site_id` lookup Section 4 needs for pinned routing) and pass the result through `kit/resource-pools.hints.capped_hold_seconds(ttl, policy_tags)` before calling `reserve()`:

```python
ttl = float(getattr(getattr(_settings, "capacity", None), "hold_ttl_seconds", 0) or 0)
if ttl <= 0:
    return
claim = compute_capacity_claim_from_order(order_dict)
site_id, policy_tags = await lookup_pool_policy_tags(sqlite_client, claim)  # new; None, {} if unresolvable
ttl = capped_hold_seconds(ttl, policy_tags)
...
held = await capacity.reserve(..., ttl_seconds=ttl, ...)
```

This changes nothing about `ttl_seconds`' meaning at the site ledger — it still enforces only whatever value the storefront actually sends, exactly as this document's existing "Keep hints advisory and domain-owned" decision requires ("The site ledger continues enforcing only the actual caller-supplied TTL and does not treat the tag as authority"). Consistent with this function's existing fail-open posture (a hold that can't be placed leaves acceptance untouched), an unresolvable `policy_tags` lookup should leave `ttl` unchanged rather than block hold placement — matching `capped_hold_seconds`' own designed behavior of falling back to the caller's requested value on any invalid/missing preference.



### Open questions (added 2026-08-03, after further review)

The above moved to "resolved" too quickly. Digging further into the same function surfaced real questions:

**Q1 -- resolved: `"fungible"` / `"specific_resource"` (2026-08-03).** "Fungible" is clearly established (`is_fungible_pool`, `pool_id`'s own field docstring). "specific_resource" is confirmed too -- it already appears verbatim in bare-metal's `SQLiteClient.count_open_bare_metal_resources` docstring ("specific-resource publications"), not just something invented for this document. Generalization holds because "resource" is already this codebase's established domain-neutral noun (`resource_id`, `ResourcePool`, `resource_pool_projection`), so "specific_resource" generalizes the same way "resource" already does across GPUs, bare-metal machines, and future domains alike. `listing_mode` values: `"fungible"` / `"specific_resource"`, no further naming question outstanding.

**Q2 -- acknowledged, no question, good investigative result** (kept for the record: `listing_mode` changes claim identity and which key `available_compute_slices` generates per candidate, not just a label).

**Q3 -- resolved: site-pinning and resource-pinning are different layers, and the code needs to say so.** You're right that `_reserve_pinned` was the wrong name and, more importantly, wrongly scoped. Reservations are always site-pinned once a listing has a mapping entry (fungible or resource-specific alike) -- the storefront's only job is picking the site. Resource-level assignment is the provisioning service's job: either the site's own ledger admission match at reserve time, or its fulfillment provider's placement at `schedule_resource` time. Neither is a storefront decision. Fixed in the code block above: renamed to `_reserve_at_site`/`_reserve_by_placement`, and the condition for calling `_reserve_at_site` is now "a site mapping exists for this listing," full stop -- not conditioned on `listing_mode` at all. This also removes the naming collision Q1 was worried about, since Section 4 no longer uses the word "pinned" anywhere.

**Q4 -- investigated properly this time; bare metal's situation is not what task 4.5/5.4 assumed.** Two findings that cut in opposite directions:

- **Publication is already ahead of VM, not behind.** `arkhai_bare_metal.projections.TrustedBareMetalProjection` (`domains/bare_metal/src/arkhai_bare_metal/projections.py`) is a per-site, revision/digest-identified, complete/stale-tracked projection-generation model -- structurally almost exactly what Section 2 discussed and rejected building for VM, already modeled here as a pydantic contract. `arkhai_bare_metal.storefront_adapter.available_bare_metal_listing_candidates` already derives listing candidates purely from `TrustedBareMetalProjection` snapshots (`bare_metal_listing_candidates`, `close_stale_bare_metal_listings`, `record_derived_bare_metal_listing`) -- there is no local-physical-authority-table equivalent to VM's `resources`/`compute_capacity_pools` in bare-metal's publication path at all. `derived_bare_metal_listings` already has a `site_id` column (confirmed via migration), ahead of VM's `derived_compute_listings`. If anything, Section 4's VM mapping work should look to this design rather than the reverse.
- **But none of it is wired to anything real, and capacity reservation doesn't exist at all.** `projection_snapshot` (the callback `TrustedBareMetalProjection` snapshots come from) is passed through `publication.py` but never actually constructed anywhere in the bare-metal storefront's composition root -- confirmed by search, nothing builds a real implementation. `runtime.py`'s health check hardcodes `"site_projection": "unavailable"` and `"fulfillment": "unavailable"` unconditionally; its own docstring says "trusted site bindings are composed later" (never happened yet). And there is no capacity-reservation client at all for bare metal anywhere in the repo -- no `AggregateCapacityClient` usage, no `reserve()` call, no hold/TTL placement, confirmed by search across the whole `domains/bare_metal` tree.

So the honest answer to "is this transferable": the pattern 5.4 needs (cap an existing hold TTL) has nothing to attach to on bare metal, because the thing it would cap -- a working capacity-reservation flow -- doesn't exist there yet. Porting 5.4 specifically isn't "port a pattern," it's "build bare-metal capacity reservation from scratch" (site client wiring, reserve/hold/commit flow, negotiation-time integration mirroring `sync_negotiation.py`), which is a materially larger undertaking than this task, and out of proportion with the rest of Section 5. That's a real project on its own, not a small pickup. **Resolution (2026-08-03): not a new gap.** `openspec/changes/market-platform-bare-metal-10-storefront-composition` already owns exactly this -- its Sections 3 ("Trusted multi-site composition": site bindings, aggregate capacity/projection wiring, reserve, retain generations, persist selected site) and 4 ("POOLS-7 fulfillment integration": schedule/status/result/teardown) are precisely this work, unstarted, stalled at exactly this point since 2026-07-22 while its own Sections 1-2 (packaging, negotiation/settlement/publication contract) are complete. That change was updated rather than duplicated: it now names POOLS-8's `AggregateCapacityClient.reserve(site=...)` (Section 4) as a direct dependency of its own Section 3.2, and its stale claim that the aggregator "is not durable selected-site fulfillment routing" was corrected. A bare-metal hold-TTL cap belongs there, once its Section 3-4 land -- not as new POOLS-8 scope.

None of these are resolved -- recorded here for input before task 5.1/5.2's code sketches above get treated as final.

## Section 6 design (opened 2026-08-03)

Grounded against the full schemas of `resources` and `compute_capacity_pools` (not just the columns seen in earlier passes), `resource_transition_events`, `compute_pool_members`, and the one-time `_backfill_compute_pools` migration that originally populated `compute_capacity_pools` from `resources`.

### Retirement is column-level, not table-level, for the two hybrid tables

Every table in Section 1's inventory turns out to fit one of three buckets once read in full -- and two of them are internally split, which task 6.1's "physical-identity writers/readers" framing doesn't yet say out loud:

| Table | Physical columns (retirement candidate once projection-sourced) | Commercial columns (must survive) |
|---|---|---|
| `resources` | `resource_type`, `resource_subtype`, `unit`, `value`, `state`, `attributes` | `min_price`, `token`, `max_duration_seconds`, `accepted_escrows` -- **confirmed present on this table too**, not just `compute_capacity_pools` |
| `hosts` | all (pure physical validator input) | none |
| `compute_pool_members` | all (pure physical membership) | none |
| `compute_capacity_pools` | `total_gpu_count`, `gpu_model`, `region`, `sla` | `seller_id`, `pricing_policy_id`, `escrow_policy_id`, `allocation_policy`, `min_price`, `token`, `accepted_escrows`, `max_duration_seconds` |
| `resource_transition_events` | all (audit trail of `resources`' physical-column mutations) | n/a -- existing rows are history, not a live concern |

So `resources` and `compute_capacity_pools` are each a genuine hybrid, at the column level -- not a table cleanly on one side or the other. This means task 6.1 cannot "remove" either table; it can only stop writing/reading their physical columns once the projection supersedes them, while their commercial columns become a durable pricing-policy record that survives.

**A pre-existing duplication task 6.1 should not paper over:** per-resource pricing already exists in three places today -- `resources.min_price`/`token`/`accepted_escrows`/`max_duration_seconds` (per-resource), `compute_capacity_pools`'s equivalent columns (per-pool, populated by the one-time `_backfill_compute_pools` migration that originally promoted `resources`' values up to pool level), and whatever a published `listings` row snapshots at creation time (per-listing). This duplication predates POOLS-8 and isn't something this change needs to fully resolve, but Section 6 should not silently pick one without checking whether per-resource price overrides distinct from pool-level pricing are actually exercised anywhere before deciding whether `resources`' commercial columns can simply be dropped in favor of the pool-level copy, or need their own preserved home.

### The retiring cluster and what's still open

`hosts`, `compute_pool_members`, `resources`' physical columns, `resource_transition_events`, `resource_capacity_validator.py`, and the CSV-import/`upsert_resource` physical-write path all retire together, once Section 4's redirect of `available_compute_slices` to the projection+mapping table lands -- they form one connected cluster (validator checks `hosts`; `upsert_resource` writes `resources` and, via `_sync_compute_pool_for_resource`, `compute_capacity_pools`/`compute_pool_members`; CSV import calls `upsert_resource`), not independent removals.

**Resolved (2026-08-03):** CSV import (`host_csv_importer.py`/`resource_csv_importer.py`) is not useful once the rest of the storefront is refactored to consume the projection — remove rather than repurpose. `upsert_resource`'s admin API and its `_sync_compute_pool_for_resource` side effect retire alongside it. This does not change `compute_capacity_pools`' surviving commercial columns (task 6.2) — operators still need *some* way to set pool-level pricing policy, just not through the CSV/resource-registration path; how that's edited going forward (direct admin endpoint against the narrowed `compute_capacity_pools`, presumably) is ordinary task 6.1 implementation detail, not a design question.

### Staged rollout means freeze-then-redirect, not drop, in this change

Task 6.3 asks for "a rollback path to the previous reader during staged rollout" -- that's only possible if the previous reader's data still exists. Recommend this change's actual migration work stops at freezing writes to the retiring physical columns/tables and redirecting reads to the projection, without dropping the underlying schema in the same migration. A genuine `DROP`/column removal belongs in a follow-up cleanup change after a full deployment cycle confirms rollback is never needed -- matching this document's non-destructive posture everywhere else (no migration in this change deletes agreement history; every other schema change so far has been additive).

## Design promotion record

Renamed to match `openspec/README.md`'s "Design promotion record" template exactly (was "Permanent Documentation Promotion" through Section 6 of this document's own drafting -- corrected here in Section 7 rather than silently, per this document's own amend-don't-replace convention). Rebuilt as a full audit against every accepted decision above, not just the four rows carried forward from earlier sections; several material decisions from Sections 3, 4, and 6 had never been added.

| Accepted decision | Permanent location |
|---|---|
| `pool_id` is a site-local operator slug, never globally unique; every durable/public reference keys on `(site_id, pool_id[, resource_id])` | `openspec/specs/resource-pool-management/spec.md#pool-identity` |
| Per-site/family projection load-state visibility, no durable persistence; "ignorance ≠ zero" applies to projection consumers | `openspec/specs/site-capacity/spec.md#projection-load-state` |
| Resource-pool projection gains allowlisted `label`/`enabled`/`mechanism`/`policy_tags`/`pool_views` metadata; `pool_views` is a generic, versioned delegate shape (mirrors `publication_views`) that `kit/site` never interprets | `openspec/specs/site-capacity/spec.md#resource-pool-projection` |
| `derived_compute_listings`/`derived_bare_metal_listings` are the commercial-mapping table (extended with `site_id`), not a new schema; pricing/settlement/policy already live on `listings` via `listing_id` | `openspec/specs/storefront-publication/spec.md#commercial-mapping` |
| `AggregateCapacityClient.reserve(site=...)` dispatches to `_reserve_at_site`/`_reserve_by_placement`; site-pinning applies to every listing with a known site mapping regardless of `listing_mode`, never only resource-pinned ones | `openspec/specs/storefront-publication/spec.md#claim-routing` |
| Domain-neutral hint keys (`listing_mode`, `max_reservation_hold_seconds`) live in `kit/resource-pools`; domains own accepted values/defaults | `openspec/specs/resource-pool-management/spec.md#listing-and-hold-hints` |
| `listing_mode` values are `"fungible"`/`"specific_resource"`; formalizes the pooled-vs-specific-resource decision `available_compute_slices` already made implicitly from local table membership | `openspec/specs/resource-pool-management/spec.md#listing-mode` and `openspec/specs/storefront-publication/spec.md#publication-candidates` |
| `compute_capacity_pools`/`compute_pool_members` are live-read (not orphaned) by `domains/vms/listings/reconciler.available_compute_slices` | `openspec/specs/storefront-publication/spec.md#local-physical-authority` |
| Local physical-authority retirement is column-level for `resources`/`compute_capacity_pools` (both hybrid physical+commercial), table-level for `hosts`/`compute_pool_members`; freeze-then-redirect in this change, `DROP` deferred to a follow-up cleanup change | `openspec/specs/storefront-publication/spec.md#local-physical-authority` |
| CSV import (`host_csv_importer.py`/`resource_csv_importer.py`) and `upsert_resource` are removed, not repurposed, once the projection is the physical-registration source | `openspec/specs/storefront-publication/spec.md#local-physical-authority` |

`market-platform-bare-metal-10-storefront-composition`'s dependency on this change's `reserve(site=...)` mechanism was recorded directly in that change's own `design.md`/`tasks.md` (2026-08-03) rather than as a row here -- it's that change's promotion record to carry, not this one's.
