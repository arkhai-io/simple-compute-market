## Context

The site authority now publishes two independent projections: `site_resource_pools` for host/resource facts and `site_capacity_buckets` for grouped advisory capacity. Each has revision/digest identity. VM storefront startup loads and polls both into atomic in-memory caches with stale retention. No production publication or claim-building reader consumes those caches, accepted identities are not durable across restart, and pool labels/provider/enabled/policy tags are absent from the resource projection.

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
- Persist complete independently versioned projection generations per trusted site.
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

### Persist configured sites and projection families independently

Storefront persistence records each operator-trusted `site_id` binding separately from remote payloads. For each `(site_id, projection_kind)`, it stores the accepted revision, digest, fetched/stale metadata, and one complete generation. Replacement is transactional per family; failure retains the previous generation as stale and never writes an empty projection.

A restart loads durable generations before polling. Revision sequences are authority-local and projection-family-local; comparing revisions across sites or families is invalid.

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

- **[Projection data becomes stale]** → Retain last complete generation with explicit freshness and require live admission for every reservation.
- **[Mapping duplicates identity]** → Store references and commercial overlays, not an independently authored physical truth.
- **[Pool metadata leaks secrets]** → Project allowlisted normalized fields only and test payload redaction.
- **[Pinned site is unavailable]** → Report/retry that authority; do not silently reserve elsewhere under the same listing.
- **[Local inventory removal breaks operator workflows]** → Gate each deletion on reader inventory, migration, and focused compatibility evidence.

## Migration Plan

1. Add durable configured-site and projection-generation tables without changing current publication.
2. Extend producer payloads additively and load old payloads with absent optional metadata.
3. Backfill commercial mappings from current listings/local inventory where identity is unambiguous; quarantine ambiguous rows.
4. Switch publication and claim construction behind observable comparison/feature controls.
5. Remove proven-superseded physical-authority writers/readers only after parity and restart tests.

Rollback restores the previous publication/claim reader while retaining additive projection tables. Listings created from mappings retain enough provenance to close safely; no migration deletes agreement history.

## Resolved Questions (design review, 2026-08-03)

- **Are Resource Pool IDs globally generated after POOLS-7 identity cleanup, or must every persistent/publication reference remain explicitly site-scoped?** Resolved: `pool_id` is NOT globally unique and was never made so. `kit/resource-pools/src/market_resource_pools/db.py`'s `ResourcePool.id` docstring is explicit that it is an "operator-chosen slug (e.g. 'hetzner-eu-central')... [n]ot a UUID," and that cross-site pool ownership is deliberately left to the storefront rather than encoded in the identifier, because one provisioning-service database is one site and every row in it already implicitly belongs to that site. POOLS-7's early planning text (`pools-7-storefront-fulfillment-cutover/design.md`, "Final planning decisions") proposed globally unique identifiers across the board, but the identifiers that actually shipped as globally unique opaque values are `capacity_reservation_id`, `fulfillment_id`, `provisioned_resource_id`, and `settlement_resource_id` — not `pool_id`, which was deliberately kept as a human-legible, site-local slug. Two different sites may coincidentally reuse the same `pool_id` string with no relationship to each other.

  Consequence for this change: every durable storefront record this change introduces that keys off a projected pool or resource (accepted projection generations, the commercial mapping table, and any cached reference used for direct claim routing) MUST key on the explicit `(site_id, pool_id)` pair — or `(site_id, pool_id, resource_id)` where a resource-level identity is also involved — never on `pool_id` alone. This matches the "Persist configured sites and projection families independently" decision's existing `(site_id, projection_kind)` scoping and extends the same rule to identities *inside* a projection generation's payload, not only to the generation record itself. `storefront-publication`'s existing "Trusted provisioning-site identity" requirement (a storefront binds each provisioning connection to an operator-configured `site_id` and never accepts a counterparty-asserted one) is the trust boundary that makes this safe: the storefront supplies `site_id`, the projection supplies `pool_id`/`resource_id`, and only their pairing is a stable identity.

## Section 2 design discussion (opened 2026-08-03)

Grounded against the actual current implementation, not just the prior "Persist configured sites and projection families independently" decision's prose:

- **Current in-memory shape.** `core_storefront.site_projections.ProjectionCache` (generic, `core/storefront/`) is the only cache implementation and is used only by the VM storefront's `market_storefront.services.site_projection_cache` today (bare-metal has no consumer yet — confirmed by grep, so changing `ProjectionCache` itself has a small, known blast radius). It is entirely process-local: `_caches: dict[str, SiteProjectionCaches]` is a module global rebuilt from scratch by `load_site_projections()` on every startup, which immediately does a **blocking live fetch** (`await asyncio.gather(caches.resource_pools.load(), caches.capacity_buckets.load())`) before the storefront can serve from it — there is no seeded/stale-from-disk state today, exactly as this document's Context section already claimed.
- **Where `site_id` actually comes from today.** `market_storefront.services.capacity_client._capacity_settings()` reads `[capacity.sites]` (name → authority URL) from `settings.toml`/dynaconf at call time. This mapping is already durable — it survives restart via the operator's own config file, independent of any storefront database. This matters for schema scope, below.

**Open question A — does this change need a separate `configured_sites` table, or does the generation table alone suffice?**

The existing decision text says the storefront "records each operator-trusted `site_id` binding separately from remote payloads." Two readings, with different schema cost:

1. **Narrow reading:** this is describing a *trust* property (`site_id` is the storefront's own locally-configured identifier, never accepted from a remote's self-report — already true today via `[capacity.sites]`, and already normatively required by `storefront-publication`'s "Trusted provisioning-site identity"), not a mandate for a second table. Under this reading, one table — `site_projection_generations(site_id, projection_kind, revision, digest, value_json, fetched_at)`, primary key `(site_id, projection_kind)` — is sufficient. "Currently configured" is answered by checking live `[capacity.sites]`, not a persisted flag, at the point the storefront decides which generations to seed caches from at startup.
2. **Literal reading:** a standalone `configured_sites(site_id, first_seen_at, ...)` table, updated separately from generation replacement, so a site's binding record and its projection data have independent lifecycles (e.g. so a site removed from live config but still holding open agreements has *something* durably distinguishing "known site, currently unreachable/removed" from "never seen").

  My recommendation is **(1)**: config already gives us a durable, unambiguous answer to "is this site currently trusted," re-derived fresh every startup — a second table would either duplicate that (drift risk) or would need its own reconciliation logic against config that doesn't otherwise exist anywhere in this codebase's patterns (`resource_pools`, `hosts`, etc. are all reconciled from a single authoritative source, not synced against a second local mirror of the same fact). If a future need surfaces for durable state that outlives a site's removal from config (e.g. an audit trail), that's better served by *not deleting* generation rows for orphaned `site_id`s than by adding a second table now. This also directly resolves task 2.1's "storefront migrations and repositories for trusted configured-site bindings" down to one migration, one repository, matching the one-table shape.

**Open question B — is "stale/error state" itself persisted, or re-derived at each restart?**

`ProjectionCacheView` already carries `state`/`last_error` as runtime fields. Persisting them durably would mean every failed poll writes to disk, which is unnecessary churn and drifts from the actual meaning: "stale" is entirely a function of *not yet having reconfirmed this generation this process lifetime*, not a fact about the generation itself. Recommendation: persist only `revision`, `digest`, `value_json`, and `fetched_at` (task 2.2's "accepted value" and "fetched time"); `state` and `last_error` remain process-local, computed as: every generation loaded from disk at startup starts life as `ProjectionState.stale` (matching task 2.3's "restore ... as stale until polling confirms or replaces it" in this document's Migration Plan) until the first successful `poll_once()`/`refresh()` promotes it to `loaded`, exactly mirroring today's in-memory-only failure handling — just seeded from disk instead of `None` at construction.

**Open question C — how does `ProjectionCache` learn to start from a seed instead of `not_loaded`?**

Today `ProjectionCache.__init__` always starts `_identity=None, _value=None, _state=not_loaded`. Persistence needs a seeded-construction path: either (a) a new optional `seed: ProjectionCacheView[T] | None` constructor parameter that, when given, initializes `_identity`/`_value` from it and forces `_state = ProjectionState.stale` regardless of the seed's own recorded state, or (b) a `ProjectionCache.from_stored(...)` classmethod doing the same. (a) is a smaller, more consistent diff with the existing dataclass-heavy style in this module. This is a `core_storefront` change, not VM-storefront-local, but has exactly one current caller to update.

**Open question D — SQLite storage convention.** The VM storefront's existing persistence (`resources`, `hosts`, `compute_capacity_pools`, etc.) is all raw SQL via `market_storefront.utils.sqlite_client.SQLiteClient` + `.utils.migrations.py`, not SQLAlchemy — this is a different package from `kit/site`/`kit/resource-pools`, which do use SQLAlchemy. Recommendation: match the local convention (raw SQL, `sqlite_client.py`/`migrations.py`) rather than introducing a second ORM into this specific package, consistent with how every other storefront-local table in this inventory is built.

**Proposed startup sequencing for task 2.3** (pending confirmation of A–C above): `load_site_projections()` changes from "build caches, then immediately live-fetch" to (1) read live `[capacity.sites]` config, (2) for each configured site, read any persisted `(site_id, projection_kind)` generation and construct `ProjectionCache` seeded stale via question C's mechanism (or `not_loaded` if no persisted row exists — first-ever startup for that site), so the storefront can begin serving from a stale-but-non-empty cache immediately without waiting on a network round trip, then (3) kick off the existing poll/refresh cycle, which will confirm-and-promote-to-`loaded` or replace-and-persist as today's `poll_once()`/`refresh()` already do, with one addition: a successful `refresh(force=True)` must now also write the new generation to disk transactionally (task 2.2), not just update the in-memory dataclass fields.



## Permanent Documentation Promotion

| Decision | Permanent destination |
|---|---|
| Independent durable projection generations and stale behavior | `openspec/specs/site-capacity/spec.md` and `architecture.md` |
| Commercial mapping, direct claim routing, and retirement boundary | `openspec/specs/storefront-publication/spec.md` and `architecture.md` |
| Domain-neutral hint keys and domain-owned values | `openspec/specs/resource-pool-management/spec.md` and `architecture.md` |
