# Tasks — unbacked listing publication

> **Planned 2026-09-23.** `design.md` — including "Decisions added in the planning
> review" — and the delta specs govern. No task was complete when this plan was
> written; the plan history at the end records how the pre-revision tasks map onto
> this one.

The blocking prerequisites — `settle-listing-vocabulary`,
`project-capacity-resources-without-hosts`, and
`pool-declared-advertisement-and-backing` — have landed. Two further dependencies do
not block implementation:

- **System evidence gate.** Tasks 6.7 and 6.8, and the end-to-end part of closeout
  (7.9), wait on `compose-contact-exchange-across-compute` Sections 1–3 and 3b, which
  wait on `contact-payload-retention`. Until the VM storefront composes contact
  exchange, an unbacked VM candidate has no settlement option and yields no listing.
- **Completion dependency.** Closeout cannot finish before
  `pools-9-retire-local-physical-authority`, whose origination statement this change's
  promoted architecture text sits beside.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`; a hand-built HTTP payload
does not satisfy the no-raw-calls rule. Suites are run with the owning project's
Makefile target: `make test-core`, `make test-kits`, `make test-storefront`,
`make test-vms-domain`, `make test-bare-metal`, `make test-apicredits`,
`make test-registry`, and `make test-compute-provisioning`.


## Implementation record

Implemented and reviewed. The review's findings and the agreed resolutions are in
`design.md`, "Decisions from the code review"; Section 8 implements them and reopens
the tasks whose claims the review showed false or overclaimed. Promotion (7.7) and the
rest of closeout land on this branch after Section 8, before merge.

Landed since the review, each in its own commit: the VM listings, negotiation, and
settlement wheels (`design.md`, "Packaging decided alongside the review"); and fixes
from the first two end-to-end runs — the pause wakes an idle loop, the guard compares
only fields its source resolves, and the second e2e seller derives from local tables
(`design.md`, "Findings during implementation").

Open before completion:

- **6.9** — provisioning emitting both declarations, parsed by the canonical site
  client and consumed by the storefront, as one integration test.
- **6.17** — the loop is held by the lifecycle pause, a pause reaches an idle loop at
  once, a projection change wakes an idle loop, its dry run is repeatable, and its
  routes run the timer's cycle (unit tests). Still missing, as 8.14: the same through
  the typed client against the real app, and sync/async parity for the loop name.
- **6.18** — refresh, divergence, undisclosed backing, and the site-reset refusal
  are covered against storefront state. The registry side of an in-place refresh
  is covered only by the kit's publish and reopen tests.
- **6.19** — the source check is covered for the pinned site, another pool or
  site, a fungible member, an unbacked listing with no site call, and an unloaded
  projection; negotiation covers both refusal reasons. Round zero of
  `evaluate-negotiate` is not yet exercised separately.
- **6.7, 6.8** — gated on `compose-contact-exchange-across-compute` Sections 1–3
  and 3b.
- **6.25** — `make test` passes in a full environment, and the latest end-to-end
  run passes. In the build container, where they run against committed lockfiles
  because the torch index is unreachable, the only failures are two that are not this
  change's: `domains/vms/storefront` integration `test_alkahest.py` needs a local
  chain, and `e2e-tests` unit `test_hosted_public_boundary.py` asserts compose
  content. `make check-reinit` passes.
- **7.3–7.9** — documentation compliance, compression, roadmap and index currency,
  promotion, citations, and the end-to-end pipeline. Two things found now bear on
  them. `openspec/specs/registry-discovery/spec.md` places two requirements after
  its `## Evidence` section, so OpenSpec cannot archive this change's
  registry-discovery delta until they move inside `## Requirements`. The citation
  check reports 17 unresolvable citations, all present at the planning checkpoint
  and none in a file this change touches.

## 0. Settled preconditions

- [x] 0.1 Confirm `build_storefront_derivation_key` is reused unchanged, with the
      VM source envelope carrying the same fields it carries today and backing
      absent from it. Backing is fixed at pool creation, so a supply move is a move
      between pools and the key differs by `pool_id`; pool-level backing immutability
      (`capacity_backing_immutable`) has landed.
- [x] 0.2 Confirm the binding trace still matches the code: every consumer takes
      either `PublicationBinding` or `CapacityBinding`, and none needs both. One that
      does is a signal the separation is wrong, not a site to cast past.

## 1. Durable schema

All in `core/storefront/src/core_storefront/`, as new entries in `_MIGRATIONS`
(`sqlite_migrations.py`); the binding-schema migration that created the immutability
trigger stays frozen.

- [x] 1.1 **Expand migration.** Add `storefront_listing_bindings.capacity_backing
      TEXT CHECK (capacity_backing IN ('backed', 'unbacked'))`, nullable with no
      default; backfill every existing row as `backed`; then drop and recreate
      `storefront_listing_bindings_immutable` with `capacity_backing` in its
      `UPDATE OF` list and `WHEN` clause. The backfill precedes the recreation.
- [x] 1.2 Leave `site_id` `NOT NULL` and populated for every listing. It is the
      listing's origin site. Do not tie the discriminator to `site_id`
      nullability: the `negotiation_domain_binding_complete_insert` trigger is
      all-or-nothing across the six domain-binding columns.
- [x] 1.3 **Contract migration**, a separate migration ID: a `BEFORE INSERT` trigger
      refusing a binding whose `capacity_backing` is `NULL`.
- [x] 1.4 Confirm a database written by the previous version migrates and loads, and
      that rerunning both migrations is idempotent.
- [x] 1.5 **Closure-reason migration**, a third migration ID: add
      `listings.closed_by TEXT CHECK (closed_by IN ('seller', 'reconciliation'))`;
      enumerate every `listings.status` value in use first; backfill every existing
      closed row as `reconciliation`; install triggers requiring `closed_by` exactly
      when the status is closed. The backfill reproduces the previous behaviour, under
      which any closed listing was reopenable.
- [x] 1.6 `domain_registry.py`: `StorefrontListingBinding` gains a required
      `capacity_backing` with no default, carried by `from_source_envelope` and
      `as_record`, validated against the two values.
- [x] 1.7 Name `capacity_backing` in every binding writer:
      - both inserts in `sqlite_client.py`, and add it to each post-insert equality
        check so a second bind with the opposite backing is refused rather than
        absorbed by `ON CONFLICT … DO UPDATE SET last_reconciled_at`;
      - `domains/vms/storefront/src/market_storefront/domain_migration.py`'s
        `INSERT OR IGNORE` (`RAISE(ABORT)` is not suppressed by `OR IGNORE`);
      - `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/sqlite_client.py`
        and `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/migrations.py`'s
        `INSERT OR IGNORE`, ordering the bare-metal legacy
        migration after the core expand migration;
      - the raw fixtures in `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py`
        and `domains/vms/storefront/tests/unit/test_reconciler.py`.
- [x] 1.8 *(reopened by review: `load_listing` did not return it; true since 8.5)* `sqlite_client.py`: `update_listing` takes `closed_by` for a close and
      clears it on reopen; `load_listing` returns it.

## 2. Binding types and negotiation

- [x] 2.1 `kit/capacity-publication/src/market_capacity_publication/capacity.py`:
      introduce `_ListingIdentity` with the existing non-empty validation,
      `CapacityBinding` and `UnbackedBinding` as sibling subclasses each carrying a
      `ClassVar` `capacity_backing`, `PublicationBinding` as their union, and one
      loader keyed by the durable value that raises on anything else. Export them
      from `__init__.py`. No `admission` field.
- [x] 2.2 `kit/capacity-publication/src/market_capacity_publication/publication.py`: `PublicationCandidate.binding`, `BoundListing.binding`,
      and the `PublicationDomainHooks.binding_for_listing` return widen to
      `PublicationBinding`; `_require_persisted_binding` is unchanged in body, since
      dataclass equality compares classes.
- [x] 2.3 Keep the runtime's durable comparison identical across both variants. If a
      branch proves necessary, record why.
- [x] 2.4 `PublicationRuntime.close` takes the closure reason as a required argument;
      reconciliation-plan closes pass `reconciliation`.
- [x] 2.5 `CapacityRuntime` reserve, commit, release, and truncate keep typing against
      `CapacityBinding` and refuse anything else before any effect.
- [x] 2.6 `domains/vms/storefront/src/market_storefront/services/capacity_client.py`:
      `capacity_binding_for_listing` returns `PublicationBinding`, loaded through the
      2.1 loader from the durable `capacity_backing`. Callers that reserve —
      `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_service.py`'s `fulfill_vm_obligation` and
      `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`'s `_reservation_binding` — require
      `CapacityBinding` and refuse an unbacked one before reserving.
- [x] 2.7 `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`:
      relax the two identity-only `isinstance(..., CapacityBinding)` guards (before
      settlement-artifact construction and in `persist_opening`) to
      `PublicationBinding`; `require_capacity_binding` and
      `compute_round_zero_decision` accept either. `_place_capacity_hold` skips an
      unbacked binding without a warning and records a stage event saying no hold
      applies.
- [x] 2.8 `kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py`:
      `RoundRequest` gains the opaque `binding`, populated from
      `ResolvedNegotiation.binding`, symmetric with the other carriers.
- [x] 2.9 API credits (`domains/apicredits/storefront/src/apicredits_storefront/services/capacity_client.py`,
      `domains/apicredits/storefront/src/apicredits_storefront/services/publication_service.py`):
      types move with the protocol, and every close
      path names its closure reason. No behaviour change.

## 3. Specification

- [x] 3.1–3.8 The delta specs carry the requirement scoping, the listing-identity
      rule, the source-scoped guard, the backing transition as a move between pools,
      the scoping of `site-capacity`'s claim-identity requirement, and the
      planning-review requirements: settlement options for unbacked listings, the
      publication loop, the durable seller close, and durable terms. Written during
      planning; promoted in 7.7.

## 4. Projection, derivation, and reconciliation

VM derivation lives in `domains/vms/listings/reconciler.py` unless another file is
named.

- [x] 4.1 Read `capacity_backing` live from the current projection at each point of
      need and never cache the projected tag; the binding's discriminator is derived
      from it at publication and is immutable.
- [x] 4.1a **Joint producer-version rule**, per site and per projection generation,
      in `domains/vms/storefront/src/market_storefront/services/site_projection_cache.py`
      and `_projected_pool_rows`: resolve each pool through
      `market_resource_pools.resolve_pool_declarations`; a generation in which no
      pool carries either tag reads every pool as backed with `deliverable_modes`
      serving as advertisement authorization; in any other generation a pool raising
      `PoolDeclarationError` or `MissingPoolDeclarationError` is unresolvable.
- [x] 4.1b Report, in the storefront's system status
      (`domains/vms/storefront/src/market_storefront/services/system_service.py`, following
      `listing_cardinality_mode_explanations()`), each site read under the
      compatibility rule and each unresolvable pool with the resolver's problem codes;
      log once per site generation.
- [x] 4.1c Gate `_projected_pool_rows` on `PoolDeclarations.advertises("vm")` in place
      of `pool_delivers_offering_mode`, and carry the resolved backing onto each row
      and candidate.
- [x] 4.1d Read the projected pool's `enabled`: `false` yields no candidates. In a
      generation read under the compatibility rule, an absent `enabled` is not a
      disablement.
- [x] 4.2 Range slices over declared quantity for an unbacked pool and over
      available quantity for a backed one, in `_projected_pool_rows` and
      `available_compute_slices`. A fungible pool's range is the largest single
      member's value, declared or available.
- [x] 4.3 Report unresolvable pools and members separately from pools that resolved
      and yielded nothing, and exclude their listings from close, refresh, and reopen
      in `stale_open_listing_ids` and `closed_available_listing_ids`. One unresolvable
      member holds a whole fungible pool and only its own listings in a
      specific-resource pool.
- [x] 4.3a **Enumeration quantity.** An absent `gpu_count` yields no listing and an
      operator notice naming the member; a declared zero yields none silently; a
      malformed count makes the member unresolvable. Remove every substituted default
      on the derivation path: `_projected_resource_usage`, `listing_resource_key`,
      `listing_pool_key`, the stored-listing readers in `closed_available_listing_ids`,
      `domains/vms/domain/src/arkhai_vms/storefront_adapter.py`
      (`vm_listing_resource_key`), `domains/vms/storefront/src/market_storefront/publication_binding.py`, and
      the candidate capacity source built for publication. On the candidate side a
      missing or non-positive count raises; on the stored side a listing with no
      usable count is excluded from keyed reconciliation with a notice. The admin
      controller's `allocated_gpu_count or 1` reads a site reservation and is out of
      scope.
- [x] 4.3b Log a warning naming the pool and the differing fields for a fungible pool
      whose members declare different categorical attributes. Derivation is
      otherwise unchanged.
- [x] 4.4 A backing transition is close-and-republish: the new listing derives from a
      different pool and binds a new identity. Nothing attempts an in-place update of
      backing.
- [x] 4.5 **Retire `derived_compute_listings` from publication.** Delete
      `record_derived_listing`, `load_derived_listing_for_slice`,
      `reopen_local_derived_listing`, `mark_derived_listings_closed`,
      `mark_derived_listings_open`, and the fresh-database
      `ensure_derived_compute_listings_table`, and their callers in
      `domains/vms/storefront/src/market_storefront/services/publication_service.py` and
      `domains/vms/storefront/src/market_storefront/cli_publish.py`. A closed listing is
      found by the candidate's derivation key in `storefront_listing_bindings`. This
      fixes the migrated-database abort confirmed during planning.
- [x] 4.6 **The reconciliation comparison.** Add one VM function, beside the
      reconciler in `domains/vms/listings/`, comparing a stored listing with a fresh
      derivation of its own source and with its binding, returning the outcomes in
      design's "One comparison gates refresh and every reopen path". Classify every
      published field as identity or term there, per the listing-identity rule, and
      record the classification in its docstring.
- [x] 4.7 **Refresh through the publication-source seams.**
      - `domains/vms/domain/src/arkhai_vms/storefront_adapter.py`: an open listing no
        longer covers its slice unless the comparison reports it unchanged.
      - The VM `reopen_existing` callback reconciles the listing bound under the
        candidate's derivation key: in-place update for a term or missing published
        backing; reconciliation close with a logged refusal for an identity or live
        backing difference; reopen of a reconciliation-closed listing with the fresh
        payload; nothing for a seller-closed or unchanged one.
      - `core/storefront/src/core_storefront/publication_runner.py`: `publish_round`
        accepts an `unchanged` outcome from `reopen_existing` and counts it as
        skipped. No other core change; core compares no payload.
- [x] 4.8 **Capacity-event reopen.** In `domains/vms/storefront/src/market_storefront/services/publication_service.py`
      (`reopen_available_compute_listings_after_capacity_change`) and
      `closed_available_listing_ids`: reopen only reconciliation-closed listings, and
      only when the comparison allows it. Republish stored terms.
- [x] 4.9 **Published backing.** `vm_listing_resource_for_listing` and every VM
      publish path stamp `listing_resource.capacity_backing` from the binding.
      `domains/vms/listings/models.py`'s `ComputeResource` carries the field, optional
      on read so a stored listing awaiting disclosure still loads.
- [x] 4.10 **Seller close.** `close_order` in `domains/vms/storefront/src/market_storefront/services/publication_service.py`
      passes `seller`; the loop and the capacity-event path pass `reconciliation`.
      `resume` in `domains/vms/storefront/src/market_storefront/controllers/listings_controller.py` reopens a seller-closed
      listing, clears its reason, and publishes; on a reconciliation-closed listing it
      returns 409 naming the reason and changes nothing.
- [x] 4.11 **Settlement options for unbacked listings.**
      `domains/vms/storefront/src/market_storefront/settlement_composition.py`: the VM composition receives
      an explicit per-mechanism declaration of capacity-backed fulfillment —
      `alkahest.v1` and `fiat.stripe.v1` fulfil through capacity, and
      `contact-exchange.v1` does not if it is composed for VM by then — as an injected
      collaborator with no default entry. Publication drops the options it names from
      an unbacked candidate with an operator notice, and yields no listing if none
      remain. The admin create path in `domains/vms/storefront/src/market_storefront/services/listing_service.py`
      applies the
      same rule and resolves the pool's declarations to choose the binding variant,
      calling `CapacityRuntime.require_binding` only for a backed one.
- [x] 4.12 **The inventory guard.**
      - `domains/vms/negotiation/policies.py`: `has_matching_inventory_guard` checks
        the declared match against the 4.6 derivation of the listing's own source, over
        declared quantity, rejecting with `no_matching_declaration`; for a backed listing
        it checks availability over the pinned site's availability, rejecting with
        `no_matching_inventory`. Fungible listings match a single member.
      - `domains/vms/negotiation/storefront_round.py`: `default_seller_round_hook` and
        `_DefaultSellerRoundHook` take the binding; `_default_seller_policy_inputs`
        fetches only the pinned site's snapshot, and none for an unbacked binding.
      - `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`: `_default_seller_round_hook`
        is built per round, in `evaluate` from `RoundRequest.binding` and in
        `compute_round_zero_decision` from its resolved binding.
      - Source selection is publication's, by `use_site_projection_for_listings`.
      - `SellerRoundHook` in `kit/policy` is unchanged.

## 5. Publication loop, command, published shape, and filter

- [x] 5.1 Publish backing in `listing_resource` on every compute-family listing (4.9,
      5.11).
- [x] 5.2 Republish existing listings carrying explicit `capacity_backing: backed`
      through the loop's refresh before the filter is relied on.
- [x] 5.3 `core/registry/filter-spec.yaml`: add the `capacity_backing` field and an
      exact `op: in`, `value_type: string`, `on_missing: fail` filter beside the
      other `listing_resource` axes. The API-credits schema
      (`domains/apicredits/registry/filter-spec.yaml`) is not touched.
- [x] 5.4 Confirm an unbacked listing validates against the existing `anyOf` with no
      structural change to the listing shape.
- [x] 5.5 Record the etag consequence: adding a filter changes the spec's etag and
      buyers re-fetch, without a version bump.
- [x] 5.6 Add the publication loop as a storefront service
      (`domains/vms/storefront/src/market_storefront/services/publication_loop.py`, new):
      one cycle runs the core publication runner over the VM source with in-process
      callbacks for publish, reopen, and close, replacing the HTTP-to-self and
      direct-database callbacks now in `cli_publish.py`. Its settlement terms resolve
      from pool clauses and configured defaults only.
- [x] 5.7 Register it as a gated loop in `domains/vms/storefront/src/market_storefront/lifecycle.py`, start
      it in `domains/vms/storefront/src/market_storefront/startup.py`, and wake it from
      `site_projection_poller_loop` in
      `domains/vms/storefront/src/market_storefront/services/site_projection_cache.py` when a site's resource-pool projection generation
      changes. A held loop stays held.
- [x] 5.8 `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`: add `publication` to
      `ADVANCE_LOOP_NAMES`, `POST /api/v1/admin/lifecycle/publication/run-cycle`
      running exactly the timer's cycle, and `POST /api/v1/admin/lifecycle/publication/dry-run` reporting the
      planned publish, refresh, close, reopen, and hold decisions with reasons and
      applying none.
- [x] 5.9 `core/storefront-client/src/storefront_client/client.py`: name `publication`
      among the loops in the sync and async lifecycle method docstrings. No new
      method.
- [x] 5.10 **Command.** Rewrite `domains/vms/storefront/src/market_storefront/cli_publish.py` as a
      typed-client front end: a one-shot run calls `run-cycle`, `--dry-run` calls
      `dry-run`, and `--abort-all` seller-closes every open listing through the API.
      Remove `run_watch_loop`, `--watch`, `--poll-interval`, `--db`, `--settlement`,
      `--max-duration-seconds`, and `--inventory`, and every direct SQLite read in the
      module. Retire `_pool_hint_resolution_settings`' command-clause parameter.
- [x] 5.11 **Bare metal.**
      - `domains/bare_metal/src/arkhai_bare_metal/schema.py`: `BareMetalListing`
        gains a required `capacity_backing: Literal["backed"]`.
      - `domains/bare_metal/src/arkhai_bare_metal/publication.py` sets it explicitly.
      - `domains/bare_metal/src/arkhai_bare_metal/storefront_publication.py` and
        `domains/bare_metal/src/arkhai_bare_metal/storefront_adapter.py`
        apply the listing-identity rule through `skip_keys` and `reopen_existing`
        (identity: `host_id`, `physical_host_id`, `capabilities`, site labels; terms:
        durations, access methods, settlement options), returning `unchanged` where
        nothing differs.
      - `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication.py`
        and `publication_cli.py` name the closure reason on every close.
      - Bare-metal publication stays operator-invoked.

## 6. Validation

- [x] 6.1 **Unit and library integration** *(relabelled by 8.18)*. Both binding migrations and triggers, including refusal of a
      `NULL` insert and of an update to `capacity_backing`; the closure-reason
      migration, backfill, and triggers; the binding loader's refusal of an unknown
      value; `CapacityBinding != UnbackedBinding` over equal fields; exhaustive
      filter matching including a listing with no backing under both backed and
      unbacked queries (`core/registry` tests).
- [x] 6.2 *(reopened by review, closed by 8.12–8.13: publication and negotiation were proved separately (8.13))* **Integration.** An unbacked listing publishes and then negotiates through
      the real storefront app, exercising the thread binding and the completeness
      trigger.
- [x] 6.3 **Integration.** An unbacked listing causes no reserve, site, or provider
      effect through acceptance: the capacity collaborator is mocked and asserted
      never invoked, and no capacity hold is recorded.
- [x] 6.4 **Integration.** Publish and query backing through the canonical
      `RegistryClient` against the real registry app.
- [x] 6.5 *(reopened by review, closed by 8.12–8.13: evidence is not app-level (8.12))* **Integration.** Removing or disabling a source declaration, and disabling
      its pool, closes the published unbacked listing.
- [x] 6.5a *(reopened by review, closed by 8.12–8.13: evidence is not app-level (8.12))* **Integration.** A declared shape change that alters the derivation
      envelope closes the old listing and publishes a new one under a different
      derivation key, leaving the original binding row unmodified.
- [x] 6.6 *(reopened by review, closed by 8.12–8.13: evidence is not app-level (8.12))* **Integration.** A backed listing's publication path is unchanged apart
      from the disclosed backing and the corrections the design lists.
- [ ] 6.7 **System.** Backed and unbacked listings from one storefront are returned
      by one buyer query across running services. Gated on
      `compose-contact-exchange-across-compute` Sections 1–3.
- [ ] 6.8 **System.** Two seller sites publishing unbacked supply to one storefront
      retain distinct origin and source identity. Gated on that change's Sections 1–3
      and 3b.
- [x] 6.9 **Integration.** The real provisioning app emits `capacity_backing` and
      `advertisable_modes`, the canonical site client parses them, and the storefront
      consumes that exact response.
      Done by 8.17, split at the site client's contract fixture: the real
      provisioning app's response is validated on one side and the storefront's
      publication tests consume the same built shape on the other.
- [x] 6.10 *(reopened by review, closed by 8.12–8.13: evidence is not app-level (8.12))* **Integration.** Old-producer skew: a projection carrying neither tag on
      any pool resolves every pool as backed with delivery serving as advertisement,
      so a previously valid backed listing still publishes, and system status reports
      the compatibility rule. A projection carrying the tags on some pools and neither
      on one holds that pool. The older-producer projection is a recorded site-client
      response, because no current provisioning image can emit one.
- [x] 6.10a *(reopened by review, closed by 8.12–8.13: evidence is not app-level (8.12))* **Integration.** A `capacity_backing` value outside the two holds that pool,
      and system status names its problem codes.
- [x] 6.11 **System — decided not to add.** Mixed site and storefront versions are
      supported, but an upgraded provisioning service refuses to start with a pool
      lacking valid declarations, so no deployed pipeline can host an old producer.
      6.10 is the coverage.
- [x] 6.12 *(reopened by review, closed by 8.12–8.13: evidence is not app-level (8.12))* **Integration.** A supply move from an unbacked pool to a backed one
      closes the old listing and binds a new one under a different identity and
      derivation key; the original binding row is unmodified.
- [x] 6.13 *(reopened by review, closed by 8.12–8.13: evidence is not app-level (8.12))* **Integration.** After republication, no listing in storefront-local state
      lacks an explicit backing value. Count, do not sample. Registry copies across
      independently operated deployments are rollout evidence, not a test here.
- [x] 6.14 **Integration.** An unbacked listing reaches acceptance and
      settlement-artifact construction.
- [x] 6.15 **Unit.** A declaration with no `gpu_count` yields no listing and a notice;
      zero yields none silently; a malformed count holds the member, and a whole
      fungible pool; no key builder substitutes a count.
- [x] 6.16 *(reopened by review: API credits violated it; closed by 8.1–8.4. The
      publication-cycle half moves to the real app in 8.12)* **Integration.** Durable seller close: a seller-closed listing stays closed
      through a capacity release and a publication cycle, and no replacement binds;
      `resume` reopens it; `resume` on a reconciliation-closed listing returns 409
      and changes nothing; a close naming no reason is refused.
- [x] 6.17 **Integration.** Publication loop controls through the typed client: the
      lifecycle pause holds the loop; two dry runs report the same plan and change
      nothing; a run-cycle while held applies exactly that plan and leaves the loop
      held; a projection generation change wakes an unheld loop. Add the
      sync/async parity check for the loop name in the storefront's unit suite.
      Done by 8.14 (typed client, real app) with the unit coverage noted above.
- [x] 6.18 **Integration.** Refresh and reopen gating: a pool pricing change updates
      an open listing in place at every registry; a changed `gpu_model` or pool
      `region` tag closes the listing and a later capacity release does not reopen it;
      a listing without published backing gains it in place; the site-reset case logs
      its refusal, leaves the listing closed, and binds nothing new.
      Done: storefront state as noted above, and the registry side by 8.15.
- [x] 6.19 **Unit and integration.** The inventory guard: declared match without any
      availability read or site call for an unbacked listing; `no_matching_declaration`
      for a shrunk or disabled declaration; rejection when only another pool or site
      matches; a fungible match on one member; availability read from the pinned
      site only, with other sites receiving zero calls; the same checks in
      `evaluate-negotiate` round zero.
      Done: unit coverage as noted above, and round zero through the admin route
      by 8.16.
- [x] 6.20 **Unit and integration.** Settlement options for unbacked listings: options
      whose mechanism fulfils through capacity are dropped with a notice; a candidate
      left with none yields no listing; backed candidates are unaffected. Integration
      injects a declaration marking one registered mechanism as not fulfilling through
      capacity, so 6.2, 6.3, 6.5, 6.5a, 6.12, 6.14, 6.16, and 6.18 can exercise
      unbacked listings before contact exchange is composed for VM.
- [x] 6.21 *(reopened by review: the integration half is not app-level; relabelled by 8.18)* **Unit and library integration.** Bare metal: the listing model refuses a listing
      without `capacity_backing`; publication sets it; a term change refreshes in
      place and an identity change closes and refuses; both binding writers name
      backing.
- [x] 6.22 **Unit.** `market-storefront publish` calls only the storefront API through
      the typed client and opens no database; each retired flag is rejected.
- [x] 6.23 *(reopened by review, closed by 8.12–8.13: evidence is not app-level (8.12))* **Integration.** Regression for the confirmed migrated-database defect: on a
      database carrying the retirement triggers, close and reopen complete with no
      write to `derived_compute_listings`.
- [x] 6.24 **System.** Audit every VM scenario that creates listings —
      `test_full_deal.py`, `test_full_deal_buyer_cli.py`,
      `test_buy_oneshot_buyer_cli.py`, `test_compute_dynamic_listings.py`,
      `test_multi_registry.py`, and `test_non_erc20_settlement.py` under
      `e2e-tests/tests/e2e/roles/scenarios/vms/` — so each holds the loops with
      `pause_storefront` before creating listings or advances the publication loop and
      asserts on what it derives, per `docs/development/TESTING.md`.
- [ ] 6.25 Run `make test-kits`, `make test-core`, `make test-storefront`,
      `make test-vms-domain`, `make test-bare-metal`, `make test-apicredits`,
      `make test-registry`, and `make test-compute-provisioning`; then
      `make check-reinit`, adding reinit upgrade lines for every consumer of
      `arkhai-kit-negotiation-runtime`, `arkhai-kit-capacity-publication`, the core
      storefront, and the storefront client.

## 7. Closeout

- [x] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The rationale to keep at the binding is why origin and admission are
      separate; at the loop, why terms come only from durable sources; at the close,
      why a seller's close is never reopened by reconciliation. None names a review
      or change.
- [x] 7.2 **Import placement.** Review imports this change added or touched —
      including the lazy imports in `_projected_pool_rows`, `negotiation_runtime.py`,
      and the new loop — and migrate function-level ones to module level where no
      genuine circular import or documented lazy-load reason exists. Verify against
      the real test suites.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. Confirm the no-source-inventory rule, the
      two reconciliation loops, the publication loop, the durable seller close, and
      durable terms landed as normative requirements.
- [ ] 7.4 **Narrative compression.** Shorten completed-task notes to final behavior,
      material validation evidence, unresolved work, and promotion destinations; move
      any remaining rationale into `design.md` first.
- [ ] 7.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, remove this change's
      row from Goal 7's gap table and absorb the result into that goal's
      current-state prose. Goal 7 keeps its rate-comparison gap, its introduction
      gap until `compose-contact-exchange-across-compute` lands, and gains a
      bare-metal advertisement gap owned by
      `bare-metal-publication-reads-pool-declarations`.
- [ ] 7.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`, including the system-evidence
      gate on `compose-contact-exchange-across-compute` and the completion dependency
      on `pools-9-retire-local-physical-authority`. The row and graph edge for
      `bare-metal-publication-reads-pool-declarations` were added when it was
      created; confirm them.
- [ ] 7.7 **Promotion.** Promote, after code review:
      - `openspec/specs/storefront-publication/spec.md`,
        `openspec/specs/registry-discovery/spec.md`, and
        `openspec/specs/site-capacity/spec.md` from the delta specs. Moving
        `registry-discovery`'s two requirements that sit outside its `## Requirements`
        section is a prerequisite, or archiving the delta is refused.
      - `openspec/specs/storefront-publication/architecture.md`: the listing-identity
        rationale, the reconciliation comparison, and why publication is autonomous.
      - `docs/development/ARCHITECTURE.md`, "Storefront capacity boundary": backing is
        declared, never inferred, and independent of cardinality and settlement. The
        Terms entries landed with `pool-declared-advertisement-and-backing`; confirm
        rather than promote them twice.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Combined compute-family
        storefront": the binding-schema and closure-reason rollback posture, and that
        storefront-wide settlement terms are configuration.
      - `docs/development/TESTING.md`: the storefront's lifecycle loops, including
        publication, in the pause-and-step table.
      - `docs/seller-quickstart.md`: publication without `--settlement` or
        `--inventory`, and the loop controls.
      Then complete the design-promotion record below.
- [ ] 7.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=unbacked-listing-publication` and resolve every
      match, including any citation of a tombstoned file.
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline (`make
      test-deployment`) passes and record the run, its result, and the scenarios that
      exercise this change: 6.7, 6.8, and the 6.24 scenarios. Gated like 6.7 and 6.8.
      The system tier advances individual stages and does not run the publication
      loop; record that the loop's evidence is the integration suite (E3), not a
      scenario. Run 3 (114 passed, 3 skipped) predates E1 and is not this evidence.
      If the pipeline cannot run for an unrelated reason, record the blocker, its
      cause, and the change that owns it, and treat the gated validations as unrun.

## 8. Code review remediation

Decisions and reasons: `design.md`, "Decisions from the code review" and "Decisions
from the third end-to-end run". Order: R1–R3, then R7–R8, then R6 with E1 and E2,
then R4–R5 together with 6.2, 6.9, and 6.17–6.19, then closeout (Section 7). Run every affected suite, `make check-reinit`, and `make dist`
after each group; each group can be its own fileset.

**Correctness (R1–R3)**

- [x] 8.1 **Core reopen guard (R1).** `core/storefront/src/core_storefront/sqlite_client.py`:
      `update_listing(status="open")` on a seller-closed listing raises unless called
      with `reopened_by="seller"`; state the refusal's reason in the exception. Unit
      tests: reconciliation reopen of a seller close refused; seller reopen allowed and
      clears `closed_by`; reconciliation reopen of a reconciliation close allowed.
      Done. The guard is `write_listing_update` in `core_storefront.sqlite_client`, a
      connection-level write inside the caller's `BEGIN IMMEDIATE` transaction;
      `update_listing` wraps it and raises `SellerClosedListingError`. It also keeps
      `seller` when reconciliation closes an already seller-closed listing, and the
      upsert conflict path refuses to overwrite a seller's close with another
      status and keeps `seller` when it writes another close (the second found in
      pre-closeout review; `test_an_upserted_close_keeps_a_seller_close` fails
      without it). Tests are real-DB
      library integration, in the new `core/storefront/tests/integration/`
      (`test_listing_closure.py`), which `make test` now runs; 4 of 8 fail without
      the guard.
- [x] 8.2 **Kit reopen names who reopens (R1).**
      `kit/capacity-publication/src/market_capacity_publication/publication.py`:
      `reopen` takes the reopener and passes it to the repository; `reconcile` passes
      reconciliation and skips a seller-closed candidate, reporting it, rather than
      failing the plan. The VM storefront's `reopen_order` (used by `resume`) passes
      seller.
      Done. `reopen` requires `reopened_by`; `reconcile` reports a seller-closed
      candidate under `seller_closed`. The VM `resume` reopens as the seller; the
      loop, admin release, and failure-handling reopens name reconciliation.
- [x] 8.3 **API credits (R1).** `domains/apicredits/listings/reconciler.py`
      (`reopenable_credit_listing_ids`) and the storefront's capacity reopen in
      `domains/apicredits/storefront/.../services/publication_service.py` exclude
      seller-closed listings. Regression test through the API-credits storefront: seller
      close, quota returns, capacity reconciliation does not reopen it.
      Done. `reopenable_credit_listing_ids` admits only reconciliation closes. The
      regression enters the capacity-event reconciler (`_capacity_reconciler`) with a
      `released` delta over a real database; the API-credits storefront exposes no
      capacity-event control through its typed client, so it cannot be driven from
      the app (recorded in `design.md`). It fails only with both this predicate and
      the core guard removed; the predicate has its own unit test.
- [x] 8.4 **Bare metal (R1).** `reopen_derived_bare_metal_listing_if_present` reopens
      through `update_listing` instead of raw SQL, and `load_derived_bare_metal_listing`
      or its caller sees `closed_by`. Regression test: a seller-closed bare-metal listing
      is not reopened by its publication command.
      Done. Bare metal's reopen and reconciliation close go through
      `write_listing_update`, imported where used because the package root is
      installed without the storefront extra by the buyer and provisioning adapters.
      The reopen reads `closed_by` and leaves a seller close as a clean skip. Tests
      drive the core publication runner: a seller close stays closed with no failure
      and nothing published; a reconciliation close reopens in place.
- [x] 8.5 **Closure provenance in the listing (R2).** `load_listing` and
      `list_listings` return `closed_by`; remove `load_listing_closed_by` and move its
      callers (VM publication loop, listings controller `resume`, reconciler predicates
      as needed) onto the listing's own field. Task 1.8 is then true as written.
      Done. Both return `closed_by`; `load_listing_closed_by` is gone and its
      callers read the listing.
- [x] 8.6 **Close is local first (R3).** `PublicationRuntime.close` lets a local
      failure propagate before any registry close; `reconcile` records a failed close
      per listing and continues. Failure-ordering test: the repository raises, the
      registry is never called, and the error reaches the caller.
      Done. The kit's close lets a local failure propagate before any registry;
      `reconcile` reports `failed_closes` and continues, and the VM loop records each
      as a `fail` action. The VM close route answers a local database failure with
      503 `listing_close_incomplete` (controller unit test).

**Structure (R7, R8, R6)**

- [x] 8.7 **No hidden reconciler state (R7).** Replace `_BINDING_BACKING` in
      `domains/vms/listings/reconciler.py` with an immutable row record (listing ID,
      listing resource, site, binding backing) returned by `_bound_vm_listings`.
      Done. `BoundVmListing` (listing ID, listing resource, site, binding backing)
      replaces the process-global map; `closed_available_listing_ids` reads the
      backing from the row.
- [x] 8.8 **Capacity events are backed-only (R8).** The capacity-event path in
      `domains/vms/storefront/src/market_storefront/services/capacity_client.py` (and
      the admin release and failure-handling reopen paths that share its predicates)
      acts only on listings bound as backed. Test through the real capacity-event
      path: one backed and one unbacked listing, an availability-only delta, only the
      backed listing changes.
      Done. `stale_open_listing_ids` takes a required `backed_only`: the loop passes
      `False`, the capacity-event close and the admin release handler `True`.
      `closed_available_listing_ids`, whose callers are all availability paths,
      reads backed listings only. The test publishes one listing of each kind
      through the loop, then enters the capacity-event reconciler with
      availability-only deltas: a drop closes only the backed listing and a release
      reopens only the backed one. The reopen half fails without the filter; the
      close half held already, because unbacked slices range over declared
      quantity. It lives in `test_publication_loop.py` with the world it shares and
      moves onto the real app with that file in 8.12.
- [x] 8.9 **Declaration reader in the kit (R6).** Move the site-generation reader
      (`read_site_declarations`, `ResolvedPool`, `SiteDeclarations`, the enablement
      reason) from `domains/vms/listings/pool_declarations.py` into
      `kit/resource-pools/src/market_resource_pools/` beside `resolve_pool_declarations`,
      with its tests; VM imports it. Bump the kit's version if its public surface
      changes, and add `reinit` lines where its consumers need them. In the move, a
      generation with no pools is not read under the compatibility rule (E2); unit
      test that an empty generation reports no compatibility reading.
      Done. `market_resource_pools.site_declarations`, exported from the package;
      `domains/vms/listings/pool_declarations.py` and its VM test file are
      tombstoned, and the tests live in
      `kit/resource-pools/tests/unit/test_site_declarations.py`. E2: a generation
      with no named pools is not read under the compatibility rule (two tests, both
      failing under the old rule). The reconciler keeps its import local, since the
      buyer installs `arkhai-vms-listings` without the `pools` extra; the buyer suite
      passes with no resource-pools kit installed. The kit stays at 0.2.0: the
      addition is additive and a bump would force every consumer's lock, so `reinit`
      reinstalling it carries the change, as for the other packages this section
      touches.
- [x] 8.10 **Bare-metal advertisement (R6 follow-up).** Confirm whether bare-metal
      publication reads a pool's `advertisable_modes`. If it does not, report the
      finding before changing anything: fixing it may be out of this change's scope.
      Done: it does not. Decided to record it rather than fix it here (`design.md`,
      R6 follow-up): the new change `bare-metal-publication-reads-pool-declarations`
      owns it, indexed under Goal 7, and the advertisement requirement is scoped to
      listings derived from the resource-pool projection.
- [x] 8.10a **Publishers name their contributions (E1).**
      `core/storefront/src/core_storefront/publication_plugins.py` and
      `publication_composition.py`: the builder takes the exact contributions to
      build and refuses a name no registration carries before calling any factory.
      `domains/vms/storefront/src/market_storefront/publication_wiring.py` names
      `vms`; `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication.py`
      names its resolved registration. Core unit tests: a two-contribution registry
      builds only the named source and calls no other factory; an unknown name fails
      first. Replace `test_publication_wiring.py`'s patched core builder with a real
      two-contribution registry. The app-level proof is 8.11's fixture.
      Done. Core requires `contributions` and refuses, before any factory runs, an
      unregistered name, arguments for a contribution not being built, an empty
      selection, or a bare string. The VM loop resolves its registration by
      offering mode. `test_publication_wiring.py` builds the registry through
      startup discovery from a two-domain selection instead of patching the core
      builder; it and the core test fail with the builder building every
      registration.

**Test levels (R4–R5) and the open validation**

- [x] 8.11 **Real-app publication fixture.** An integration fixture running the VM
      storefront app with its container wired, a patched site projection, real
      `[Settlement]` and `[pricing].settlements` configuration compiled by the loop's
      own request path, a settlement-composition double at the mechanism boundary
      declaring per test which mechanisms fulfil through capacity (`design.md`,
      R4–R5), and the canonical `StorefrontClient`. Reuse the admin-API and
      negotiate-controller fixtures' app and chain patterns. Register both `vms`
      and `bare_metal`, as the combined e2e storefront does, so every loop test runs
      under the registry that exposed E1.
      Done: `domains/vms/storefront/tests/publication_app.py`. Settings select both
      `vms` and `bare_metal`; `storefront_domains`, `settlement`, and
      `pricing.settlements` are replaced rather than overridden, since an override
      merges into the test configuration's lists. The double carries an integral
      clause rate into the escrow's base-unit rate. An opt-in `negotiation` flag adds
      the negotiation route, its runtime, and a buyer client.
- [x] 8.12 **Convert every publication-loop case.** Every case in
      `tests/integration/test_publication_loop.py` drives the loop through
      `admin_run_lifecycle_cycle("publication")` or
      `admin_dry_run_lifecycle_cycle("publication")` and asserts through the client
      where an API exists. Cases that only make sense directly become unit tests with
      mocked collaborators. Remove `VmPublicationCycle`'s injected `request_builder` if
      nothing then uses it.
      Done. All eighteen cases run through the client; none needed to become a unit
      test. Bindings, which no API exposes, are read from storefront persistence, and
      raw SQL is used only for state no API reaches. The R8 case now advances the
      `capacity-events` loop through its route. Reverting E1's builder fails all
      eighteen; reverting R8's filter fails only its own. `request_builder` is
      removed.
- [x] 8.13 **6.2 in one flow.** One test publishes an unbacked listing through the loop
      and negotiates it to acceptance through the same app.
      Done: `test_an_unbacked_listing_publishes_and_negotiates_to_acceptance`, with
      no reservation or hold at any point.
- [x] 8.14 **6.17.** Through the typed client: pause holds the loop, dry-run twice
      reports the same actions and changes nothing, run-cycle while held applies one
      cycle and leaves the loop held, and the sync and async clients accept the loop
      name alike. (A projection change waking an idle loop is covered in
      `tests/unit/test_loop_gate_wiring.py`.)
      Done. `test_the_lifecycle_pause_holds_the_loop_while_its_controls_step_it`
      starts the loop as startup does while held: the pause reports it `paused`,
      two dry runs match and change nothing, `run-cycle` applies exactly that plan,
      and the loop is still `paused` after. It fails with the loop's gate removed
      (the loop reports `starting`). `test_both_clients_address_the_publication_loop_alike`
      checks both variants send the same route and operation for the step and the
      dry run; signature parity was already covered.
- [x] 8.15 **6.18.** The registry side of an in-place refresh and of a reopen, through
      a registry reachable by the app, in addition to storefront state.
      Done. The fixture's opt-in `registries` replaces `MultiRegistryClient`, where
      this codebase wraps the independently operated registries, with a recorder
      across two configured registries with development authority pins; the
      registry's own side is 6.4's. A term refresh republishes in place to both with
      no status change; a reconciliation close sends `closed` to both; a reopen
      republishes and sends `open` to both. The reopen test fails when the kit's
      `reopen` omits the explicit registry reopen.
- [x] 8.16 **6.19.** Round zero of `evaluate-negotiate` runs the guard, through the admin
      route.
      Done. `test_round_zero_evaluation_runs_the_inventory_guard` evaluates an opening
      round against a loop-published unbacked listing: `accept` while its declaration
      supports it, `reject` with `no_matching_declaration` once the declaration
      shrinks and before any cycle closes the listing. This is new evidence for
      behaviour already implemented; it was not re-verified by reverting round
      zero's hook construction.
- [x] 8.17 **6.9.** One integration test: the provisioning app emits both declarations,
      the canonical site client parses them, and the storefront consumes them.
      Done through a contract fixture (`design.md`, R4–R5):
      `kit/site-client/src/market_site_client/fixtures/resource_pools.py`, with its
      own unit test that the validator refuses a missing declaration, enablement,
      metadata, or capacity. Producer: the provisioning integration test
      `test_the_projection_carries_both_declarations_as_storefronts_read_them`
      creates a backed and an unbacked pool (its member naming no host) through the
      pool API, reads the projection through `SiteCapacityClient`, validates it, and
      resolves it through `read_site_declarations`. Consumer: the storefront
      fixture's `pool()` builds every projection with the same builders.
- [x] 8.18 **Library tests out of `unit/`.** Move the core migration and trigger tests
      that open a real database from `core/storefront/tests/unit/` to
      `core/storefront/tests/integration/`, and relabel any other claim in Section 6
      whose evidence is at a different level than it states.
      Done. `test_domain_binding_migrations.py` moved to
      `core/storefront/tests/integration/`, beside `test_listing_closure.py`; it
      reuses the unit suite's test contract rather than copying it. The other
      real-database files in `core/storefront/tests/unit/` predate this change and
      move when next touched. Relabelled: 6.1 (its migration and trigger evidence is
      library integration), and 6.21, whose integration half is bare metal's
      operator-invoked publication command run through the core publication runner
      against a real database, since bare-metal publication has no service route
      to drive.
- [x] 8.20 **Registries converge on local status (R3, pre-closeout review).**
      Core: `list_publication_divergence`, and `publish_listing_to_registries`
      takes an optional target subset. Kit: `publication_divergence`, `converge`,
      and the reopen's status update recorded. VM: each cycle converges, reported
      as `converge` (and `fail` if unrepaired). API credits: each capacity
      reconciliation converges. Tests: core real-DB divergence; kit unit tests for
      a missed close, a failed reopen (fails without the reopen being recorded),
      and a still-unreachable registry; VM app-level, one of two registries missing
      a close and then a reopen, repaired by the next `run-cycle` alone (both fail
      without convergence); API-credits unit test that every reconciliation ends by
      converging. The API-credits reconcile tests moved to `tests/integration/`.
- [x] 8.21 **Bare-metal registry convergence.** Decided: owned by
      `bare-metal-publication-reads-pool-declarations` (its task 2.4 and a spec
      requirement), and its index row says so.
- [x] 8.19 **Version `kit/resource-pools` and `kit/site-client`.** Once every
      Section 8 change is in place and `make test` passes, bump
      `arkhai-kit-resource-pools` for the `site_declarations` addition and
      `arkhai-kit-site-client` for its `fixtures` subpackage, raise `arkhai-vms-listings`' `pools` extra to
      require it, and update every consumer's lock (the VM storefront's by hand, as
      its torch index cannot be reached from the build container), then rerun
      `make check-reinit` and the consumers' suites.
      Done, widened to every package whose sources this change altered, minor for
      new or changed API and patch otherwise: `arkhai-core-storefront` 0.6.0,
      `arkhai-core-storefront-client` 0.19.1, `arkhai-kit-capacity-publication`
      0.2.0, `arkhai-kit-negotiation-runtime` 0.2.0, `arkhai-kit-resource-pools`
      0.3.0, `arkhai-kit-site-client` 0.4.0, `arkhai-vms` 0.3.0,
      `arkhai-vms-storefront` 0.5.0, `arkhai-bare-metal` 0.4.0,
      `arkhai-bare-metal-storefront` 0.4.0, `arkhai-apicredits-domain` 0.3.0, and
      `arkhai-apicredits-storefront` 0.4.0. The three VM wheels this change created
      stay at their first version, 0.1.0; `core/registry`'s filter spec is not in its
      wheel, so that package is unchanged. Every internal constraint on a bumped
      package names its new version, plus `arkhai-apicredits-domain>=0.3.0` in the
      API-credits storefront and `arkhai-core-storefront>=0.6.0` in the VM domain.
      Locks re-resolved from their committed state upgrading only the bumped
      packages; the VM storefront's by hand, confirmed with
      `uv lock --locked --offline`. No lock's package sources changed, and no lock
      holds an internal version other than the built one. Image version pins follow.
      The gitignored VM buyer lock needs the same update locally.

## Plan history

The pre-revision plan was replaced during planning. Its tasks map as follows:

- 1.1, 1.3, 1.4: amended to the two-migration expand and contract (1.1, 1.3, 1.4); the
  column is added with no default rather than defaulting existing rows.
- 2.1: amended to sibling `CapacityBinding` and `UnbackedBinding` classes; the
  `admission` field was dropped for the one-name rule.
- 2.5–2.7: kept as 2.7, 2.6–2.9.
- 3.1–3.8: written into the delta specs during planning (3.1–3.8 above).
- 3.5a: superseded by the listing-identity rule and the reconciliation comparison
  (4.6).
- 3.6: restated to its purpose — no storefront-local table sources an unbacked
  listing — and made true by retiring `derived_compute_listings` from publication
  (4.5).
- 4.1a, 4.1b: superseded by the joint per-site generation rule (4.1a) with
  unresolvable pools held rather than failed closed.
- 4.3a: widened to the three enumeration-quantity cases (4.3a).
- 4.2, 4.3: amended — deriving unbacked candidates through the existing path and
  keeping them out of availability reconciliation are realized as the declared and
  available slice ranges (4.2), with unresolvable pools held (4.3).
- 5.2: amended — republication happens through the loop's refresh.
- 6.11: decided not to add; see its note.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Backing is declared, never inferred, and is independent of cardinality and settlement mechanism | `docs/development/ARCHITECTURE.md` — "Storefront capacity boundary" |
| A listing's origin site is not its admission authority; the binding carries both separately | `openspec/specs/storefront-publication/spec.md` |
| Pool advertise-authorization is separate from execute-authorization | `openspec/specs/storefront-publication/spec.md` |
| Site-pinned routing and capacity-availability reconciliation are capacity-backed requirements; source-publication reconciliation applies to all listings | `openspec/specs/storefront-publication/spec.md` |
| An unbacked listing is derived only from the site projection | `openspec/specs/storefront-publication/spec.md` |
| Backing transitions are close-and-republish, not in-place | `openspec/specs/storefront-publication/spec.md` |
| A listing's identity is the physical resource it offers; terms of sale change in place; a listing commits only to the fields it publishes | `openspec/specs/storefront-publication/spec.md`; rationale in `openspec/specs/storefront-publication/architecture.md` |
| Projected pool declarations are judged jointly per site generation; unresolvable pools are held | `openspec/specs/storefront-publication/spec.md` |
| Claim construction describes what happens when capacity admission is requested | `openspec/specs/site-capacity/spec.md` |
| A published shape comes from its source declaration; a declaration with no enumeration quantity yields no listing | `openspec/specs/storefront-publication/spec.md` |
| A listing derived from the resource-pool projection advertises only a mode its pool declares advertisable, backed or not; bare metal is outside it until `bare-metal-publication-reads-pool-declarations` | `openspec/specs/storefront-publication/spec.md` |
| The seller's inventory guard rechecks a listing against a fresh derivation of its own source, and checks availability only for backed listings | `openspec/specs/storefront-publication/spec.md` |
| The common listing binding is the only VM listing mapping | `openspec/specs/storefront-publication/spec.md` |
| An unbacked listing publishes only settlement options its domain does not fulfil through capacity | `openspec/specs/storefront-publication/spec.md` |
| Publication runs as a controllable storefront lifecycle loop | `openspec/specs/storefront-publication/spec.md`; controls in `docs/development/TESTING.md`; rationale in `openspec/specs/storefront-publication/architecture.md` |
| Terms come only from durable sources | `openspec/specs/storefront-publication/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| A seller's close is durable | `openspec/specs/storefront-publication/spec.md` |
| Backing is filtered exactly and fail-on-missing; every compute-family domain publishes it | `openspec/specs/registry-discovery/spec.md` |
| The binding discriminator and closure reason are enforced by trigger; rollback drops those triggers | `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Combined compute-family storefront" |
| Roadmap currency | `docs/development/ROADMAP.md` — Goal 7 |
| Campaign index currency | `openspec/changes/README.md` — Goal 7 row and graph |
