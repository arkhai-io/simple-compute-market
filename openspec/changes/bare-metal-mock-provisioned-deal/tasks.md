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
      `kit/compute-executor-mock`. Amended by 1.16: a `(offering_mode, action)` table in
      compute provisioning and `compute_provisioning.executor_mock` ("Executors are
      selected by offering mode and action, and each adapter owns its mock").
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
- [x] 1.16 **Decision gate.** Resolve the 2026-10-01 design review. Decided with the
      maintainer: administrative acceptance and opening previews go through
      `NegotiationRuntime`, with the opening request as the preview's body; executor
      selection moves to compute provisioning keyed by `(offering_mode, action)`; the mock
      mechanism is a compute-family module in `compute_provisioning`, not a foundation
      kit; the deal-on-every-run requirement applies compute provisioning only where
      delivery crosses it; the kit settlement-servicing worker, composed for every
      mechanism, starts and retries bare-metal fulfillment. Sections 4–7 were replanned
      accordingly, and every section now ends at its own gate. Replanning verified the
      new premises against code: composition already refuses duplicate
      `(offering_mode, action)` keys, so 4.1 extends it rather than adding a registry;
      the job service's only bare-metal routing is its playbook-path special case; the
      worker has no single-obligation step, so 5.3 adds `service_obligation`; VM and API
      credits hold only at acceptance, so 5.6 proves the post-force-accept path rather
      than idempotency; `preview_opening` can stop before `start`'s first write; and
      evaluate-negotiate and force-accept have the callers 5.5, 5.7, and 5.9 name.

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
      result reads are idempotent. Planned in 7.7.
- [ ] 3.6 **Pause survives restart.** In the same suite, an authenticated trading pause
      remains active across the rebuild and new negotiations are refused until an
      authenticated resume. Planned in 7.7.

## 4. Executor selection and the compute mock mechanism

Decision: "Executors are selected by offering mode and action, and each adapter owns its
mock". Reviewable alone: provisioning only, no storefront or scenario change.

- [ ] 4.1 Extend composition with job executors:
      `provisioning/compute/service/src/compute_provisioning_service/composition.py`'s
      `ExecutorAdapterContribution` gains `job_executor`, `job_actions`, and
      `playbook_path`; `compose_adapter_bundles` builds `ComposedComputeAdapters.job_executors`
      keyed by `(offering_mode, action)` under the same duplicate refusal it applies to
      contract actions. The `JobExecutorResolver` protocol the job service depends on goes
      in `provisioning/compute/src/compute_provisioning/adapters.py`. Tests in
      `provisioning/compute/service/tests/unit/test_composition.py` (selection,
      duplicate refusal across bundles, unknown key).
- [ ] 4.2 Add `compute_provisioning/executor_mock.py`: the rule model, store, and matching
      over an opaque job-parameter mapping, pause gates and job-done events, the
      evaluate-job dry run, and a framework-free route service raising an HTTP-shaped
      error, extracted from VM's `MockRule` and `ProgrammableMockAnsibleService`. Unit
      tests in `provisioning/compute/tests/unit/test_executor_mock.py`, moved from
      `provisioning/compute/service/tests/unit/services/test_programmable_mock.py` where
      they test mechanism rather than VM output.
- [ ] 4.3 Resolve executors in VM's job service:
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/job_service.py`
      takes the resolver port and selects each job's executor and playbook from its
      persisted `offering_mode` and action; `_playbook_path_for_params`' `bare_metal`
      special case and `_BARE_METAL_ACTIONS` are removed;
      `notify_job_done` goes to the executor that ran the job. Persistence, host
      validation, inventory rendering, and `parse_playbook_result` are unchanged. The VM
      bundle (`vm_provisioning_adapter/bundle.py`, `runtime.py`) registers the real
      Ansible service, or under the mock profile VM's mock, for its actions. Tests in
      `provisioning/compute/service/tests/unit/services/test_job_service.py`.
- [ ] 4.4 Rebuild VM's mock on the mechanism:
      `vm_provisioning_adapter/services/mock_ansible_service.py` keeps its VM default
      output; `vm_provisioning_adapter/controllers/test_controller.py` binds the
      mechanism's route service at the unchanged `/test/mock-rules` paths and keeps the
      shared `/test/jobs/*` routes. VM-specific cases stay in `test_programmable_mock.py`;
      `provisioning/compute/service/tests/integration/test_test_controller.py` passes
      unchanged.
- [ ] 4.5 Add the bare-metal mock:
      `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/services/bare_metal_mock_executor.py`
      constructs its own instance of VM's Ansible-shaped programmable mock, with its own
      rule store and bare-metal default output: a default grant emits
      `node_grant_access_data` (tenant user and SSH port; tenant address from the
      registered host record, as a real run's) and a default reclaim emits
      `node_reclaim_access_data`. `bundle.py` and `runtime.py` register the real Ansible
      service, or under the mock profile the mock, as the job executor for
      `(bare_metal, NODE_GRANT_ACCESS_ACTION)` and `(bare_metal, NODE_RECLAIM_ACCESS_ACTION)`
      with the bare-metal playbook path;
      new `controllers/test_controller.py` binds the route service at
      `/test/bare-metal/mock-rules`; `routers.py` exposes it. Tests in
      `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_mock_executor.py`:
      default output parses through the real result path into the credentials
      `BareMetalFulfillmentProvider.fetch_credentials` reads; a bare-metal rule never
      matches a VM job and the reverse.
- [ ] 4.6 Compose it: `provisioning/compute/service/src/compute_provisioning_service/container.py`
      builds the table from both bundles and passes the resolver to the job service;
      `main.py` mounts the bare-metal test router under the mock profile beside VM's.
      Provisioning readiness reports each offering mode's executor mode
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
- [ ] 4.8 **Gate.** Relock the changed projects (`make lock PROJECTS=...` for
      `provisioning/compute`, `provisioning/compute/service`, and both adapters); the
      provisioning, provisioning-service, and both adapters' suites pass; the VM lane
      passes unchanged.

## 5. Negotiation runtime operations and deal-control route services

Decisions: "Deal controls are kit-owned route services", "Administrative acceptance goes
through the runtime", "Evaluate-negotiate previews the real opening". Reviewable alone:
kits, core, and the VM and API-credit storefronts; bare metal binds in Sections 6–7.

- [ ] 5.1 `kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py`: add
      `accept_administratively` (the continuation's existing resolution with an
      administrator actor, then the `Acceptance` built through the domain hooks at the
      administrator's amount, the administrator's accept message, and
      `_commit_acceptance`) and `preview_opening` (`start`'s resolution, decode,
      `validate_opening`, pause and liveness checks, round-zero evaluation,
      `agreement_terms`, and `build_artifacts`, factored into one function `start` also
      calls, stopping before `create_negotiation_thread`). Unit tests in
      `kit/negotiation-runtime/tests/unit/test_administrative_acceptance.py` and
      `test_opening_preview.py`: hooks run on administrative acceptance; preview refuses
      every opening `start` refuses and writes nothing.
- [ ] 5.2 `kit/storefront/src/market_storefront_kit/deal_control_routes.py`: the
      stage-event read over `core_storefront.stage_log` (filters and streaming as VM's
      `system_controller.stream_events`), evaluate-negotiate over `preview_opening`, and
      force-accept over `accept_administratively`. Unit tests in
      `kit/storefront/tests/unit/test_deal_control_routes.py`.
- [ ] 5.3 `kit/settlement-runtime/src/market_settlement_runtime/servicing.py`:
      `SettlementServicingWorker.service_obligation(obligation_ref)`, the per-record body
      `run_once` applies (factored out, with the same retry scheduling and terminal
      handling). `kit/settlement-runtime/src/market_settlement_runtime/admin_routes.py`: settle
      verify over the mechanism adapter's escrow read with no adoption, evaluate-settle
      over a new `FulfillmentPreviewHook` port in `ports.py`, and settle wait as a
      bounded long-poll over an injected settle-status reader and terminal predicate.
      Unit tests in `kit/settlement-runtime/tests/unit/test_admin_routes.py` and
      `test_servicing.py` (`service_obligation` matches one `run_once` pass for that
      obligation; a concurrent pass sees it busy).
- [ ] 5.4 `kit/capacity-publication/src/market_capacity_publication/admin_routes.py`:
      admin reserve through a listing's capacity binding, and the capacity-released
      callback dispatching to an injected domain release hook. Unit tests in
      `kit/capacity-publication/tests/unit/test_admin_routes.py`.
- [ ] 5.5 Wire models and client: `core/storefront/src/core_storefront/models/listing_models.py`'s
      `EvaluateNegotiateRequest` becomes the opening request and the response reports
      refusals before policy; `core/storefront-client/src/storefront_client/client.py`'s
      async and sync `evaluate_negotiate` take it. Every caller moves to the opening body:
      `domains/vms/storefront/tests/integration/test_listings_api.py`,
      `test_publication_loop.py`, and e2e `scenarios/vms/test_full_deal_buyer_cli.py` and
      `test_non_erc20_settlement.py` (`test_full_deal.py` in 5.10).
- [ ] 5.6 Prove the hold path after force-accept. VM's `place_hold` and API credits'
      `_place_quota_hold` run only at acceptance (verified 2026-10-01), so administrative
      acceptance places the hold once. Focused tests in
      `domains/vms/storefront/tests/integration/test_negotiations_api.py` and the
      API-credit negotiation suite: after force-accept the hold and settlement plan exist,
      and settlement consumes the hold exactly as after a negotiated acceptance.
- [ ] 5.7 Rebind VM: `controllers/system_controller.py` (events),
      `listings_controller.py` (evaluate-negotiate over the preview; remove
      `ListingService.evaluate_negotiate` and its round-zero helper's admin use),
      `negotiations_controller.py` (force-accept), `settle_controller.py` (verify,
      evaluate, wait), `admin_controller.py` (portfolio reservations, capacity-released);
      VM's evaluate-settle job-spec build becomes its `FulfillmentPreviewHook` from
      `services/admin_settle_service.py`, whose remaining code is removed;
      `middleware/admin_identity.py` keeps its route recognition. VM storefront suites
      pass, with force-accept tests now asserting the committed settlement plan and hold.
- [ ] 5.8 Rebind API credits: `controllers/system_controller.py` (events),
      `negotiations_controller.py` (force-accept), `settle_controller.py` (wait).
      API-credit suites pass, with force-accept asserting the quota hold.
- [ ] 5.9 Remove `NegotiationService.force_accept` from
      `core/storefront/src/core_storefront/services/negotiation_service.py`, and its cases
      from `domains/vms/storefront/tests/unit/services/test_negotiation_service.py`;
      `test_negotiations_api.py` covers force-accept through the route service.
- [ ] 5.10 VM's stage 05a in `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py`
      sends the opening request it later sends to `negotiate_new`.
- [ ] 5.11 **Gate.** Bump and relock the changed kits, core packages, and consumers; the
      kit, core, VM storefront, and API-credit storefront suites pass; the VM lane passes,
      including 05a on the new body and 06b with the runtime acceptance.

## 6. Bare metal on the kit negotiation runtime

Decision: "Bare metal negotiates through the kit runtime" (migrated
`bare-metal-and-credits-domain-stacks` 4a.1, 4a.2, runtime half of 4a.3). Reviewable
alone: the bare-metal storefront's negotiation surface.

- [ ] 6.1 Re-verify (former 4a.1) that `negotiation_service.py`, `negotiation.py`, the
      negotiate routes in `api.py`, and thread persistence in `sqlite_client.py` are
      domain-local and no bare-metal module imports `market_negotiation_runtime`.
- [ ] 6.2 Add `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/negotiation_runtime.py`
      implementing `NegotiationDomainHooks` (former 4a.2): `validate_opening` decoding
      the closed `bare_metal.v1` demand and calling `opening_guard.py`'s domain function;
      physical selection and exact settlement-option validation as `evaluate_round`
      inputs; `agreement_terms`; `build_artifacts` producing the accepted obligation the
      settlement runtime consumes; `persist_artifacts` saving `BareMetalTerms` and the
      settlement plan; `place_hold` as today, idempotent per negotiation. The seller
      policy in `negotiation.py` stays as the domain's policy, now evaluated by the
      runtime for every round.
- [ ] 6.3 Serve the existing negotiate and listing-negotiation routes in `api.py` over the
      runtime, compose it in `runtime.py`, and bind the Section 5 storefront-kit route
      services (events, evaluate-negotiate, force-accept). Tombstone
      `negotiation_service.py`; remove the hook class from `negotiation.py` and thread
      persistence from `sqlite_client.py`, with a migration in `migrations.py` if the
      runtime's tables differ.
- [ ] 6.4 Tests (with former 4a.6's focused cases): rewrite `test_negotiation.py` and
      `test_http_negotiation.py` for multi-round negotiation; force-accept recording
      `BareMetalTerms` and the hold; evaluate-negotiate refusing what `negotiate/new`
      refuses; opening refusal for each forbidden demand field; terms-mismatch refusal;
      the conformance matrix `multi-domain-storefront-composition` added, run under the
      bare-metal contract.
- [ ] 6.5 **Gate.** The bare-metal storefront suite passes; the bare-metal lane's
      publication scenario passes unchanged.

## 7. Bare-metal settlement, fulfillment, and release

Decisions: "Settlement starts fulfillment", "The lease lifecycle owns release for every
offering mode", "The Alkahest path commits the lease window and registers the lease",
"Bare-metal publication has a dry run", "Restart recovery is proven at integration level,
as VM's is". Reviewable alone: the bare-metal storefront's settlement and fulfillment
paths and provider-neutral release in provisioning.

- [ ] 7.1 Servicing worker for every mechanism: `runtime.py` composes
      `SettlementServicingWorker` whenever a settlement mechanism is registered, not only
      `fiat.stripe.v1`; its `on_ready` dispatches by the obligation's mechanism, hosted
      to the existing lifecycle callbacks and Alkahest to `fulfillment_service.py`;
      `lifecycle_steps.py` then registers the settlement-servicing step on the Alkahest
      path too. `settlement_service.py`'s `verify` wakes the worker for the adopted
      obligation and calls `service_obligation` once, and `status` drops its
      no-fulfillment assertion. Remove `POST /api/v1/fulfillments/begin` from `api.py`
      and `BareMetalFulfillRequest` from `models.py`; remove `begin()` from
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
      `provisioning/compute/src/compute_provisioning/release.py` as
      `FulfillmentReleaseExecutor` and `FulfillmentReleaseJobPort`; tombstone
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
- [ ] 7.6 Tests: `test_settlement.py` and `test_http_settlement.py` (verify wakes and
      steps the worker; a failed first attempt is retried by the worker's schedule and
      by nothing else; an Alkahest-only storefront has a settlement-servicing step;
      `begin` is gone); `test_fulfillment_service.py` (commit with window, lease
      registration, teardown through terminate, repeated teardown returns the same
      lease, release only on callback); `test_hosted_lifecycle.py` (hosted dispatch
      unchanged); `test_site_clients.py`; `test_publication_cycle.py` (preview applies
      nothing); `test_app_composition.py`;
      `domains/bare_metal/buyer/tests/test_buyer_composition.py`.
- [ ] 7.7 Restart integration tests (tasks 3.5, 3.6):
      `domains/bare_metal/storefront/tests/test_restart_recovery.py` rebuilds the
      production application over one database file with a loopback site
      (`tests/loopback.py`).
- [ ] 7.8 **Gate.** The bare-metal storefront, buyer, provisioning, and
      provisioning-service suites pass; the VM and bare-metal lanes pass unchanged.

## 8. Shared compute deal stages and the VM scenario

Decision: "Compute deal stages are shared". Behaviour-neutral for VM. Reviewable alone:
e2e-tests only.

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
- [ ] 8.5 **Gate.** The VM lane passes with the rewritten scenario.

## 9. The bare-metal mock-provisioned deal

Decision: "The scenario is VM's deal, stage for stage". Reviewable alone: e2e-tests and
lane configuration; depends on Sections 4–8.

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
- [ ] 9.6 **Gate.** The bare-metal lane passes with publication and the mock deal.

## 10. Pipeline: images built once and an API-credit lane

Decisions: "Lanes run on images built once", "API credits runs in its own lane", "Lane
composition files". Reviewable alone: compose files, Make targets, and the workflow; no
service code.

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
- [ ] 10.4 **Gate.** All three lanes pass from one build; record each job's duration beside
      the previous single-lane build time.

## 11. Permanent documentation

- [ ] 11.1 `docs/development/ARCHITECTURE.md`: kit layers gain the deal-control route
      services and the negotiation runtime's administrative acceptance and opening
      preview; the compute provisioning description gains the `(offering_mode, action)`
      executor table and the compute-family mock mechanism; "Release" states that every offering mode
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
| Compute mock executors share `compute_provisioning.executor_mock`; job execution resolves its executor by `(offering_mode, action)` | `openspec/specs/market-composition/spec.md` — "Compute mock executors share one compute-family mechanism"; `openspec/specs/physical-provisioning/spec.md` — "Job execution resolves its executor by offering mode and action"; `docs/development/ARCHITECTURE.md`; `docs/development/TESTING.md` |
| Administrative acceptance and opening previews go through the negotiation runtime | `openspec/specs/market-composition/spec.md` — "Kit-owned synchronous negotiation runtime" and "Storefront deal controls are kit-owned route services"; `docs/development/ARCHITECTURE.md` kit layers |
| Bare metal composes the kit negotiation runtime | `openspec/specs/market-composition/spec.md` — "Kit-owned synchronous negotiation runtime" |
| Lease release delegates to durable fulfillment teardown for every offering mode; storefront teardown goes through lease termination | `openspec/specs/physical-provisioning/spec.md` — "Lease release delegates to durable fulfillment teardown", "Storefront teardown goes through lease termination"; `docs/development/ARCHITECTURE.md` "Release" |
| Settlement starts bare-metal fulfillment through the kit servicing worker, composed for every mechanism; the Alkahest path commits and registers its lease | `openspec/specs/storefront-publication/spec.md` — "Complete bare-metal seller lifecycle"; `docs/development/ARCHITECTURE.md` |
| Lane composition files split per market | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/TESTING.md` |
| Scope migrations, the real-host scenario's disposition, and why the scenario uses typed clients | This change's `design.md` |
