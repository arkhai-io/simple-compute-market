# Tasks — share site projection state

Carved out of `kit-owned-listing-and-fulfillment-lifecycles` on 2026-10-14 as the
prerequisite of `unbacked-bare-metal-listings`. Design reviewed in three rounds; planning
questions P1 and P2 decided 2026-10-15 with the review waived. Depends on nothing open.

Section order follows the layers: the core primitive and the kits first (2–7), then VM
(8–10), bare metal (11–14), the API-credit storefront and the loop controller's last
callers (15), the bare-metal chart (16), and closeout (17). Every section leaves each
end-to-end lane able to run: the bare-metal storefront's configuration and its Compose and
lane files change in one section (11), and its publication timer lands with the scenarios
that hold it (13). The bare-metal chart is non-functional from Section 11 until Section 16,
which the owner accepted; its render tests keep passing in between because they read only
the chart.

All paths under `domains/vms/storefront/` are VM's storefront, under
`domains/bare_metal/storefront/` bare metal's, and under `domains/apicredits/storefront/`
the API-credit storefront's; `src/` abbreviates each package's source root
(`market_storefront`, `arkhai_bare_metal_storefront`, `apicredits_storefront`).

## 1. Design

- [x] 1.1 **Decision gate.** Record the carve-out and its direction. Decided with the
      maintainer: bare metal shares VM's projection state and publication loop through
      the kit, as a prerequisite change, rather than adding a version watch to bare
      metal's publication ("A prerequisite, carved out of the kit lifecycle change";
      "Bare metal publishes on the same loop controller as VM").
- [x] 1.2 **Decision gate.** Decide each open question in `design.md` and record the
      decision there. Decided with the maintainer through three design reviews: D0–D6,
      D14 (D14a–d), and C1–C12; `design.md`'s open questions are none.
- [x] 1.3 Plan the implementation, naming the files each decision touches, the
      focused, integration, and end-to-end suites, and the permanent documentation
      destinations. Planned 2026-10-15; P1 and P2 decided on the way (`design.md` D6, C4).

The closeout placeholder that followed 1.3 was replanned as Section 17.

## 2. Per-site projection state in the kit

Delivers `SiteProjectionState` over a primitive that serializes each family's operations
(D2, D3, D4; `market-composition` "Per-site projection state is kit-owned and held once per
process"; `storefront-publication` "Projection-backed listing candidate derivation"). Touches
`core/storefront` and `kit/capacity-publication`; composes into no storefront yet.

- [ ] 2.1 `core/storefront/src/core_storefront/site_projections.py`: `ProjectionCache` runs
      `poll_once`, `refresh`, and `refresh_after_topology_error` under one per-cache lock,
      the version check included. A caller arriving while an operation runs waits for it
      and returns its result rather than polling again, and a failed operation never
      replaces a `loaded` view or a `fetched_at` that a later-started operation already
      confirmed (D2, 03 F3). Keep the `validate` hook and every state transition as they
      are. Tests in `core/storefront/tests/unit/test_site_projections.py` (unit): a poll
      and a refresh started together run once each in order; a failing version check that
      began before a successful refresh completed leaves the view `loaded` with the later
      `fetched_at`; the existing coalescing test still passes.
- [ ] 2.2 `kit/capacity-publication/src/market_capacity_publication/site_projections.py`
      (new): `SiteProjectionState` with the interface `design.md` D2 records, over a
      `core_storefront.aggregation.AggregateCapacityClient`. Move VM's
      `_RemoteProjectionClient` (`domains/vms/storefront/src/services/site_projection_cache.py`)
      here as the per-family client. The constructor builds a resource-pool and a
      capacity-bucket `ProjectionCache` for every site the aggregate names, installs each
      site's topology-error handler, and takes `on_resource_pool_change`. `values(family)`,
      `view(site_id, family)`, `status()` (as `core_storefront.models.system_models.ProjectionFamilyStatus`),
      `poll_once()` (first load included), `refresh_site(site_id, *, families=None)`, and
      `run(*, interval, gate, wait)`. An unconfigured site raises `CapacityBindingError`;
      an unknown family raises `ValueError`; `refresh_site` never raises for a failed
      fetch. Export `RESOURCE_POOL` and `CAPACITY_BUCKET` and the class from `__init__.py`.
- [ ] 2.3 Same module: the refresh categories of D4. `poll_once` and the topology drift
      check (one coalesced check of every family of the site, never retrying the request)
      call `on_resource_pool_change` when a resource-pool identity changed;
      `refresh_site` never does. A failed operation in any category keeps the site's last
      generation `stale` with its error and does not advance its confirmation.
- [ ] 2.4 Same module: `freshly_confirmed(view, *, now, window_seconds)`, the source-check
      rule both domains apply (D5): `loaded`, a `fetched_at`, and an age within the window.
      The window itself is each storefront's configuration, resolved in Sections 9 and 13.
- [ ] 2.5 Tests in `kit/capacity-publication/tests/unit/test_site_projection_state.py`
      (new, unit, over a fake aggregate injected through the constructor): both families
      loaded per site; `values` omits a site holding nothing and maps a loaded empty site to
      `[]`; a failed poll keeps the last generation `stale` and omits nothing from
      `values`; `poll_once` wakes on a resource-pool change only; `refresh_site` never
      wakes; a topology error checks both families once and wakes on a resource-pool change;
      unknown site and family errors; `freshly_confirmed` at, inside, and past the window,
      and for each non-`loaded` state.
- [ ] 2.6 `kit/capacity-publication/pyproject.toml`: bump the version; pin the
      `arkhai-core-storefront` release carrying 2.1. Refresh the locks the repository's
      tooling names (`make lock`).
- [ ] 2.7 Validation: `make test-core`, `make -C kit test-capacity-publication`,
      `make check-architecture`, `make check-packaging`, `make test`.
      End-to-end: none; nothing composes the state until Section 8.

## 3. The loop controller is the one place a cycle runs

Delivers `run_cycle` as the single cycle boundary with outcome recording and a snapshot
(D6; `market-composition` "A loop records each cycle's outcome with the controller").
Touches `kit/storefront` and `kit/capacity-publication`. The existing `start_loop` and
step-only `register_step` stay until Section 15 removes them, once every storefront has
moved.

- [ ] 3.1 `kit/storefront/src/market_storefront_kit/lifecycle.py`: `register_loop(name, *,
      step, interval_seconds, route=None, preview=None, wake=None)` registers a loop's step
      and interval; the controller starts its timer, a gate, `run_cycle`, `idle` loop over
      the same operation. `run_cycle(name)` holds that loop's lock, runs the step, and
      records exactly one terminal outcome in a `finally`; a held loop runs no timer cycle,
      so a step while held never waits on one. `dry_run` takes no lock and records nothing.
- [ ] 3.2 Same module: outcome recording. Each outcome carries when the cycle finished,
      whether it completed, and for a failure the stage (`compose`, `run`, or `converge`)
      and the error. The step names its current stage through an operation the controller
      gives it. The controller takes, at construction, the exception types whose messages
      may be shown — each storefront's own configuration and publication errors — and
      records any other exception by type only; the full exception is logged.
- [ ] 3.3 Same module: `snapshot()` returning every loop's state and last outcome; an
      `exited` or `cancelled` loop stays distinct from a `running` one whose last cycle
      failed. Export the outcome and snapshot types from `__init__.py`.
- [ ] 3.4 `kit/capacity-publication/src/market_capacity_publication/capacity.py` and
      `capacity_remote.py`: each per-site capacity-event cursor has its own lock, taken by
      that site's poller cycle and by the capacity-events step for that site, the one
      exception in shape D6 names (`market-composition`: "A kit runtime that fans one loop
      out into independent per-site cycles MUST serialize each site's cycle").
- [ ] 3.5 Tests (unit). `kit/storefront/tests/unit/test_lifecycle_controller.py`: a step
      requested during a timer cycle runs after it, never alongside, each recording its
      own outcome; a raising step records one failed outcome naming its stage; a
      non-disclosed exception's message is absent from the outcome; a preview records
      nothing; a held loop runs no timer cycle and a step while held completes at once;
      the snapshot distinguishes an exited loop from a failing one; a pause still lands
      within the quiescence bound with a long interval and the real loop body.
      `kit/capacity-publication/tests/unit/test_capacity_event_pollers.py`: a site's step
      waits for that site's running poll and not for another site's.
- [ ] 3.6 Bump both packages' versions and refresh the locks. Validation:
      `make -C kit test-storefront test-capacity-publication`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: none until a storefront registers
      a loop this way (Sections 9, 13, 15).

## 4. Site trust from the site's service peer

Delivers response verification against a provider of a site's active principals, and the
shared resolution of a site's service peer (D14b; `storefront-publication` "Site authority
principals rotate with bounded overlap"). Touches `kit/site-client`,
`provisioning/compute/client`, and `core/storefront`; composes into no storefront yet.

- [ ] 4.1 `kit/site-client/src/market_site_client/client.py`: `_AuthenticatedSiteClient`
      and both public clients accept, in place of a fixed `TrustedIdentitySet`, a provider
      read at each response's verification. A fixed set remains accepted as a constant
      provider, so callers that pin one (registries, tests) are unchanged.
- [ ] 4.2 `provisioning/compute/client/src/compute_provisioning_client/base.py` and
      `client.py`: the same, because bare metal's per-site provisioning client verifies the
      same site authority's responses.
- [ ] 4.3 `core/storefront/src/core_storefront/identity_authority.py` (or a sibling module
      it owns): the resolution VM performs in
      `domains/vms/storefront/src/middleware/service_peer_auth.py`'s
      `_allowed_service_principals` and `initialize_service_peer_identities` moves here, so
      both compute storefronts share it: seeding configured service peers into durable
      state, refusing a site bound to no peer or to more than one, and a site's currently
      active principals (`active_principals(now)`) for both response verification and
      callbacks. VM's middleware calls it; its behavior is unchanged.
- [ ] 4.4 Tests (unit). `kit/site-client/tests/unit/test_client.py`: a provider is read per
      response, so a rotation that ends its overlap is honored without rebuilding the
      client; the existing fixed-set tests pass unchanged. The provisioning client's unit
      suite: the same. `core/storefront/tests/unit/test_identity_authority.py`: peer
      seeding, the no-peer and two-peer refusals, and active principals through a rotation.
      VM's `tests/unit/test_service_peer_identity.py` passes unchanged.
- [ ] 4.5 Bump the three packages' versions and refresh the locks. Validation:
      `make -C kit test-site-client`, `make test-compute-provisioning-client`,
      `make test-core`, `make test-storefront`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: none until Sections 10 and 12.

## 5. The values-schema generator in `kit/config`

Delivers the generic generator in `kit/config`, VM keeping only its section list (D14c).
Touches `kit/config`, VM's storefront, and the root `Makefile`.

- [ ] 5.1 `kit/config/src/market_config/values_schema.py` (new): the generic parts of
      `domains/vms/storefront/src/values_schema.py` — field publicizing, secret refusal,
      sink typing over sink models passed in (so `kit/config` takes no `kit/delivery`
      dependency), rendering, the drift check, and the `write`/`check` entry — plus the
      refusal of a retired key in a storefront's `config`, which C4 needs.
- [ ] 5.2 `domains/vms/storefront/src/values_schema.py`: reduced to VM's section list, its
      discovered sinks, its settlement registry, and the schema files it writes (its own
      chart and the umbrella's storefront definition). The root `Makefile`'s
      `helm-values-schema` keeps its target and output.
- [ ] 5.3 Tests. `kit/config/tests/unit/test_values_schema.py` (new, unit): publicizing,
      secret refusal, sink typing, retired-key refusal, and drift detection over a small
      model set. VM's `tests/unit/test_values_schema.py` passes with the committed schemas
      unchanged, proving the move regenerates the same definition.
- [ ] 5.4 Bump `kit/config`'s version, declare it where VM imports it, refresh the locks.
      Validation: `make -C kit test-config`, `make test-storefront`,
      `make helm-values-schema` with no diff, `make -C helm test-render`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end: none.

## 6. Alkahest release conditions derived by the mechanism

Delivers listing `demands` derived by `kit/alkahest` for every domain, with each domain
declaring its release models (D14d; `storefront-publication` "An Alkahest listing advertises
its release conditions"). Touches `kit/alkahest`, VM's and bare metal's storefronts. Bare
metal still reads its settlement configuration from its present source; Section 11 changes
the source, not the derivation.

- [ ] 6.1 `kit/alkahest/src/market_alkahest/` (a new `release_conditions.py`, exported):
      the derivation now in `domains/vms/storefront/src/services/publication_terms.py`
      (`_recipient_demands_for_chains`, `_heartbeat_oracle_demands_for_chains`,
      `_splitter_demands_for_chains`, `_demands_for_chains`), taking the
      `[Settlement.alkahest]` policy, the seller wallet, and each chain's address book, and
      returning one release condition per chain. It is built with the Alkahest publication
      option (`settlement_config.py`'s `alkahest_option_builder` or the registration), so
      every domain composing Alkahest gets it.
- [ ] 6.2 Release-model declaration: a domain's Alkahest seller stage declares the models it
      can deliver (`recipient`, `oracle_gated`, `interruptible`); composition refuses a
      configured model the domain does not declare, naming it. VM declares all three
      (`src/settlement_stages.py`'s `VmAlkahestSellerStage`); bare metal declares `recipient`
      and `oracle_gated` (`src/settlement_stages.py`, `src/settlement_composition.py`).
- [ ] 6.3 VM: `publication_terms.py` reads the kit's derivation and keeps no derivation of
      its own; `demands_for_publication_clauses` and its caller in
      `services/publication_loop.py` are unchanged in output.
- [ ] 6.4 Bare metal: `src/publication_composition.py` takes the kit's derivation and stops
      reading `BARE_METAL_STOREFRONT_DEMANDS`; remove it from `compose.bare-metal.yml` and
      `tests/test_publication_cli.py`. Startup refuses `interruptible` (spec scenario "A
      domain is configured for a release model it cannot deliver").
- [ ] 6.5 Tests. `kit/alkahest/tests/unit/test_release_conditions.py` (new, unit): each
      model's condition per chain, the oracle-gated wallet-as-oracle refusal, the
      mutual-exclusion refusal, and the undeclared-model refusal. VM's
      `tests/unit/test_heartbeat_gated_listings.py` moves its derivation cases to the kit
      and keeps the composition cases. Bare metal (application integration, through the
      typed client): `tests/test_publication_cycle.py` — a listing with an Alkahest option
      advertises the recipient arbiter paying the seller wallet on its chain;
      `tests/test_app_composition.py` — startup refuses `interruptible`.
- [ ] 6.6 Bump versions and refresh locks. Validation: `make -C kit test-alkahest`,
      `make test-storefront`, `make test-bare-metal`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: `e2e_deal`, `e2e_non_erc20_settlement`
      (VM lane), and `e2e_bare_metal_mock_deal` (bare-metal lane, whose listing now
      advertises its condition).

## 7. The release-condition invariant holds without seller policy

Delivers correction 9's fix: plan materialization uses exactly the authorized condition and
fails closed, and the escrow-shape guard fails closed (D14d; `negotiation-protocol` "An
Alkahest obligation uses exactly the release condition its listing authorizes"). Touches
`kit/alkahest`, `kit/policy`, and both domains' tests.

- [ ] 7.1 Reproduce first: write these tests and run them against the unfixed code before
      7.2, recording the failing run in the task note (the section commits them passing):
      through each domain's seller
      negotiation runtime and plan materialization, a buyer naming the listing's arbiter
      with a substituted recipient, with no escrow-shape guard configured, reaches a
      materialized plan using the buyer's condition; a listing authorizing no condition
      accepts the buyer's; a proposal naming no escrow address skips the guard. VM:
      `tests/integration/test_negotiate_controller.py` (application integration, typed
      client). Bare metal: `tests/test_http_negotiation.py` (application integration,
      typed client). Kit: `kit/alkahest/tests/unit/test_plans.py`.
- [ ] 7.2 `kit/alkahest/src/market_alkahest/alkahest.py`
      (`materialize_escrow_terms_from_proposal`) and `proposals.py`
      (`escrow_proposal_from_accepted_entry`, `validate_selected_escrow_plan`,
      `accepted_escrow_artifacts_from_proposal`): a selected condition must equal one the
      listing authorizes for its chain, arbiter and demand data both; with no selection
      the listing's authorized condition is used; a missing or unreadable authorized
      condition refuses before any obligation is accepted; the recipient-arbiter fallback
      to the buyer's recipient goes. The domains' plan builders
      (`domains/bare_metal/storefront/src/settlement.py`, VM's settlement stages) reach it
      unchanged in signature.
- [ ] 7.3 `kit/policy/src/market_policy/scalar_policies.py`'s `escrow_shape_guard` (and
      `accept_exact_listing`'s same pattern): a listing advertising no condition for the
      proposal's chain rejects with its own reason instead of skipping the check.
- [ ] 7.4 Tests. The 7.1 reproductions now refuse, with no obligation accepted.
      `kit/policy/tests/unit/test_escrow_shape_guard.py` (new, unit): the guard's
      fail-closed and matching cases. VM's `tests/unit/test_escrow_fields_policy.py` and
      bare metal's `tests/test_negotiation.py` updated where they relied on the skip.
- [ ] 7.5 Bump versions and refresh locks. Validation: `make -C kit test-alkahest
      test-policy`, `make test-storefront`, `make test-bare-metal`, `make test-vms-buyer`
      (the buyer's `validate_selected_escrow_plan` caller), `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: `e2e_deal`, `e2e_deal_buyer_cli`,
      `e2e_non_erc20_settlement`, `e2e_bare_metal_mock_deal`.

## 8. VM composes the shared projection state

Delivers VM on one injected `SiteProjectionState` (D2, D3, D4, C2, C7; corrections 3 and 7;
`storefront-publication` "Projection-backed listing candidate derivation"). Touches VM's
storefront only. The largest section by file count: about ten production modules and
fifteen test files, mechanically.

- [ ] 8.1 Composition: `src/server.py` builds the state once over the capacity runtime's
      aggregate client, with `wake_publication_loop` as `on_resource_pool_change`;
      `src/container.py` holds it; `src/startup.py`'s `_load_site_projections` calls
      `poll_once()`. The poller registers as the `site_projection_poller` loop on the
      controller with `register_loop`, interval `[capacity].poll_interval`, replacing
      `site_projection_poller_loop`.
- [ ] 8.2 Consumers take the injected state, never a module: `services/capacity_client.py`
      (`site_pool_projection`, `site_capacity_buckets`, `_reconcile`),
      `services/listing_sources.py`, `services/listing_source_check.py`,
      `services/publication_loop.py`, `negotiation_runtime.py`
      (`lookup_pool_policy_tags`), `failure_actions.py`, `services/system_service.py`
      (projection status from `status()`), `server.py` (`PoolOverrideService`'s
      `projection_source` reads `values(RESOURCE_POOL)` and `refresh_site` calls
      `refresh_site(site_id)`), and `controllers/admin_controller.py`.
- [ ] 8.3 Refresh categories (D4, C7): inline reconciliation in `admin_controller.py`
      (`_close_oversized_compute_listings`, `_reopen_available_compute_listings`) and
      `failure_actions.py` (`_release_capacity`) calls `refresh_site` and never wakes; the
      admin route `POST /api/v1/admin/capacity/projections/refresh` runs `poll_once()` and
      returns `status()`, whether or not the loops are held, keeping its wire contract (D3);
      the override service's wake stays as it is.
- [ ] 8.4 `lifecycle_steps.py`: the `site-projections` step runs `poll_once()` and returns
      `status()` (C2).
- [ ] 8.5 `services/site_projection_cache.py` reduced to
      `listing_cardinality_mode_explanations`, reading the state it is given; `_caches`,
      the loaders, the poller, the refresh functions, and the unused
      `refresh_after_topology_error` go. Rename the module if only explanations remain, and
      fix the docstring in `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`
      that names it.
- [ ] 8.6 Tests build their own state over `tests/fake_site.py`'s fake aggregate and inject
      it through the container, never patching a module (`TESTING.md` "Mocking
      convention"): `tests/unit/services/test_site_projection_cache.py`,
      `tests/unit/test_listing_source_check.py`, `tests/unit/test_publications_wiring.py`,
      `tests/unit/test_remote_capacity_client.py`, `tests/unit/test_sync_negotiation_hold_cap.py`,
      `tests/unit/test_loop_gate_wiring.py`, `tests/unit/test_lifecycle_advance_routes.py`,
      `tests/unit/services/test_system_service.py`, `tests/integration/test_admin_api.py`,
      `tests/integration/test_negotiate_controller.py`,
      `tests/integration/test_abandon_truncation.py`, `tests/integration/test_listings_api.py`,
      `tests/integration/test_pool_overrides_api.py`, and the helpers
      `tests/publication_app.py` and `tests/fake_site.py`. New application-integration
      cases, through the typed client: the admin refresh with one site unreachable keeps
      that site's generation `stale` and wakes publication on another site's change, held
      and not held (spec scenario "An operator refreshes every site during an outage");
      a topology-sensitive refusal checks both families once and does not retry ("A
      refused reservation reveals drift"); stepping `site-projections` while held runs the
      poller's cycle ("The projection step is run while held").
- [ ] 8.7 Validation: `make test-storefront`, `make test-vms-domain`, `make test`.
      End-to-end (VM lane): `e2e_deal`, `e2e_deal_buyer_cli`, `multi_registry` (which
      calls the admin refresh), `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
      `e2e_pool_declared_modes`, `e2e_vm_introduction`.

## 9. VM loops on the cycle boundary, freshness, and lifecycle status

Delivers VM's loops on `run_cycle`, the confirmation window for source checks, and the
`lifecycle` status section (D5, D6; `storefront-publication` "The seller's inventory guard
checks a listing against its own source", "Operator-visible acceptance and projection
state"; `market-composition` "A loop records each cycle's outcome with the controller").
Touches VM's storefront, `core/storefront`'s status model, and the VM lane's configuration.

- [ ] 9.1 `src/lifecycle.py` and `src/lifecycle_steps.py`: every VM loop —
      `negotiation_watchdog`, `settlement_servicing`, `fulfillment_resume`, `publication`,
      `introduction_retention`, and the site-projection poller from Section 8 — registers
      its step and interval with `register_loop`; `startup.py` starts none of them as a
      self-gating task. The per-site capacity-event pollers keep their fan-out with the
      per-site lock from 3.4. Publication's cycle (`services/publication_loop.py`) names
      its stages `compose`, `run`, `converge`, and VM's configuration and publication
      errors are the controller's disclosed types.
- [ ] 9.2 Freshness (D5): `services/listing_source_check.py` confirms a listing only when
      every family it reads — resource pools, and the capacity buckets its fungible
      availability uses — is `freshly_confirmed` within `[capacity].source_confirmation_seconds`,
      defaulting to three times `[capacity].poll_interval` when not stated; any other
      condition is `unverifiable` (retryable). Document the key, commented with its default,
      in `src/settings.toml`.
- [ ] 9.3 The VM lane's overlays (`storefront.bob.toml`, `storefront.alice.toml`) widen
      `source_confirmation_seconds` to cover a held scenario's run, with a comment saying
      why, so a scenario that holds the loops and negotiates without stepping
      `site-projections` is not refused.
- [ ] 9.4 Status: `core/storefront/src/core_storefront/models/system_models.py`'s
      `HealthResponse` gains `lifecycle` (each loop's state and last outcome, from the
      controller's snapshot), and `services/system_service.py` fills it. Additive on the
      wire.
- [ ] 9.5 Tests. Unit: `tests/unit/test_listing_source_check.py` — a loaded generation past
      the window, a stale bucket family beside a fresh resource-pool family, and the
      default window from `poll_interval`. Application integration, through the typed
      client: `tests/integration/test_negotiate_controller.py` — with the loops held past
      the window a round is refused as retryable and succeeds after stepping
      `site-projections` (spec scenario "The loops are held past the confirmation window"),
      and an unbacked listing's stale site refuses ("An unbacked listing's site is
      stale"); a status test — a failing publication cycle stepped and timer-run is
      reported failed with its stage, and a loop's state is reported ("Publication fails
      every cycle", "A stepped cycle fails"). `tests/unit/test_loop_gate_wiring.py` and
      `tests/unit/test_lifecycle_advance_routes.py` updated to the registered loops.
- [ ] 9.6 Validation: `make test-storefront`, `make test-core`, `make test`.
      End-to-end (VM lane): `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`,
      `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `e2e_vm_introduction`.

## 10. VM startup refusal, per-site trust, and the interval key

Delivers VM's refusal to start without publication, its per-site service-peer trust, and
`settlement_servicing_interval_seconds` (D6, D14b, C4; `storefront-publication` "A storefront
that cannot publish refuses to start", "Site authority principals rotate with bounded
overlap"). Touches VM's storefront, its chart's generated schema, and the VM lane's
configuration.

- [ ] 10.1 Startup refusal (`src/startup.py` or a composition-time check beside it): no
      registry, or a registry without its authority pin while `enable_registry_discovery`
      is true; no enabled settlement mechanism; a configured site with no service peer or
      more than one (through 4.3). Each problem is named, and no loop starts. An empty
      `[pricing].settlements` is not a refusal.
- [ ] 10.2 Per-site trust: `services/capacity_client.py`'s `build_capacity_runtime_for`
      gives each site's `CapacitySite` the provider of that site's peer's active
      principals (4.1, 4.3) instead of the shared `[provisioning.identity]` set, and the
      runtime's cache key stops carrying principals. `[provisioning.identity]` remains
      only for `build_fulfillment_client` and `services/fulfillment_service.py`.
- [ ] 10.3 Interval key (C4): `src/settings.toml`, `src/settlement_composition.py`,
      `src/startup.py`, and the lane overlays use `settlement_servicing_interval_seconds`; a
      configuration stating `claims_sweep_interval` refuses startup naming its replacement;
      VM's section list marks the key retired and `make helm-values-schema` regenerates
      both schemas, so an agent's `config` stating it is refused at render.
- [ ] 10.4 The VM lane's overlays declare every site's service peer if any does not yet,
      so the lane starts under 10.1.
- [ ] 10.5 Tests. Unit: `tests/unit/test_config_loader.py` — the retired key's refusal.
      Application integration, through the typed client: startup refusals named per
      problem with no loop started; the empty-settlements storefront starts and publishes
      a pool whose override states clauses ("A storefront's terms live in its pools"); a
      site's responses verify against its peer's principals and, after the admin rotation
      routes complete a rotation and its overlap ends, only against the replacement,
      without a restart ("A site's responses follow its rotation"); a principal of one
      site does not verify another's responses. `helm/charts/storefront/tests/test_render.py`
      — `claims_sweep_interval` in an agent's `config` is refused naming the key.
- [ ] 10.6 Validation: `make test-storefront`, `make -C helm test-render` (with
      `STOREFRONT_PYTHON` for the loader check), `make test`. End-to-end (VM lane): every
      VM scenario, since each starts the storefront; and the storefront smoke tests.

## 11. Bare-metal configuration through files

Delivers bare metal on `storefront.toml`, `storefront.json`, and `storefront.secrets.toml`
under VM's keys, with Compose and the lane mounting files (D14, D14a, C4, C9, C10, C11;
`deployment-state` "Independently deployable bare-metal seller role", "A storefront's
configuration reaches it through its configuration system"; `storefront-publication` "A
storefront that cannot publish refuses to start"). Touches bare metal's storefront, the
Compose files, the root `Makefile`, `e2e-tests/`, and `scripts/tests/`. Large: every
environment read changes in one commit so the lane never runs half-converted.

- [ ] 11.1 `src/settings.toml` (new, packaged): defaults under VM's keys and defaults —
      `[Identity]`, `[Settlement]`, `[registry]`, `[capacity]` (`poll_interval = 5`,
      `publication_interval_seconds = 30`), `[pricing]`, `[negotiation]`, `[Delivery]`,
      `[Wallet]`, `[Chains]`, `base_url`, `db_path`, `negotiation_timeout_seconds`,
      `negotiation_watchdog_interval`, `settlement_servicing_interval_seconds`,
      `payment_reconciliation_interval`; and the site list, each site's URL and its service
      peer. `pyproject.toml` packages it and declares `arkhai-kit-config`.
- [ ] 11.2 `src/config.py` (new): the loader over `market_config.storefront_config_files()`
      with the packaged defaults and the loader's documented environment override layer,
      as VM's `utils/config.py` builds it, and typed models for bare metal's sections,
      named for their concepts (D14a). The signing credential stays
      `ARKHAI_IDENTITY_CREDENTIAL` and is never loaded into settings.
- [ ] 11.3 Every environment read moves to configuration, the variables retiring:
      `server.py` (watchdog, timeout, payment-reconciliation interval), `delivery.py`,
      `runtime.py` (chains, wallet key and address, identity, administrators, public URL,
      settlement, sites, placement, database path, negotiation policies, registry,
      servicing interval), `publication_service.py` (registry), `publication_composition.py`
      (publication clauses; it no longer receives `os.environ`), `pool_overrides.py`
      (maximum duration as `[pricing].default_max_duration_seconds`), and
      `pool_override_cli.py`. `[Settlement]` replaces the settlement JSON, `[Wallet]` and
      `[Chains.<name>]` and the overlay's wallet key replace their variables, and the
      all-or-none Alkahest input rule keeps its refusal (C11). Bare metal publishes to
      every `[registry].urls` entry (C10).
- [ ] 11.4 C10: a pool whose effective maximum lease duration, through its override and
      then `[pricing].default_max_duration_seconds`, is absent or not positive is held and
      reported in the cycle's per-site report; the absent default is not a startup refusal.
- [ ] 11.5 Startup refusal (D6), at composition: no `[registry].urls` or a registry without
      its authority pin; no enabled settlement mechanism; no configured site. (The
      one-peer-per-site refusal lands with durable trust in Section 12.) Each problem named,
      no loop started.
- [ ] 11.6 CLIs: `pool-override` and `publish` read the storefront's URL and identity from
      the same configuration files; `publish` still runs in-process until Section 14.
- [ ] 11.7 Development and lane files (C9): a committed development `storefront.toml` for
      bare metal (`domains/bare_metal/storefront/storefront.dev.toml`, fixture values
      commented as such) with shortened intervals as VM's overlays have, and a secrets file
      the lane writes; `domains/bare_metal/compose.yml`, `compose.bare-metal.yml`, and
      `compose.bare-metal-local.yml` mount them at `/etc/arkhai/` with `XDG_CONFIG_HOME=/etc`
      and pass only the credential through the environment; the root `Makefile`'s
      `e2e-bare-metal-dev-env` produces only bare-metal files and the variables the
      Compose files still read; `e2e-tests/Makefile` and `e2e-tests/config/config-docker.yml`
      follow.
- [ ] 11.8 Tests. `tests/test_runtime_environment.py` becomes `tests/test_config_loader.py`
      (unit): defaults, file layering, the overlay winning, an override through the
      loader's environment layer applying and never refusing (spec scenario "An operator
      overrides a setting on a development cluster"), and the credential never in
      settings. Application integration: `tests/test_app_composition.py` — each startup
      refusal named and no loop started; `tests/test_publication_cycle.py` — a pool with no
      lease bound held and reported while others publish ("A bare-metal pool resolves no
      lease bound"). Every test that set bare-metal variables
      (`test_introduction_delivery.py`, `test_publication_cli.py`, `test_pool_override_cli.py`,
      `test_app_composition.py`) writes configuration files into a temporary
      `XDG_CONFIG_HOME` instead. `scripts/tests/test_bare_metal_compose.py` and
      `scripts/tests/test_lane_compose.py`: the storefront's environment carries only the
      credential and the configuration directory.
- [ ] 11.9 Refresh the locks. Validation: `make test-bare-metal`, `make test-e2e-unit`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end
      (bare-metal lane): `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_introduction`.

## 12. Bare-metal durable site trust

Delivers bare metal's sites bound to durable service peers whose active principals verify
responses and callbacks, and reservations that survive a rotation (D14b;
`storefront-publication` "Site authority principals rotate with bounded overlap";
`deployment-state` "Independently deployable bare-metal seller role"). Touches bare metal's
storefront and its development configuration.

- [ ] 12.1 Startup seeds each configured site's service peer into core's durable identity
      state through 4.3, refusing a site with no peer or more than one, naming it.
      Administrators stay on configuration.
- [ ] 12.2 `src/site_clients.py`: `BareMetalSiteBinding` carries the site's peer, not a
      principal; `parse_site_bindings` reads the configuration of 11.1;
      `build_trusted_site_clients` gives each site's `SiteCapacityClient` and
      `ComputeProvisioningClient` the provider of that peer's active principals (4.1, 4.2).
- [ ] 12.3 Callbacks: `src/api.py`'s `capacity_released` and the service-role read of
      system status verify against the selected site's peer's active principals, the same
      set its responses verify against.
- [ ] 12.4 Reservations: `bare_metal_selected_site_bindings` pins the site's peer subject;
      the principal it records is an audit record, so `DurableReservationSiteMap` loads
      after an authorized rotation. Written as fresh schema in `src/migrations.py`, with
      no upgrade or backfill, because bare metal has never been deployed outside the
      development cluster; the immutability trigger keeps the binding unchanged.
- [ ] 12.5 Rotation routes: bare metal serves the identity rotation, completion, status,
      and retirement routes VM serves (`core_storefront.identity_lifecycle`), reached
      through `StorefrontClient`'s `admin_initiate_identity_rotation`,
      `admin_complete_identity_rotation`, and `admin_get_identity_status`.
- [ ] 12.6 The development `storefront.toml` and the lane's site configuration declare the
      site's service peer.
- [ ] 12.7 Tests. `tests/test_site_clients.py`:
      `test_selected_site_binding_survives_restart_and_rejects_authority_rotation` becomes a
      restart after an authorized rotation that keeps the reservation bound ("A bare-metal
      storefront restarts after a rotation"); a site with no peer, or two, refuses startup
      ("A site has no service peer"). Application integration, through the typed client:
      a rotation completed through the routes moves both response verification and
      `capacity_released` callbacks to the replacement once the overlap ends;
      `tests/test_deal_controls.py`'s per-site callback checks pass against peers;
      `tests/test_migrations.py` covers the fresh schema.
- [ ] 12.8 Validation: `make test-bare-metal`, `make test`. End-to-end (bare-metal lane):
      `e2e_bare_metal_mock_deal` (its release callback), `e2e_bare_metal_publication`,
      `e2e_bare_metal_introduction`.

## 13. Bare metal on held projections and a publication loop

Delivers bare-metal publication, recheck, and overrides over the shared state, with every
loop on the cycle boundary and the scenarios holding them (D1, D2, D4, D5, D6, C2, C3, C5,
C6, C7; `storefront-publication` "Publication runs as a controllable storefront lifecycle
loop", "A site whose projection is not held holds its listings", "Bare-metal opening
rechecks its listing against its source", "Bare metal joins the site-scoped pool-override
store"). Touches bare metal's storefront and `e2e-tests/`.

- [ ] 13.1 `src/runtime.py`: builds one `SiteProjectionState` over the sites' aggregate
      client with the publication wake as `on_resource_pool_change`, held by the runtime and
      passed to every consumer; startup loads it with `poll_once()`.
- [ ] 13.2 Loops (`src/lifecycle_steps.py`, `src/server.py`): `site_projections` (step:
      `poll_once()` and `status()`, C2) and `publication` (interval
      `[capacity].publication_interval_seconds`, woken by the state) join
      `negotiation_watchdog`, `settlement_servicing`, `payment_reconciliation`, and
      `introduction_retention`, each registered with `register_loop`; `publication_lock`
      goes. Publication names its stages, and bare metal's configuration and publication
      errors are the controller's disclosed types. Each loop catches its failing cycle.
- [ ] 13.3 `src/publication.py`: `_classify_site` reads `values(RESOURCE_POOL)` and runs
      `trusted_bare_metal_projection` on the held value; a site holding nothing is
      `site_projection_unknown`, a refused generation `site_projection_refused`; the cycle
      fetches no site and records no generation.
- [ ] 13.4 `src/listing_source_check.py`: the recheck reads `view(site, RESOURCE_POOL)`,
      requires `freshly_confirmed` within `[capacity].source_confirmation_seconds`
      (default three poll intervals) and an accepted generation, and calls no site (D5).
- [ ] 13.5 Overrides: `src/runtime.py`'s `pool_override_service()` gives
      `PoolOverrideService` `projection_source` over `values(RESOURCE_POOL)`, `refresh_site`
      over the state's `refresh_site`, and the publication wake; the write's live check is
      unchanged. C3: fresh databases stop creating `bare_metal_accepted_site_generations`,
      migration `bare-metal-storefront-0011` stays in the chain with its ID retired, and
      `record_accepted_generation` and `accepted_site_projection` go.
- [ ] 13.6 C5, C7: `health()`'s `site_projections` comes from `status()` for both families
      and calls no site; `capacity_released` and the administrator reserve refresh nothing.
- [ ] 13.7 C6 (`e2e-tests/`): an opt-in per-module fixture holding the bare-metal loops,
      resumed in a finaliser, taken with `pytest.mark.usefixtures` by
      `test_bare_metal_publication.py`, `test_bare_metal_mock_deal.py`, and
      `test_bare_metal_introduction.py` (whose `held_loops` it replaces); each steps
      `site-projections` wherever a site changed before stepping publication. The
      development `storefront.toml` widens `source_confirmation_seconds` for held
      scenarios, as 9.3 does for VM.
- [ ] 13.8 Tests, application integration through the typed client:
      `tests/test_publication_cycle.py` — an unknown site keeps its listings while another
      reconciles, a refused generation holds its site, a new pool publishes on the timer
      without a command, and two consumers read one generation without a site call ("Two
      consumers read one site"); `tests/test_http_system.py` — the startup loop set, the
      held step and preview, `test_concurrent_publication_steps_run_one_after_the_other`
      kept against `run_cycle`, health from held state; a recheck suite — not held,
      stale, expired, and refused generations each refuse as retryable with no site call;
      `tests/test_pool_overrides_api.py` — `test_status_follows_the_generations_publication_accepted`
      becomes status from the held projection, unknown before the first poll and after a
      restart, and an accepted write refreshes the site and wakes publication;
      `tests/test_migrations.py` — a fresh database has no accepted-generation table.
- [ ] 13.9 Validation: `make test-bare-metal`, `make test-e2e-unit`, `make test`.
      End-to-end (bare-metal lane): `e2e_bare_metal_publication`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_introduction`.

## 14. Bare-metal status and the publish command

Delivers the bare-metal `lifecycle` and derivation status and the API-client `publish`
command (D6, C1; `storefront-publication` "Operator-visible acceptance and projection
state", "Publication runs as a controllable storefront lifecycle loop"). Touches bare
metal's storefront.

- [ ] 14.1 `src/models.py`'s `BareMetalHealthResponse` and `src/runtime.py`'s `status()`:
      `lifecycle` from the controller's snapshot, and the latest per-site derivation
      summary — each site's holds and their reasons, a refused generation and a pool held
      for missing terms or an unordered or absent lease bound included — as VM's
      `publication_derivation` reports.
- [ ] 14.2 `src/publication_cli.py` and `src/cli.py`'s `publish`: runs one cycle (or a
      preview) through `StorefrontClient.admin_run_lifecycle_cycle` /
      `admin_dry_run_lifecycle_cycle`, signing as the storefront's identity read from the
      configuration files, and opens no database (C1).
- [ ] 14.3 Tests. Application integration, through the typed client: status reports a
      failing cycle with its stage, a refused generation as loaded with the site's hold
      ("A bare-metal site serves a generation bare metal refuses"), and a held pool's
      reason. `tests/test_publication_cli.py`: the command reaches a running in-process app
      through its client and touches no database ("An operator runs the bare-metal
      publication command", "Publication runs from the command").
- [ ] 14.4 Validation: `make test-bare-metal`, `make test`. End-to-end (bare-metal lane):
      `e2e_bare_metal_publication`; no scenario runs the `publish` command.

## 15. The API-credit storefront's loops, and the controller's one loop form

Delivers P1 and P2: the API-credit storefront's loops on `run_cycle` and its interval key
renamed, then the kit's old loop forms removed (D6, C4). Touches the API-credit storefront
and `kit/storefront`.

- [ ] 15.1 `src/startup.py` and `src/lifecycle_steps.py`: `negotiation_watchdog`,
      `settlement_servicing`, and `payment_reconciliation` register with `register_loop`;
      the per-site capacity-event pollers keep the per-site lock of 3.4.
- [ ] 15.2 `src/settings.toml`, `src/startup.py`, `src/settlement_composition.py`:
      `settlement_servicing_interval_seconds` replaces `claims_sweep_interval`, which
      refuses startup naming its replacement.
- [ ] 15.3 `kit/storefront/src/market_storefront_kit/lifecycle.py`: remove `start_loop` and
      the step-only `register_step` once no caller remains; bump the version.
- [ ] 15.4 Tests. The API-credit storefront's lifecycle and startup suites: the registered
      loop set, the retired key's refusal. `kit/storefront/tests/unit/test_lifecycle_controller.py`:
      the removed forms' tests go.
- [ ] 15.5 Refresh the locks. Validation: `make test-apicredits`, `make -C kit
      test-storefront`, `make test-storefront`, `make test-bare-metal`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end
      (API-credit lane): `e2e_credits_deal`, `e2e_credits_payment_deal`.

## 16. The bare-metal chart on the storefront chart's agent shape

Delivers the bare-metal chart rendering configuration through unchanged under a generated
schema (D14c, C8; `deployment-state` "Independently deployable bare-metal seller role", "A
storefront's configuration reaches it through its configuration system"; `design.md`
"Validation tiers"). Touches `helm/charts/bare-metal-storefront`, the umbrella, the root
`Makefile`, bare metal's storefront, and `helm/scripts/test-render.sh`.

- [ ] 16.1 `src/values_schema.py` (new, bare metal): its section list and sinks over
      `market_config.values_schema`, writing only
      `helm/charts/bare-metal-storefront/values.schema.json`; the root `Makefile`'s
      `helm-values-schema` also runs it. Drift test `tests/test_values_schema.py`, run by
      `make test`.
- [ ] 16.2 `helm/charts/bare-metal-storefront`: `values.yaml` as one agent's keys at the top
      level (`config` rendered unchanged into `storefront.json` in a ConfigMap, the Secret
      overlay mounted as `storefront.secrets.toml`, the credential Secret, the port the
      container, probes, and Service share, persistence), `XDG_CONFIG_HOME`, and only
      release-known derivations (C8); the old values (`siteBindingsSecret`,
      `settlementConfigSecret`, `chains`, `sellerEvmAddress`, `walletKeySecret`,
      `alkahestAddressBook`, `adminPrincipals`, `publicUrl`, `databasePath`) go;
      `templates/deployment.yaml` sets only `XDG_CONFIG_HOME` and
      `ARKHAI_IDENTITY_CREDENTIAL` in the pod environment; `examples/production-values.yaml`
      follows. The umbrella's `bare-metal-storefront` entry keeps deferring to the
      subchart's schema.
- [ ] 16.3 `helm/charts/bare-metal-storefront/tests/test_render.py`: production values
      render the ConfigMap, the overlay, and their mounts together, asserted in one helper;
      the pod environment carries only the configuration directory and the credential
      (spec scenario "The chart renders a storefront's environment"); the schema refuses a
      misspelled or secret key in `config`, naming it; break a mount once to see the test
      fail. Tier 2: load one rendered `storefront.json` with bare metal's own loader through
      an interpreter `BARE_METAL_STOREFRONT_PYTHON` names, which `test-render.sh` sets when
      bare metal's environment exists, skipping otherwise.
- [ ] 16.4 Validation: `make test-bare-metal`, `make helm-values-schema` with no diff,
      `make -C helm test-render` with both loader interpreters set, `make
      test-deployment-packaging`, `make test`. End-to-end: none in the pipeline, which
      deploys no chart.
- [ ] 16.5 Tier 3, in a local session with a cluster: deploy the umbrella with the
      bare-metal storefront enabled from the example values, confirm it starts, reports
      its loops and both projection families in status, and publishes; record the
      evidence or the blocker here. Not runnable in a cloud session.

## 17. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order. It edits
documentation only; a part needing code returns the change to implementation.

- [ ] 17.1 **Comment hygiene.** Confirm `make check-comment-hygiene` passes and that no
      comment the change added names a change, a review, or a migration provenance.
- [ ] 17.2 **Import placement.** Confirm the imports each section added are at module level
      unless a recorded reason keeps one local.
- [ ] 17.3 **Documentation compliance.** Re-check D0–D6, D14a–d, C1–C12, P1, and P2 against
      the placement rules in `openspec/README.md`.
- [ ] 17.4 **Narrative compression.** Shorten Sections 2–16's notes to final behavior,
      material evidence, deferred work, and destinations; move any rationale not yet in
      `design.md` there first.
- [ ] 17.5 **Roadmap currency.** `docs/development/ROADMAP.md`: Goal 4's gap row "VM keeps
      its own per-site projection cache" is closed, and Goal 7's current state says bare
      metal holds projections and publishes on a loop, with unbacked supply still
      `unbacked-bare-metal-listings`'. Name the update in the promotion record.
- [ ] 17.6 **Campaign index currency.** `openspec/changes/README.md`: this change's row
      (status, notes) and the graph line `share-site-projection-state (held projections and
      a publication loop for bare metal) ──► unbacked-bare-metal-listings`; other rows'
      `Depends on` are archive cleanup's. Name it in the promotion record.
- [ ] 17.7 **Packaging.** `make check-packaging` and `make check-architecture-change
      CHANGE=share-site-projection-state`, resolving every failure; the change owns no
      exception row.
- [ ] 17.8 **End-to-end pipeline.** Record a passing run of all three lanes on the closeout
      commit and the scenarios exercising this change: `e2e_deal`, `e2e_deal_buyer_cli`,
      `e2e_buy`, `multi_registry`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
      `e2e_pool_declared_modes`, `e2e_vm_introduction`, `e2e_non_erc20_settlement`,
      `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_introduction`, `e2e_credits_deal`, `e2e_credits_payment_deal`; and
      16.5's chart evidence or its blocker.
- [ ] 17.9 **Promotion.** Write the permanent documents and complete the design-promotion
      record below:
      - `docs/development/ARCHITECTURE.md`: "Capacity publication and multi-domain storefront
        composition" (the kit owns per-site projection state; both compute storefronts
        publish on a loop over it, correcting "VM publication reads the kit's site
        projections"); "Storefront capacity boundary"; "Kit areas" (`kit/config`'s
        values-schema generator, `kit/alkahest`'s release-condition derivation); "Package
        and dependency layers" (a domain's tooling never writes another domain's artifact,
        as guidance no check enforces).
      - `openspec/specs/storefront-publication/architecture.md`: "Projection families",
        "Reconciliation", "Storefront pool overrides", "Unknown sites and inline
        reconciliation", "Autonomous publication", "Trusted site routing", "Role and
        service-peer identity", "Settlement option reconciliation".
      - `openspec/specs/market-composition/architecture.md`: "Storefront composition kit"
        (the kit's projection state and the controller's cycle boundary), "Settlement
        configuration registration" (release models a domain declares).
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`: "Kubernetes: ConfigMap and Secret
        mounting" (the configuration-system invariant beside its pod rule); "Storefront
        agents: pass-through configuration" (`settlement_servicing_interval_seconds`, the
        rollback note that an older release ignores it and services at its 30-second
        default, `source_confirmation_seconds`); "Per-domain stack composition"; "Combined
        compute-family storefront"; "Storefront listing shapes and pool overrides" (the
        bare-metal text); "Bare-metal role configuration"; VM's startup refusal and per-site
        trust.
      - `docs/development/TESTING.md`: "Pause the loop, then advance it explicitly" (the
        bare-metal rows, `site-projections` and `publication` among its loops, and the
        API-credit row); "Chart Render Tests" (the generator in `kit/config`, bare metal's
        drift test and loader check).
      - `docs/bare-metal-seller-quickstart.md`: "Configure public bindings", "Start and
        inspect".
      - `openspec/specs/README.md`: no new capability or companion; record that disposition.
      - The `spec.md` files the deltas cover (`storefront-publication`,
        `market-composition`, `deployment-state`, `negotiation-protocol`) are written by the
        archive in 17.11; the record names them.
- [ ] 17.10 **Documentation citations.** `make check-doc-citations
      CHANGE=share-site-projection-state`, resolving every match, then `bunx
      @fission-ai/openspec@1.14.0 validate share-site-projection-state --strict`.
- [ ] 17.11 **Archival.** `bunx @fission-ai/openspec@1.14.0 archive share-site-projection-state
      -y`, merging the four deltas; the index row links the archive.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| | |
