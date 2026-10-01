# Tasks — bare-metal mock-provisioned deal

Design decided and planned 2026-10-01. Both prerequisites are archived:
`bare-metal-publication-reads-pool-declarations` built the bare-metal end-to-end lane,
and `kit-owned-storefront-loop-lifecycle` built the bare-metal lifecycle pause and steps.
Scope was widened during design to parity with VM's typed-client deal, absorbing work
migrated from three sibling changes; `design.md` records each decision.

## 1. Design

- [x] 1.1 **Decision gate.** Decide where the bare-metal mock results live — in the mock
      Ansible service, or contributed by the bare-metal adapter — and record it in
      `design.md`. Amended by 1.11.
- [x] 1.2 **Decision gate.** Establish which typed client drives the buyer's side of
      bare-metal fulfillment, result, access, and teardown, and record it.
- [x] 1.3 **Decision gate.** Decide whether the release-qualified real-host scenario stays
      parked or is removed, and record the consequence for the permanent protected-lane
      requirement. Settled by 1.15.
- [x] 1.4 **Decision gate.** Decide which loops the lifecycle pause holds and which get a
      step, and record it. Implemented by `kit-owned-storefront-loop-lifecycle`.
- [x] 1.5 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations. Order the
      sections so every lane stays green at each step: kit extractions with VM and
      API-credit rebinding; bare-metal behaviour (negotiation runtime, settlement-started
      fulfillment, lease-owned release, publication dry run, mock); shared compute deal
      stages with VM moved onto them; the bare-metal scenario; the pipeline. Resolve the
      planning checks `design.md` names: the generic lease routes for bare-metal
      reservations, the identity overlay split, and `multi_registry`'s registry use.
      Planned as Sections 4–11. The three checks and one new finding (the Alkahest path
      never commits or registers its lease) are recorded in `design.md`.
- [x] 1.6 **Decision gate.** Decide the scenario's scope. Decided: VM's typed-client deal
      stage for stage, every dry run included, plus a second deal proving buyer teardown
      and capacity reuse ("The scenario is VM's deal, stage for stage").
- [x] 1.7 **Decision gate.** Decide whether stage definitions are shared. Decided:
      `helpers/compute_deal_stages.py` with a per-domain driver, compute domains only;
      VM moves onto it first ("Compute deal stages are shared").
- [x] 1.8 **Decision gate.** Decide how bare metal reaches multi-round negotiation and
      force-accept. Decided: compose it onto the kit negotiation runtime in this change,
      migrated from `bare-metal-and-credits-domain-stacks` ("Bare metal negotiates
      through the kit runtime").
- [x] 1.9 **Decision gate.** Decide whether the change blocks on
      `kit-owned-storefront-shell`. Decided: no; the deal controls become kit route
      services here ("Deal controls are kit-owned route services").
- [x] 1.10 **Decision gate.** Decide who owns capacity release. Decided: the lease
      lifecycle, for every offering mode; the storefront's direct site release is removed
      ("The lease lifecycle owns release for every offering mode").
- [x] 1.11 **Decision gate.** Decide the executor seam and where the mock mechanism lives.
      Decided: an action-keyed executor table in the job service and
      `kit/compute-executor-mock` ("Executors are routed by action, and each adapter owns
      its mock").
- [x] 1.12 **Decision gate.** Decide where restart recovery is proven. Decided: storefront
      integration tests, as VM's is ("Restart recovery is proven at integration level, as
      VM's is").
- [x] 1.13 **Decision gate.** Decide how lanes obtain images. Decided: built once per
      pipeline run and shared ("Lanes run on images built once").
- [x] 1.14 **Decision gate.** Decide whether API credits gets its own lane here. Decided:
      yes, migrated from `apicredits-end-to-end-lane` ("API credits runs in its own
      lane").
- [x] 1.15 **Decision gate.** Decide the real-host scenario's disposition. Decided: kept,
      deactivated, under a marker no lane selects ("The real-host scenario stays,
      deactivated").

## 3. Buyer-side deal requirements

Former tasks 3.1–3.4 are properties of the `market` command, which this change's
typed-client scenario cannot observe ("Buyer CLI requirements belong with the buyer").
Former tasks 3.5–3.6 are storefront behaviour proven at integration level.

- [x] 3.1 **Migrated** to `bare-metal-and-credits-domain-stacks` 4b.6 (demand is exact
      and buyer-bounded), with its `buyer-orchestration` delta.
- [x] 3.2 **Migrated** to `bare-metal-and-credits-domain-stacks` 4b.7 (a provisioning
      route offered to the buyer is refused).
- [x] 3.3 **Migrated** to `bare-metal-and-credits-domain-stacks` 4b.8 (result and
      evidence decode strictly).
- [x] 3.4 **Migrated** to `bare-metal-and-credits-domain-stacks` 4b.9 (teardown is
      authenticated and idempotent at the buyer). The storefront half — a repeated
      teardown returns the same operation and capacity is released once — is proven by
      this change's second deal and the `physical-provisioning` delta.
- [ ] 3.5 **Restart recovery.** Bare-metal storefront integration tests rebuild the
      application over the same database file and a fake site after settlement commit
      and after teardown acceptance; the buyer retrieves the same operation with no
      second obligation, mechanism selection, or teardown, and duplicate polling and
      result reads are idempotent. Planned in 8.6.
- [ ] 3.6 **Pause survives restart.** In the same suite, an authenticated trading pause
      remains active across the rebuild and new negotiations are refused until an
      authenticated resume. Planned in 8.6.

## 4. Compute executor mock kit and the executor seam

Decision: "Executors are routed by action, and each adapter owns its mock". VM's lane
must stay green at the end of this section with no scenario change.

- [ ] 4.1 Create `kit/compute-executor-mock` (`arkhai-kit-compute-executor-mock`,
      `market_compute_executor_mock`), standard library and pydantic only:
      `pyproject.toml`, `Makefile`, `src/market_compute_executor_mock/__init__.py`,
      `rules.py` (the rule model, store, and matching now in VM's `MockRule` and
      `ProgrammableMockAnsibleService`), `gates.py` (pause gates and job-done events),
      `evaluate.py` (the evaluate-job dry run), `routes.py` (a framework-free route
      service for add, list, delete, resume, and evaluate, raising an HTTP-shaped error
      as `market_storefront_kit.LifecycleRouteError` does). Unit tests in
      `tests/unit/test_rules.py`, `test_gates.py`, `test_routes.py`, moved from
      `provisioning/compute/service/tests/unit/services/test_programmable_mock.py`
      where they test mechanism rather than VM output.
- [ ] 4.2 Register the kit in `kit/Makefile` (`test-compute-executor-mock`,
      `dist-compute-executor-mock`, both added to `test` and `dist-ci`).
- [ ] 4.3 Give the job service an executor table:
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/job_service.py`
      gains `register_executor(actions, executor)`; `_process_job` selects by
      `params.action` with the constructor's Ansible service as the default, and
      `notify_job_done` goes to the executor that ran the job. Persistence, host
      validation, inventory rendering, and `parse_playbook_result` are unchanged.
      Focused tests in `provisioning/compute/service/tests/unit/services/test_job_service.py`.
- [ ] 4.4 Rebuild VM's mock on the kit:
      `vm_provisioning_adapter/services/mock_ansible_service.py` keeps its VM default
      output and composes the kit's rules and gates;
      `vm_provisioning_adapter/controllers/test_controller.py` binds the kit route
      service at the unchanged `/test/mock-rules` paths and keeps the shared
      `/test/jobs/*` routes; `domains/vms/provisioning/adapter/pyproject.toml` depends on
      the kit. VM-specific cases stay in `test_programmable_mock.py`;
      `provisioning/compute/service/tests/integration/test_test_controller.py` passes
      unchanged.
- [ ] 4.5 Add the bare-metal mock:
      `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/services/bare_metal_mock_executor.py`
      on the kit, whose default grant emits `node_grant_access_data` (tenant user and
      SSH port; tenant address from the registered host record, as a real run's) and
      whose default reclaim emits `node_reclaim_access_data`;
      `bare_metal_provisioning_adapter/runtime.py` registers the real Ansible service,
      or under the mock profile the mock, for `NODE_GRANT_ACCESS_ACTION` and
      `NODE_RECLAIM_ACCESS_ACTION`; new `controllers/test_controller.py` binds the kit
      route service at `/test/bare-metal/mock-rules`; `routers.py` exposes it;
      `pyproject.toml` depends on the kit. Tests in
      `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_mock_executor.py`:
      default output parses through the real result path into the credentials
      `BareMetalFulfillmentProvider.fetch_credentials` reads; a bare-metal rule never
      matches a VM job and the reverse.
- [ ] 4.6 Compose it: `provisioning/compute/service/src/compute_provisioning_service/container.py`
      registers the bare-metal executor on the VM runtime's job service;
      `main.py` mounts the bare-metal test router under the mock profile beside VM's.
      Provisioning readiness reports each adapter's executor mode
      (`domains/vms/provisioning/client/src/vm_provisioning_operator/models.py` and the
      status service that fills it). Integration test
      `provisioning/compute/service/tests/integration/test_bare_metal_mock_profile.py`: a
      bare-metal grant under the mock profile reaches `active` through fulfillment
      convergence, held and released by a bare-metal rule.
- [ ] 4.7 Typed clients: `provisioning/compute/src/compute_provisioning/client.py` route
      contracts for `/test/bare-metal/mock-rules*`;
      `e2e-tests/src/e2e_harness/provisioning_test_client.py` gains the bare-metal rule
      methods; `provisioning/compute/service/tests/integration/test_provisioning_client_endpoint_coverage.py`
      covers them.
- [ ] 4.8 Relock every project whose dependencies changed (`make lock PROJECTS=...` for
      the two adapters, `provisioning/compute/service`, and `kit/compute-executor-mock`)
      and run the provisioning service, both adapters', and the kit's suites.

## 5. Deal controls as kit route services

Decision: "Deal controls are kit-owned route services". Wire paths and canonical client
methods are unchanged; VM and API credits rebind before bare metal binds (Section 6).

- [ ] 5.1 `kit/storefront/src/market_storefront_kit/deal_control_routes.py`: the
      stage-event read over `core_storefront.stage_log` (filters and streaming as VM's
      `system_controller.stream_events`), evaluate-negotiate over an injected round-zero
      policy callable, and force-accept over core `NegotiationService.force_accept`.
      Unit tests in `kit/storefront/tests/unit/test_deal_control_routes.py`.
- [ ] 5.2 `kit/settlement-runtime/src/market_settlement_runtime/admin_routes.py`: settle
      verify over the mechanism adapter's escrow read with no adoption, evaluate-settle
      over a new `FulfillmentPreviewHook` port in `ports.py`, and settle wait as a
      bounded long-poll over an injected settle-status reader and terminal predicate.
      Unit tests in `kit/settlement-runtime/tests/unit/test_admin_routes.py`.
- [ ] 5.3 `kit/capacity-publication/src/market_capacity_publication/admin_routes.py`:
      admin reserve through a listing's capacity binding, and the capacity-released
      callback dispatching to an injected domain release hook. Unit tests in
      `kit/capacity-publication/tests/unit/test_admin_routes.py`.
- [ ] 5.4 Rebind VM: `domains/vms/storefront/src/market_storefront/controllers/system_controller.py`
      (events), `listings_controller.py` (evaluate-negotiate),
      `negotiations_controller.py` (force-accept), `settle_controller.py` (verify,
      evaluate, wait), `admin_controller.py` (portfolio reservations, capacity-released);
      VM's evaluate-settle job-spec build becomes its `FulfillmentPreviewHook` from
      `services/admin_settle_service.py`, whose remaining code is removed;
      `middleware/admin_identity.py` keeps its route recognition. Existing VM storefront
      suites pass unchanged.
- [ ] 5.5 Rebind API credits: `domains/apicredits/storefront/src/apicredits_storefront/controllers/system_controller.py`
      (events), `negotiations_controller.py` (force-accept), `settle_controller.py`
      (wait). Existing API-credit suites pass unchanged.
- [ ] 5.6 Bump and relock the three kits and their consumers; run the kit, VM storefront,
      and API-credit storefront suites. The VM lane passes unchanged.

## 6. Bare metal on the kit negotiation runtime

Decision: "Bare metal negotiates through the kit runtime" (migrated
`bare-metal-and-credits-domain-stacks` 4a.1, 4a.2, runtime half of 4a.3).

- [ ] 6.1 Re-verify (former 4a.1) that `negotiation_service.py`, `negotiation.py`, the
      negotiate routes in `api.py`, and thread persistence in `sqlite_client.py` are
      domain-local and no bare-metal module imports `market_negotiation_runtime`.
- [ ] 6.2 Add `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/negotiation_runtime.py`
      implementing `NegotiationDomainHooks` (former 4a.2): `validate_opening` decoding
      the closed `bare_metal.v1` demand and calling `opening_guard.py`'s domain function;
      physical selection and exact settlement-option validation as `evaluate_round`
      inputs; `agreement_terms`; `build_artifacts` producing the accepted obligation the
      settlement runtime consumes; `place_hold` as today. The seller policy in
      `negotiation.py` stays as the domain's policy, now evaluated by the runtime for
      every round.
- [ ] 6.3 Serve the existing negotiate and listing-negotiation routes in `api.py` over the
      runtime, compose it in `runtime.py`, and bind the Section 5 storefront-kit route
      services (events, evaluate-negotiate, force-accept). Tombstone
      `negotiation_service.py`; remove the hook class from `negotiation.py` and thread
      persistence from `sqlite_client.py`, with a migration in `migrations.py` if the
      runtime's tables differ.
- [ ] 6.4 Tests (with former 4a.6's focused cases): rewrite `test_negotiation.py` and
      `test_http_negotiation.py` for multi-round negotiation, force-accept, and
      evaluate-negotiate; opening refusal for each forbidden demand field; terms-mismatch
      refusal; the conformance matrix `multi-domain-storefront-composition` added, run
      under the bare-metal contract.

## 7. Bare-metal settlement, fulfillment, and release

Decisions: "Settlement starts fulfillment", "The lease lifecycle owns release for every
offering mode", "The Alkahest path commits the lease window and registers the lease",
"Bare-metal publication has a dry run".

- [ ] 7.1 Settlement starts fulfillment: `settlement_service.py` invokes the fulfill hook
      once after `verify` adopts the obligation and drops `status`'s no-fulfillment
      assertion; `settlement_composition.py` resumes verified obligations with no started
      fulfillment each servicing cycle; `domain_runtime.py` keeps `fulfill_bare_metal`
      as the hook. Remove `POST /api/v1/fulfillments/begin` from `api.py` and
      `BareMetalFulfillRequest` from `models.py`; remove `begin()` from
      `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/fulfillment.py`.
- [ ] 7.2 Commit and register: `fulfillment_service.py` commits the reservation with the
      materialized lease window before scheduling, as `hosted_lifecycle.py` does, and
      registers the lease (`offering_mode=bare_metal`, executor target, create job) once
      fulfillment is active; `site_clients.py`'s `SelectedSiteFulfillmentClient` gains
      `register_lease`, `terminate_lease`, and `get_lease`, routed by the reservation's
      recorded site.
- [ ] 7.3 Provider-neutral release: move `VmReleaseExecutor`, `FulfillmentTeardownPort`,
      `FulfillmentServiceTeardownPort`, and `VmFulfillmentReleaseJobPort` from
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/release.py` into
      `provisioning/compute/src/compute_provisioning/release.py`
      as `FulfillmentReleaseExecutor` and `FulfillmentReleaseJobPort`; tombstone
      `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/release.py`
      after moving `get_physical_host_id` to its remaining caller's module; both
      adapters' `runtime.py` and `bundle.py` register the shared components;
      `container.py`'s `_make_release_job_dispatcher` reads the aggregate for both modes.
      Tests: `provisioning/compute/tests/unit/test_release.py`,
      `provisioning/compute/service/tests/unit/services/test_release_executors.py`,
      `test_ledger_lease_lifecycle.py`, and `integration/test_legacy_backfill_teardown.py`
      updated; a bare-metal expiry case in `integration/test_bare_metal_leases_api.py`
      showing the aggregate leaves `active` and capacity stays held until `torn_down`.
- [ ] 7.4 Teardown through lease termination: `fulfillment_service.py`'s teardown calls
      the site's contract lease terminate and returns the lease operation; `status()`
      no longer calls `capacity_client.site(...).release(...)`; the lifecycle records
      `released` only from the capacity-released callback, bound in `api.py` through the
      Section 5 capacity-publication route service with the site's authority principal
      verified as the caller. `api.py` also binds settle verify, evaluate-settle (a
      bare-metal `FulfillmentPreviewHook` previewing scheduling and materialization with
      no writes), settle wait, and admin reserve.
- [ ] 7.5 Publication dry run: `lifecycle_steps.py` registers a preview for
      `publication` reporting the opens, closes, refreshes, and holds one pass would
      make; `publication_composition.py` and `publication.py` expose the non-publishing
      pass it needs.
- [ ] 7.6 Tests: `test_settlement.py` and `test_http_settlement.py` (settle starts
      fulfillment once; servicing resumes an unstarted one; `begin` is gone);
      `test_fulfillment_service.py` (commit with window, lease registration, teardown
      through terminate, repeated teardown returns the same lease, release only on
      callback); `test_site_clients.py`; `test_publication_cycle.py` (preview applies
      nothing); `test_app_composition.py`; `domains/bare_metal/buyer/tests/test_buyer_composition.py`.

## 8. Shared compute deal stages and the VM scenario

Decision: "Compute deal stages are shared". Behaviour-neutral for VM; the VM lane is the
gate.

- [ ] 8.1 Move shared helpers out of `e2e-tests/tests/e2e/roles/scenarios/vms/`: the
      escrow helper to `tests/e2e/roles/helpers/escrow.py` (tombstone
      `scenarios/vms/escrow_helper.py`); `DealLease`, `advance_fulfillment_to`,
      `wait_for_stage_event`, `delete_mock_rules_if_present`, `advance_storefront`,
      `dry_run_storefront`, `pause_storefront`, and the convergence-pause fixture body to
      `tests/e2e/roles/helpers/compute_deal.py`. Update every importer:
      `scenarios/vms/conftest.py`, `test_full_deal_buyer_cli.py`,
      `test_buy_oneshot_buyer_cli.py`, `test_compute_dynamic_listings.py`,
      `test_listing_shapes.py`, `test_multi_registry.py`, `test_non_erc20_settlement.py`,
      and `tests/unit/test_escrow_helper_rpc_url.py` (re-checked by grep when the move
      is made).
- [ ] 8.2 Add `tests/e2e/roles/helpers/compute_deal_stages.py`: `ComputeDealState`
      (from VM's `DealState`), the `ComputeDealDriver` protocol, and one stage class per
      shared VM stage (00, 00a–00e, 00f1, 00g, 00h, 04a, 05a, 05b, 06b, 07, 07b, 08a,
      08c, 08b, 09a, 09b, 09bb, 09c, 10a, 10b, 11a, 11b), each preserving its stage ID,
      dry-run-then-advance shape, and `require_state` consumers.
- [ ] 8.3 Rewrite `scenarios/vms/test_full_deal.py` as ordered subclasses of the shared
      stages plus VM's own inserted stages (00f resource seed, 02b, 03a, 03b, 09a2), and
      add `scenarios/vms/compute_deal_driver.py`; `scenarios/vms/conftest.py` provides
      `deal_driver` and `deal_state`. No assertion is weakened.
- [ ] 8.4 Unit test `tests/unit/test_compute_deal_stages.py`: stage subclasses keep
      definition order, the base classes are not collected, and every state field has
      a consumer.
- [ ] 8.5 Gate: the VM lane passes with the rewritten scenario.
- [ ] 8.6 Restart integration tests (tasks 3.5, 3.6):
      `domains/bare_metal/storefront/tests/test_restart_recovery.py` rebuilds the
      production application over one database file with a loopback site
      (`tests/loopback.py`).

## 9. The bare-metal mock-provisioned deal

Decision: "The scenario is VM's deal, stage for stage".

- [ ] 9.1 Add `scenarios/bare_metal/compute_deal_driver.py`: backed pool, host record,
      and whole-host capacity declaration; publication preview then step; bare-metal
      provision terms; bare-metal rule IDs; the lease view over `/api/v1/leases/{id}`;
      evaluate-settle expectations; result with no access coordinates and access
      carrying host, port, and user, through `BareMetalFulfillmentTransport`.
- [ ] 9.2 Extend `scenarios/bare_metal/conftest.py` with the fixtures the shared stages
      request (storefront buyer, admin, and service clients; provisioning and test
      clients; registry client; `deal_state`; `deal_driver`; host registration;
      storefront pause and resume).
- [ ] 9.3 Add `scenarios/bare_metal/test_bare_metal_mock_deal.py`
      (`pytestmark = pytest.mark.e2e_bare_metal_mock_deal`): the shared stages in order,
      bare metal's publication stages in place of VM's listing stages, and the
      second-deal stages (buyer teardown sent twice returns the same operation, capacity
      released once, listing reopened).
- [ ] 9.4 Register `e2e_bare_metal_mock_deal` in `e2e-tests/pyproject.toml` and add it to
      `E2E_BARE_METAL_MODULE` in `e2e-tests/Makefile`; `e2e_bare_metal_deal` stays in no
      lane. Add `arkhai-bare-metal-buyer` to `e2e-tests/pyproject.toml` and relock.
- [ ] 9.5 Lane configuration: a host inventory record and any settings the driver
      needs in `e2e-tests/config/config-docker.yml`'s bare-metal section and
      `dev-env/bare-metal/`; the bare-metal storefront's service-peer trust for the
      site's capacity-released callback in the lane's environment
      (`make e2e-bare-metal-dev-env` in the root `Makefile`).
- [ ] 9.6 Gate: the bare-metal lane passes with publication and the mock deal.

## 10. Pipeline: images built once and an API-credit lane

Decisions: "Lanes run on images built once", "API credits runs in its own lane", "Lane
composition files".

- [ ] 10.1 Split the overlay: `compose.vms-local.yml` (VM bindings) and
      `compose.apicredits-local.yml` (API-credit bindings, including the storefront EVM
      key); tombstone `compose.local-identities.yml`; `compose.apicredits.yml` becomes
      `include`-only; `docker-compose.yml` documents layering both. Update every
      reference: `compose.vms.yml`, `domains/apicredits/compose.yml`,
      `e2e-tests/Makefile`, `.github/workflows/e2e.yml`,
      `scripts/tests/test_multi_storefront_compose.py`,
      `e2e-tests/tests/unit/test_hosted_public_boundary.py`,
      `e2e-tests/tests/e2e/roles/README.md`, `dev-env/identities/README.md`,
      `openspec/changes/repair-storefront-alkahest-configuration/tasks.md`.
- [ ] 10.2 Lane targets in `e2e-tests/Makefile`: `e2e-vm-run`, `e2e-bare-metal-run`,
      `e2e-apicredits-run` bring a lane up from loaded images and run its markers;
      `test-e2e-<lane>` becomes `build-dev` plus run; `test-e2e` runs all three in turn;
      `E2E_MODULE` drops `e2e_credits_deal` and a new `E2E_APICREDITS_MODULE` holds it;
      `e2e-images-save` and `e2e-images-load` save and load the image set
      `build-dev` produces as one zstd archive.
- [ ] 10.3 `.github/workflows/e2e.yml`: an `e2e-images` job (uv, Foundry, `make
      build-dev`, `e2e-images-save`, `actions/upload-artifact` with one-day retention);
      `e2e-vm`, `e2e-bare-metal`, and new `e2e-apicredits` jobs `needs: e2e-images`,
      download, load, run their target, and collect logs and tear down with their own
      compose files.
- [ ] 10.4 Gate: all three lanes pass from one build; record each job's duration beside
      the previous single-lane build time.

## 11. Permanent documentation

- [ ] 11.1 `docs/development/ARCHITECTURE.md`: kit layers gain `kit/compute-executor-mock`
      and the deal-control route services; "Release" states that every offering mode
      releases through the fulfillment aggregate and that storefront teardown goes
      through lease termination; the fulfillment-hook paragraph states that bare metal's
      settle path starts fulfillment.
- [ ] 11.2 `docs/development/TESTING.md`: three lanes on images built once; the loop table
      gains the bare-metal publication preview; shared compute deal stages and the
      per-domain driver; the mock profile's per-adapter executors and rule routes; the
      "blocked—not mocked" bare-metal statement replaced by the pipeline deal and the
      protected lane's distinct role.
- [ ] 11.3 `docs/development/DEPLOYMENT_AND_CONFIG.md`: the compose file list names the
      per-market overlays.
- [ ] 11.4 Promote the deltas into `openspec/specs/test-compatibility/spec.md`,
      `market-composition/spec.md`, `physical-provisioning/spec.md`, and
      `storefront-publication/spec.md`.

## 2. Closeout

- [ ] 2.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match,
      then read the comments this change adds for references to the review or
      migration that introduced them. Amended 2026-10-01 from a placeholder.
- [ ] 2.2 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.
- [ ] 2.3 **Import placement.** For each function-level import this change adds or
      touches, move it to module level unless a verified circular import or a documented
      lazy-load reason keeps it; verify each move against the real suites.
- [ ] 2.4 **Documentation compliance.** Re-check every accepted decision in `design.md`
      against `openspec/README.md`'s placement rules.
- [ ] 2.5 **Narrative compression.** Compress completed-task notes to final behaviour,
      validation evidence, deferred work, and permanent destinations.
- [ ] 2.6 **Roadmap currency.** Update Goal 7's current state (and Goal 4's, for the
      bare-metal deal and the negotiation composition) in
      `docs/development/ROADMAP.md`.
- [ ] 2.7 **Campaign index currency.** Update this change's row and the Goal 3, 4, and 7
      graphs in `openspec/changes/README.md`, and the rows of
      `bare-metal-and-credits-domain-stacks`, `kit-owned-storefront-shell`,
      `apicredits-end-to-end-lane`, and `unbacked-bare-metal-listings`, whose
      dependency on this change is satisfied.
- [ ] 2.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-mock-provisioned-deal` and resolve
      every match, including references to the tombstoned compose overlay, escrow
      helper, and release modules.
- [ ] 2.9 **End-to-end pipeline.** Confirm all three lanes pass from one image build and
      record the run, its result, and the scenarios exercising this change: VM's
      `test_full_deal.py` on the shared stages, `test_bare_metal_mock_deal.py`, and
      `test_credits_deal_buyer_cli.py` in its own lane.
- [ ] 2.10 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A deployable domain's deal runs on every pipeline run, holding, previewing, and advancing each transition | `openspec/specs/test-compatibility/spec.md` — "A deployable domain's deal runs on every end-to-end run"; `docs/development/TESTING.md` |
| Compute-family deal stages are defined once with a per-domain driver | `openspec/specs/test-compatibility/spec.md` — "Compute-family deal stages are defined once"; `docs/development/TESTING.md` |
| Each domain runs in its own lane on images built once | `openspec/specs/test-compatibility/spec.md` — "Each domain runs in its own lane on images built once"; `docs/development/TESTING.md` |
| Bare-metal restart recovery is proven at integration level | `openspec/specs/test-compatibility/spec.md` — "Bare-metal storefront restart recovery is proven at integration level" |
| Deal controls are kit-owned route services | `openspec/specs/market-composition/spec.md` — "Storefront deal controls are kit-owned route services"; `docs/development/ARCHITECTURE.md` kit layers |
| Mock executors share `kit/compute-executor-mock`; executors are routed by action | `openspec/specs/market-composition/spec.md` — "Mock executors share one compute-family kit"; `openspec/specs/physical-provisioning/spec.md` — "Executor actions route to the owning adapter's executor"; `docs/development/TESTING.md` |
| Bare metal composes the kit negotiation runtime | `openspec/specs/market-composition/spec.md` — "Kit-owned synchronous negotiation runtime" |
| Lease release delegates to durable fulfillment teardown for every offering mode; storefront teardown goes through lease termination | `openspec/specs/physical-provisioning/spec.md` — "Lease release delegates to durable fulfillment teardown", "Storefront teardown goes through lease termination"; `docs/development/ARCHITECTURE.md` "Release" |
| Settlement starts bare-metal fulfillment; the Alkahest path commits and registers its lease | `openspec/specs/storefront-publication/spec.md` — "Complete bare-metal seller lifecycle"; `docs/development/ARCHITECTURE.md` |
| Lane composition files split per market | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/TESTING.md` |
| Scope migrations, the real-host scenario's disposition, and why the scenario uses typed clients | This change's `design.md` |
