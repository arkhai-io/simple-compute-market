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
| `compute_capacity_pools` | `migrations.py` | Commercial pool concept, auto-derived side effect of `upsert_resource`; **no confirmed external reader** |
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
- `services/listing_service.py`'s `create_listing` (the operator/API-driven listing path) takes seller-supplied `offer_resource` (including `pool_id`/`resource_id`) directly from the request body and writes only to the generic, domain-neutral `listings` table (`upsert_listing`, defined in `core_storefront`) — it does not read `resources`/`hosts`/`derived_compute_listings` at all. This is a second, independent listing-creation path alongside the CLI/reconciler-driven derived-listing path above; the two converge only in that both ultimately write rows the shared `listings` table's publication/close/reopen logic treats uniformly.

**Closing the remaining open items:**
- `resource_transition_events`: an append-only audit log of direct-set mutations applied to a `resources` row (`SQLiteClient.apply_resource_transition`), written only from `admin_controller.py`. Classification: **physical authority** — provenance/audit trail for the same locally-authored resource state `resources` itself holds, not commercial. No other reader found.
- `compute_capacity_pools`/`compute_pool_members`: schema only in `migrations.py`; the only writer is `SQLiteClient._sync_compute_pool_for_resource`, an internal side effect that every `upsert_resource` call triggers automatically to maintain a derived per-pool GPU-count aggregate. No production code outside `sqlite_client.py` itself reads either table — no admin, listing, reconciler, or publication call site was found. Classification: **commercial pool concept** (fields are `seller_id`/`pricing_policy_id`/`escrow_policy_id`/`allocation_policy`/`min_price`/`token`/`accepted_escrows` — exactly the storefront commercial capacity-pool object this change's own non-goal warns must not be conflated with a provisioning-side Resource Pool), but with **no confirmed current consumer** — a candidate for early, low-risk retirement, or at minimum for double-checking against every admin API response shape before Section 6 touches it, since an unread write path is easy to miss as "load-bearing" if a response serializer happens to include it without a code path this grep could find.
- Migration readers: `migrations.py` only creates schema for these tables additively; no migration performs a data backfill by reading `resources`/`hosts`/`derived_compute_listings`. Closed — nothing further to trace here.
- e2e readers: no `e2e-tests` file references these table names directly; e2e coverage exercises them only indirectly through HTTP admin/listing endpoints, which are already covered by the `admin_controller.py` inventory above. Closed.

Task 1.4 is now materially complete. The one remaining soft spot is confirming `compute_capacity_pools`/`compute_pool_members` truly have zero external readers (this pass found none, but did not exhaustively check every admin response schema for an included-but-unqueried field) before treating that as settled enough to plan removal against.



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



| Decision | Permanent destination |
|---|---|
| Per-site/family projection load-state visibility (no durable persistence); "ignorance ≠ zero" applies to projection consumers | `openspec/specs/site-capacity/spec.md` and `architecture.md` |
| Commercial mapping, direct claim routing, and retirement boundary | `openspec/specs/storefront-publication/spec.md` and `architecture.md` |
| Domain-neutral hint keys and domain-owned values | `openspec/specs/resource-pool-management/spec.md` and `architecture.md` |
