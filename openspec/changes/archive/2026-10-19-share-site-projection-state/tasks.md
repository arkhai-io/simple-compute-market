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

- [x] 2.1 `core/storefront/src/core_storefront/site_projections.py`: `ProjectionCache` runs
      `poll_once`, `refresh`, and `refresh_after_topology_error` under one per-cache lock,
      the version check included. A caller arriving while an operation runs waits for it
      and returns its result rather than polling again, and a failed operation never
      replaces a `loaded` view or a `fetched_at` that a later-started operation already
      confirmed (D2, 03 F3). Keep the `validate` hook and every state transition as they
      are. Tests in `core/storefront/tests/unit/test_site_projections.py` (unit): a poll
      and a refresh started together run once each in order; a failing version check that
      began before a successful refresh completed leaves the view `loaded` with the later
      `fetched_at`; the existing coalescing test still passes.
      Done: every operation runs through one lock; a *poll* (`poll_once`, unforced
      `refresh()`, `refresh_after_topology_error`) joins one in flight and returns its view,
      and a *forced refresh* waits for it and then fetches, because an inline refresh
      reconciles a change its caller has just made (`design.md` D2, amended to say so;
      "Implementation findings"). The coalescing test is renamed
      `test_concurrent_forced_refreshes_never_overlap`. Unit, `make test-core`: ten new
      cases; against the earlier cache five fail and one hangs to its timeout.
- [x] 2.2 `kit/capacity-publication/src/market_capacity_publication/site_projections.py`
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
      Done as planned, `freshly_confirmed` exported too; a client that is not an
      `AggregateCapacityClient` is refused. **Differed:** VM's `_RemoteProjectionClient` was
      copied, not moved; 8.5 removed VM's copy. `run` was later removed with its test (8.5):
      the controller's timer runs the poller.
- [x] 2.3 Same module: the refresh categories of D4. `poll_once` and the topology drift
      check (one coalesced check of every family of the site, never retrying the request)
      call `on_resource_pool_change` when a resource-pool identity changed;
      `refresh_site` never does. A failed operation in any category keeps the site's last
      generation `stale` with its error and does not advance its confirmation.
      Done: `poll_once` and each site's drift check compare every site's resource-pool
      identity before and after and wake on a difference (a first load is a change); the
      drift check runs `refresh_after_topology_error` on both of the site's families.
- [x] 2.4 Same module: `freshly_confirmed(view, *, now, window_seconds)`, the source-check
      rule both domains apply (D5): `loaded`, a `fetched_at`, and an age within the window.
      The window itself is each storefront's configuration, resolved in Sections 9 and 13.
      Done; an age equal to the window still confirms.
- [x] 2.5 Tests in `kit/capacity-publication/tests/unit/test_site_projection_state.py`
      (new, unit, over a fake aggregate injected through the constructor): both families
      loaded per site; `values` omits a site holding nothing and maps a loaded empty site to
      `[]`; a failed poll keeps the last generation `stale` and omits nothing from
      `values`; `poll_once` wakes on a resource-pool change only; `refresh_site` never
      wakes; a topology error checks both families once and wakes on a resource-pool change;
      unknown site and family errors; `freshly_confirmed` at, inside, and past the window,
      and for each non-`loaded` state.
      Done (unit, 22 cases), plus refresh-site family selection, failed refreshes and drift
      checks confirming nothing, status without rows, and the non-aggregate refusal.
- [x] 2.6 `kit/capacity-publication/pyproject.toml`: bump the version; pin the
      `arkhai-core-storefront` release carrying 2.1. Refresh the locks the repository's
      tooling names (`make lock`).
      Done: `arkhai-core-storefront` 0.12.1, `arkhai-kit-capacity-publication` 0.8.0, the
      three storefronts' exact pins following. The PyTorch index is unreachable from the
      implementing sessions, so `domains/vms/storefront/uv.lock` (and later
      `domains/vms/buyer/uv.lock`) were edited by hand to what uv writes, here and at every
      later bump; 16.6 relocked them with no diff.
- [x] 2.7 Validation: `make test-core`, `make -C kit test-capacity-publication`,
      `make check-architecture`, `make check-packaging`, `make test`.
      End-to-end: none; nothing composes the state until Section 8.
      Done. The three PyTorch-index projects (`kit/policy`, `domains/vms/buyer`,
      `domains/vms/storefront`) ran frozen against the rebuilt wheels throughout the change,
      as every later validation task records; every other suite ran under `make -k test`.
      **Correction (end-to-end):** 2.1's change reaches VM's projection-backed scenarios at
      once, through VM's existing cache.

## 3. The loop controller is the one place a cycle runs

Delivers `run_cycle` as the single cycle boundary with outcome recording and a snapshot
(D6; `market-composition` "A loop records each cycle's outcome with the controller").
Touches `kit/storefront` and `kit/capacity-publication`. The existing `start_loop` and
step-only `register_step` stay until Section 15 removes them, once every storefront has
moved.

- [x] 3.1 `kit/storefront/src/market_storefront_kit/lifecycle.py`: `register_loop(name, *,
      step, interval_seconds, route=None, preview=None, wake=None)` registers a loop's step
      and interval; the controller starts its timer, a gate, `run_cycle`, `idle` loop over
      the same operation. `run_cycle(name)` holds that loop's lock, runs the step, and
      records exactly one terminal outcome in a `finally`; a held loop runs no timer cycle,
      so a step while held never waits on one. `dry_run` takes no lock and records nothing.
      Done. **Differed:** `register_loop` registers only and `start_loops()` starts every
      registered timer, since registration happens where no event loop runs; it also takes
      `initial_delay_seconds`. Every step, a step-only loop's included, runs through the
      locked, recorded `run_cycle`. The timer's gate re-read under the lock and its wake
      handling are in `design.md`, "Implementation findings".
- [x] 3.2 Same module: outcome recording. Each outcome carries when the cycle finished,
      whether it completed, and for a failure the stage (`compose`, `run`, or `converge`)
      and the error. The step names its current stage through an operation the controller
      gives it. The controller takes, at construction, the exception types whose messages
      may be shown — each storefront's own configuration and publication errors — and
      records any other exception by type only; the full exception is logged.
      Done: `CycleOutcome(finished_at, trigger, completed, stage, error)` with
      `CycleError(type, message)`; the stage operation is `controller.enter_stage(stage)`;
      the constructor takes `disclosed_errors` and `clock`. A cancelled cycle, and a step
      cancelled while queued (no stage), each record a cancelled outcome ("Implementation
      findings").
- [x] 3.3 Same module: `snapshot()` returning every loop's state and last outcome; an
      `exited` or `cancelled` loop stays distinct from a `running` one whose last cycle
      failed. Export the outcome and snapshot types from `__init__.py`.
      Done: `snapshot()` maps every loop name to `LoopSnapshot(name, state, last_outcome)`;
      `last_outcome(name)` reads one; the types have `to_dict()`.
- [x] 3.4 `kit/capacity-publication/src/market_capacity_publication/capacity.py` and
      `capacity_remote.py`: each per-site capacity-event cursor has its own lock, taken by
      that site's poller cycle and by the capacity-events step for that site, the one
      exception in shape D6 names (`market-composition`: "A kit runtime that fans one loop
      out into independent per-site cycles MUST serialize each site's cycle").
      Done: `SiteEventCursor` carries an `asyncio.Lock`, held by the step for the whole
      cycle; the site poller takes it and re-reads its gate under it; the preview takes
      none.
- [x] 3.5 Tests (unit). `kit/storefront/tests/unit/test_lifecycle_controller.py`: a step
      requested during a timer cycle runs after it, never alongside, each recording its
      own outcome; a raising step records one failed outcome naming its stage; a
      non-disclosed exception's message is absent from the outcome; a preview records
      nothing; a held loop runs no timer cycle and a step while held completes at once;
      the snapshot distinguishes an exited loop from a failing one; a pause still lands
      within the quiescence bound with a long interval and the real loop body.
      `kit/capacity-publication/tests/unit/test_capacity_event_pollers.py`: a site's step
      waits for that site's running poll and not for another site's.
      Done (unit): `make -C kit test-storefront` 31 new cases, through injected seams
      (`cycle_lock_factory`, the controller's logger, timer handles) rather than yields;
      `make -C kit test-capacity-publication` two new over parked fake feeds. Each
      serialization, gate, wake, and cursor rule was shown to fail with its mechanism
      removed. **Also changed:** bare metal's runtime builds its controller from a
      `loop_controller_factory` init field, so
      `test_concurrent_publication_steps_run_one_after_the_other` observes the controller's
      lock.
- [x] 3.6 Bump both packages' versions and refresh the locks. Validation:
      `make -C kit test-storefront test-capacity-publication`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: none until a storefront registers
      a loop this way (Sections 9, 13, 15).
      Done: `arkhai-kit-storefront` 0.4.0, `arkhai-kit-capacity-publication` 0.8.1, pins and
      locks following. **Correction (end-to-end):** every scenario that steps a loop now
      runs through the locked, recorded cycle, and every capacity-event poller through its
      cursor lock.

## 4. Site trust from the site's service peer

Delivers response verification against a provider of a site's active principals, and the
shared resolution of a site's service peer (D14b; `storefront-publication` "Site authority
principals rotate with bounded overlap"). Touches `kit/site-client`,
`provisioning/compute/client`, and `core/storefront`; composes into no storefront yet.

- [x] 4.1 `kit/site-client/src/market_site_client/client.py`: `_AuthenticatedSiteClient`
      and both public clients accept, in place of a fixed `TrustedIdentitySet`, a provider
      read at each response's verification. A fixed set remains accepted as a constant
      provider, so callers that pin one (registries, tests) are unchanged.
      Done: `expected_authorities` is an `AuthorityTrust` (a set or a zero-argument
      provider), read once per response inside verification; a provider that raises or
      returns no set fails that response closed; anything else is a `TypeError` at
      construction.
- [x] 4.2 `provisioning/compute/client/src/compute_provisioning_client/base.py` and
      `client.py`: the same, because bare metal's per-site provisioning client verifies the
      same site authority's responses.
      Done, the same shape in `SigningBase`, failing closed with
      `ComputeProvisioningAuthenticationError`; each client defines its own `AuthorityTrust`
      alias, since the two share no package but `kit/identity`.
- [x] 4.3 `core/storefront/src/core_storefront/identity_authority.py` (or a sibling module
      it owns): the resolution VM performs in
      `domains/vms/storefront/src/middleware/service_peer_auth.py`'s
      `_allowed_service_principals` and `initialize_service_peer_identities` moves here, so
      both compute storefronts share it: seeding configured service peers into durable
      state, refusing a site bound to no peer or to more than one, and a site's currently
      active principals (`active_principals(now)`) for both response verification and
      callbacks. VM's middleware calls it; its behavior is unchanged.
      Done in a sibling module, `core_storefront/service_peers.py`, over a
      `ServicePeerConfigs` mapping each storefront passes in: `seed_service_peers`,
      `require_one_service_peer_per_site` (raising `ServicePeerConfigurationError` naming
      every problem site), and the per-site reads. The SQLite-reading provider was replaced
      by `ServicePeerTrust` in 10.2.
- [x] 4.4 Tests (unit). `kit/site-client/tests/unit/test_client.py`: a provider is read per
      response, so a rotation that ends its overlap is honored without rebuilding the
      client; the existing fixed-set tests pass unchanged. The provisioning client's unit
      suite: the same. `core/storefront/tests/unit/test_identity_authority.py`: peer
      seeding, the no-peer and two-peer refusals, and active principals through a rotation.
      VM's `tests/unit/test_service_peer_identity.py` passes unchanged.
      Done (unit): site client 8 and provisioning client 5 new cases, a provider read per
      response following a rotation (six fail with the provider read once). **Differed
      (level):** the core cases are library integration,
      `core/storefront/tests/integration/test_service_peers.py`, since they run against real
      SQLite (`TESTING.md`).
- [x] 4.5 Bump the three packages' versions and refresh the locks. Validation:
      `make -C kit test-site-client`, `make test-compute-provisioning-client`,
      `make test-core`, `make test-storefront`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: none until Sections 10 and 12.
      Done: `arkhai-kit-site-client` 0.11.0, `arkhai-compute-provisioning-client` 0.7.0,
      `arkhai-core-storefront` 0.13.0; **also** `arkhai-kit-capacity-publication` 0.8.2,
      which pins core exactly. **Correction (end-to-end):** VM's seeding and callback
      resolution run in core from here, for every VM-lane scenario.

## 5. The values-schema generator in `kit/config`

Delivers the generic generator in `kit/config`, VM keeping only its section list (D14c).
Touches `kit/config`, VM's storefront, and the root `Makefile`.

- [x] 5.1 `kit/config/src/market_config/values_schema.py` (new): the generic parts of
      `domains/vms/storefront/src/values_schema.py` — field publicizing, secret refusal,
      sink typing over sink models passed in (so `kit/config` takes no `kit/delivery`
      dependency), rendering, the drift check, and the `write`/`check` entry — plus the
      refusal of a retired key in a storefront's `config`, which C4 needs.
      Done: `market_config.values_schema` (`model_fragment`, `settlement_fragment`,
      `sink_typed_section`, `config_definition(sections, *, retired=())`, `render`,
      `stale_files`, `main`), not re-exported from the package root. A retired key is
      refused in any spelling; one among entries an `additionalProperties` schema types,
      under a combinator, under another retired key, or still on a typed section is refused
      at generation (**corrected (review)**: the first version reopened a webhook's secret
      `url`). **Differed:** `sink_typed_section` takes the sink key and the section's own
      settings from its caller, since `kit/config` may not import `kit/delivery`.
      `settlement_fragment` states `[Settlement]`'s `schema_version` and `priority` itself,
      the settlement runtime exporting no constant for them.
- [x] 5.2 `domains/vms/storefront/src/values_schema.py`: reduced to VM's section list, its
      discovered sinks, its settlement registry, and the schema files it writes (its own
      chart and the umbrella's storefront definition). The root `Makefile`'s
      `helm-values-schema` keeps its target and output.
      Done: VM's module keeps `DEFINITION`, `ROLE`, `SCHEMA_FILES`, `RETIRED_KEYS`, its
      `[Delivery]` settings, and `storefront_config_definition`; `make helm-values-schema`
      passes `--root ../../..`. VM writes the umbrella's `storefront` definition too: that
      subchart is VM's chart, so the schema is VM's artifact (17.9).
- [x] 5.3 Tests. `kit/config/tests/unit/test_values_schema.py` (new, unit): publicizing,
      secret refusal, sink typing, retired-key refusal, and drift detection over a small
      model set. VM's `tests/unit/test_values_schema.py` passes with the committed schemas
      unchanged, proving the move regenerates the same definition.
      Done. Kit (unit, `test_values_schema.py`, 30 cases after review); VM's file keeps the
      cases on its own definition and committed schemas, which regenerate with no diff.
- [x] 5.4 Bump `kit/config`'s version, declare it where VM imports it, refresh the locks.
      Validation: `make -C kit test-config`, `make test-storefront`,
      `make helm-values-schema` with no diff, `make -C helm test-render`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end: none.
      Done: `arkhai-kit-config` 0.3.0; VM declares `>=0.3.0`. End-to-end: none, the
      pipeline's Compose lanes render no chart.

Section 5 handoff, kept for closeout (promoted in 17.9): the generator is in `kit/config`
(pydantic only) with its own unit tests, so only each storefront's section list needs its
environment, which `TESTING.md` says.

Validation environment, every section: this change's implementing sessions could not reach
`download.pytorch.org`, so `kit/policy`, `domains/vms/buyer`, and `domains/vms/storefront`
ran in environments synced frozen from the committed locks with the rebuilt internal wheels
reinstalled (`UV_FROZEN=1`); their hand-edited locks were relocked with no diff in 16.6.

## 6. Alkahest release conditions derived by the mechanism

Delivers listing `demands` derived by `kit/alkahest` for every domain, with each domain
declaring its release models (D14d; `storefront-publication` "An Alkahest listing advertises
its release conditions"). Touches `kit/alkahest` and the VM, bare-metal, and API-credit
storefronts (the API-credit storefront added by 6.7). Bare metal still reads its settlement configuration from its present source; Section 11 changes
the source, not the derivation.

- [x] 6.1 `kit/alkahest/src/market_alkahest/` (a new `release_conditions.py`, exported):
      the derivation now in `domains/vms/storefront/src/services/publication_terms.py`
      (`_recipient_demands_for_chains`, `_heartbeat_oracle_demands_for_chains`,
      `_splitter_demands_for_chains`, `_demands_for_chains`), taking the
      `[Settlement.alkahest]` policy, the seller wallet, and each chain's address book, and
      returning one release condition per chain. It is built with the Alkahest publication
      option (`settlement_config.py`'s `alkahest_option_builder` or the registration), so
      every domain composing Alkahest gets it.
      Done: `market_alkahest.release_conditions` (`release_conditions`,
      `publication_release_conditions`, the release models, `ReleaseModelError`,
      `require_deliverable_release_model`), VM's refusals kept in wording. **Differed:** the
      conditions are one kit function each domain calls where it builds the listing, not an
      option-builder output (`design.md` D14d, as delivered).
- [x] 6.2 Release-model declaration: a domain's Alkahest seller stage declares the models it
      can deliver (`recipient`, `oracle_gated`, `interruptible`); composition refuses a
      configured model the domain does not declare, naming it. VM declares all three
      (`src/settlement_stages.py`'s `VmAlkahestSellerStage`); bare metal declares `recipient`
      and `oracle_gated` (`src/settlement_stages.py`, `src/settlement_composition.py`).
      Done: VM declares all three models, bare metal `recipient` and `oracle_gated` (a new
      `AlkahestStage`); each composition refuses a configured, enabled or disabled,
      undeclared model. **Consequence:** VM refuses a section stating both oracle-gated and
      interruptible at startup. **Amended (review):** VM checks first,
      `require_vm_release_model`, before the database or signer.
- [x] 6.3 VM: `publication_terms.py` reads the kit's derivation and keeps no derivation of
      its own; `demands_for_publication_clauses` and its caller in
      `services/publication_loop.py` are unchanged in output.
      Done: `demands_for_publication_clauses` keeps its signature and output over the kit;
      VM's four derivation functions and its stages' `publication_chains` go.
- [x] 6.4 Bare metal: `src/publication_composition.py` takes the kit's derivation and stops
      reading `BARE_METAL_STOREFRONT_DEMANDS`; remove it from `compose.bare-metal.yml` and
      `tests/test_publication_cli.py`. Startup refuses `interruptible` (spec scenario "A
      domain is configured for a release model it cannot deliver").
      Done: the settlement composition derives the conditions for the Alkahest escrows it
      built; `BARE_METAL_STOREFRONT_DEMANDS` goes. **Differed:** the derivation sits in the
      settlement composition and covers only built options, where VM derives from its
      clauses whatever their readiness.
- [x] 6.5 Tests. `kit/alkahest/tests/unit/test_release_conditions.py` (new, unit): each
      model's condition per chain, the oracle-gated wallet-as-oracle refusal, the
      mutual-exclusion refusal, and the undeclared-model refusal. VM's
      `tests/unit/test_heartbeat_gated_listings.py` moves its derivation cases to the kit
      and keeps the composition cases. Bare metal (application integration, through the
      typed client): `tests/test_publication_cycle.py` — a listing with an Alkahest option
      advertises the recipient arbiter paying the seller wallet on its chain;
      `tests/test_app_composition.py` — startup refuses `interruptible`.
      Done. Kit (unit, 19 cases). VM (application integration, through the typed client): a
      backed pool's listing advertises the recipient arbiter paying the seller. Bare metal:
      the cycle-level case and, **corrected (review)**, application integration
      (`tests/test_http_publication_settlement.py`) through `admin_run_lifecycle_cycle` and
      `get_listing`, each failing with the derivation removed; application startup refuses
      `interruptible` with no storefront installed. VM application startup
      (`tests/integration/test_release_model_startup.py`) refuses both models together with
      no database written.
- [x] 6.6 Bump versions and refresh locks. Validation: `make -C kit test-alkahest`,
      `make test-storefront`, `make test-bare-metal`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: `e2e_deal`, `e2e_non_erc20_settlement`
      (VM lane), and `e2e_bare_metal_mock_deal` (bare-metal lane, whose listing now
      advertises its condition).
      Done: `arkhai-kit-alkahest` 0.5.0; VM's floor `>=0.5.0`, bare metal's stated.
      **Correction (end-to-end):** every VM-lane publishing scenario and the three
      bare-metal scenarios derive their listings' `demands` through the kit; the mock deal's
      escrow is the advertised condition, so it is unchanged.
- [x] 6.7 The API-credit storefront: its Alkahest seller stage declares `{recipient}`, its
      composition refuses any other configured model at startup, and its listings publish
      the kit-derived conditions for the chains of the Alkahest escrows they publish.
      **Plan gap (review):** the plan named VM and bare metal only, though D14d covers every
      domain composing Alkahest, and the API-credit storefront composes it with
      `escrow_shape_guard` among its default seller policies, so Section 7's fail-closed
      rules would otherwise refuse every API-credit Alkahest deal.
      **Plan gap (review):** the plan named VM and bare metal only; the API-credit
      storefront composes Alkahest with `escrow_shape_guard` by default (`design.md`,
      "Implementation findings"). Done: `AlkahestSellerStage.release_models` declares
      `{recipient}`; the composition refuses another model first
      (`require_api_credit_release_model`) and publishes the kit's conditions for the
      accepted escrows that survive the backing filter; the lane's `storefront.credits.toml`
      names the address book and `[wallet].address`. **Behaviour changes:** a
      caller-supplied escrow on an unconfigured chain is refused; an unset wallet publishes
      a recipient condition that every deal refuses (open, `design.md`). The
      publish-from-quota route gains `ApiCreditListingClient`. Application integration
      (`tests/integration/test_alkahest_release_conditions.py`): published from quota
      through the typed client, read by a buyer's `get_listing`, and startup refusing
      `interruptible` with no database written. **Corrected (re-review):** the buyer's
      selection of the demand is evidenced by Section 7's `test_negotiate_cli.py` case and
      `e2e_credits_deal`.

## 7. The release-condition invariant holds without seller policy

Delivers correction 9's fix: plan materialization uses exactly the authorized condition and
fails closed, and the escrow-shape guard fails closed (D14d; `negotiation-protocol` "An
Alkahest obligation uses exactly the release condition its listing authorizes"). Touches
`kit/alkahest`, `kit/policy`, and both domains' tests.

- [x] 7.1 Reproduce first: write these tests and run them against the unfixed code before
      7.2, recording the failing run in the task note (the section commits them passing):
      through each domain's seller
      negotiation runtime and plan materialization, a buyer naming the listing's arbiter
      with a substituted recipient, with no escrow-shape guard configured, reaches a
      materialized plan using the buyer's condition; a listing authorizing no condition
      accepts the buyer's; a proposal naming no escrow address skips the guard. VM:
      `tests/integration/test_negotiate_controller.py` (application integration, typed
      client). Bare metal: `tests/test_http_negotiation.py` (application integration,
      typed client). Kit: `kit/alkahest/tests/unit/test_plans.py`.
      Done, run against the unfixed kit (0.5.0) first. Bare metal (application integration,
      `tests/test_http_negotiation.py`): unfixed, a substituted recipient, a listing
      advertising none, and an unpinned proposal were each accepted paying the buyer's
      recipient -- correction 9 reproduced. **Differed:** VM prepends the shape guard to
      every chain, so "no guard" is an injected seller-round hook; unfixed, VM accepted
      three cases that should refuse, though it never used the buyer's condition. Kit (unit,
      `test_plans.py`): four of five failed unfixed.
- [x] 7.2 `kit/alkahest/src/market_alkahest/alkahest.py`
      (`materialize_escrow_terms_from_proposal`) and `proposals.py`
      (`escrow_proposal_from_accepted_entry`, `validate_selected_escrow_plan`,
      `accepted_escrow_artifacts_from_proposal`): a selected condition must equal one the
      listing authorizes for its chain, arbiter and demand data both; with no selection
      the listing's authorized condition is used; a missing or unreadable authorized
      condition refuses before any obligation is accepted; the recipient-arbiter fallback
      to the buyer's recipient goes. The domains' plan builders
      (`domains/bare_metal/storefront/src/settlement.py`, VM's settlement stages) reach it
      unchanged in signature.
      Done, `arkhai-kit-alkahest` 0.6.0: `ReleaseConditionError`
      (`release_condition_<reason>`), the selected condition only, the recipient fallback
      gone, and `validate_selected_escrow_plan` comparing demand bytes. **Differed:** first
      enforced at each domain's acceptance call site; **amended (7.6):** the owner moved it
      inside the kit's materialization. The empty-wallet case refuses as `_unreadable`
      (open, `design.md`).
- [x] 7.3 `kit/policy/src/market_policy/scalar_policies.py`'s `escrow_shape_guard` (and
      `accept_exact_listing`'s same pattern): a listing advertising no condition for the
      proposal's chain rejects with its own reason instead of skipping the check.
      Done: `release_condition_not_advertised` and
      `exact_listing:release_condition_not_advertised`. **Corrected (review):** the guard
      still passes a proposal with no or the zero escrow address and a listing accepting no
      escrow; `accept_exact_listing` rejects those as before. `kit/policy` keeps 0.4.0
      (`kit/negotiation-runtime` pins it exactly).
- [x] 7.4 Tests. The 7.1 reproductions now refuse, with no obligation accepted.
      `kit/policy/tests/unit/test_escrow_shape_guard.py` (new, unit): the guard's
      fail-closed and matching cases. VM's `tests/unit/test_escrow_fields_policy.py` and
      bare metal's `tests/test_negotiation.py` updated where they relied on the skip.
      Done: the seven reproductions refuse with a `release_condition_*` 409 and nothing
      recorded. Kit (unit) `test_release_authorization.py`, `test_selected_escrow_plan.py`;
      policy (unit) `test_escrow_shape_guard.py`, 17 cases; VM and bare-metal negotiation
      suites carry advertised conditions. API credits: the negotiation runtime over a real
      database, **corrected (review)** from "application integration".
- [x] 7.5 Bump versions and refresh locks. Validation: `make -C kit test-alkahest
      test-policy`, `make test-storefront`, `make test-bare-metal`, `make test-vms-buyer`
      (the buyer's `validate_selected_escrow_plan` caller), `make check-architecture`,
      `make check-packaging`, `make test-apicredits` (the API-credit storefront composes
      Alkahest and runs `escrow_shape_guard` by default), `make test`. End-to-end:
      `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_non_erc20_settlement`,
      `e2e_bare_metal_mock_deal`, and the API-credit lane's `e2e_credits_deal` and
      `e2e_credits_payment_deal`.
      Done: the VM, bare-metal, and API-credit storefronts and the VM buyer require
      `>=0.6.0`. The pipeline was not run for this section.
- [x] 7.6 The release-condition invariant is enforced inside `kit/alkahest`, so no caller can
      skip it (owner decision, 2026-10-16; recorded in `design.md` D14d, with the rejected
      alternative of authorization at each storefront's acceptance boundary). Every kit entry
      point that encodes an obligation's release condition from a proposal takes the listing
      and authorizes the condition itself: a selection must equal a condition the listing
      authorizes for the chain (arbiter and demand data), no selection takes the listing's,
      and a missing or unreadable authorized condition refuses before anything is accepted.
      No public kit entry point encodes a condition from a proposal without authorizing it.
      The plan
      builders' signatures change; every caller in VM, bare metal, the API-credit storefront,
      the VM and API-credit buyers, and the core buyer's orchestration moves to the new shape,
      and the call-site authorization the kit now does goes. Every Section 7 refusal reason,
      HTTP status, and test holds. Bump `arkhai-kit-alkahest` (minor, incompatible API) and
      raise every consumer's floor.
      Done, `arkhai-kit-alkahest` 0.7.0: `market_alkahest.release_authorization` reads what
      a listing authorizes; encoding is private behind
      `encode_authorized_release_condition`; every materializing entry point takes the
      listing (`design.md` D14d, as delivered (Section 7)). **Corrected (review):** the
      public recipient-condition builder became verification's private legacy builder; VM's
      refund reads the accepted plan's obligation and materializes nothing;
      `arkhai-core-buyer` 0.5.0 and `arkhai-vms-settlement` 0.3.0 for their incompatible
      changes. **Differed (judgement):** with no selection the listing's condition is used
      rather than refused; the three buyer resume paths refuse a run-log holding only an
      accepted proposal (`escrow_release_condition_missing`, exit 3). Evidence: kit unit 41
      new cases calling each materializer directly; every consumer's suite on the final
      wheels.
- [x] 7.7 **(04 F1)** An exact settlement selection of a mechanism the composed registry
      builds no accepted obligation for is accepted without a settlement plan only when
      that mechanism settles from the accepted Agreement alone (Arkhai payments). Any other
      — Alkahest, whose registration has no obligation builder — is refused with a named
      4xx reason before anything is recorded, in all three storefronts; contact exchange
      (it has a builder) and payments keep working.
      Done: every seller entry declares `settles_from_agreement`; bare metal and the
      API-credit storefront refuse a builder-less exact selection with 409
      `settlement_selection_requires_plan` before anything is recorded; VM's generic branch
      refuses the same. **Differed (reading):** the owner's direction is carried out as
      refusing the planless acceptance (`design.md`, "Implementation findings"). Tests (each
      failing against the unfixed admission): bare metal and API credits application
      integration through `StorefrontClient`; VM unit and application integration.
- [x] 7.8 **(04 F2)** Accepted escrow artifacts fail closed on any plan-materialization
      failure, in `kit/alkahest` (owner: "Solve this at the kit layer"), under a refusal of its
      own; `ReleaseConditionError`'s reasons stay as they are. Each storefront refuses the
      round with 409, and the storefronts' handling of a recorded failure goes.
      Done, `arkhai-kit-alkahest` 0.8.0: `SettlementPlanMaterializationError`
      (`settlement_plan_unmaterializable`), `accepted_escrow_terms_error` gone,
      `authorized_escrow_proposal_at_amount` for the API-credit non-accepting rounds; every
      storefront answers the round 409. **Found:** VM answered 500 before; the API-credit
      storefront accepted planless. The three storefronts require `>=0.8.0`. Tests: kit
      unit; the API-credit runtime over a real database (now asserting the real plan); VM
      application integration (409, nothing recorded).
- [x] 7.9 **(04 F3)** One application-integration test in the provisioning service suite
      composes `market_capacity_publication.SiteProjectionState` over the production
      `SiteCapacityClient` against the in-process provisioning app: the first `poll_once`
      loads both families, a capacity declaration is picked up by the next poll, and an
      authority outage keeps the last generation `stale` with its error.
      Done: `provisioning/compute/service/tests/integration/test_site_projection_state.py`
      (application integration): the state over a production `SiteCapacityClient` against
      the in-process provisioning app loads both families, follows a second declaration, and
      keeps both families `stale` through an outage. **Differed:** the dev group also
      declares `arkhai-core-storefront`, which the test imports. Evidence for 7.7–7.9 and
      Section 9's follow-up: every affected suite passed, `make -k test` passed every suite
      it ran.

Section 7 notes: no scenario sends an unauthorized condition; the refusals are
application-integration evidence. The lanes' deals settle under the listing's condition, now
materialized and verified against the listing (`e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
`e2e_non_erc20_settlement`, `e2e_bare_metal_mock_deal`, `e2e_credits_deal`). The items
Section 7 left for the owner are `design.md`'s open list; the 7.6 decision is D14d. Left as
they are: `verify_escrow_for_settlement` still computes an `effective_recipient`, reached
only by its test seam and the legacy no-proposal path; the API-credit integration tests
patch `storefront_config.CHAINS`, the accepted-artifacts builder taking no injected chains.

## 8. VM composes the shared projection state

Delivers VM on one injected `SiteProjectionState` (D2, D3, D4, C2, C7; corrections 3 and 7;
`storefront-publication` "Projection-backed listing candidate derivation"). Touches VM's
storefront only. The largest section by file count: about ten production modules and
fifteen test files, mechanically.

- [x] 8.1 Composition: `src/server.py` builds the state once over the capacity runtime's
      aggregate client, with `wake_publication_loop` as `on_resource_pool_change`;
      `src/container.py` holds it; `src/startup.py`'s `_load_site_projections` calls
      `poll_once()`. The poller registers as the `site_projection_poller` loop on the
      controller with `register_loop`, interval `[capacity].poll_interval`, replacing
      `site_projection_poller_loop`.
      Done: `_build_vm_services` builds the state over the runtime's aggregate with
      `wake_publication_loop`; the container holds it (`container.site_projections()`),
      startup loads it with `poll_once()`. **Differed:** the poller's step registers in
      `lifecycle_steps` at import, since `startup` cannot import it back; its timer
      registers at startup (Section 9). **Amended (review):** `server.py` imports
      `lifecycle_steps` explicitly; the capacity reconciler's projections are a late-bound
      provider the root binds.
- [x] 8.2 Consumers take the injected state, never a module: `services/capacity_client.py`
      (`site_pool_projection`, `site_capacity_buckets`, `_reconcile`),
      `services/listing_sources.py`, `services/listing_source_check.py`,
      `services/publication_loop.py`, `negotiation_runtime.py`
      (`lookup_pool_policy_tags`), `failure_actions.py`, `services/system_service.py`
      (projection status from `status()`), `server.py` (`PoolOverrideService`'s
      `projection_source` reads `values(RESOURCE_POOL)` and `refresh_site` calls
      `refresh_site(site_id)`), and `controllers/admin_controller.py`.
      Done: injected through constructors and builders (`ListingService`,
      `build_vm_negotiation_runtime`, `SystemService`, `build_pool_override_service`,
      `VmPublicationCycle`), read from the container by the cycle, failure actions,
      lifecycle steps, and reconciler. **Behaviour change:** an override write refreshes
      both of the site's families. **Amended (review):** the admin controller takes the
      state through `Depends`; the failure policy's release never fails once the site
      released (`design.md`, "Implementation findings").
- [x] 8.3 Refresh categories (D4, C7): inline reconciliation in `admin_controller.py`
      (`_close_oversized_compute_listings`, `_reopen_available_compute_listings`) and
      `failure_actions.py` (`_release_capacity`) calls `refresh_site` and never wakes; the
      admin route `POST /api/v1/admin/capacity/projections/refresh` runs `poll_once()` and
      returns `status()`, whether or not the loops are held, keeping its wire contract (D3);
      the override service's wake stays as it is.
      Done: the inline paths call `refresh_site(site)` and wake nothing. **Corrected
      (review):** the admin refresh route runs the controller's
      `run_cycle("site-projections")`, held or not, rather than `poll_once()` directly, so
      its answer reflects a change made before asking and the cycle is recorded (`design.md`
      D3); `test_site_projection_state.py`'s refresh-during-timer case fails with the direct
      call.
- [x] 8.4 `lifecycle_steps.py`: the `site-projections` step runs `poll_once()` and returns
      `status()` (C2).
      Done: the step polls the container's state and returns
      `site_projection_status(state)`; it is the registered timer's step.
- [x] 8.5 `services/site_projection_cache.py` reduced to
      `listing_cardinality_mode_explanations`, reading the state it is given; `_caches`,
      the loaders, the poller, the refresh functions, and the unused
      `refresh_after_topology_error` go, and so does VM's `_RemoteProjectionClient`, which
      2.2 copied into the kit rather than moved. Rename the module if only explanations remain, and
      fix the docstring in `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`
      that names it. Once the poller registers through `register_loop`, remove
      `SiteProjectionState.run` and its tests unless something else calls it: it reads its
      gate once and can then wait on a family's lock, the gap Section 3 closed for the
      controller's timer and the capacity-event poller.
      Done: `services/site_projection_cache.py` is deleted; the explanations live in
      `services/listing_cardinality_explanations.py`; nothing called
      `SiteProjectionState.run`, so it went (`arkhai-kit-capacity-publication` 0.9.0).
      **Also changed:** `openspec/specs/site-capacity/spec.md`'s evidence line now cites
      `kit/capacity-publication/tests/unit/test_site_projection_state.py`, a permanent spec
      edited outside the deltas (17.9).
- [x] 8.6 Tests build their own state over `tests/fake_site.py`'s fake aggregate and inject
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
      Done: `tests/fake_site.py`'s `FakeProjectionSite` and `site_projection_state`; every
      listed file builds and injects a state, and no test patches a projection module. The
      harness now holds what a site served at its last poll, so suites step
      `site-projections` before publication (`design.md`, "Implementation findings"). New
      application integration through `StorefrontClient`:
      `tests/integration/test_site_projection_state.py` (an outage during the admin refresh,
      held and not; the held step) and `test_admin_api.py`'s refused reservation checking
      both families once.
- [x] 8.7 Validation: `make test-storefront`, `make test-vms-domain`, `make test`.
      End-to-end (VM lane): `e2e_deal`, `e2e_deal_buyer_cli`, `multi_registry` (which
      calls the admin refresh), `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
      `e2e_pool_declared_modes`, `e2e_vm_introduction`.
      Done; VM storefront frozen, unit and integration passing. **End-to-end, read from the
      scenarios' code:** every VM-lane scenario composes the state; `multi_registry`,
      `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `e2e_vm_introduction`, and the
      deal scenarios call the admin refresh, and the deal scenarios step `site-projections`.

## 9. VM loops on the cycle boundary, freshness, and lifecycle status

Delivers VM's loops on `run_cycle`, the confirmation window for source checks, and the
`lifecycle` status section (D5, D6; `storefront-publication` "The seller's inventory guard
checks a listing against its own source", "Operator-visible acceptance and projection
state"; `market-composition` "A loop records each cycle's outcome with the controller").
Touches VM's storefront, `core/storefront`'s status model, and the VM lane's configuration.

- [x] 9.1 `src/lifecycle.py` and `src/lifecycle_steps.py`: every VM loop —
      `negotiation_watchdog`, `settlement_servicing`, `fulfillment_resume`, `publication`,
      `introduction_retention`, and the site-projection poller from Section 8 — registers
      its step and interval with `register_loop`; `startup.py` starts none of them as a
      self-gating task. The per-site capacity-event pollers keep their fan-out with the
      per-site lock from 3.4. Publication's cycle (`services/publication_loop.py`) names
      its stages `compose`, `run`, `converge`, and VM's configuration and publication
      errors are the controller's disclosed types.
      Done: `register_vm_lifecycle_steps()` registers steps at import, `register_vm_loops()`
      timers at startup's last step, `lifecycle_loops`. **Differed:** timers register at
      startup; the fulfillment-resume step became the timer's cycle; loops start after
      preflight and the first load (`design.md`, "Implementation findings"). Publication
      names `compose`, `run`, `converge`; `lifecycle.DISCLOSED_CYCLE_ERRORS` are the kit's
      and core's capacity and binding errors. Unit `test_loop_gate_wiring.py`, rewritten.
- [x] 9.2 Freshness (D5): `services/listing_source_check.py` confirms a listing only when
      every family it reads — resource pools, and the capacity buckets its fungible
      availability uses — is `freshly_confirmed` within `[capacity].source_confirmation_seconds`,
      defaulting to three times `[capacity].poll_interval` when not stated; any other
      condition is `unverifiable` (retryable). Document the key, commented with its default,
      in `src/settings.toml`.
      Done: `check_listing_source(..., confirmation_window_seconds=, clock=)` confirms only
      freshly confirmed families, before any derivation; the window is read at each check;
      `source_confirmation_clock` is the runtime's seam. **Amended (review):** exact and
      fungible listings are told apart by their binding, a fungible one needing a held
      bucket family.
- [x] 9.3 The VM lane's overlays (`storefront.bob.toml`, `storefront.alice.toml`) widen
      `source_confirmation_seconds` to cover a held scenario's run, with a comment saying
      why, so a scenario that holds the loops and negotiates without stepping
      `site-projections` is not refused.
      Done: `[capacity].source_confirmation_seconds = 3600` in both overlays, commented.
      **Corrected (review):** the umbrella's `bob` agent widens it too, which the Helm
      validation deploys.
- [x] 9.4 Status: `core/storefront/src/core_storefront/models/system_models.py`'s
      `HealthResponse` gains `lifecycle` (each loop's state and last outcome, from the
      controller's snapshot), and `services/system_service.py` fills it. Additive on the
      wire.
      Done: core's `LoopCycleError`, `LoopCycleOutcome`, `LoopStatus`, and
      `HealthResponse.lifecycle` (`arkhai-core-storefront` 0.14.0), on system status only.
      **Amended (review):** the typed client names it, `arkhai-core-storefront-client`
      0.26.0.
- [x] 9.5 Tests. Unit: `tests/unit/test_listing_source_check.py` — a loaded generation past
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
      Done. Unit `test_listing_source_check.py` (six new; four fail with the freshness test
      disabled). Application integration through `StorefrontClient`:
      `test_negotiate_controller.py::TestSourceConfirmationWindow` (refused 503 past the
      window, countered after a held `site-projections` step, the step shown to poll) and
      `tests/integration/test_lifecycle_status.py` (timer and stepped failures, disclosed
      and not, held loops). **Corrected (review):** an integration run that stalled was the
      publication driver's stranded worker thread, fixed below.
- [x] 9.6 Validation: `make test-storefront`, `make test-core`, `make test`.
      End-to-end (VM lane): `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`,
      `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `e2e_vm_introduction`.
      Done. **End-to-end, read from the scenarios' code:** every VM-lane scenario runs its
      loops on the controller's timer within the widened window; those holding and stepping
      loops step them through the recorded cycle. The window's refusal is
      application-integration evidence only.

Section 9 review fixes: the publication driver no longer strands its worker thread
(`PublicationCycleStopped`, `arkhai-kit-capacity-publication` 0.9.2); a fungible listing
needs a freshly confirmed bucket family; the umbrella's `bob` widens the window; the typed
client names `lifecycle`; startup refuses an unusable window;
`stop_loops`/`clear_loops(keep_registrations=)` (`arkhai-kit-storefront` 0.5.0) and an async
`reset_for_tests()`. Each is in `design.md`, "Implementation findings". **Found and decided
later (06 F2, 10.9):** capacity-event reconciliation read held buckets a delta does not
refresh.

Section 9 follow-up: the intermittent
`test_payment_settlement.py::test_settlement_is_pending_until_a_verified_receipt_then_delivers_once`
is deterministic, holding delivery at the harness's gate; no production code changed (20 of
20 runs).

## 10. VM startup refusal, per-site trust, and the interval key

Delivers VM's refusal to start without publication, its per-site service-peer trust, and
`settlement_servicing_interval_seconds` (D6, D14b, C4; `storefront-publication` "A storefront
that cannot publish refuses to start", "Site authority principals rotate with bounded
overlap"). Touches VM's storefront, its chart's generated schema, and the VM lane's
configuration.

- [x] 10.1 Startup refusal (`src/startup.py` or a composition-time check beside it): no
      registry, or a registry without its authority pin while `enable_registry_discovery`
      is true; no enabled settlement mechanism; a configured site with no service peer or
      more than one (through 4.3). Each problem is named, and no loop starts. An empty
      `[pricing].settlements` is not a refusal.
      Done in `src/startup_refusal.py`: `publication_startup_problems` and
      `require_publishable_storefront` (`StorefrontStartupError`, every problem named),
      before the database, signer, or any collaborator; site reading moved into
      `utils.config.configured_capacity_sites`. **Superseded (10.10, 10.18):** the registry
      is checked unconditionally, and retired settings are reported under their own heading.
- [x] 10.2 Per-site trust: `services/capacity_client.py`'s `build_capacity_runtime_for`
      gives each site's `CapacitySite` the provider of that site's peer's active
      principals (4.1, 4.3) instead of the shared `[provisioning.identity]` set, and the
      runtime's cache key stops carrying principals. `[provisioning.identity]` remains
      only for `build_fulfillment_client` and `services/fulfillment_service.py`. The
      provider is read synchronously on the event loop per response, so it must not block
      on SQLite (04 F4): hold each peer's principal records in memory, loaded at seeding
      and reloaded when an identity rotation, completion, or retirement commits, and
      evaluate `active_principals(now)` over them at each call (still "at verification
      time", D14b); bare metal's 12.2 composes the same provider.
      Done (04 F4): `core_storefront.service_peers.ServicePeerTrust`, holding each site's
      peer status in memory and reloading after each change committed through its identity
      authority; `arkhai-core-storefront` 0.15.0; the capacity runtime's sites carry
      late-bound providers and its cache key no principals; the callback middleware reads
      the trust from the container. **Corrected (round 05/06, 05 F1):** this text left
      `build_fulfillment_client` on `[provisioning.identity]`; 10.8 moves it onto the site's
      peer, and 10.21 retires the set.
- [x] 10.3 Interval key (C4): `src/settings.toml`, `src/settlement_composition.py`,
      `src/startup.py`, `src/utils/config.py`'s `settlement_servicing_interval()` (the one
      reader, used by the servicing worker and `src/lifecycle_steps.py`'s registration),
      and the lane overlays use `settlement_servicing_interval_seconds`; a
      configuration stating `claims_sweep_interval` refuses startup naming its replacement;
      VM's section list marks the key retired and `make helm-values-schema` regenerates
      both schemas, so an agent's `config` stating it is refused at render. The charts'
      hand-written `config.allOf` block of retired keys is a second home for retirements:
      decide between them first (Section 5 handoff).
      Done: `settlement_servicing_interval()` reads the new key, the old one refused naming
      its replacement. **Decided (two homes):** keys of the storefront's own configuration
      that it no longer reads are in its catalogue (`RETIRED_KEYS`, generated into both
      schemas), and the chart's hand-written block holds only the chart's own pre-0.2.0
      values; the inventory keys moved to the catalogue (`design.md` C4, "Two homes for
      retired keys"; 17.9).
- [x] 10.4 The VM lane's overlays declare every site's service peer if any does not yet,
      so the lane starts under 10.1.
      Already so for both overlays. **Found (for the owner):** a release from the chart
      defaults alone now refuses to start, naming no enabled mechanism; **decided (06 F1):**
      10.7's `helm/local-values.yaml` enables one for `deploy-local`, the defaults enabling
      none.
- [x] 10.5 Tests. Unit: `tests/unit/test_config_loader.py` — the retired key's refusal.
      Application integration, through the typed client: startup refusals named per
      problem with no loop started; the empty-settlements storefront starts and publishes
      a pool whose override states clauses ("A storefront's terms live in its pools"); a
      site's responses verify against its peer's principals and, after the admin rotation
      routes complete a rotation and its overlap ends, only against the replacement,
      without a restart ("A site's responses follow its rotation"); a principal of one
      site does not verify another's responses. `helm/charts/storefront/tests/test_render.py`
      — `claims_sweep_interval` in an agent's `config` is refused naming the key.
      Done. Unit: `test_config_loader.py`, `tests/unit/test_startup_refusal.py`. Application
      startup (the real app and lifespan): `tests/integration/test_publishable_startup.py`,
      each break refused with no database file and no loop. Application integration: a
      storefront with no configured clauses publishes a pool whose override states them;
      `tests/integration/test_site_trust.py`, a rotation through the admin routes moving
      response verification without a restart. Chart render: the renamed interval refused in
      any spelling. **Differed (level):** that such a storefront starts is unit evidence
      (10.16 adds a lifespan case).
- [x] 10.6 Validation: `make test-storefront`, `make -C helm test-render` (with
      `STOREFRONT_PYTHON` for the loader check), `make test`. End-to-end (VM lane): every
      VM scenario, since each starts the storefront; and the storefront smoke tests.
      Done; VM storefront frozen (unit 1055, integration 440), `make -C helm test-render`
      with the loader check run. **End-to-end, read from the lanes' configuration:** both VM
      overlays pass the refusal, and every site response and provisioning callback verifies
      against the `default` peer through the trust.

### Round 05/06 triage fixes (owner dispositions 2026-10-16)

Review 06 (external, Sections 8–10) and check 05 (Section 10's fresh-context check), both of
`5eff4a6`, were triaged together in `reviews/06-implementation-external.triage.md`. The fixes
below landed as one commit before Section 11, followed by a fresh-context check; the gate passed
2026-10-18, and validation 09 ran the pipeline on `8f5d102`, which carries them.

- [x] 10.7 (06 F1 / 05 F2) **Default release starts locally.** Chart defaults stay free of
      Alkahest. `helm/local-values.yaml` enables Alkahest against the Anvil instance the chart
      deploys, with the known development wallets (public, commented as test-only, never for a
      public network), and contact exchange with a development contact. A render test loads the
      `deploy-local` render's `storefront.json` through `STOREFRONT_PYTHON` and runs the real startup
      refusal (`publication_startup_problems`), asserting no problem. Document in
      `DEPLOYMENT_AND_CONFIG.md` at closeout (17.9).
      Done: `helm/local-values.yaml` enables Alkahest on the dev-env Anvil and contact
      exchange with a development contact on a reserved domain; the wallet key stays in the
      out-of-band `arkhai-bob-runtime` overlay; the chart defaults enable nothing. Chart
      render tests run the storefront's real refusal over the local render (passing) and the
      defaults' (refused). **Corrected (round 08, 08 F1, F7):** the address book was not in
      the image; 10.20 mounts it and derives the release conditions, and 10.27 removes the
      repeated agent.
- [x] 10.8 (05 F1) **Per-site fulfillment trust.** `build_fulfillment_client` gives each per-site
      `ComputeProvisioningClient` its site's peer provider from `ServicePeerTrust`, as the capacity
      clients have; `[provisioning.identity]` stays only on the provisioning-service client
      (`fulfillment_service.py` `_provisioning_client`). Correct 10.2's text, which widened the
      exception beyond D14b. Tests: a rotation moves fulfillment response verification; one site's
      principal is refused on another site's fulfillment responses.
      Done: each per-site `ComputeProvisioningClient` verifies against its site's peer; four
      tests drop their `get_provisioning_authorities` patch. Application integration in
      `tests/integration/test_site_trust.py`: fulfillment responses follow a rotation, and
      one site's principal is refused on another's (both fail with one site's provider
      everywhere).
- [x] 10.9 (06 F2) **Capacity events refresh buckets inline.** Capacity-event reconciliation calls
      `refresh_site(site_id, families=[CAPACITY_BUCKET])` before deriving candidates and never wakes
      publication (refresh-and-reconcile); a failed fetch keeps the generation stale and reconciles
      over what is held. Add the row to `design.md` D4 and a scenario to the storefront-publication
      delta. Regression test (application integration): change availability and emit a reserving
      event without stepping `site-projections` — the backed fungible listing closes; release —
      it reopens. Keep the existing explicit-refresh test.
      Done: capacity-event reconciliation refreshes the event's site's bucket family (every
      site's for a full reconcile) first and wakes nothing; `design.md` D4 and the
      storefront-publication delta record it. Application integration through
      `StorefrontClient`: `test_a_capacity_event_reconciles_on_the_buckets_current_with_it`
      (fails without the refresh).
- [x] 10.10 (05 F3) **Registry discovery switch removed.** `enable_registry_discovery` is no
      longer read; registry publication is always on, so the startup refusal checks the registry
      and its authority pin unconditionally. A configuration stating the key refuses startup naming
      it as removed (refusing, not ignoring, so an operator who turned publication off is not
      silently switched on); add it to `RETIRED_KEYS` and regenerate both schemas. Reword D6's
      parenthetical; update tests that set the switch.
      Done: VM no longer reads the switch; stating it, with any value, refuses startup under
      the retired-settings heading; both schemas refuse it. Tests that turned publication
      off publish to the harness's two recorded registries (`recorded_registries()`). The
      API-credit storefront keeps its own switch: it derives no listings from site
      projections, so D6's refusal does not cover it.
- [x] 10.11 (06 F4) **Per-site capacity-event outcomes.** `run_capacity_event_pollers` (kit) records
      each per-site timer cycle's outcome through a callback the controller provides, under a
      per-site loop name in the snapshot, keeping the per-site cursor lock; the aggregate step keeps
      its aggregate outcome. VM composes it; a status test shows a failing site feed. Bump the kit
      and move pins. Section 15's API-credit pollers reuse it.
      Done: `site_events_poller(record=)` reports each cycle it ran; VM records each site's
      cycle under `capacity_events_poller:<site>`. `arkhai-kit-capacity-publication` 0.10.0,
      `arkhai-kit-storefront` 0.6.0. Application integration:
      `test_lifecycle_status.py::test_a_sites_failing_capacity_event_feed_is_reported_under_its_loop`.
      **Superseded (10.23, 10.24):** names declared as the fan-out's children and recorders
      issued only to them replace `record_cycle`.
- [x] 10.12 (06 F3) **Poll interval validated.** `site_projection_poll_interval()` applies the
      positive, finite rule (zero refused, not defaulted); startup validates the interval and the
      derived window before anything runs. Tests: zero, negative, non-numeric, `nan`, `inf`, window
      unset.
      Done: unset is five seconds; zero, negatives, text, booleans, NaN, and infinity are
      refused naming `capacity.poll_interval`. **Differed:** the check stays a startup step
      after the database opens, as nothing reads either value before it. **Superseded
      (13.12):** through `kit/config`'s `PositiveSeconds`.
- [x] 10.13 (05 F4) **Trust reload never masks a commit.** In `ServicePeerTrust`, a reload failure
      after a committed change is logged, never raised; the commit's result or refusal is returned;
      the trust is marked stale and the next verification or callback check retries the reload.
      `register_subject` is routed through the trust. Library integration test forcing a reload
      failure after a commit.
      Done: a reload failing after a committed change never masks it. **Superseded
      (10.25):** the stale flag and synchronous retry gave way to holding nothing and a
      background reload.
- [x] 10.14 (05 F5) **Site-trust test at its stated level.** Run the real app with its lifespan (the
      trust startup seeds), observe response verification through a storefront operation that
      calls the site, send `capacity_released` signed by the old principal after the overlap
      (refused) and the new one (accepted), reset state only through public seams; fix the
      docstring. If the lifespan cannot run without a reachable provisioning service, keep the
      router-level test and label it honestly.
      Done at the router level, labelled so: the lifespan needs a reachable provisioning
      service (`design.md`, "Implementation findings"). Verification is observed through
      storefront operations (a `site-projections` cycle, a fulfillment status read), and
      after the overlap a `capacity_released` callback signed by the retired principal is
      refused 403 and by the replacement applied; state is reset only through public seams.
- [x] 10.15 (05 F6) **No module patches in the composition test.** Inject the peer configuration
      and trust into the composition root (production defaults) instead of patching
      `server.get_service_peer_configs`, `server.ServicePeerTrust`,
      `server.require_publishable_storefront`; assert "no database" through the file's absence, not
      `sqlite_module._sqlite_client`; move `_replaced_setting` to a public test utility.
      Done: `server.VmCompositionSeams` replaces the composition test's three patches; "no
      database" is the file's absence; `_replaced_setting` is
      `tests._settings_overrides.replaced_setting`.
- [x] 10.16 (05 F7) **Empty settlements start.** If cheap, a lifespan case with empty
      `[pricing].settlements` passing the refusal and reaching the database open; otherwise record
      the disclosed split as accepted.
      Done: application startup, the real lifespan with empty `[pricing].settlements` passes
      the refusal and opens the database, then stops at the next startup check.
- [x] 10.17 (05 F8) **Decisions recorded.** In `design.md`: the two homes for retired keys (beside
      C4), `[provisioning.identity]` only for the provisioning client (D14b), and this round's
      decisions (local-values settlement, capacity-event inline refresh in D4, the removed
      discovery switch in D6, per-site poller outcomes in D6). Name each destination in 17.9:
      `DEPLOYMENT_AND_CONFIG.md` "Storefront agents: pass-through configuration" (retired keys,
      removed switch, local-values settlement), storefront-publication architecture "Trusted site
      routing", the storefront-publication and market-composition deltas.
      Done: `design.md` C4 (two homes), D14b (every site client on its peer), D4
      (capacity-event row), D6 (the 2026-10-16 decisions); 17.9 names the destinations.
- [x] 10.18 (05 F9, F10, F11) **Smaller fixes.** `market-storefront config set` refuses every key in
      `RETIRED_KEYS`, naming its replacement, and the duplicate `_RETIRED_INVENTORY_KEYS` goes (unit
      test: `config set claims_sweep_interval` refused naming `settlement_servicing_interval_seconds`);
      the startup refusal reports retired-key problems under their own heading, separate from
      publication problems, docstring and test text updated; remove the unused
      `container.service_peer_trust()`; add a 17.10 note to confirm `startup_refusal.py`'s docstring
      citation resolves after the archive.
      Done: `market_storefront/retired_settings.py` is the one catalogue, standard library
      only; `config set` refuses every retired key with its explanation; startup reports
      "the storefront states retired settings" and "the storefront cannot publish"
      separately; `container.service_peer_trust()` removed; 17.11 carries the
      docstring-citation note.
- [x] 10.19 Validation for the round: VM storefront frozen, kit capacity-publication, core storefront,
      `make -C helm test-render` with `STOREFRONT_PYTHON`, `make helm-values-schema` committed,
      `make -k test` plus the frozen projects, packaging, hygiene, citations, `openspec validate
      --strict`; then a fresh-context check and the gate question for reviews 05/06.
      Done, the fresh-context check and gate being the orchestrator's (passed 2026-10-18).
      Every suite passed; the pipeline was not run (validation 09 ran it at `8f5d102`).

### Round 08 triage fixes (owner dispositions 2026-10-18)

Review 08 (`reviews/08-implementation.md`, of `8f5d102`) and validation 09 (`reviews/09-validation.md`,
same commit: pipeline passed in all three lanes; Helm deployment not run, no cluster) were triaged
together; dispositions in `reviews/08-implementation.triage.md`. The gate for reviews 05/06 passed
2026-10-18. The owner directed: make these fixes as one commit, run `make test` (with the frozen
projects), and begin Sections 11–14 with no end-to-end run or further review first.

- [x] 10.20 (08 F1) **The local release's Alkahest address book is mounted.** The storefront chart
      gains an optional address-book ConfigMap mount per agent, as the bare-metal chart's
      `alkahestAddressBook` already does; the local release mounts the development Anvil address
      book (a chart-carried copy of `kit/alkahest`'s deterministic Anvil file, marked development
      only), and both `alkahest_address_config_path` and `[Settlement.alkahest].address_config_path`
      name the mounted path. Extend the `STOREFRONT_PYTHON` render check to derive Bob's release
      conditions over the local render (not only the startup refusal), keep the chart's assertion
      that every configured address path is mounted, rename the over-claiming test, correct 10.7's
      note. Record for 17.9 (`DEPLOYMENT_AND_CONFIG.md`) which keys `arkhai-bob-runtime` must carry
      for `deploy-local` to sell under Alkahest.
      Done: the storefront chart's per-agent `alkahestAddressBook` mounts an existing
      ConfigMap read-only; **placed:** the dev-env chart carries the copy
      (`<release>-dev-env-alkahest-addresses`), commented as development only, and both
      address paths name the mounted file. Chart render tests: the mount, the copy equal to
      `kit/alkahest`'s, and the start-and-derive check through `STOREFRONT_PYTHON` deriving
      one condition paying Bob's wallet (fails with the old path). For 17.9:
      `arkhai-bob-runtime`'s overlay must carry `[Wallet] private_key`, Anvil account 2's
      published development key, never for a public network; `[registry.auth]` only for a
      registry requiring write keys.
- [x] 10.21 (08 F2) **Lease termination per site; `[provisioning.identity]` retired.** VM's
      `terminate_vm_lease` routes through the per-site fulfillment aggregate by the site that holds
      the reservation, as bare metal's teardown does (`site_clients.terminate_lease`), verifying
      against that site's peer; it stays the plumbing `vm-storefront-fulfillment` requires for a
      future buyer-requested early termination (buyer → storefront → site). `_provisioning_client`
      and every reader of `[provisioning.identity]` go; the key joins the retired-settings
      catalogue (stating it refuses startup naming it); the chart's provisioning-principal check
      moves onto the site's service peer; the lane overlays, chart values, and fixtures drop it;
      D14b's exception is removed. Test: termination reaches the reservation's own site and its
      response verifies against that site's peer.
      Done: `AggregateFulfillmentClient.terminate_lease(..., site_id=)` and
      `terminate_vm_lease(fulfillment_client, *, capacity_reservation_id, site_id,
      reason=None)`, still with no caller; `[provisioning.identity]` and its readers are
      gone and the key is retired (startup, `config set`, both schemas); the chart's check
      is on the site's service peer alone. **Decided (signature):** the caller names the
      site and passes the client. Tests: unit, router-level application integration (the
      termination reaches only its site and verifies against its peer), startup, CLI, and
      chart render.
- [x] 10.22 (08 F3) **`proposal.md` current.** Amend What Changes and Impact: the `core/storefront`
      and `core/storefront-client` changes; the removed registry switch's and
      `[provisioning.identity]`'s startup refusals; `deploy-local` enabling Alkahest and contact
      exchange with its address book; per-site lease termination; the storefront chart's `agents`
      map (10.27).
      Done: What Changes and Impact amended.
- [x] 10.23 (08 F4) **Per-site loop state follows the fan-out.** A per-site capacity-event loop
      reports the aggregate fan-out's terminal state once it has ended (e.g. per-site names declared
      as children of the aggregate loop). Kit unit test: a fan-out ending while sites are declared.
      Done: `declare(name, *, parent=None)`; a child reports its ended parent's state and a
      pause no longer waits for it; VM's `capacity_site_gate(site)` declares each site. Kit
      unit, three cases.
- [x] 10.24 (08 F5) **Per-site recorders only.** Replace the general `record_cycle` with recorders
      the controller issues only for names declared through the fan-out, so a loop the controller
      runs cannot be written to. Kit unit test.
      Done: `cycle_recorder(name)` issues a recorder only for a declared child, never for a
      loop the controller runs, and a recorder records nothing after `clear_loops`;
      `arkhai-kit-storefront` 0.7.0. Kit unit, two new cases.
- [x] 10.25 (08 F6) **Stale trust never blocks the loop.** On a failed reload after a change,
      `ServicePeerTrust` holds nothing (`_sites = None`), so every read refuses with 503 from memory;
      the stale flag and the synchronous retry on reads go; a background reload retries with backoff
      off the event loop until it succeeds. The reload lock stays, ordering reloads so a slower
      reload can never install an older snapshot. Correct the `site_authorities` docstring. Test: a
      read during the outage returns at once without touching SQLite; the trust recovers after the
      background reload.
      Done: a failed reload after a change sets the trust to hold nothing, so reads refuse
      503 from memory, and one background retry reloads, waiting 0.5 s doubling to 30 s;
      reloads take one lock and read while holding it; seams `retry_wait` and `start_retry`.
      `arkhai-core-storefront` 0.15.2, `arkhai-kit-capacity-publication` 0.10.1. Library
      integration, four cases.
- [x] 10.26 (08 F8) **Comments.** `scripts/validate_slice.py:64-66` names what the Helm release still
      lacks (touch only that comment); `test_site_trust.py`'s docstring says the fulfillment client
      the storefront builds is called directly.
      Done, comments only.
- [x] 10.27 (08 F7) **The storefront chart's `agents` is a map keyed by agent name.** Helm merges maps
      key by key but replaces lists, so every overlay restated Bob's whole agent. Convert
      `storefront.agents` (umbrella and storefront chart) to `agents: {<name>: {...}}`: templates
      range over name/value, the generated values schema types map values, and the list shape is
      refused naming the new shape. Slim `helm/local-values.yaml` and the four fixtures
      (`eip191-evm-values.yaml`, `payments-ed25519-values.yaml`, `contact-exchange-values.yaml`,
      `invalid-missing-identity-secret-values.yaml`) to only what they change; update render tests,
      any scripts or e2e Helm configuration that read the list, and record for 17.9
      (`DEPLOYMENT_AND_CONFIG.md` "Storefront agents: pass-through configuration") the map shape and
      the guidance that a chart value overlays change per entry is keyed, not listed. Section 16's
      bare-metal chart keeps its one-agent-at-top-level shape (C8).
      Done: `storefront.agents` is a map; a list is refused naming the map, an entry's
      `name` refused. **Differed (found):** the subchart ships `agents: {}`, since Helm
      cannot null a subchart's default from a parent; the umbrella declares Bob; storefront
      chart and umbrella 0.3.0. Overlays and fixtures state only what they change; render
      tests overlay Bob's default; the runbook's `--set` paths follow. For 17.9: the map
      shape, `null` removing a key or an agent, a chart value overlays change per entry
      being keyed, and the subchart shipping no agent.
- [x] 10.28 (08 F9) **Closeout note placed.** Move 17.10's post-archive citation note into 17.11
      (after the `archive` command, before the commit).
      Done.
- [x] 10.29 Validation for the round: the affected suites, `make helm-values-schema` committed,
      `make -C helm test-render` with `STOREFRONT_PYTHON`, `make -k test` plus the three frozen
      projects, packaging, hygiene, citations, `make check-tasks`, `openspec validate --strict`. No
      end-to-end run or further review before Sections 11–14 (owner, 2026-10-18).
      Done; every suite passed (release tooling after its overlay assertion was updated). No
      end-to-end run or further review before Sections 11–14 (owner, 2026-10-18).

## 11. Bare-metal configuration through files

Delivers bare metal on `storefront.toml`, `storefront.json`, and `storefront.secrets.toml`
under VM's keys, with Compose and the lane mounting files (D14, D14a, C4, C9, C10, C11;
`deployment-state` "Independently deployable bare-metal seller role", "A storefront's
configuration reaches it through its configuration system"; `storefront-publication` "A
storefront that cannot publish refuses to start"). Touches bare metal's storefront, the
Compose files, the root `Makefile`, `e2e-tests/`, and `scripts/tests/`. Large: every
environment read changes in one commit so the lane never runs half-converted.

- [x] 11.1 `src/settings.toml` (new, packaged): defaults under VM's keys and defaults —
      `[Identity]`, `[Settlement]`, `[registry]`, `[capacity]` (`poll_interval = 5`,
      `publication_interval_seconds = 30`), `[pricing]`, `[negotiation]`, `[Delivery]`,
      `[Wallet]`, `[Chains]`, `base_url`, `db_path`, `negotiation_timeout_seconds`,
      `negotiation_watchdog_interval`, `settlement_servicing_interval_seconds`,
      `payment_reconciliation_interval`; and the site list, each site's URL and its service
      peer. `pyproject.toml` packages it and declares `arkhai-kit-config`.
      Done: `src/arkhai_bare_metal_storefront/settings.toml`, in the wheel; every shipped
      list is empty (Dynaconf merges lists across layers), and an absent lease bound holds
      the pool (C10). The site list is VM's: `[capacity.sites]` and one
      `[Identity.service_peers.<peer>]` per site. `pyproject.toml` declares
      `arkhai-kit-config`, `dynaconf`, and (check fixes) `pydantic`.
- [x] 11.2 `src/config.py` (new): the loader over `market_config.storefront_config_files()`
      with the packaged defaults and the loader's documented environment override layer,
      as VM's `utils/config.py` builds it, and typed models for bare metal's sections,
      named for their concepts (D14a). The signing credential stays
      `ARKHAI_IDENTITY_CREDENTIAL` and is never loaded into settings.
      Done: `settings_source()` builds VM's Dynaconf shape, read afresh on each call; typed
      models per section, `[Wallet].private_key` secret; refusals name keys, never values;
      the credential is read apart (`identity_credential()`). **Corrected (check):** the
      override prefix is VM's `STOREFRONT` (`__` between levels), and typed sections ignore
      a key they do not name, as VM's loader does (`design.md` D14a).
- [x] 11.3 Every environment read moves to configuration, the variables retiring:
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
      Done: `build_runtime_from_configuration` replaces the environment root and carries
      every value its consumers read; the registry configuration fans out over every pinned
      registry; the all-or-none Alkahest rule names `[Wallet].address`, `[Chains]`, and
      `[Wallet].private_key`. **Differed:** `[pricing].settlements` compile at startup,
      refused by key; site bindings take each site's principal from its peer (until Section
      12). **Also changed:** the image's database-path `ENV` goes, since the override prefix
      would read it.
- [x] 11.4 C10: a pool whose effective maximum lease duration, through its override and
      then `[pricing].default_max_duration_seconds`, is absent or not positive is held and
      reported in the cycle's per-site report; the absent default is not a startup refusal.
      Done: `_hold_unbounded_pools` holds and reports `pool_lease_bound_missing`; a
      non-positive default reads as absent in the override-conflict check too.
- [x] 11.5 Startup refusal (D6), at composition: no `[registry].urls` or a registry without
      its authority pin; no enabled settlement mechanism; no configured site. (The
      one-peer-per-site refusal lands with durable trust in Section 12.) Each problem named,
      no loop started.
      Done: `src/startup_refusal.py` in VM's shape, the first step of the root.
      **Differed:** the one-peer-per-site refusal lands here, since the site bindings need
      exactly one peer. No retired-settings catalogue: bare metal had no file configuration
      before.
- [x] 11.6 CLIs: `pool-override` and `publish` read the storefront's URL and identity from
      the same configuration files; `publish` still runs in-process until Section 14.
      Done: `pool-override` signs as `settings.signer(identity_credential())` at
      `--storefront-url`, else `base_url`, its loading inside the client function under the
      existing lazy-load reason. **Superseded (14.2):** `publish` is an API client.
- [x] 11.7 Development and lane files (C9): a committed development `storefront.toml` for
      bare metal (`domains/bare_metal/storefront/storefront.dev.toml`, fixture values
      commented as such) with shortened intervals as VM's overlays have, and a secrets file
      the lane writes; `domains/bare_metal/compose.yml`, `compose.bare-metal.yml`, and
      `compose.bare-metal-local.yml` mount them at `/etc/arkhai/` with `XDG_CONFIG_HOME=/etc`
      and pass only the credential through the environment; the root `Makefile`'s
      `e2e-bare-metal-dev-env` produces only bare-metal files and the variables the
      Compose files still read; `e2e-tests/Makefile` and `e2e-tests/config/config-docker.yml`
      follow.
      Done: `domains/bare_metal/storefront/storefront.dev.toml`, every value commented as a
      development value. **Differed:** the secrets overlay is committed,
      `dev-env/identities/bare-metal.storefront.secrets.toml` (Anvil account 2's published
      key), as VM's is (`design.md` C9). Compose mounts both files at `/etc/arkhai/` with
      `XDG_CONFIG_HOME=/etc`.
- [x] 11.8 Tests. `tests/test_runtime_environment.py` becomes `tests/test_config_loader.py`
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
      Done: `tests/storefront_configuration.py` writes the files under a temporary
      `XDG_CONFIG_HOME`; unit `tests/test_config_loader.py`; composition and application
      startup `tests/test_app_composition.py` (each refusal with no database file and no
      storefront installed; a file-composed lifespan applying a `STOREFRONT_` override).
      **Corrected (level):** `test_publication_cycle.py` is the cycle's public API, not
      application integration; the application-integration lease-bound case is in
      `tests/test_http_publication_rates.py`. Static Compose tests: the storefront's
      environment is `XDG_CONFIG_HOME` and the credential only.
- [x] 11.9 Refresh the locks. Validation: `make test-bare-metal`, `make test-e2e-unit`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end
      (bare-metal lane): `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_introduction`.
      Done; no package version moved. `docs/development/RELEASING.md`'s row gains
      `arkhai-kit-config`. Bare-metal storefront 355 passed. **End-to-end, read from the
      lane's files:** every bare-metal-lane scenario starts from `storefront.dev.toml` and
      the overlay, passing the refusal.

Section 11 check fixes: VM's override prefix and ignored unknown keys (11.2); intervals
defaulting from `config.packaged_settings()`; `pool-override` reporting unreadable
configuration by key; `pydantic` declared.

Section 11 deferred: the lane's principals, site, and registry pin are stated in three
places (`storefront.dev.toml`, the root `Makefile`'s `e2e-bare-metal-dev-env`, and
`e2e-tests/config/config-docker.yml`), as VM's lane states its own, with no guard tying
them.

## 12. Bare-metal durable site trust

Delivers bare metal's sites bound to durable service peers whose active principals verify
responses and callbacks, and reservations that survive a rotation (D14b;
`storefront-publication` "Site authority principals rotate with bounded overlap";
`deployment-state` "Independently deployable bare-metal seller role"). Touches bare metal's
storefront and its development configuration.

- [x] 12.1 Startup seeds each configured site's service peer into core's durable identity
      state through 4.3, refusing a site with no peer or more than one, naming it.
      Administrators stay on configuration.
      Done: the root builds one `ServicePeerTrust` and seeds each peer, a refusal naming it.
      **Superseded (Section 14 check fixes):** seeding is in the server's start hook, as
      VM's (`design.md` D14b, "Seeding at the server's start"); the composition tests became
      application startup tests.
- [x] 12.2 `src/site_clients.py`: `BareMetalSiteBinding` carries the site's peer, not a
      principal; `parse_site_bindings` reads the configuration of 11.1;
      `build_trusted_site_clients` gives each site's `SiteCapacityClient` and
      `ComputeProvisioningClient` the provider of that peer's active principals (4.1, 4.2).
      Done: `BareMetalSiteBinding(site_id, service_peer, authority_url)`; both of a site's
      clients read `trust.site_authorities(site)`; `SiteClientFactories` is the test seam.
      **Also changed:** the diagnostic reports the peer and its active principals, primary
      first. Floors raised for the trust, the provider, and `AuthorityTrust`. Composition
      test over real SQLite: both clients follow a rotation (fails with providers read
      once).
- [x] 12.3 Callbacks: `src/api.py`'s `capacity_released` and the service-role read of
      system status verify against the selected site's peer's active principals, the same
      set its responses verify against.
      Done: `capacity_released` authenticates against its named site's peer; the
      service-role status read accepts any configured site's peer, which VM adopts (check
      fixes). Application integration over peers seeded by `tests/site_trust.py`.
- [x] 12.4 Reservations: `bare_metal_selected_site_bindings` pins the site's peer subject;
      the principal it records is an audit record, so `DurableReservationSiteMap` loads
      after an authorized rotation. Written as fresh schema in `src/migrations.py`, with
      no upgrade or backfill, because bare metal has never been deployed outside the
      development cluster; the immutability trigger keeps the binding unchanged.
      Done: migration 0004's table gains `service_peer`, edited in place (fresh schema),
      0007's trigger covering it; the principal beside it is audit only. **Superseded (check
      fixes):** a database lacking the column is refused at every start by migration 0014.
- [x] 12.5 Rotation routes: bare metal serves the identity rotation, completion, status,
      and retirement routes VM serves (`core_storefront.identity_lifecycle`), reached
      through `StorefrontClient`'s `admin_initiate_identity_rotation`,
      `admin_complete_identity_rotation`, and `admin_get_identity_status`.
      Done in `src/api.py`: rotation, retirement (the completion), and status, committing
      through the trust; an administrator rotation is refused as not registered.
- [x] 12.6 The development `storefront.toml` and the lane's site configuration declare the
      site's service peer.
      Already so (Section 11); only the comment changed.
- [x] 12.7 Tests. `tests/test_site_clients.py`:
      `test_selected_site_binding_survives_restart_and_rejects_authority_rotation` becomes a
      restart after an authorized rotation that keeps the reservation bound ("A bare-metal
      storefront restarts after a rotation"); a site with no peer, or two, refuses startup
      ("A site has no service peer"). Application integration, through the typed client:
      a rotation completed through the routes moves both response verification and
      `capacity_released` callbacks to the replacement once the overlap ends;
      `tests/test_deal_controls.py`'s per-site callback checks pass against peers;
      `tests/test_migrations.py` covers the fresh schema.
      Done: composition-level restart after an authorized rotation (configuration naming the
      replacement); application integration `tests/test_site_trust.py`, the file-composed
      app with only the site's transport replaced, a rotation through the routes moving
      response verification and callbacks to the replacement without a restart (fails with a
      plain identity authority).
- [x] 12.8 Validation: `make test-bare-metal`, `make test`. End-to-end (bare-metal lane):
      `e2e_bare_metal_mock_deal` (its release callback), `e2e_bare_metal_publication`,
      `e2e_bare_metal_introduction`.
      Done: `make lock` recorded the raised floors; bare-metal storefront 366 passed.
      **End-to-end, read from the lane's files:** every bare-metal scenario's site responses
      and the mock deal's callback verify against the seeded `bare_metal_e2e_site` peer.

Section 12 notes: a restart after a rotation needs configuration naming the replacement, as
on VM; the delta scenario "A bare-metal storefront restarts after a rotation" holds under it
(17.9).

Section 12 check fixes (`design.md` D14b): the service-role status read accepts every
configured site's peer in both storefronts; a callback returns the trust's own refusal for
its named site; `test_one_configured_sites_authority_cannot_report_anothers_release`;
migration `bare-metal-storefront-0014-refuse-reservations-without-their-peer`, naming
`docs/bare-metal-seller-quickstart.md`'s "Resetting the storefront database".

## 13. Bare metal on held projections and a publication loop

Delivers bare-metal publication, recheck, and overrides over the shared state, with every
loop on the cycle boundary and the scenarios holding them (D1, D2, D4, D5, D6, C2, C3, C5,
C6, C7; `storefront-publication` "Publication runs as a controllable storefront lifecycle
loop", "A site whose projection is not held holds its listings", "Bare-metal opening
rechecks its listing against its source", "Bare metal joins the site-scoped pool-override
store"). Touches bare metal's storefront and `e2e-tests/`.

- [x] 13.1 `src/runtime.py`: builds one `SiteProjectionState` over the sites' aggregate
      client with the publication wake as `on_resource_pool_change`, held by the runtime and
      passed to every consumer; startup loads it with `poll_once()`.
      Done: the root builds the state over the trusted aggregate with a `PublicationWake`;
      the runtime carries it and the intervals and window, read once; the server's start
      runs the escrow backfill, then `poll_once()`, then the timers.
- [x] 13.2 Loops (`src/lifecycle_steps.py`, `src/server.py`): `site_projections` (step:
      `poll_once()` and `status()`, C2) and `publication` (interval
      `[capacity].publication_interval_seconds`, woken by the state) join
      `negotiation_watchdog`, `settlement_servicing`, `payment_reconciliation`, and
      `introduction_retention`, each registered with `register_loop`; `publication_lock`
      goes. Publication names its stages, and bare metal's configuration and publication
      errors are the controller's disclosed types. Each loop catches its failing cycle.
      Done: one table of loops feeds steps (when the runtime is built) and timers (when the
      server starts). **Differed (name):** the poller is VM's `site_projection_poller` on
      route `site-projections`. `publication_lock` is gone; `DISCLOSED_CYCLE_ERRORS` adds
      `BareMetalPublicationError`. **Also changed:** a stop hook stops and awaits every
      timer, a divergence from VM (`design.md` D6, as delivered for bare metal; the open
      question).
- [x] 13.3 `src/publication.py`: `_classify_site` reads `values(RESOURCE_POOL)` and runs
      `trusted_bare_metal_projection` on the held value; a site holding nothing is
      `site_projection_unknown`, a refused generation `site_projection_refused`; the cycle
      fetches no site and records no generation.
      Done. **Differed:** the cycle reads each site's `view()`, value and identity together,
      before anything is awaited; a view with no value is `site_projection_unknown`; nothing
      is recorded.
- [x] 13.4 `src/listing_source_check.py`: the recheck reads `view(site, RESOURCE_POOL)`,
      requires `freshly_confirmed` within `[capacity].source_confirmation_seconds`
      (default three poll intervals) and an accepted generation, and calls no site (D5).
      Done: an unconfigured site, no value, a generation not freshly confirmed, or a refused
      one is `unverifiable`; the window is resolved once at composition.
- [x] 13.5 Overrides: `src/runtime.py`'s `pool_override_service()` gives
      `PoolOverrideService` `projection_source` over `values(RESOURCE_POOL)`, `refresh_site`
      over the state's `refresh_site`, and the publication wake; the write's live check is
      unchanged. C3: fresh databases stop creating `bare_metal_accepted_site_generations`,
      migration `bare-metal-storefront-0011` stays in the chain with its ID retired, and
      `record_accepted_generation` and `accepted_site_projection` go.
      Done: a write refreshes both families and wakes the loop. **Corrected (wording):**
      0011 left the chain, its ID never reused, under `DEPLOYMENT_AND_CONFIG.md`'s
      frozen-table rule; nothing reads or writes the table.
- [x] 13.6 C5, C7: `health()`'s `site_projections` comes from `status()` for both families
      and calls no site; `capacity_released` and the administrator reserve refresh nothing.
      Done: `health()` reports `site_projection_status(state)`; the callback and reserve
      refresh nothing (13.8 holds them to it).
- [x] 13.7 C6 (`e2e-tests/`): an opt-in per-module fixture holding the bare-metal loops,
      resumed in a finaliser, taken with `pytest.mark.usefixtures` by
      `test_bare_metal_publication.py`, `test_bare_metal_mock_deal.py`, and
      `test_bare_metal_introduction.py` (whose `held_loops` it replaces); each steps
      `site-projections` wherever a site changed before stepping publication. The
      development `storefront.toml` widens `source_confirmation_seconds` for held
      scenarios, as 9.3 does for VM.
      Done: `bare_metal_loops_held` in `scenarios/bare_metal/conftest.py`; each scenario
      steps `site-projections` after a site change; the mock deal's driver asserts the
      stepped generation changed; `storefront.dev.toml` widens the window to 3600.
- [x] 13.8 Tests, application integration through the typed client:
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
      Done; bare-metal storefront 388 passed. **Corrected (level):**
      `test_publication_cycle.py` is the cycle's public API over a real database and held
      state. **Moved (level):** the timer publication case is in
      `tests/test_http_system.py`, the running app's composition observed through the
      controller and a reported-cycle seam with a bound, no sleep (**corrected (round 10, 10
      F4):** through the production composition, 13.13). Through `StorefrontClient`: the
      held step, health from held state, the recheck's not-held, stale, expired, and refused
      generations (four fail with the freshness test disabled), override status from the
      held projection, and C7's no-refresh paths.
- [x] 13.9 Validation: `make test-bare-metal`, `make test-e2e-unit`, `make test`.
      End-to-end (bare-metal lane): `e2e_bare_metal_publication`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_introduction`.
      Done; no lock changed. **End-to-end, read from the scenarios:** every bare-metal
      scenario holds the loops, steps `site-projections` and publication, and rechecks
      against held state inside the widened window; no scenario lets a timer publish.

Section 13 deferred: `lifecycle_steps.site_projection_status` is word for word VM's
`services/capacity_client.site_projection_status`, a candidate for the kit; VM's deal driver
asserts only `loaded` after its admin refresh, where bare metal's now asserts a changed
generation.

Section 13 check fixes: the lifespan test runs the real start and stop hooks; the held
step's hold is read from the controller; the stop hook's reasons are stated (`design.md`
D6); and `kit/pool-overrides`' docstring no longer describes operator-invoked publication.

### Round 10 triage fixes (owner dispositions 2026-10-18)

Review 10 (`reviews/10-implementation-external.md`, the owner's external review of Sections
11-13 at `fa212f0`) was triaged in `reviews/10-implementation-external.triage.md`; its gate passed
2026-10-18, with these fixes to land and the fix commit to be validated (no validation record
exists for `fa212f0`). F3 (bare-metal tests never reach the real provisioning application) was
dispositioned as validation of the fix commit, not a fix: the client-to-API contract is
provisioning's integration suite's, and the wiring the end-to-end lane's.

- [x] 13.10 (10 F1, F2) **Shared setting types in `kit/config`.** A module of two Pydantic
      annotated types, each over a plain function, exported from `market_config`:
      `PositiveSeconds`, a positive, finite number of seconds a `timedelta` can represent, and
      `SiteAuthorityUrl`, an HTTP(S) origin. `kit/config` 0.3.0 to 0.4.0; both storefronts'
      floors `>=0.4.0`; every lock `make check-packaging` asks for refreshed.
      Done: `market_config/setting_types.py`, `PositiveSeconds` and `SiteAuthorityUrl` over
      plain functions; `kit/config` 0.4.0. **Superseded (round 10 check fixes and
      follow-up):** the duration ceiling is the span from year 1 to the epoch, inclusive,
      and below half a microsecond is refused; the origin parses with pydantic's
      `AnyHttpUrl` under the origin policy, an ASCII control character refused first
      (`design.md` D6's and D14b's round-10 notes).
- [x] 13.11 (10 F1, F2) **Bare metal uses them.** `config.py`'s own `PositiveSeconds` is
      replaced by `kit/config`'s; the derived window (three `poll_interval`s) is refused by key
      when unrepresentable; `site_clients._authority_url` applies the origin rule, its
      refusals still naming the site.
      Done: bare metal uses both, the derived window refused by the interval's key, a site
      URL refused naming the site.
- [x] 13.12 (10 F1, F2) **VM uses them.** `utils/config.py`'s `_positive_seconds` delegates to
      `PositiveSeconds` through a `TypeAdapter`, refusing by key; the derived window is
      refused when unrepresentable; `configured_capacity_sites` validates each URL through
      `SiteAuthorityUrl`, refusing by key.
      Done: VM validates through `TypeAdapter`s, refusing `[<key>] <reason>`; its typed
      models do not use the types, so its generated schema is unchanged.
- [x] 13.13 (10 F4) **The timer test runs the production composition.**
      `test_a_site_declaring_new_supply_is_published_by_the_timer` composes its cycle through
      `compose_publication_cycle(runtime, cycle_factory=...)` with a reporting subclass of
      `BareMetalPublicationCycle`, substituting only the registry through the runtime's
      registry seam; the 13.8 note is corrected.
      Done: `_ObservedCycles` composes through `compose_publication_cycle` with real
      Alkahest terms, only the registry substituted; the runtime's default factory path is
      bypassed.
- [x] 13.14 Validation for the round: kit/config unit, the bare-metal storefront suite, VM
      storefront unit and integration (frozen), `make -k test` with the three PyTorch-index
      projects frozen, `make check-packaging`, `make check-comment-hygiene`, `make
      check-doc-citations`, `make check-tasks`, `openspec validate --strict`, chart render
      tests; the fresh-context check of the diff against `fa212f0`.
      Done; every suite passed; the fresh-context check's findings fixed below. The fix
      commit was validated by validation 11 (run 39158420057, all three lanes passed).

Round 10 check fixes and follow-up (owner, 2026-10-18): the representability ceiling and
microsecond floor; refusals carrying no value in their exception chain, in `kit/config`,
bare metal, and VM; the origin on `AnyHttpUrl` (`kit/config` stays 0.4.0, unreleased in this
change); a dry run's refresh or reopen logged as a preview, not a failure.

## 14. Bare-metal status and the publish command

Delivers the bare-metal `lifecycle` and derivation status and the API-client `publish`
command (D6, C1; `storefront-publication` "Operator-visible acceptance and projection
state", "Publication runs as a controllable storefront lifecycle loop"). Touches bare
metal's storefront.

- [x] 14.1 `src/models.py`'s `BareMetalHealthResponse` and `src/runtime.py`'s `status()`:
      `lifecycle` from the controller's snapshot, and the latest per-site derivation
      summary — each site's holds and their reasons, a refused generation and a pool held
      for missing terms or an unordered or absent lease bound included — as VM's
      `publication_derivation` reports.
      Done: `BareMetalHealthResponse.lifecycle` and `publication_derivation` on status, for
      the administrator and a site's service read. **Differed:** a preview records nothing;
      the per-site keys are bare metal's report reasons (`design.md` D6, as delivered
      (Section 14)).
- [x] 14.2 `src/publication_cli.py` and `src/cli.py`'s `publish`: runs one cycle (or a
      preview) through `StorefrontClient.admin_run_lifecycle_cycle` /
      `admin_dry_run_lifecycle_cycle`, signing as the storefront's identity read from the
      configuration files, and opens no database (C1).
      Done: `publish [--dry-run] [--storefront-url | -a]` through `SyncStorefrontClient`,
      the report as JSON, the administrator client in `admin_cli.py`. **Differed (from
      VM):** JSON output (`design.md` C1); `--abort-all` added in 14.6.
- [x] 14.3 Tests. Application integration, through the typed client: status reports a
      failing cycle with its stage, a refused generation as loaded with the site's hold
      ("A bare-metal site serves a generation bare metal refuses"), and a held pool's
      reason. `tests/test_publication_cli.py`: the command reaches a running in-process app
      through its client and touches no database ("An operator runs the bare-metal
      publication command", "Publication runs from the command").
      Done. Application integration through `get_system_status()`: a failed cycle with its
      stage, a running loop whose timer cycles fail, a refused generation held, and a held
      pool's reason from the latest cycle only (both running the production composition).
      `tests/test_publication_cli.py`, application integration over the loopback-served app,
      the command touching no database. **Corrected (check):** the command tests double the
      cycle, so they prove the command, client, and step route path and the composition
      handed to the cycle; the override case and the AST check were replaced (check fixes).
- [x] 14.4 Validation: `make test-bare-metal`, `make test`. End-to-end (bare-metal lane):
      `e2e_bare_metal_publication`; no scenario runs the `publish` command.
      Done; no lock changed. **End-to-end:** the bare-metal scenarios that read status
      receive the new sections; no scenario reads them or runs `publish`.

Section 14 check fixes (owner decisions 2026-10-18, `design.md` D6, C1, D14b): a pool with
no settlement clause held at compose; the derivation the last cycle's; site error text kept;
"Publication fails every cycle" failing on the database (an unreachable registry does not
fail a cycle; **resolved (owner, 2026-10-19):** the delta's example is the database); `-a`;
seeding at the server's start; a storefront nothing answers reported by origin and error
type in both storefronts' commands; VM's preview publishing no derivation report
(`arkhai-vms-listings` 0.6.0); and the command tests reading status,
`test_the_command_loads_none_of_the_storefronts_database_or_runtime` running in a fresh
interpreter.

- [x] 14.5 (owner, 2026-10-19) Seller close and administrator resume routes in bare metal,
      composed from existing kit and core parts, with VM's contracts:
      `POST /api/v1/listings/{listing_id}/close` (seller role, `close_listing`) and
      `POST /api/v1/listings/{listing_id}/resume` (administrator, `admin_resume_listing`).
      Done: `src/listing_controls.py` over the kit runtime and core's responses; 409
      `listing_closed_by_reconciliation` and 503 with no registry, as VM's.
- [x] 14.6 `publish --abort-all`, as VM's: closes every open listing as its seller, paging
      `list_listings(status="open")` and calling `close_listing` through a seller-role client
      (`admin_cli.storefront_seller_client`, beside the administrator client), prints
      `{"closed": [...]}`, and is refused beside `--dry-run`.
      Done (`publication_cli.close_all_open_listings`).
- [x] 14.7 Tests and validation. Application integration through the typed client, the real
      app and lifespan over a real database, listings published by a stepped production
      cycle to a recorded registry (`tests/test_listing_controls.py`, new): a seller's close is
      recorded `closed_by` `seller`, survives the next publication cycle (`skip`
      `closed_by_seller`), and an administrator's resume reopens it (`published`; the registry
      saw publish, closed, publish, open); a listing reconciliation closed is refused 409 and
      stays closed; a signed caller who is not the seller is refused 403, and an unsigned
      request 401 (rejection path, status only); an unknown listing is 404. Through the command
      over the loopback-served app (`tests/test_publication_cli.py`): `publish` publishes two
      listings, `publish --abort-all` closes both as their seller (its output lists exactly the
      closed listings), and the next `publish` publishes nothing; `--abort-all --dry-run` is
      refused. The delta's "Publication fails every cycle" example is now the storefront's
      database being unavailable (owner, 2026-10-19), which the status test reproduces.
      Done; bare-metal storefront 423 passed. End-to-end: none; application-integration
      evidence only.

Section 14 seller-controls check fixes (follow VM): the close refuses an unwritable database
as retryable (503 `listing_close_incomplete`); VM's per-listing pause, a paused listing
staying open and published; two known limitations shared with VM (`design.md` C1).
Bare-metal storefront 427 passed.

## 15. The API-credit storefront's loops, and the controller's one loop form

Delivers P1 and P2: the API-credit storefront's loops on `run_cycle` and its interval key
renamed, then the kit's old loop forms removed (D6, C4). Touches the API-credit storefront
and `kit/storefront`.

- [x] 15.1 `src/startup.py` and `src/lifecycle_steps.py`: `negotiation_watchdog`,
      `settlement_servicing`, and `payment_reconciliation` register with `register_loop`;
      the per-site capacity-event pollers keep the per-site lock of 3.4.
      Done, on VM's and bare metal's pattern; each site's capacity-event poller is the
      aggregate's declared child with an issued recorder. **Amended (15.3 resolved):** the
      aggregate registers with `register_fan_out`, and every loop starts together after the
      credits-service preflight and the demo seed (`design.md` D6, "the controller's loop
      forms").
- [x] 15.2 `src/settings.toml`, `src/startup.py`, `src/settlement_composition.py`:
      `settlement_servicing_interval_seconds` replaces `claims_sweep_interval`, which
      refuses startup naming its replacement.
      Done: `settlement_servicing_interval_seconds` through `positive_seconds`, refused by
      key; the old key refused first, before the signer or database, under VM's heading; the
      API-credit chart has no generated schema, so this is its guard (C4). **Resolved
      (owner, 2026-10-19):** VM adopts the check for its servicing and retention intervals.
- [x] 15.3 `kit/storefront/src/market_storefront_kit/lifecycle.py`: remove `start_loop` and
      the step-only `register_step` once no caller remains; bump the version.
      **Stopped (plan premise wrong):** both forms kept callers by design. **Resolved by the
      owner (2026-10-19): (b)**, `register_fan_out` beside `register_loop`, `start_loops`
      the one start (`design.md` D6, with (a), (c), and (d) rejected). Done: `start_loop`
      and VM's `start_registered_loop` gone, `register_step` kept as a registration's step
      half; `arkhai-kit-storefront` 0.8.0.
- [x] 15.4 Tests. The API-credit storefront's lifecycle and startup suites: the registered
      loop set, the retired key's refusal. `kit/storefront/tests/unit/test_lifecycle_controller.py`:
      the removed forms' tests go.
      Done: the kit's self-gating test bodies run as fan-outs with no children; eight new
      cases; VM's startup registers and starts the fan-out with the timers. The API-credit
      cases are in the notes below.
- [x] 15.5 Refresh the locks. Validation: `make test-apicredits`, `make -C kit
      test-storefront`, `make test-storefront`, `make test-bare-metal`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end
      (API-credit lane): `e2e_credits_deal`, `e2e_credits_payment_deal`.
      Done; every suite passed. **End-to-end, read from the lanes' files:** the API-credit
      lane's storefront runs its sweeps on the controller's timer and its fan-out through
      `start_loops`, on the packaged 30 s servicing interval under the new key.
- [x] 15.6 (owner, 2026-10-19) API-credit system status reports `lifecycle`, in VM's and bare
      metal's shape (core's `LoopStatus` over the controller's snapshot, keyed by loop name).
      Done: status fills `lifecycle` from the controller. **Also changed:** the route is the
      administrator's signed read (`admin_system_status`), since it answered unsigned and
      the typed client refused it (`design.md` D6); `/health` unchanged. Application
      integration `tests/integration/test_lifecycle_status.py` through `StorefrontClient`.

Section 15 notes: the API-credit lifecycle router's tests (component, through
`StorefrontClient` over the storefront's own registrations) hold every loop and site, record
step and timer outcomes, and report a site's failing feed under its name;
`tests/unit/test_server_composition.py` covers startup's registrations.

Section 15 check fixes: the `api-credits` delta and the modified market-composition
requirement; capacity configuration refused before the signer or database;
`register_fan_out` and `start_loops` naming children before acting; finite intervals; seams
instead of patches.

## 16. The bare-metal chart on the storefront chart's agent shape

Delivers the bare-metal chart rendering configuration through unchanged under a generated
schema (D14c, C8; `deployment-state` "Independently deployable bare-metal seller role", "A
storefront's configuration reaches it through its configuration system"; `design.md`
"Validation tiers"). Touches `helm/charts/bare-metal-storefront`, the umbrella, the root
`Makefile`, bare metal's storefront, and `helm/scripts/test-render.sh`.

- [x] 16.1 `src/values_schema.py` (new, bare metal): its section list and sinks over
      `market_config.values_schema`, writing only
      `helm/charts/bare-metal-storefront/values.schema.json`; the root `Makefile`'s
      `helm-values-schema` also runs it. Drift test `tests/test_values_schema.py`, run by
      `make test`.
      Done: `src/values_schema.py`. **Differed (shape):** no section list -- the definition
      is the whole typed settings model, closed at the root and in every section while the
      loader ignores unknown keys (`design.md` C8). **Also changed:** bare metal reads VM's
      `port`, `serve --port` overriding it, and the image runs `serve`. Unit
      `tests/test_values_schema.py`, 8 cases.
- [x] 16.2 `helm/charts/bare-metal-storefront`: `values.yaml` as one agent's keys at the top
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
      Done (`design.md` C8, as delivered): the agent shape at the top level,
      `storefront.json` in a ConfigMap, the overlay and credential Secrets,
      `enableServiceLinks: false`; chart 0.3.0. **Differed:** `alkahestAddressBook` and
      `service.type` stay; `sitePlacement` goes. **Corrected (Section 16 check fixes):** in
      an umbrella release the chart also derives the internal registry and the `default`
      provisioning site.
- [x] 16.3 `helm/charts/bare-metal-storefront/tests/test_render.py`: production values
      render the ConfigMap, the overlay, and their mounts together, asserted in one helper;
      the pod environment carries only the configuration directory and the credential
      (spec scenario "The chart renders a storefront's environment"); the schema refuses a
      misspelled or secret key in `config`, naming it; break a mount once to see the test
      fail. Tier 2: load one rendered `storefront.json` with bare metal's own loader through
      an interpreter `BARE_METAL_STOREFRONT_PYTHON` names, which `test-render.sh` sets when
      bare metal's environment exists, skipping otherwise.
      Done: chart render tests (21 after the check fixes); tier 2 runs bare metal's loader,
      startup refusal, clause compilation, and site binding over the example's render
      through `BARE_METAL_STOREFRONT_PYTHON`, and the refusal over the defaults'.
- [x] 16.4 Validation: `make test-bare-metal`, `make helm-values-schema` with no diff,
      `make -C helm test-render` with both loader interpreters set, `make
      test-deployment-packaging`, `make test`. End-to-end: none in the pipeline, which
      deploys no chart.
      Done; no version moved; bare-metal storefront 437 passed; `make -C helm test-render`
      with both loader checks run. End-to-end: none, the pipeline deploys no chart.
- [x] 16.5 Tier 3, in a local session with a cluster: deploy the umbrella with the
      bare-metal storefront enabled from the example values, confirm it starts, reports
      its loops and both projection families in status, and publishes; record the
      evidence or the blocker here. Not runnable in a cloud session.
      **Rewritten (round 12, 12 F1; `design.md` C13):** deploy the two-release topology 16.7
      commits (`make helm-topology-up`, `-check`, `-down`), declare one bare-metal pool and
      machine on release 2's provisioning service, and record, against the running releases,
      the storefront's requests admitted, both families loaded and its loops in status, a
      capacity-released callback reaching it, and a publication on release 1's registry
      found by a buyer while Bob's listings stay published. **Done (2026-10-19, the owner's
      local cluster, at `825737c`):** release 2's provisioning service answered every
      bare-metal storefront request 2xx and reported `storefront_auth: ok`; both families
      `loaded` for `default` and the publication, poller, watchdog, and servicing loops
      `running` with completed timer cycles; `test_bare_metal_publication` against release 2
      passed (11); a probe running the mock deal's stages passed twice, release 2's
      provisioning service posting `capacity-released` and the storefront recording the
      reservation released; a buyer's query on release 1's registry found the listing while
      Bob's stayed open. The owner holds the observation files; they are not in the
      repository. Not shown: a passing `make helm-topology-check` (a retained provisioning
      database and a smoke profile lacking keys, the latter fixed by 16.8), the
      `e2e_bare_metal_mock_deal` marker against the topology, and `make helm-topology-down`.
      Release 1's pods kept old images until restarted by hand (16.8). **Amended (16.8's
      check):** a rerun runs `make helm-topology-secrets` first.
- [x] 16.6 Relock `domains/vms/storefront`, `kit/policy`, and `domains/vms/buyer` with
      `make lock` in an environment that reaches the PyTorch CPU index, and run `make test`
      there unrefreshed; the hand-edited locks should produce no diff. This container's
      network policy blocks that index, so each section that bumps a package one of them
      locks edits that lock by hand, and their suites run in frozen environments.
      **Done (2026-10-19, the owner's environment, which reaches the PyTorch CPU index):**
      at `59c2cba`, `make lock` produced no lockfile change and `make check-packaging` and
      `make test` passed, so every hand-edited entry (the internal packages' versions, wheel
      names, and specifiers in `domains/vms/storefront/uv.lock` and
      `domains/vms/buyer/uv.lock`; `kit/policy`'s lock unchanged) is what uv writes. No lock
      moved after `59c2cba`.
- [x] 16.7 (round 12, 12 F1: the owner's topology) Several storefronts per registry, as separate
      Helm releases of the umbrella. Release 1 is the umbrella as `deploy-local` installs it
      (registry, Bob's VM storefront, provisioning, dev-env); release 2 is the same chart with
      only the bare-metal storefront and its own provisioning service enabled, publishing to
      release 1's registry. A committed release-2 overlay (`helm/bare-metal-release-values.yaml`,
      development values only, each fixture commented as a well-known development value never
      for a public network): release 2's provisioning trusts the bare-metal storefront's
      principal (`storefrontIdentity.principals`) and calls back its Service (`storefront.url`);
      the bare-metal chart's `global.registry.host` names release 1's registry Service, its
      registry trust pins release 1's registry principal, and its Alkahest address book is
      release 1's dev-env ConfigMap. Render tests: release 2's provisioning trusts the bare-metal
      principal and calls back the bare-metal Service; bare metal publishes to release 1's
      registry under the pinned trust; release 1 renders as it does today.
      **Stopped, then resumed (2026-10-19):** the umbrella's smoke-test profile required a
      VM agent whatever `storefront.enabled`, which no values satisfy honestly in release 2;
      the owner accepted the chart change and release 2's identities (Anvil accounts 8 and
      9). Done (`design.md` C13): the profile applies its VM-agent requirements only while
      the VM storefront is enabled, and otherwise checks provisioning trusts the bare-metal
      storefront's principal; release 1 renders byte for byte as before.
      `helm/bare-metal-release-values.yaml`, `helm/Makefile`'s `topology-*` and the root
      `helm-topology-*`. Chart render tests `helm/tests/test_release_topology.py`, run by
      `test-render.sh`. **Corrected (round 12's check):** one release running both
      storefronts on its own provisioning service is refused, naming the overlay; the
      topology targets refuse an overridden release name; `topology-check` checks release
      1's e2e-tests Secrets.
- [x] 16.8 (16.5's run; owner decision (b), 2026-10-19) The smoke profile carries what the
      release can derive, and `topology-up` rolls rebuilt images. (a) The generated smoke
      profile (`helm/templates/tests/test-config.yaml`) carries each key the release's smoke
      hooks read that its values state: `registry.authority_id` and `registry.identifier`
      from the release's registry identity, `buyer.wallet_address` from the release's
      development buyer; `buyer.marketplace_credential` is signing material, so it comes only
      from a Secret that `topology-check` checks for as it checks the e2e Secrets and that
      the overlay and 16.5 name. Render-test each derived key; release 1's render changes
      only by these keys. (b) `topology-up` restarts the topology's Deployments after its
      Helm upgrades (`kubectl rollout restart`, then `kubectl rollout status`), so rebuilt
      images under the bare local tags roll; image tagging is unchanged (the owner keeps bare
      local tags: a commit-hash tag changes when an image does not, and bare tags avoid
      image-not-found errors); the Makefile says why. (c) Nothing else narrowed;
      `topology-check`'s comment says what it now proves.
      Done (as corrected by its check): the smoke profile carries what the release's hooks
      read and its values state -- `registry.authority_id` and `registry.identifier` (what
      the release's clients trust, internal EIP-191 registry only), `buyer.wallet_address`,
      and, **differed**, `seller.wallet_address`, which the chain hook also reads; the
      buyer's credential reaches the registry smoke pod through the registry chart's
      `tests.credentialProfile` from `arkhai-e2e-credentials`. `make helm-topology-secrets`
      creates every Secret both releases read, and the deal test's `arkhai-buyer-profiles`
      volume, from development values at `helm/Makefile`'s `DEV_ACCOUNT_*` indices, never
      for a public network; `topology-up` restarts both releases' Deployments in
      `TOPOLOGY_ROLLOUT_ORDER`, never dev-env's (`design.md` C13). Chart render tests (15
      topology cases), each failing with its behaviour undone; release 2's render
      byte-identical to `825737c`'s.

Section 16 notes: the bare-metal lane's storefront starts from `serve` on the configured
`port`; no pipeline scenario deploys the chart.

Section 16 deferred: `[Delivery]`'s own settings are stated in both storefronts (each test
holds its copy equal to the other chart's committed definition; `kit/delivery` is their home
the next time that exactly pinned kit changes); the image's Docker `HEALTHCHECK` calls port
8000, which Kubernetes ignores.

Section 16 check fixes (`design.md` C8): umbrella derivations as VM's chart's, refusing
parts that disagree; VM's chart turns service links off; the `[Delivery]` copies held equal;
the rollback consequence of the closed schema; `serve` taking its process from the command
line's context.

Round 12 triage fixes (`reviews/12-implementation-external.triage.md`): 12 F2, the
API-credit capacity poll interval validated and refused by key at startup; 12 F3, the origin
guard reading the value as stated; 12 F1, the two-release topology (16.7). The fix commit
was validated by validation 13 (run 39275286164 at `825737c`, all three lanes passed).

16.5's run and 16.8 (2026-10-19): the run exposed six pre-existing defects outside this
change, which the owner sent to `unbacked-bare-metal-listings` (its `design.md` open
question 11). 16.8 and its check are render evidence (`make -C helm test-render`, the 15
topology cases among its 147 assertions and cases); no cluster was reached from those
sessions.

## 17. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order. It edits
documentation only; a part needing code returns the change to implementation.

Entered 2026-10-19 with the pre-closeout review waived by the owner ("advance to closeout when
the helm render tests are done and run a review when closeout implementation completes";
`interventions.jsonl`); the last implementation gates passed in
`reviews/10-implementation-external.triage.md` and `reviews/12-implementation-external.triage.md`.
Closeout stopped at 17.2 for a code fix round (`47d9c67`), then resumed: 17.2 was confirmed
against that commit's diff, the pipeline rerun on it (17.8), and the change archived (17.11).

- [x] 17.1 **Comment hygiene.** Confirm `make check-comment-hygiene` passes and that no
      comment the change added names a change, a review, or a migration provenance.
      Done: `make check-comment-hygiene` reports no change-ID or task-number reference and no
      OpenSpec change name in code. The comments and docstrings the change added (the diff from
      its branch point on `dev`, `9168849`) were read for fuzzier provenance: none names the
      review, round, or migration that introduced it. "Retired" and "no longer reads" describe
      the retired-settings catalogues' current behaviour, and "the change" in
      `ServicePeerTrust`'s docstrings is an identity change.
- [x] 17.2 **Import placement.** Confirm the imports each section added are at module level
      unless a recorded reason keeps one local.
      Stopped 2026-10-19 for a code fix round over the function-local imports the change added
      or touched with no reason beside them; each was settled by attempting the move.
      - Moved: `market_storefront/failure_actions.py`'s `get_escrow_codec_for` and, in
        `_release_capacity`, `capacity_availability`, `remote_site_clients`,
        `build_capacity_runtime`, and `capacity_binding_for_listing` (no cycle; the module
        already imported both packages). Four `test_failure_policy.py` cases failed on the move:
        they patched the defining modules, so their patches now target
        `market_storefront.failure_actions`, as the file's other patches do, and
        `tests/fake_site.py` patches the runtime factory there beside `fulfillment_service`'s.
        `CHAINS` stays local: tests replace `market_storefront.utils.config.CHAINS` and the
        change did not add it.
      - Moved: every local import in `apicredits/storefront/tests/unit/test_server_composition.py`
        (the listed duplicates and the ones beside them in the same tests);
        `vms/storefront/tests/integration/test_admin_api.py`'s `FakeSite` (not in the
        module-level `tests.fake_site` import, as the stop note said; now added, and that file's
        local re-imports of `FakeSite` and `site_capacity` dropped);
        `apicredits/buyer/tests/test_settle_credentials.py`'s `typer` (both local copies).
      - Reason stated beside the import (a deliberate lazy load): bare-metal `admin_cli.py`'s
        `reporting_failures` imports (moving them loads `httpx` and `storefront_client` for
        every command, `--help` included) and `cli.py`'s `build_runtime_from_configuration`
        (moving it fails `test_the_command_loads_none_of_the_storefronts_database_or_runtime`).
      - Also fixed: the VM `settings.toml` `[capacity]` comment (17.3) now describes the required
        `[capacity.sites]` table and service-peer verification, and the unread `authority_url`
        key is gone, as is the "single-site form" in the service-peer comment; the stale
        `authority_url` remarks in `storefront.bob.toml` and a test fixture went with it.
      Evidence: VM storefront unit 1101 passed, 1 skipped, and integration 448 passed
      (`UV_FROZEN=1`); `make test-apicredits` OK (storefront 182, buyer 26); bare-metal
      storefront `make test` 438 passed; `make dist`, `make check-packaging`, and
      `make check-comment-hygiene` OK. No requirement changed, so no lock or version changed.
- [x] 17.3 **Documentation compliance.** Re-check D0–D6, D14a–d, C1–C13, P1, and P2 against
      the placement rules in `openspec/README.md`.
      Done: every accepted decision is classified in the design-promotion record below —
      normative halves in the five spec deltas, which the archive writes; rationale in the
      `storefront-publication` and `market-composition` companions; repository-wide boundaries
      in `ARCHITECTURE.md`; configuration and deployment in `DEPLOYMENT_AND_CONFIG.md`; test
      methodology in `TESTING.md`; goal state in `ROADMAP.md`. D0 and corrections 1–10 are change
      history. Permanent documents were also checked against the code they describe, and these
      were corrected beside the promotion: `TESTING.md` said the chart render tests were not
      part of `make test` (`make test-deployment-packaging` runs them); `docs/seller-quickstart.md`'s
      example configuration had no site, service peer, or registry pin, all of which startup
      now requires; `docs/bare-metal-seller-quickstart.md` named a long-superseded wheel
      version; `docs/configuration.md`'s policy table lacked the guards' release-condition
      refusals. The VM `settings.toml` `[capacity]` comment, which described a single-site
      fallback and CSV inventory the storefront does not have, was found here and is fixed in
      the 17.2 round (`47d9c67`).
- [x] 17.4 **Narrative compression.** Shorten Sections 2–16's notes to final behavior,
      material evidence, deferred work, and destinations; move any rationale not yet in
      `design.md` there first.
      Done: rationale that lived only in task notes moved first to `design.md`, "Implementation
      findings", and the questions the notes left for the owner to "Open questions". Sections
      2–16 then went from about 5,500 lines to about 1,670: each task keeps its plan text, its
      checkbox, its corrections and amendments (shortened), its final evidence, and its
      destinations; section handoffs that only steered later sections went, and deferred items
      stay as "deferred" notes. Task IDs, headings, and every pipeline run ID are unchanged.
- [x] 17.5 **Roadmap currency.** `docs/development/ROADMAP.md`: Goal 4's gap row "VM keeps
      its own per-site projection cache" is closed, and Goal 7's current state says bare
      metal holds projections and publishes on a loop, with unbacked supply still
      `unbacked-bare-metal-listings`'. Name the update in the promotion record.
      Done: Goal 4's row is split — the listing-lifecycle and fulfillment-convergence gap stays
      `kit-owned-listing-and-fulfillment-lifecycles`', and "VM keeps its own per-site
      projection cache" is closed, linking this change's directory (repoint it to the archive at
      17.11) — and Goal 4's current state names the kit's per-site projection state and the
      controller's recorded cycles. Goal 7's current state says bare metal publishes on a timer
      loop over held projections and rechecks openings against them; unbacked supply stays
      `unbacked-bare-metal-listings`'.
- [x] 17.6 **Campaign index currency.** `openspec/changes/README.md`: this change's row
      (status, notes) and the graph line `share-site-projection-state (held projections and
      a publication loop for bare metal) ──► unbacked-bare-metal-listings`; other rows'
      `Depends on` are archive cleanup's. Name it in the promotion record.
      Done: the row is `in closeout`, its Notes describing the closeout (the waived review, the
      import-placement fix round during closeout, the pipeline run at the final code commit) and
      nothing of implementation, and, after the archive, linking the archive directory; the graph
      line reads `(in closeout; …)`. No other row changed. `make check-change-index`: OK.
- [x] 17.7 **Packaging.** `make check-packaging` and `make check-architecture-change
      CHANGE=share-site-projection-state`, resolving every failure; the change owns no
      exception row.
      Done at `9af52ff`, and again at `47d9c67` after the fix round: `make check-packaging` OK — every environment and image install derives
      its internal packages from its lock, every lock matches its project, the wheels the tree
      builds, and the wheelhouse, every Python version selection reads the root declaration,
      every distribution is one package under `src/`, and the layers, scope, dependencies, and
      kinds rules hold. `make check-architecture-change CHANGE=share-site-projection-state`:
      owns no architecture row. `make check-agent-skills` not owed: the change touches no
      `.agents/`, `.claude/`, or `.codex/` file. The three PyTorch-index projects' locks were
      relocked with no diff where the index is reachable (16.6).
- [x] 17.8 **End-to-end pipeline.** Record a passing run of all three lanes on the closeout
      commit and the scenarios exercising this change: `e2e_deal`, `e2e_deal_buyer_cli`,
      `e2e_buy`, `multi_registry`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
      `e2e_pool_declared_modes`, `e2e_vm_introduction`, `e2e_non_erc20_settlement`,
      `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_introduction`, `e2e_credits_deal`, `e2e_credits_payment_deal`; and
      16.5's chart evidence or its blocker.
      Done: run 39341868764, dispatched on this branch at `47d9c67` (the 17.2 fix round, the
      last code commit before the archive) through the GitHub API on 2026-10-19, success in all
      three lanes: VM 134 passed, 118 deselected; bare metal 51 passed, 201 deselected; API
      credits 1 passed, 3 skipped, 248 deselected -- the same counts as validation 13. The
      archive commit changes documentation only, so this run describes the code it carries.
      Scenarios exercising this change, as validation 13 (`reviews/13-validation.md`, run
      39275286164 at `825737c`) names them: VM -- `e2e_deal` 31, `e2e_deal_buyer_cli` 27,
      `e2e_buy` 8, `multi_registry` 21, `e2e_compute_dynamic_listings` 10,
      `e2e_alkahest_escrow_codecs` 12, `e2e_listing_shapes` 17, `e2e_vm_introduction` 6,
      `e2e_non_erc20_settlement` 2 (the fix round's `failure_actions.py` imports run in the VM
      storefront image these start); bare metal -- `e2e_bare_metal_publication` 11,
      `e2e_bare_metal_introduction` 5, `e2e_bare_metal_mock_deal` 35, each holding the loops,
      stepping `site-projections` and publication, and reading status through the typed client;
      API credits -- `e2e_credits_deal` passed, `e2e_credits_payment_deal`'s three tests skipped,
      the lane supplying no payments target. `e2e_pool_declared_modes` is not among the VM lane's
      selected modules, so no run exercises it. Earlier runs: 39117263451 (`8f5d102`, validation
      09), 39158420057 (`da61cc9`, validation 11), 39275286164 (`825737c`, validation 13). What no
      scenario exercises -- the bare-metal `publish` command and seller listing controls, reading
      `lifecycle` or `publication_derivation`, the API-credit signed status, a VM publication
      preview, a timer publication cycle, the startup refusals, and any chart deployment -- is
      application-integration, unit, or render evidence, as validation 13 lists. 16.5's chart
      evidence: the owner's local two-release run at `825737c` (16.5), which proves the
      topology's behaviour as deployed at that commit. 16.8's later chart and `helm/Makefile`
      changes -- the smoke profile's derived keys, the registry chart's credential profile,
      `topology-up`'s rollout restart, `make helm-topology-secrets`, and the deal test's
      buyer-profile volume -- have chart render evidence only (16.8), and `make
      helm-topology-check` has not yet been shown passing against a cluster. The owner reruns
      `make helm-topology-secrets`, `helm-topology-up`, `helm-topology-check`, and
      `helm-topology-down` on a cluster before the pull request (closeout triage, 14 F5 / 15 F1).
- [x] 17.9 **Promotion.** Write the permanent documents and complete the design-promotion
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
      - `docs/configuration.md`: "Bare-metal storefront" (the seller chain from
        `[negotiation].policies`, not an environment variable); and
        `docs/attachments/baremetal-dispatch/index.md`: its startup and settlement text naming
        `BARE_METAL_STOREFRONT_SETTLEMENT` and the other retired variables (Section 11's
        handoff).
      - `docs/bare-metal-seller-quickstart.md`: "Configure public bindings", "Start and
        inspect".
      - `openspec/specs/README.md`: no new capability or companion; record that disposition.
      - The `spec.md` files the deltas cover (`storefront-publication`,
        `market-composition`, `deployment-state`, `negotiation-protocol`, and `api-credits`)
        are written by the archive in 17.11; the record names them.
      - **Amended (Section 15 and its check):** `openspec/specs/api-credits/spec.md` -- "API-credit
        system status is the administrator's signed read" (from the `api-credits` delta);
        `openspec/specs/market-composition/spec.md` -- "Storefront timer loops are held and
        stepped through one kit controller", modified for the two registration forms (from
        its delta); `docs/development/DEPLOYMENT_AND_CONFIG.md` -- the API-credit storefront's
        `settlement_servicing_interval_seconds`, its startup refusals (renamed setting,
        unreadable capacity configuration), and its status as the administrator's signed read
        with `lifecycle`; the other Section 15 destinations are in its notes.
      - **Amended (round 05/06, 10.17):** `DEPLOYMENT_AND_CONFIG.md` "Storefront agents:
        pass-through configuration" -- the storefront's one retired-key catalogue beside the
        chart's own retired values block (C4's two homes), `enable_registry_discovery` removed
        and refused, and `helm/local-values.yaml` enabling Alkahest on the release's Anvil and
        contact exchange for `deploy-local` while the chart defaults enable none (D6);
        `storefront-publication/architecture.md` "Trusted site routing" -- every site client,
        capacity and fulfillment, on its site's peer, `[provisioning.identity]` only for the
        provisioning-service client, and the stale-trust rule (D14b), and "Unknown sites and
        inline reconciliation" -- a capacity event refreshes its site's buckets first (D4);
        `market-composition/architecture.md` "Storefront composition kit" -- per-site
        capacity-event outcomes through the controller's `record_cycle` (D6). The normative
        halves are in the storefront-publication and market-composition deltas.
      - **Amended (round 08, 10.20, 10.21, 10.24, 10.25, 10.27; superseding the round 05/06
        bullet where they differ):** `DEPLOYMENT_AND_CONFIG.md` "Storefront agents: pass-through
        configuration" -- `storefront.agents` keyed by agent name, a list refused naming the map,
        an overlay stating only what it changes and `null` removing a key or an agent, the
        subchart shipping no agent, and the guidance that a chart value overlays change per
        entry is keyed, not listed; the per-agent `alkahestAddressBook` and the dev-env chart's
        Anvil address-book ConfigMap the local release mounts; the keys `arkhai-bob-runtime`
        must carry for `deploy-local` to sell under Alkahest (10.20's note);
        `[provisioning.identity]` removed and refused, so the section's sentence requiring
        `config.provisioning.identity` is corrected to the site's service peer alone;
        `storefront-publication/architecture.md` "Trusted site routing" -- no
        `[provisioning.identity]` exception, early lease termination at the reservation's site,
        and a failed reload after a change leaving the trust holding nothing until a background
        reload succeeds (in place of the stale-trust rule); `market-composition/architecture.md`
        "Storefront composition kit" -- per-site names declared as the aggregate loop's
        children, following its end, and recorders the controller issues only to them (in place
        of `record_cycle`); `TESTING.md` "Chart Render Tests" -- the storefront chart's
        `STOREFRONT_PYTHON` check runs the startup refusal and derives the local release's
        Alkahest release conditions over its render, beside the loader check.
      - **Amended (Section 12 and its check):** besides Section 12's handoff destinations,
        state that bare metal's identity routes cannot rotate an administrator (refused as not
        registered, its administrators being configuration); that the status read accepts
        every configured site's peer in both storefronts (`DEPLOYMENT_AND_CONFIG.md` and
        `storefront-publication/architecture.md` "Role and service-peer identity"); that a
        restart after a rotation needs configuration naming the replacement; and that the
        site-binding shape is a site, its URL, and its service peer, where
        `docs/bare-metal-seller-quickstart.md` (around line 156, the `authority_principal` in
        `BARE_METAL_STOREFRONT_SITES_JSON`) and `helm/charts/bare-metal-storefront/values.yaml`
        (around line 30, `siteBindingsSecret`'s entry shape, Section 16's) still show a
        principal, and health's `sites` entries now report `service_peer` and
        `authority_principals`.
      - **Amended (round 10, 13.10-13.12):** `docs/development/ARCHITECTURE.md` "Kit areas" --
        `kit/config` holds the setting types storefronts share, `PositiveSeconds` and
        `SiteAuthorityUrl`, beside its values-schema generator; `DEPLOYMENT_AND_CONFIG.md`
        "Storefront agents: pass-through configuration" and "Bare-metal role configuration" --
        bare metal's typed intervals and timeouts and VM's `[capacity].poll_interval` and
        `source_confirmation_seconds` are positive, finite numbers of seconds that can be applied
        to an instant without leaving `datetime`'s range (at most the span from year 1 to the
        epoch) and at least a microsecond, the unstated source-confirmation window (three poll
        intervals) included and refused under `[capacity].poll_interval`; VM's
        `settlement_servicing_interval_seconds` and retention sweep interval are not checked so;
        and every `[capacity.sites]` URL is an HTTP(S) origin, parsed by the WHATWG URL standard
        (pydantic's `AnyHttpUrl`) with no path, credentials, query, or fragment, handed to the
        site client as its normalized origin, refused when the storefront starts under the
        site's key, not by the chart's values schema; a host the standard accepts but nothing
        resolves fails at the first poll (D6 and D14b's round-10 notes). The normative half is the storefront-publication delta's "A
        storefront that cannot publish refuses to start".
      - **Amended (Section 16 check fixes):** `DEPLOYMENT_AND_CONFIG.md`'s rollback note
        gains the bare-metal chart's closed values schema: an older chart refuses at render
        a newer values file stating a key it does not know (`helm upgrade` to the older chart
        with the newer values, or `--reuse-values`), while `helm rollback` and the
        storefront's own start are unaffected.
      - **Amended (round 12, 12 F1; `design.md` C13):** `DEPLOYMENT_AND_CONFIG.md`, a new
        Kubernetes release-topology subsection beside "Stateful service persistence"'s
        `deploy-local` text: several storefronts per registry, each storefront in its own
        release with its own provisioning service (which trusts and calls back one
        storefront); the two local releases, `helm/bare-metal-release-values.yaml`, the
        out-of-band Secrets release 2 needs, `make helm-topology-up`/`-down`/`-check`, one
        namespace; that an end-to-end scenario needing release 2 names it on its Makefile
        target and in its suite module; and the umbrella's smoke-test profile checking the
        bare-metal storefront's trust when the VM storefront is disabled.
        `ARCHITECTURE.md` "Deployment topology" ("Production and staging", and "Local
        development" for the Helm side): the supported topology is several storefronts per
        registry as separate releases, several sites per storefront through each storefront's
        per-site state, and several storefronts per site not yet supported (a provisioning
        service trusts and calls back one storefront). `TESTING.md` "Chart Render Tests": the
        umbrella's Python render tests live in `helm/tests/` and `test-render.sh` runs them
        beside each chart's.
      - **Amended (16.5's run, 16.8; `design.md` C13):** `DEPLOYMENT_AND_CONFIG.md`'s
        release-topology subsection (above) also states that `make helm-topology-up` restarts
        both releases' Deployments after its upgrades, registry then provisioning then
        storefronts, because local images keep bare tags, and never dev-env's Anvil (a
        restart keeps its contracts but loses every transaction since start-up); that `make
        helm-topology-secrets` creates every Secret both releases read from development
        values at `helm/Makefile`'s `DEV_ACCOUNT_*` indices, and what each holds, and the deal
        test's `arkhai-buyer-profiles` volume; and that `topology-check`, `test`, and
        `test-module` check the Secrets and volume their tests read.
        "Kubernetes: ConfigMap and Secret mounting": the umbrella's generated smoke-test
        profile carries the registry pins (internal registry only), the development buyer's
        and the target agent's wallet addresses, and the registry chart's
        `tests.credentialProfile` layers a Secret's profile file (locally
        `arkhai-e2e-credentials`' `e2e-secret`) into the registry smoke pod for the signing
        material no values carry, its values quoted because YAML reads an unquoted
        `0x`-prefixed value as an integer.
      Done: every document named above, and each amendment's destination, is written to describe
      the current system: `ARCHITECTURE.md` "Capacity publication and multi-domain storefront
      composition", "Storefront capacity boundary", "Kit areas", "Scope", "Site authority",
      "Local development", "Production and staging", "Operator lifecycle controls"; the
      `storefront-publication` companion's "Projection families", "Bare-metal listing shapes",
      "Storefront pool overrides", "Unknown sites and inline reconciliation", "Autonomous
      publication", "Registry convergence", "Trusted site routing", "Role and service-peer
      identity", "Settlement option reconciliation"; the `market-composition` companion's
      "Storefront composition kit" and "Settlement configuration registration";
      `DEPLOYMENT_AND_CONFIG.md`'s ConfigMap and smoke-profile rules, "Storefront agents:
      pass-through configuration" (the agents map, address-book mount, local release, two homes of
      retired keys, rollback), a new "Storefront startup and site trust" (startup refusal, origin
      rule, per-site service-peer trust, durations and the confirmation window, the servicing
      interval, the API-credit storefront's refusals, system status), "Per-domain stack
      composition", a new "Release topology", "Combined compute-family storefront", "Migrations at
      startup" (bare metal's frozen table), "Storefront listing shapes and pool overrides",
      "Contact-exchange contacts", and "Bare-metal role configuration" (files, keys, loader, the
      chart); `TESTING.md`'s loop table, traps, and "Chart Render Tests"; `docs/configuration.md`;
      the dispatch attachment; both seller quickstarts; `ROADMAP.md` (17.5); the index (17.6).
      `openspec/specs/README.md`: no new capability or companion, so unchanged. The
      `openspec/specs/site-capacity/spec.md` evidence line 8.5 edited outside the deltas is
      recorded below. The five `spec.md` files the deltas cover were written by the archive
      (17.11).
- [x] 17.10 **Documentation citations.** `make check-doc-citations
      CHANGE=share-site-projection-state`, resolving every match, then `bunx
      @fission-ai/openspec@1.14.0 validate share-site-projection-state --strict`.
      Done after promotion: `make check-doc-citations CHANGE=share-site-projection-state` — OK,
      every cited path resolves and none is a tombstone. The unscoped run reports nothing in a
      document this closeout edited (its 16 matches are in `VALIDATION_RUNBOOK.md`'s
      `scripts/validate/` lines and other changes' documents, all pre-existing); every `helm/`,
      `domains/`, `kit/`, and `dev-env/` path the promoted text cites, which the check does not
      scan, was checked to exist. `bunx @fission-ai/openspec@1.14.0 validate
      share-site-projection-state --strict`: valid. Both rerun at `47d9c67`, after the fix round,
      with the same results.
- [x] 17.11 **Archival.** `bunx @fission-ai/openspec@1.14.0 archive share-site-projection-state
      -y`, merging the five deltas (`api-credits` added in Section 15's check); the index row links the archive.
      **Amended (round 05/06, 05 F11; moved here from 17.10 in round 08, 08 F9):** after the
      `archive` command and before the commit, confirm that the requirement
      `domains/vms/storefront/src/market_storefront/startup_refusal.py`'s docstring cites, "A
      storefront that cannot publish refuses to start" in
      `openspec/specs/storefront-publication/spec.md`, exists there; until the archive it is
      only in the change's delta.
      Done (2026-10-19, at `47d9c67`'s tree): the deltas were not synchronized by hand (no
      requirement they add was in a permanent `spec.md`), so `bunx @fission-ai/openspec@1.14.0
      archive share-site-projection-state -y` merged them, without `--skip-specs`: `api-credits` +1,
      `deployment-state` +1 ~1, `market-composition` +2 ~1, `negotiation-protocol` +1,
      `storefront-publication` +2 ~9; archived as
      `openspec/changes/archive/2026-10-19-share-site-projection-state/`. The merged specs' diff
      shows each added requirement once, each modified one replaced in place, no duplicate
      requirement heading, and no other requirement changed. "A storefront that cannot publish
      refuses to start", which `startup_refusal.py`'s docstring cites, now exists in
      `openspec/specs/storefront-publication/spec.md`. The index row and the unowned-items note,
      and `ROADMAP.md`'s closed Goal 4 row, link the archive. `openspec validate --specs
      --strict`: 23 passed, 0 failed. `make check-change-index`: OK.

Closeout triage (reviews 14 and 15, 2026-10-20; `reviews/14-closeout.triage.md`), documentation
edits: `storefront-publication/spec.md`'s bare-metal pool-override Evidence reads the held
projection and cites existing tests (14 F1); `deployment-state/spec.md`'s bare-metal role, and
`DEPLOYMENT_AND_CONFIG.md`'s bare-metal site reporting, keep diagnostics credential-free and let a
site's public URL appear in its error text (14 F2); the open questions moved to
`kit-owned-storefront-shell` and `unbacked-bare-metal-listings`, with their index rows' Notes
(14 F3 / 15 F3); 17.8 states the Helm evidence's gap (14 F5 / 15 F1); 17.3 and 16.5 corrected
(14 F6); present tense in `ROADMAP.md` and the `storefront-publication` companion (14 F7); two
index sentences reworded as resolved (14 F8); `docs/seller-quickstart.md`'s registry pin live
(14 F9).

## Design promotion record

`spec.md` destinations marked *(archive)* were written by 17.11's archive from this change's
deltas. Every other destination was written by hand at closeout.

| Accepted decision | Permanent location |
|---|---|
| D0: a prerequisite carved out of `kit-owned-listing-and-fulfillment-lifecycles`; corrections 1–10 | Change history (`design.md`); the result in `docs/development/ROADMAP.md` Goal 4 and the index row |
| D1: each dedicated compute storefront publishes its own domain on a timer loop; the combined storefront publishes VM only | `openspec/specs/storefront-publication/spec.md#requirement-publication-runs-as-a-controllable-storefront-lifecycle-loop` *(archive)*; `openspec/specs/storefront-publication/architecture.md#autonomous-publication`; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| D2: one injected `SiteProjectionState` per process, both families of every site, one operation at a time per family | `openspec/specs/market-composition/spec.md#requirement-per-site-projection-state-is-kit-owned-and-held-once-per-process` *(archive)*; `openspec/specs/market-composition/architecture.md#storefront-composition-kit`; `docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition` |
| D3: refreshes update the state in place, keeping last-known generations; VM's admin refresh is the poller's cycle through the controller | `openspec/specs/storefront-publication/spec.md#requirement-projection-backed-listing-candidate-derivation` *(archive)*; `openspec/specs/market-composition/architecture.md#storefront-composition-kit`. Retiring the route: handed to `kit-owned-storefront-shell` |
| D4: every storefront holds both families; refresh categories; a topology error checks every family; a capacity event refreshes its site's buckets first | `openspec/specs/storefront-publication/spec.md#requirement-projection-backed-listing-candidate-derivation` *(archive)*; `openspec/specs/storefront-publication/architecture.md#projection-families` and `#unknown-sites-and-inline-reconciliation` |
| D5: a domain checks generation trust when it reads; a source check confirms only from a freshly confirmed generation within `[capacity].source_confirmation_seconds` | `openspec/specs/storefront-publication/spec.md#requirement-the-sellers-inventory-guard-checks-a-listing-against-its-own-source` and `#requirement-bare-metal-opening-rechecks-its-listing-against-its-source` *(archive)*; `openspec/specs/storefront-publication/architecture.md#projection-families` and `#bare-metal-listing-shapes`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust`; `docs/development/TESTING.md#2-integration-tests` |
| D6: a storefront that cannot publish refuses to start; missing terms hold pools instead | `openspec/specs/storefront-publication/spec.md#requirement-a-storefront-that-cannot-publish-refuses-to-start` *(archive)*; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust`; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary`; `openspec/specs/storefront-publication/architecture.md#autonomous-publication` |
| D6: `run_cycle` is the one cycle boundary; one recorded outcome per invocation; disclosed errors; `lifecycle` in status | `openspec/specs/market-composition/spec.md#requirement-a-loop-records-each-cycles-outcome-with-the-controller` *(archive)*; `openspec/specs/storefront-publication/spec.md#requirement-operator-visible-acceptance-and-projection-state` *(archive)*; `openspec/specs/market-composition/architecture.md#storefront-composition-kit`; `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` |
| D6 (2026-10-16): the registry switch removed; retired keys refused under their own heading | `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration` and `#storefront-startup-and-site-trust` |
| D6 (2026-10-16, revised 2026-10-18): per-site capacity-event outcomes; names declared as the fan-out's children; recorders issued only to them | `openspec/specs/market-composition/spec.md#requirement-a-loop-records-each-cycles-outcome-with-the-controller` *(archive)*; `openspec/specs/market-composition/architecture.md#storefront-composition-kit` |
| D6 (2026-10-16, revised 2026-10-18): the local release sells (`helm/local-values.yaml`, the dev-env address book, `storefront.agents` keyed by name) | `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration`; `docs/development/TESTING.md#chart-render-tests` |
| D6, as delivered for bare metal (Sections 13, 14): the root builds the state and wake; steps at build, timers at start; loops stopped at shutdown; `BareMetalPublicationError`; the window resolved at composition; the per-site derivation summary; a preview records nothing in either storefront | `openspec/specs/storefront-publication/architecture.md#autonomous-publication` and `#projection-families`; `docs/development/DEPLOYMENT_AND_CONFIG.md#bare-metal-role-configuration` |
| D6 (round 10): durations are positive seconds a `datetime` can absorb, through `kit/config`'s `PositiveSeconds` | `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust`; `docs/development/ARCHITECTURE.md#kit-areas` |
| D6 (2026-10-19, P1): the API-credit storefront's loops on the controller; a loop registers as a timer loop or a fan-out; `start_loops()` the only start | `openspec/specs/market-composition/spec.md#requirement-storefront-timer-loops-are-held-and-stepped-through-one-kit-controller` *(archive, modified)*; `openspec/specs/market-composition/architecture.md#storefront-composition-kit`; `docs/development/ARCHITECTURE.md#operator-lifecycle-controls`; `docs/development/TESTING.md#2-integration-tests` |
| D6 (2026-10-19): API-credit status reports `lifecycle` and is the administrator's signed read | `openspec/specs/api-credits/spec.md#requirement-api-credit-system-status-is-the-administrators-signed-read` *(archive)*; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust` |
| D14, D14a: bare metal reads the storefront files under VM's keys and loader shape | `openspec/specs/deployment-state/spec.md#requirement-independently-deployable-bare-metal-seller-role` *(archive, modified)*; `docs/development/DEPLOYMENT_AND_CONFIG.md#bare-metal-role-configuration` and `#per-domain-stack-composition`; `docs/configuration.md` "Bare-metal storefront"; `docs/bare-metal-seller-quickstart.md` "Configure public bindings" |
| Owner principle: a storefront's configuration reaches it through its configuration system, held by review, never a runtime refusal | `openspec/specs/deployment-state/spec.md#requirement-a-storefronts-configuration-reaches-it-through-its-configuration-system` *(archive)*; `docs/development/DEPLOYMENT_AND_CONFIG.md#kubernetes-configmap-and-secret-mounting`. Its mechanical check is `check-storefront-environment-reads`' |
| D14b: per-site trust from each site's durable service peer in both storefronts; `ServicePeerTrust`; the failed-reload rule; `[provisioning.identity]` retired; early lease termination at the reservation's site; the status read's union; bare metal seeding at start, reservations pinning the peer, the identity routes, administrators in configuration | `openspec/specs/storefront-publication/spec.md#requirement-site-authority-principals-rotate-with-bounded-overlap` *(archive, modified)*; `openspec/specs/deployment-state/spec.md#requirement-independently-deployable-bare-metal-seller-role` *(archive)*; `openspec/specs/storefront-publication/architecture.md#trusted-site-routing` and `#role-and-service-peer-identity`; `docs/development/ARCHITECTURE.md#site-authority`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust`; `docs/bare-metal-seller-quickstart.md` "Configure public bindings" and "Resetting the storefront database" |
| D14b (round 10 and its follow-up): a site URL is an HTTP(S) origin parsed by the WHATWG standard, through `kit/config`'s `SiteAuthorityUrl` | `openspec/specs/storefront-publication/spec.md#requirement-a-storefront-that-cannot-publish-refuses-to-start` *(archive)*; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-startup-and-site-trust`; `docs/development/ARCHITECTURE.md#kit-areas` |
| D14c: the values-schema generator in `kit/config`; each storefront writes only its own chart's schema | `docs/development/ARCHITECTURE.md#kit-areas`; `docs/development/TESTING.md#chart-render-tests` |
| Owner principle: a domain's tooling never writes another domain's artifact, as guidance no check enforces | `docs/development/ARCHITECTURE.md#scope` |
| D14d: Alkahest release conditions derived by `kit/alkahest` for every domain; release models declared per domain; the invariant held in the kit's materialization; the escrow-shape guard fails closed | `openspec/specs/storefront-publication/spec.md#requirement-an-alkahest-listing-advertises-its-release-conditions` *(archive)*; `openspec/specs/negotiation-protocol/spec.md#requirement-an-alkahest-obligation-uses-exactly-the-release-condition-its-listing-authorizes` *(archive)*; `docs/development/ARCHITECTURE.md#kit-areas`; `openspec/specs/storefront-publication/architecture.md#settlement-option-reconciliation`; `openspec/specs/market-composition/architecture.md#settlement-configuration-registration`; `docs/configuration.md` "Bundled policies" |
| 7.7, 7.8: no Alkahest deal accepted without its plan; `settles_from_agreement`; `SettlementPlanMaterializationError` | `openspec/specs/negotiation-protocol/spec.md#requirement-an-alkahest-obligation-uses-exactly-the-release-condition-its-listing-authorizes` *(archive)*; `openspec/specs/market-composition/architecture.md#settlement-configuration-registration` |
| C1: the bare-metal `publish` command is an API client; `--abort-all`; bare metal's close, pause, and resume routes | `openspec/specs/storefront-publication/spec.md#requirement-publication-runs-as-a-controllable-storefront-lifecycle-loop` *(archive)*; `openspec/specs/storefront-publication/architecture.md#autonomous-publication`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides`; `docs/bare-metal-seller-quickstart.md` "Start and inspect"; the seller close's durability is the existing `#requirement-a-sellers-close-is-durable` |
| C2: the `site-projections` step is the poller's cycle | `openspec/specs/market-composition/spec.md#requirement-per-site-projection-state-is-kit-owned-and-held-once-per-process` *(archive)*; `docs/development/TESTING.md#2-integration-tests` |
| C3: the accepted-generation table frozen; override status from the held projection | `openspec/specs/storefront-publication/spec.md#requirement-bare-metal-joins-the-site-scoped-pool-override-store` *(archive, modified)*; `openspec/specs/storefront-publication/architecture.md#storefront-pool-overrides`; `docs/development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup` |
| C4 (P2): VM's interval keys; `settlement_servicing_interval_seconds` in every storefront, the old key refused; one catalogue of retired keys beside the chart's own block; the rollback notes | `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration`, `#storefront-startup-and-site-trust`, and `#bare-metal-role-configuration` |
| C5: bare-metal health and status read held state | `openspec/specs/storefront-publication/spec.md#requirement-operator-visible-acceptance-and-projection-state` *(archive)*; `docs/bare-metal-seller-quickstart.md` "Start and inspect" |
| C6: bare-metal scenarios hold the loops and step `site-projections` | `docs/development/TESTING.md#2-integration-tests` |
| C7: an operation that does not reconcile inline refreshes nothing | `openspec/specs/storefront-publication/architecture.md#unknown-sites-and-inline-reconciliation` |
| C8: the bare-metal chart on the storefront chart's agent shape; derivations; closed schema; service links off; `port` a setting | `openspec/specs/deployment-state/spec.md#requirement-independently-deployable-bare-metal-seller-role` *(archive)*; `docs/development/DEPLOYMENT_AND_CONFIG.md#bare-metal-role-configuration` and `#kubernetes-configmap-and-secret-mounting`; `docs/development/TESTING.md#chart-render-tests`; `docs/development/ARCHITECTURE.md#production-and-staging` |
| C9: Compose and the lane mount files; the committed development overlay | `docs/development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition` |
| C10: an absent or non-positive lease bound holds the pool; every `[registry].urls` entry published to | `openspec/specs/storefront-publication/spec.md#requirement-a-storefront-that-cannot-publish-refuses-to-start` *(archive)*; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides` |
| C11: `[Settlement]`, `[Wallet]`, `[Chains]`, and the overlay's wallet key in place of the variables | `docs/development/DEPLOYMENT_AND_CONFIG.md#bare-metal-role-configuration` |
| C12: documentation | This record |
| C13: several storefronts per registry, each in its own release with its own provisioning service; the two local releases, their targets, Secrets, and restart; the smoke profile's derived keys and credential profile | `docs/development/ARCHITECTURE.md#production-and-staging` and `#local-development`; `docs/development/DEPLOYMENT_AND_CONFIG.md#release-topology` and `#kubernetes-configmap-and-secret-mounting`; `docs/development/TESTING.md#chart-render-tests` |
| Validation tiers for chart work | `docs/development/TESTING.md#chart-render-tests` |
| Owner principle: the compute storefront pulls every resource pool once for all listing types | `openspec/specs/storefront-publication/spec.md#requirement-projection-backed-listing-candidate-derivation` *(archive)*; `openspec/specs/storefront-publication/architecture.md#projection-families` |
| Owner principle: storefronts converge on one compute storefront | Not promoted: a future `ROADMAP.md` goal, as `design.md` records |
| Implementation findings | Change history (`design.md`); the behaviour each states is in the destinations above and in the code's docstrings |
| Open questions left for the owner | `design.md`, "Open questions"; VM's and the API-credit storefront's stop hooks recorded as a current limitation in `openspec/specs/storefront-publication/architecture.md#autonomous-publication`. At the closeout triage: the stop hooks moved to `openspec/changes/kit-owned-storefront-shell/design.md#questions-to-settle-before-planning`, the six settlement questions to `openspec/changes/unbacked-bare-metal-listings/design.md#open-questions` (question 12), and the version bumps settled (14 F4) |
| Section 8's edit of a permanent spec outside the deltas | `openspec/specs/site-capacity/spec.md`'s evidence line for per-site load-state reporting, citing `kit/capacity-publication/tests/unit/test_site_projection_state.py` |
| Roadmap currency (17.5) | `docs/development/ROADMAP.md`, Goal 4's current state and its closed gap row; Goal 7's current state |
| Campaign index currency (17.6) | `openspec/changes/README.md`, this change's row and its Goal 7 graph line |
| Capability index | `openspec/specs/README.md`: unchanged; no new capability or companion |
