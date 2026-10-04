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
- [x] 1.17 **Decision gate.** Resolve the 2026-10-02 implementation and layering reviews.
      Decided with the maintainer: provisioning execution leaves the VM adapter into
      `compute_provisioning` (jobs, hosts, executor table, rule and gate mechanism,
      composition contract types, job and host wire models) and an Ansible family-kit
      distribution, with domains contributing codecs, playbooks, preparation, and result
      meaning; no adapter imports another adapter or the deployed service; the executor
      table resolves complete `JobExecutor`s; `system_service.py` is split by owner and
      diagnostics are contributed; relays and VM pool configuration stay VM's; the
      fulfillment-provider helper is deferred. The review's Section 4–5 fixes are
      accepted ("Implementation-review fixes for Sections 4–5"). Planned as Sections 5A
      and 5B.
- [x] 1.18 **Decision gate.** Define the layer `compute_provisioning` belongs to. Decided
      with the maintainer: a family kit ("Compute provisioning is a family kit"),
      promoted to `ARCHITECTURE.md` in 11.1.
- [x] 1.19 **Decision gate.** Confirm the Ansible distribution and the fulfillment-provider
      helper's timing. Decided with the maintainer: the Ansible mechanics are a sibling
      family-kit distribution, `provisioning/compute/ansible`; the job-backed
      fulfillment-provider helper lands in this change as 5B.12, after the boundary is
      proven. The family-kit definition was refined after architectural review
      ("Compute provisioning is a family kit").

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

- [x] 4.1 Extend composition with job executors:
      `provisioning/compute/service/src/compute_provisioning_service/composition.py`'s
      `ExecutorAdapterContribution` gains `job_executor`, `job_actions`, and
      `playbook_path`; `compose_adapter_bundles` builds `ComposedComputeAdapters.job_executors`
      keyed by `(offering_mode, action)` under the same duplicate refusal it applies to
      contract actions. The `JobExecutorResolver` protocol the job service depends on goes
      in `provisioning/compute/src/compute_provisioning/adapters.py`. Tests in
      `provisioning/compute/service/tests/unit/test_composition.py` (selection,
      duplicate refusal across bundles, unknown key).
- [x] 4.2 Add `compute_provisioning/executor_mock.py`: the rule model, store, and matching
      over an opaque job-parameter mapping, pause gates and job-done events, the
      evaluate-job dry run, and a framework-free route service raising an HTTP-shaped
      error, extracted from VM's `MockRule` and `ProgrammableMockAnsibleService`. Unit
      tests in `provisioning/compute/tests/unit/test_executor_mock.py`, moved from
      `provisioning/compute/service/tests/unit/services/test_programmable_mock.py` where
      they test mechanism rather than VM output.
- [x] 4.3 Resolve executors in VM's job service:
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/job_service.py`
      takes the resolver port and selects each job's executor and playbook from its
      persisted `offering_mode` and action; `_playbook_path_for_params`' `bare_metal`
      special case and `_BARE_METAL_ACTIONS` are removed;
      `notify_job_done` goes to the executor that ran the job. Persistence, host
      validation, inventory rendering, and `parse_playbook_result` are unchanged. The VM
      bundle (`vm_provisioning_adapter/bundle.py`, `runtime.py`) registers the real
      Ansible service, or under the mock profile VM's mock, for its actions. Tests in
      `provisioning/compute/service/tests/unit/services/test_job_service.py`.
- [x] 4.4 Rebuild VM's mock on the mechanism:
      `vm_provisioning_adapter/services/mock_ansible_service.py` keeps its VM default
      output; `vm_provisioning_adapter/controllers/test_controller.py` binds the
      mechanism's route service at the unchanged `/test/mock-rules` paths and keeps the
      shared `/test/jobs/*` routes. VM-specific cases stay in `test_programmable_mock.py`;
      `provisioning/compute/service/tests/integration/test_test_controller.py` passes
      unchanged.
- [x] 4.5 Add the bare-metal mock:
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
      Corrected 2026-10-02: the test parses through the real parser and the job service's
      result payload; it does not call `fetch_credentials` (added by 5A.4). The mock is
      replaced by 5B.7.
- [x] 4.6 Compose it: `provisioning/compute/service/src/compute_provisioning_service/container.py`
      builds the table from both bundles and passes the resolver to the job service;
      `main.py` mounts the bare-metal test router under the mock profile beside VM's.
      Provisioning readiness reports each offering mode's executor mode
      (`domains/vms/provisioning/client/src/vm_provisioning_operator/models.py` and the
      status service that fills it). Integration test
      `provisioning/compute/service/tests/integration/test_bare_metal_mock_profile.py`: a
      bare-metal grant under the mock profile reaches `active` through fulfillment
      convergence, held and released by a bare-metal rule.
      Corrected 2026-10-02: the integration test registers a bare-metal lease and proves
      its grant job runs through the bare-metal mock, held and released by a bare-metal
      rule, failed by another, and that resuming an unknown rule is refused. It does not
      exercise fulfillment convergence or reclaim; the Section 9 scenario does. Its raw
      lease request and its sleep are replaced by 5A.2 and 5A.3.
- [x] 4.7 Typed clients: `provisioning/compute/src/compute_provisioning/client.py` route
      contracts for `/test/bare-metal/mock-rules*`;
      `e2e-tests/src/e2e_harness/provisioning_test_client.py` gains the bare-metal rule
      methods; `provisioning/compute/service/tests/integration/test_provisioning_client_endpoint_coverage.py`
      covers them.
      Corrected 2026-10-02: the endpoint-coverage file was not changed; 5A.4 adds the
      coverage.
- [ ] 4.8 **Gate.** Relock the changed projects (`make lock PROJECTS=...` for
      `provisioning/compute`, `provisioning/compute/service`, and both adapters); the
      provisioning, provisioning-service, and both adapters' suites pass; the VM lane
      passes unchanged.
      Local part done 2026-10-01; the VM lane is unrun (no container runtime where it
      was implemented). Results: `provisioning/compute` 153 passed; provisioning
      service 674 unit and 286 integration passed; bare-metal adapter 7 passed;
      bare-metal storefront 220 passed; `make check-packaging` passes.
- **Section 4 implementation notes (2026-10-01).**
  - Versions: `arkhai-compute-provisioning` 0.8.0, `arkhai-compute-provisioning-service`
    0.5.0, `arkhai-vms-provisioning-adapter` 0.5.0,
    `arkhai-bare-metal-provisioning-adapter` 0.3.0,
    `arkhai-vms-provisioning-operator-client` 0.6.0 (readiness gains
    `executor_modes`). Relocked: both adapters, the operator client, the bare-metal
    storefront, e2e-tests, the provisioning service, and `provisioning/compute`.
  - `domains/vms/storefront/uv.lock` could not be resolved there (its index needs
    `download-r2.pytorch.org`); its `arkhai-compute-provisioning` entry was moved to
    0.8.0 by hand, matching exactly what the other relocks produced for that entry.
    Regenerate it with `make lock PROJECTS=domains/vms/storefront` to confirm.
  - Deviations: the table extends `ExecutorAdapterContribution` with `job_executions`
    (one `JobExecution` per action) rather than three fields; VM registers
    `VM_JOB_ACTIONS`. `JobExecutorTable` refuses to resolve before composition freezes
    it. The existing `test_programmable_mock.py` cases stay as VM coverage beside the
    mechanism's own tests. The bare-metal mock subclasses VM's Ansible-shaped mock and
    renders its fact per run through a new `default_stdout` hook, which also removed
    the VM mock's temporary mutation of its default output. The integration test
    reaches the mock through lease registration rather than fulfillment convergence;
    the scenario covers convergence (Section 9).
  - Found: `e2e-tests/tests/unit/test_hosted_public_boundary.py::test_buyer_deployment_mounts_separate_profile_state_and_credential`
    fails at the baseline too; it reads `compose.vms.yml`, which 10.1 rewrites, and is
    fixed there.

## 5. Negotiation runtime operations and deal-control route services

Decisions: "Deal controls are kit-owned route services", "Administrative acceptance goes
through the runtime", "Evaluate-negotiate previews the real opening". Reviewable alone:
kits, core, and the VM and API-credit storefronts; bare metal binds in Sections 6–7.

- [x] 5.1 `kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py`: add
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
- [x] 5.2 `kit/storefront/src/market_storefront_kit/deal_control_routes.py`: the
      stage-event read over `core_storefront.stage_log` (filters and streaming as VM's
      `system_controller.stream_events`), evaluate-negotiate over `preview_opening`, and
      force-accept over `accept_administratively`. Unit tests in
      `kit/storefront/tests/unit/test_deal_control_routes.py`.
- [x] 5.3 `kit/settlement-runtime/src/market_settlement_runtime/servicing.py`:
      `SettlementServicingWorker.service_obligation(obligation_ref)`, the per-record body
      `run_once` applies (factored out, with the same retry scheduling and terminal
      handling). `kit/settlement-runtime/src/market_settlement_runtime/admin_routes.py`: settle
      verify over the mechanism adapter's escrow read with no adoption, evaluate-settle
      over a new `FulfillmentPreviewHook` port in `ports.py`, and settle wait as a
      bounded long-poll over an injected settle-status reader and terminal predicate.
      Unit tests in `kit/settlement-runtime/tests/unit/test_admin_routes.py` and
      `test_servicing.py` (`service_obligation` matches one `run_once` pass for that
      obligation; a concurrent pass sees it busy).
      Corrected 2026-10-02: `test_servicing.py` proves immediate start, retry of a failed
      start by the worker's schedule, and refusal of an unknown obligation; the
      concurrent-pass case is added by 5A.5.
- [x] 5.4 `kit/capacity-publication/src/market_capacity_publication/admin_routes.py`:
      admin reserve through a listing's capacity binding, and the capacity-released
      callback dispatching to an injected domain release hook. Unit tests in
      `kit/capacity-publication/tests/unit/test_admin_routes.py`.
- [x] 5.5 Wire models and client: `core/storefront/src/core_storefront/models/listing_models.py`'s
      `EvaluateNegotiateRequest` becomes the opening request and the response reports
      refusals before policy; `core/storefront-client/src/storefront_client/client.py`'s
      async and sync `evaluate_negotiate` take it. Every caller moves to the opening body:
      `domains/vms/storefront/tests/integration/test_listings_api.py`,
      `test_publication_loop.py`, and e2e `scenarios/vms/test_full_deal_buyer_cli.py` and
      `test_non_erc20_settlement.py` (`test_full_deal.py` in 5.10).
- [x] 5.6 Prove the hold path after force-accept. VM's `place_hold` and API credits'
      `_place_quota_hold` run only at acceptance (verified 2026-10-01), so administrative
      acceptance places the hold once. Focused tests in
      `domains/vms/storefront/tests/integration/test_negotiations_api.py` and the
      API-credit negotiation suite: after force-accept the hold and settlement plan exist,
      and settlement consumes the hold exactly as after a negotiated acceptance.
      Corrected 2026-10-02: VM's test proves the settlement plan, terminal state, and the
      hold's reservation request at the site, invoking the runtime directly. API credits
      deliberately grants no unfunded quota hold; its test proves force-accept records
      what a negotiated acceptance records — credit terms, agreed price, and no hold.
      The successful path through `StorefrontClient` is added by 5A.1.
- [x] 5.7 Rebind VM: `controllers/system_controller.py` (events),
      `listings_controller.py` (evaluate-negotiate over the preview; remove
      `ListingService.evaluate_negotiate` and its round-zero helper's admin use),
      `negotiations_controller.py` (force-accept), `settle_controller.py` (verify,
      evaluate, wait), `admin_controller.py` (portfolio reservations, capacity-released);
      VM's evaluate-settle job-spec build becomes its `FulfillmentPreviewHook` from
      `services/admin_settle_service.py`, whose remaining code is removed;
      `middleware/admin_identity.py` keeps its route recognition. VM storefront suites
      pass, with force-accept tests now asserting the committed settlement plan and hold.
- [x] 5.8 Rebind API credits: `controllers/system_controller.py` (events),
      `negotiations_controller.py` (force-accept), `settle_controller.py` (wait).
      API-credit suites pass, with force-accept asserting the quota hold.
- [x] 5.9 Remove `NegotiationService.force_accept` from
      `core/storefront/src/core_storefront/services/negotiation_service.py`, and its cases
      from `domains/vms/storefront/tests/unit/services/test_negotiation_service.py`;
      `test_negotiations_api.py` covers force-accept through the route service.
- [x] 5.10 VM's stage 05a in `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py`
      sends the opening request it later sends to `negotiate_new`.
- [ ] 5.11 **Gate.** Bump and relock the changed kits, core packages, and consumers; the
      kit, core, VM storefront, and API-credit storefront suites pass; the VM lane passes,
      including 05a on the new body and 06b with the runtime acceptance.
      Local part done 2026-10-02; the VM lane is unrun. Results: negotiation runtime 17,
      settlement runtime 123, storefront kit 56, capacity-publication 66, core storefront
      182, storefront client 44, API-credit storefront 97, bare-metal storefront 220,
      kit/config 134, hosted-settlement 189, contact-exchange 37, alkahest 182, core buyer
      126, bare-metal buyer 14 passed; VM storefront 1060 unit passed and every
      integration file passes except the pre-existing failures below and
      `test_alkahest.py`, which needs Node and Anvil; `make check-packaging` and
      `make check-comment-hygiene` pass.
- **Section 5 implementation notes (2026-10-02).**
  - Versions: `arkhai-kit-negotiation-runtime` 0.3.0, `arkhai-kit-settlement-runtime`
    0.1.3, `arkhai-kit-storefront` 0.2.0 (now depends on the negotiation runtime),
    `arkhai-kit-capacity-publication` 0.4.0, `arkhai-core-storefront` 0.7.0,
    `arkhai-core-storefront-client` 0.23.0, `arkhai-vms-storefront` 0.9.0,
    `arkhai-apicredits-storefront` 0.6.0; exact pins moved everywhere they appear.
  - `domains/vms/storefront/uv.lock` and `domains/vms/buyer/uv.lock` could not be
    resolved there (their index needs `download-r2.pytorch.org`); their internal-wheel
    entries, the VM storefront's own specifiers and version, and the new
    `arkhai-kit-storefront` → `arkhai-kit-negotiation-runtime` edge were set from the
    built wheels' metadata, and `check-locks` accepts them. Regenerate both with
    `make lock PROJECTS="domains/vms/storefront domains/vms/buyer"`.
  - Design-review option A: the kit's due-obligation query lists a ready obligation
    whose fulfillment never started, through its `fulfill` operation, so every
    domain's `on_ready` hook is reachable and the worker's retry schedule governs a
    failed start. VM and API credits already registered such hooks.
  - Deviations: settle verify, admin reserve, and the capacity-released callback are
    kit-owned route services over per-domain hooks, not over a kit read, because their
    requests and effects are domain-shaped; the kit owns validation, refusals, and
    response shape. `FulfillmentPreviewHook` lives beside the routes in
    `admin_routes.py`. Verify and evaluate hooks are optional, so API credits binds
    only wait. VM's `AdminSettleService` remains as VM's verify and preview hooks.
  - Found: API credits' force-accept route called core `force_accept` without the
    administrator principal it requires and failed on every call; rebinding fixed it.
  - VM evaluate-negotiate tests now send real openings: the hosted-selection test opens
    below the hosted rate so the strategy counters, the unknown-listing test expects a
    refused preview, and the floor test was removed (an accepting preview builds the
    settlement plan, which `test_negotiate_controller.py`'s accepting openings cover).
    The hand-seeded force-accept success test was removed (a thread with no recorded
    terms cannot pass through the runtime); `TestAdministrativeAcceptance` in
    `test_negotiate_controller.py` and the API-credit
    `test_force_accept_records_what_a_negotiated_acceptance_records` replace it. The
    inventory-guard preview test runs against a negotiating publication app, and a
    policy rejection is now a refused preview.
  - Checkpoint 1 (2026-10-02): `make test` green after the maintainer relocked the
    projects whose locks had recorded an absolute wheelhouse path (they were run with
    an absolute `--find-links`). The e2e run passed the bare-metal lane (11) and failed
    VM stage 08a: force-accept now places VM's acceptance hold, and evaluate-settle
    probed only free capacity, so it reported no VM while settle would commit that
    hold. Evaluate-settle now takes the `negotiation_id` settle names and, when its
    acceptance holds capacity, reports the held reservation and its host (from the
    site snapshot); otherwise it probes. `EvaluateSettleRequest` gains
    `negotiation_id`, `EvaluateSettleResponse` gains `capacity_reservation_id`, both
    client variants pass it, and VM stage 08a and `test_non_erc20_settlement.py` send
    it. VM unit 1062 passed; core storefront 182 and client 44 passed.
  - Pre-existing VM failures (unrelated modules, not caused here): in
    `test_negotiate_controller.py`, `test_amountless_exact_escrow_can_start_and_accept`
    and `test_an_unbacked_listing_negotiates_to_acceptance_without_the_site` (policy
    counters where the tests expect accept); in `test_publication_loop.py`, five
    term-refresh and shape-priced publication tests (publication refuses where they
    expect publish or refresh). These could not be compared against a true baseline
    environment there; they exercise publication pricing, which this change does not
    touch.

## 5A. Implementation-review fixes for Sections 4–5

Decision: "Implementation-review fixes for Sections 4–5". Reviewable alone: tests, one
client method, and the gate signal; no behaviour change. Lands before 5B so 5B moves
code that is already correctly covered.

- [x] 5A.1 Typed force-accept: in `domains/vms/storefront/tests/integration/test_negotiations_api.py`
      the fixture gains the chain configuration `test_negotiate_controller.py` uses, opens
      a real negotiation that counters, and force-accepts it through
      `StorefrontClient.force_accept_negotiation`, asserting the settlement plan, terminal
      state at the forced amount, and the hold's reservation request at the site. Add an
      API-credit equivalent through its application and `StorefrontClient` in
      `domains/apicredits/storefront/tests/integration/test_force_accept_api.py`.
- [x] 5A.2 Typed lease registration: a bare-metal lease registration method on the
      provisioning client in `provisioning/compute/src/compute_provisioning/client.py`
      for the existing `/api/v1/bare-metal/leases/` route contract;
      `test_bare_metal_mock_profile.py` uses it instead of a raw request. Extend the
      integration and e2e test-route clients with any method the tests need.
      Amended 2026-10-02 with the maintainer: a bare-metal-typed method there would make
      the family kit depend on `arkhai_bare_metal`. `ComputeProvisioningClient` gains a
      market-neutral `authenticated_request`; `domains/bare_metal/src/arkhai_bare_metal/provisioning_client.py`
      adds `BareMetalLeaseClient` (register, get, get by escrow, list) over any transport
      offering it, with unit tests in `domains/bare_metal/tests/test_provisioning_client.py`.
      `test_bare_metal_mock_profile.py` and `test_bare_metal_leases_api.py` use it, and the
      latter's hand-built lease client is removed. The integration fixture in
      `provisioning/compute/service/tests/integration/conftest.py` mounts both adapters'
      test routers, so the suite no longer depends on `ACTIVE_PROFILES=mock` being set when
      `main.py` is imported (plain `pytest` mounted only VM's and the bare-metal rule
      routes returned 404).
- [x] 5A.3 Deterministic gates: `compute_provisioning/executor_mock.py`'s `MockRuleSet`
      signals when a job reaches a rule's gate and reports how many jobs wait there;
      `MockRuleRouteService.list` reports it. `test_bare_metal_mock_profile.py` waits on
      `AsyncJobQueue.on_job_started` and the gate-reached signal, and
      `test_bare_metal_mock_executor.py` on the gate-reached signal; both sleeps go. Unit
      tests for the signal in `provisioning/compute/tests/unit/test_executor_mock.py`.
- [x] 5A.4 Coverage claimed but missing: the five bare-metal test routes in
      `test_provisioning_client_endpoint_coverage.py`; a test in
      `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_fulfillment_provider.py`
      feeding the mock's job result to `BareMetalFulfillmentProvider.fetch_credentials`.
- [x] 5A.5 `service_obligation` concurrency: a worker pass running while
      `service_obligation` holds the fulfillment lease sees the obligation busy and
      starts no second fulfillment.
- [x] 5A.6 Test placement: move `kit/settlement-runtime/tests/unit/test_servicing.py` to
      `tests/integration/` and `domains/apicredits/storefront/tests/unit/test_sync_negotiation.py`
      to `tests/integration/`, adding `tests/integration` to each project's test paths
      where missing.
- [x] 5A.7 **Gate.** The touched suites pass; `make check-packaging` passes.
      Done 2026-10-02: `provisioning/compute` 157; provisioning service 674 unit and
      287 integration, under both plain `pytest` and `ACTIVE_PROFILES=mock`; bare-metal
      adapter 8; `arkhai_bare_metal` 135; settlement runtime 124; API-credit storefront
      101; VM storefront 1062 unit (1 skipped) and every integration file except
      `test_alkahest.py` (needs Node and Anvil), failing only the seven known
      pre-existing cases (two in `test_negotiate_controller.py`, five in
      `test_publication_loop.py`). Run whole, `test_publication_loop.py` is killed in
      the sandbox (SIGKILL); run test by test it gives 33 passed and those five; the
      baseline was not compared. `make check-packaging` and `make check-comment-hygiene`
      pass; `openspec validate --strict` passes. The VM lane is unrun (no container
      runtime here).
- **Section 5A implementation notes (2026-10-02).**
  - 5A.1, VM: the administrator force-accept test lives in
    `domains/vms/storefront/tests/integration/test_negotiate_controller.py`'s
    `TestAdministrativeAcceptance`, not `test_negotiations_api.py`: that fixture already
    has the chain configuration, a fake site, and a projection-backed listing, so its
    application gains the negotiations router and administrator middleware and the test
    force-accepts a real countered negotiation through an administrator
    `StorefrontClient`, asserting the committed plan, terminal state at the forced
    amount, and the hold's reservation request at the site.
  - 5A.1, API credits: `tests/integration/test_force_accept_api.py` drives force-accept,
    its terminal and unknown-administrator refusals, the stage-event read, and settle
    wait through `StorefrontClient`. Found: API credits' force-accept, events, and
    settle-wait routes authenticated their own route name and path, not the contract
    the canonical client signs, so no client call could succeed (no e2e scenario uses
    them). `controllers/negotiations_controller.py`, `system_controller.py`, and
    `settle_controller.py` now authenticate the client's operations and resources, as
    the lifecycle controller does; the four tests fail against the former controllers.
    API credits' advance and listing-administration routes keep the same mismatch,
    outside this change's controls. The kit route services do not yet own their signed
    contracts (VM derives them in its administrator middleware, API credits in its
    controllers); recorded for the maintainer's decision.
  - 5A.2: as amended above. `BareMetalLeaseClient` takes any transport offering
    `authenticated_request`; `arkhai_bare_metal` gains no dependency.
  - 5A.3: `MockRuleSet.hold` counts jobs waiting at a closed gate; `wait_until_held`
    returns once a count is reached, does not bound itself, and raises `LookupError`
    for an unknown or gateless rule or one removed while waited on; `list()` reports
    `waiting`. Deleting a rule still does not release a held job (unchanged).
  - 5A.5: the worker reserves no fulfillment lease itself; the `on_ready` hook does,
    through `SettlementRuntime.reserve_fulfillment`, and that reservation is what makes
    a concurrent pass see the obligation as busy (the due query excludes an unexpired
    `fulfill` lease). `service_obligation`'s docstring now says so. Every storefront
    hook reserves today; bare metal's Alkahest hook (7.1) must too.
  - 5A.6: both files were split by level rather than moved whole. Loop-ordering tests
    with no database stay in `kit/settlement-runtime/tests/unit/test_servicing.py`;
    API-credit term-decoding and artifact-assembly tests stay in
    `tests/unit/test_sync_negotiation.py`. The real-SQLite tests are in each project's
    `tests/integration/test_servicing.py` and `test_sync_negotiation.py`; API credits'
    shared fixtures moved to `tests/integration/conftest.py` and
    `tests/integration/credit_negotiation.py`. `kit/settlement-runtime`'s test paths and
    a `tests/integration/__init__.py` were added.
  - Found: `provisioning/compute/service/tests/integration/conftest.py` mounted only VM's
    test router when `main.py` had not, so plain `pytest` (without the Makefile's
    `ACTIVE_PROFILES=mock`) returned 404 for every bare-metal rule route; it now mounts
    both.
  - No version changes: the rebuilt `arkhai-compute-provisioning`, `arkhai-bare-metal`,
    and `arkhai-kit-settlement-runtime` wheels keep their versions and add no
    dependency.

## 5B. Provisioning execution boundary

Maintainer rulings that review findings have contested are recorded in `design.md`,
"Maintainer rulings for review": plaintext secret submission (option A) stands, with
on-wire protection out of scope; `ARCHITECTURE.md` describes the target ownership
because the branch merges whole.

Decisions: "Compute provisioning is a family kit", "Provisioning execution leaves the VM
adapter", "Pre-release wire and schema changes are accepted", "Job and host authority
shape". Steps run in the order listed (5B.2a before 5B.3). Each is behaviour-neutral
unless it says it changes a wire format or schema, and ends with the provisioning,
provisioning-service, both adapters', and operator-client suites green; a step that
changes a schema includes migration tests (fresh database, upgrade with conversion,
idempotent rerun). 5B.11 is the lane gate. Planning names files; implementation
re-verifies them by grep before each move.

- [x] 5B.1 Neutral contracts first: move `ExecutorAdapterBundle`,
      `ExecutorAdapterContribution`, `ComposedComputeAdapters`, and
      `compose_adapter_bundles` from
      `provisioning/compute/service/src/compute_provisioning_service/composition.py` into
      `provisioning/compute/src/compute_provisioning/composition.py`; move the wire models
      and client operations from
      `domains/vms/provisioning/client/src/vm_provisioning_operator/models.py`, classified
      by owner rather than copied wholesale: host models (`HostCreate`, `HostUpdate`,
      `HostResponse`, `HostListResponse`), job models (`JobSubmitResponse`,
      `JobStatusResponse`, `JobLogsResponse`, `JobListResponse`), lease models
      (`Lease*`), and aggregate `HealthResponse` and `VersionResponse` to
      `compute_provisioning`; the job authority's canonical result and credential forms
      are the existing `ResultEnvelope` and `CredentialEnvelope`, and
      `CredentialResponse` and `CredentialListResponse` become compatibility DTOs built
      from them at the route boundary; readiness models (`AnsibleReadinessResponse`,
      `InventoryInfo`, `FileInfo`, `SshKeyInfo`) and `HostConnectivityResponse` go to the
      Ansible distribution in 5B.6; `VmActionRequest` and `CreateVmRequest` stay VM's.
      `vm_provisioning_operator` re-exports every moved name.
      Added 2026-10-02 with the maintainer: the provisioning route-contract table becomes
      contributable. `compute_provisioning/client.py` keeps the contract type, the
      family-kit routes, and the table's assembly; bare metal's lease and
      `/test/bare-metal/*` contracts move beside `BareMetalLeaseClient` in
      `arkhai_bare_metal`, and VM's VM-, relay-, and VM-test-route contracts move to its
      operator client or adapter; the provisioning service assembles the domains'
      contributions, and `ComputeProvisioningClient`, the e2e test client, and the
      service's authentication middleware read the assembled table. Re-verify every
      reader of `resolve_provisioning_route_contract` and `ADMIN_PROVISIONING_OPERATIONS`
      by grep. Test: `compute_provisioning` names no domain route, and assembly refuses
      a duplicate or overlapping contract.
      Done 2026-10-02:
      - Composition contract types and `compose_adapter_bundles` are in
        `provisioning/compute/src/compute_provisioning/composition.py`, exported by
        `compute_provisioning`; both bundles and `container.py` import them from there;
        the service's `composition.py` is tombstoned, its `__init__.py` exports nothing,
        and the unit test moved to `provisioning/compute/tests/unit/test_composition.py`.
      - Host, job, and aggregate health and version wire models are in
        `compute_provisioning/hosts/models.py`, `compute_provisioning/jobs/models.py`,
        and `compute_provisioning/system_models.py`, with KVM and Ansible wording removed
        from their descriptions (no field or validation change);
        `vm_provisioning_operator.models` re-exports them.
      - `CredentialResponse` and `CredentialListResponse` stay in the operator client as
        compatibility DTOs, built from `CredentialEnvelope` when the job routes move
        (5B.6). The `Lease*` models stay VM's (design: "the `Lease*` operator models stay
        VM's").
      - Amended after the job and host design review: the re-exports and the credential
        DTOs are removed in 5B.5, the host models above are replaced by
        connection-neutral ones in 5B.4, and the `Lease*` models leave the generic
        surface in 5B.8.
      - Route contracts: `ProvisioningRouteContract` carries `roles`;
        `route_contract_from_declaration`, `ProvisioningRouteTable`, and
        `assemble_provisioning_route_table` are in `compute_provisioning/client.py`.
        VM declares `VM_PROVISIONING_ROUTES` in `vm_provisioning_operator/routes.py`
        (24: host capacity, VM operations, `/api/v1/leases*`, `/api/v1/admin/leases/*`,
        `/test/mock-rules*`, `/test/evaluate-job`); bare metal declares
        `BARE_METAL_PROVISIONING_ROUTES` in `arkhai_bare_metal/provisioning_client.py`
        (9), whose `BareMetalLeaseClient` names the declaration per call. Each adapter's
        `routers.py` exposes its declarations; `main.py` assembles
        `provisioning_route_table` and passes it to `ProvisioningAuthMiddleware`, whose
        `route_table` is now required. The VM operator client, the e2e test client, and
        the integration fixture resolve against assembled tables. Relay contracts stay in
        the family table (design: "Relay routes stay in the family table until relays
        move"). A one-off comparison found all 108 operations with identical method,
        path, roles, required role, and resources before and after.
      - Floors raised and relocked: the operator client's `arkhai-compute-provisioning`
        to `>=0.8.0`; the bare-metal adapter's `arkhai-bare-metal` to `>=0.6.0`; e2e-tests
        declares `arkhai-bare-metal>=0.6.0` and its operator-client floor is `>=0.6.0`.
      - Tests: `provisioning/compute/tests/unit/test_route_table.py` (family table names
        no domain route, roles, order within a contribution, cross-contribution
        ambiguity, duplicates, declaration validation, the client signing a named route);
        `provisioning/compute/service/tests/unit/test_route_table_composition.py` (every
        contributed route resolves to itself); `domains/bare_metal/tests/test_provisioning_client.py`
        (each call names a declaration describing its request).
      - Validation: `provisioning/compute` 163; provisioning service 694 unit and 287
        integration; `arkhai_bare_metal` 136; bare-metal adapter 8; the VM adapter's
        `make test` file 39; e2e unit 236 with the known pre-existing failure.
- [x] 5B.2 **Decision gate.** Review the proposed job authority shape. Decided with the
      maintainer after design review (2026-10-02): `design.md`, "Pre-release wire and
      schema changes are accepted" and "Job and host authority shape" (credential option
      B as one forward migration; envelopes for results and credentials; executor-owned
      retry classification and redaction; `JobRetryPolicy`; first-class `host_id`;
      opaque execution handle; terminal cancellation; no `notify_job_done`; a
      connection-neutral host authority with per-kind codecs; the generic lease routes
      serving `LeaseView`; host authority before the engine). The steps below are
      replanned accordingly.
- [x] 5B.2a Executor contract and the transitional executor. Behaviour-neutral.
      `provisioning/compute/src/compute_provisioning/jobs/executor.py`: `JobExecutor`
      (`execute`, `cancel`), `JobRun` (job id, opaque parameters, `ExecutionHost`, handle
      and log callbacks), `JobSuccess`, `JobFailure` (carrying
      `ProvisioningErrorEnvelope` with `retryable`), and `JobRetryPolicy`;
      `ExecutionHost` (`host_id`, `pool_id`, connection envelope) in
      `compute_provisioning/hosts/execution.py`, built for now from today's host row by a
      transitional function in the VM adapter. `compute_provisioning/adapters.py`:
      `JobExecutorTable` resolves `JobExecutor`s; `JobExecution` is removed and
      `executor_modes`/`runners` follow. `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_job_executor.py`:
      `AnsibleJobExecutor(runner, playbook_path, classification, timeout)` holding the
      Ansible half of `_process_job` (parameter rebuild, relay-token resolution, vars
      file, inventory, playbook, parse, result payload as a `ResultEnvelope`, credential
      extraction as `CredentialEnvelope`s, redaction, `non_retryable_errors`
      classification, `SIGTERM` cancellation). `job_service.py` drives it through the
      contract and keeps its persistence for now, writing the outcome in today's row
      shape. Both bundles, both runtimes, `container.py`, and the integration conftest's
      executor table register `AnsibleJobExecutor`s; the mock runners stay the runner
      inside them. Tests: `provisioning/compute/tests/unit/test_job_executor_table.py`
      updated; `provisioning/compute/service/tests/unit/services/test_job_service.py`
      and `test_ansible_job_executor.py` (classification, redaction, handle, cancel); the
      service suites pass unchanged.
      Done 2026-10-02:
      - `compute_provisioning/jobs/executor.py` (`JobExecutor`, `JobRun`, `JobSuccess`,
        `JobFailure`, `JobRetryPolicy`), `compute_provisioning/hosts/execution.py`
        (`ExecutionHost`), and `compute_provisioning/hosts/connection.py`
        (`ConnectionEnvelope`, brought forward from 5B.3 because `ExecutionHost`
        carries it; the `ConnectionCodec` protocol stays in 5B.3). `JobExecutorTable`
        resolves executors; `JobExecution` and `runners()` are gone (`executors()`
        replaces the latter); `ExecutorAdapterContribution.job_executors` replaces
        `job_executions`.
      - `vm_provisioning_adapter/services/ansible_job_executor.py`: `AnsibleJobExecutor`
        and `execution_host_from_record` (today's host row as an `ssh` connection). Both
        runtimes build one in `adapter_bundle` (VM's with the relay resolver, which moved
        from the job service; bare-metal jobs name no relay). `job_service.py` routes,
        looks up the host, runs the executor, and stores what it reports in today's row
        shape; it stores the reported handle as JSON in `process_id` and hands it back to
        `cancel`. `cancel_job` is async, as are the job and contract cancel routes and
        `ComputeContractService.cancel_job`.
      - The executor-side job-done notification is dropped: nothing consumed it (the
        shared wait route polls the job), and the engine's own terminal observer
        arrives with 5B.5. `JobRetryPolicy` is defined here and adopted by the engine in
        5B.5; the job service keeps its settings-based backoff until then.
      - Tests: `provisioning/compute/tests/unit/test_job_executor_table.py` rewritten,
        `test_job_contract_values.py` added, `test_composition.py` updated; the service's
        `tests/unit/services/test_job_service.py` keeps routing and retry arithmetic, and
        `test_ansible_job_executor.py` takes parameter rebuilding, redaction, retry
        classification, and the result payload, and adds a run's handle, outcome, and
        credentials, failure classification, refusal of a non-`ssh` host, and
        cancellation of a real process.
      - Validation: `provisioning/compute` 174; provisioning service 701 unit and 287
        integration; bare-metal adapter 8; the VM adapter's `make test` file 39.
- [x] 5B.3 Ansible distribution skeleton with the `ssh` connection codec. Behaviour-neutral.
      `provisioning/compute/ansible/` (`compute_provisioning_ansible`): `pyproject.toml`
      depending on `arkhai-compute-provisioning` and pydantic only (verify it needs no
      Ansible Python package before committing), `Makefile`, `tests/`, registered in the
      root `Makefile`'s build and dist targets and `docs/development/BUILD_AND_PACKAGING.md`'s
      project list if it lists projects. `connection.py`: the `ssh` codec (payload
      model: `ssh_host`, `public_host`, `ssh_port`, `ssh_user`, `ssh_key_type`,
      `ssh_key_value`; `ssh_key_value` declared secret; validation).
      `compute_provisioning/hosts/connection.py`: the `ConnectionCodec` protocol (kind,
      version, payload validation, secret fields) beside `ConnectionEnvelope`. Tests
      in `provisioning/compute/ansible/tests/unit/test_ssh_connection.py`.
      Done 2026-10-02: `provisioning/compute/ansible/` (`pyproject.toml`, `Makefile`,
      `README.md`, `uv.lock`) with `compute_provisioning_ansible.connection`
      (`SshConnection`, `SshConnectionCodec`; key material is secret only when
      `ssh_key_type` is `embedded`, a key path is not); `ConnectionCodec` in
      `compute_provisioning/hosts/connection.py`. Confirmed no Ansible Python package is
      needed: Ansible runs as a subprocess. Root `Makefile`: `dist-compute-provisioning-ansible`
      (a prerequisite of `dist`, `dist-ci`, and `dist-domains`) and
      `test-compute-provisioning-ansible` (in `test`); `BUILD_AND_PACKAGING.md` lists no
      projects, and the layout and lock checks discover the project from its lock. The
      first lock was created with `uv lock --find-links ../../../.dist`, since
      `scripts/uv_project.py lock` refreshes only an existing lock. Validation: the
      distribution 9; `provisioning/compute` 174; `make check-packaging` passes.
      Corrected for 5B.4: an embedded key is submitted in plaintext and encrypted by
      `HostService` with the service's Fernet key (`HostCreate`'s description saying the
      caller encrypts was stale; an earlier note here repeated it). Settled with the
      maintainer (option A): submission stays as it is, and the codec protects and
      decrypts (design: "The host authority is connection-neutral, and connection secrets
      stay protected"); 5B.4 reshapes this step's codec to public fields, submitted
      secrets, and protected values, replacing `secret_fields`.
- [x] 5B.4 Host authority. Changes the host wire format and schema.
      `compute_provisioning/hosts/connection.py`: `ConnectionEnvelope` gains `public` and
      `protected` in place of `payload`; `ProtectedValue` (`scheme`, `ciphertext`, a
      representation that never shows the ciphertext); `ConnectionCodec` validates public
      fields, submitted secrets, and protected values (names and schemes) and protects
      submitted secrets, in place of `secret_fields`.
      `compute_provisioning_ansible/connection.py`: the `ssh` codec reshaped to public
      fields (`ssh_host`, `public_host`, `ssh_port`, `ssh_user`, optional `key_path`) and
      an optional `fernet-v1` `private_key`, exactly one naming the key, protecting a
      submitted `private_key` with the Fernet key composition gives it (the service's
      `ssh_decryption_key`); decryption arrives in 5B.6. The distribution gains
      `cryptography` (through `arkhai-kit-config`'s `encrypt_secret` and
      `decrypt_secret`, if that keeps the dependency light, else directly). `compute_provisioning/hosts/`: the host record; the service from the generic
      parts of `vm_provisioning_adapter/services/host_service.py` (CRUD, enabled state,
      pool association, codec validation, the capacity-derivation port, the
      pre-execution lookup returning `ExecutionHost` with the protected envelope,
      applying an imported inventory with its pool-change and capacity effects, a
      pool-change hook); a framework-free host route service; the `hosts` table metadata
      on the hosts base. `hosts/models.py`: `HostCreate`, `HostUpdate`, `HostResponse`
      carry `connection` with write-only `secrets` (an embedded key is submitted as
      `secrets.private_key`, plaintext as today); a response names protected values and
      schemes without ciphertext. The Ansible distribution gains INI parsing and rendering between
      inventory files and host records with `ssh` connections (from `host_service.py`;
      importing with embedded keys reads each key file and submits it to the codec to
      protect, as `seed_from_ini` does today).
      Migration in `compute_provisioning_service/db/migrations.py`: `connection_kind`,
      `connection_version`, JSON `connection_public` and `connection_protected` replace the
      `ssh_*` columns; `path` keys become `key_path` and the service-encrypted `embedded`
      ciphertext becomes a `fernet-v1` `private_key` byte for byte, with no cryptography
      in the migration.
      The transitional `AnsibleJobExecutor` reads the envelope (a `private_key` is handed
      to the runner as today's embedded key, which the runner still decrypts until 5B.6).
      Callers: VM's host controller and operations, `vm_provisioning_operator/client.py`,
      the bare-metal adapter, e2e's host registration (`e2e-tests/src/e2e_harness/`,
      `tests/e2e/roles/`), the development environment's host configuration (`dev-env/`,
      `e2e-tests/config/`), and the integration fixtures. Tests:
      `provisioning/compute/tests/unit/test_hosts.py` (envelope and `ProtectedValue`
      never disclose ciphertext in representations or responses; submitted secrets are
      never stored or returned) and
      `tests/integration/test_host_authority.py` (CRUD, codec refusal, lookup carrying
      the protected envelope, import application, pool-change hook, no protected value
      in any read); the codec's tests updated; migration tests (fresh database, upgrade
      with conversion, idempotent rerun, ciphertext preserved byte for byte); the
      service suites.
      Done 2026-10-02:
      - `compute_provisioning/hosts/`: `connection.py` (`ConnectionEnvelope` with
        `public` and `protected`, `ProtectedValue` whose representation omits its
        ciphertext, `ConnectionCodec` with `build` and `validate`, `ConnectionCodecs`),
        `models.py` (`ConnectionSubmission` with write-only `secrets`, `ConnectionView`,
        and `HostCreate`, `HostUpdate`, `HostResponse` carrying `connection`), `db.py`
        (`Host` on the hosts declarative base), and `service.py` (`HostAuthority`:
        CRUD through the codecs, `lookup` returning `ExecutionHost`, `apply_inventory`
        with capacity derivation in its transaction, pool-change hooks; `InventoryHost`;
        `host_response`). An update's `connection` replaces the whole connection, and a
        stored secret the new connection still needs is kept unless resubmitted;
        `HostUpdate.enabled`, accepted and ignored before, is applied.
      - `compute_provisioning_ansible`: the `ssh` codec reshaped (public fields, an
        optional `fernet-v1` `private_key` it protects through `market_config`'s
        `encrypt_secret`, one copy of that code; `ssh_connection` validates its public
        fields) and `inventory.py` (`parse_inventory_ini`, from `host_service.py`). The
        distribution depends on `arkhai-kit-config` and `arkhai-kit-resource-pools`.
      - VM adapter: `host_service.py` tombstoned; the runtime builds `HostAuthority` with
        the `ssh` codec and VM's relay pool-change check as a hook; the hosts controller,
        host operations, system diagnostics, and job service use it;
        `ansible_job_executor.inventory_target` turns an `ExecutionHost` into the
        runner's inventory input, an embedded key still protected (the runner decrypts it
        until 5B.6). The adapter and the service depend on the distribution; both
        adapters, the service, and the distribution were relocked.
      - Service: `db/models.py` re-exports `Host`; `db/database.py` creates the hosts
        metadata; startup seeding parses and applies the INI; migration
        `20261002_001_host_connection_envelope`. `_drop_columns_via_table_rebuild` now
        recreates outbound foreign keys and refuses to drop a column one uses (`hosts`
        references `resource_pools`). The `ssh_decryption_key` comment in
        `settings.toml` describes its role.
      - Callers: the e2e smoke test and VM scenario host registrations build
        `ConnectionSubmission` from `compute_provisioning.hosts`;
        `docs/development/VALIDATION_RUNBOOK.md` and
        `tools/issue-discovery/config/phases/local.yaml` show the new request body. The
        INI files under `dev-env/` are unchanged: the import format is the same.
      - Removed with no production caller: `render_inventory_ini` and
        `get_decrypted_key_value`; the runner renders the only inventory.
      - Tests: `provisioning/compute/tests/integration/test_host_authority.py` (10) and
        the value tests in `test_job_contract_values.py`; the distribution's
        `test_ssh_connection.py` and `test_inventory.py`; the service's
        `tests/unit/test_host_connection_migration.py` (conversion with ciphertext byte for
        byte, idempotent rerun, a fresh database keeping its pool foreign key);
        `test_host_service.py` and `test_host_ssh_port.py` tombstoned (their cases moved
        to those files); integration host registrations rewritten to `ssh_connection`;
        `TestEmbeddedKey` in `test_hosts_api.py` (protected on registration, returned by
        scheme only, decryptable only with the service's key). The integration suite's
        Fernet key is a deterministic all-zero development value.
      - `compute_provisioning` did not declare `sqlalchemy` directly at first; corrected
        after the second implementation review (see "Review round 2" under 5B.6).
      - Validation: `provisioning/compute` 187; the distribution 16; provisioning service
        926 (unit and integration); bare-metal adapter 8; the VM adapter's `make test`
        file 39; e2e unit 236 with the known pre-existing failure.
- [x] 5B.5 Job authority. Changes job wire formats and the schema, and fixes the
      cancellation race. `compute_provisioning/jobs/`: the engine from the generic parts
      of `job_service.py` (submission and idempotency, `JobRetryPolicy` retry timing and
      counts, the retry scheduler, reads, cancellation through the executor with
      conditional terminal transitions, the engine-signalled terminal observer), the job
      queue from `compute_provisioning_service/services/async_job_queue.py`, the rule and
      gate mechanism moved from `compute_provisioning/executor_mock.py` beside it, the
      `ansible_jobs` and `credentials` table metadata on a jobs base, and framework-free
      route services (read, list, logs, cancel, contract record, test drain, wait,
      summary). Migration: `host_id` added and filled (parameter, else
      `executor_target`, else `default_host_id`); JSON `execution_handle` replaces
      `process_id`; `result` stored as `ResultEnvelope`, converted as the contract route
      builds it; `credentials` stores one `CredentialEnvelope` per row in place of its
      SSH columns, converted as VM's contract credentials route builds it. Removed:
      `CredentialResponse`, `CredentialListResponse`, and the operator client's
      re-exports (callers import from `compute_provisioning`). Readers move to the
      envelope: both fulfillment providers, the compute adapters' contract route, the
      shared test wait route, `e2e-tests/src/e2e_harness/provisioning_test_client.py`,
      and VM and bare-metal e2e scenarios that read job results. Tests: engine unit tests
      in `provisioning/compute/tests/unit/test_job_engine.py` (retry policy, outcome
      application, classification honoured); `provisioning/compute/tests/integration/test_job_authority.py`
      (idempotency, cancellation before and after a handle, a late outcome after
      cancellation leaves `cancelled`); migration tests; the service suites.
      Done 2026-10-02, in three parts. Persistence and readers:
      - `compute_provisioning/jobs/db.py`: `JobRecord` (`ansible_jobs`, with `host_id`,
        JSON `execution_handle`, and `result` as a `ResultEnvelope`) and `JobCredential`
        (`credentials`, one `CredentialEnvelope` per row) on the jobs base;
        `JobStatus` and `TERMINAL_JOB_STATUSES`. The service's `db/models.py`
        re-exports them for its own modules and `db/database.py` creates their tables.
      - Migration `20261002_002_job_envelopes`: `host_id` from the parameters, then the
        target, then `default_host_id` (passed through `run_migrations` and
        `apply_schema_migrations`, read by `db/migrate.py` from settings); a bare
        `process_id` becomes `{"pid": n}`; results and credentials become the envelopes
        the contract route served (VM `vm_<action>`, bare metal `bare_metal_access`; a
        job predating offering modes is a VM job); `process_id` and the SSH credential
        columns are dropped.
      - Each mode's executor names its result kind (`vm_result_kind`,
        `bare_metal_result_kind` beside each runtime) and drops empty credential
        fields; the contract route serves the stored envelopes, so `validate_result`
        and `validate_credentials` left `ExecutorAdapter`, `FunctionalExecutorAdapter`,
        composition's hook check, and both compute adapters.
      - Wire: `JobStatusResponse` carries `host_id` and `result` as a `ResultEnvelope`;
        `JobCredentialsResponse` serves `/api/v1/jobs/{id}/credentials`;
        `CredentialResponse` and `CredentialListResponse` are deleted. Both fulfillment
        providers and the shared test wait route read envelopes.
      - Fixed a defect found here: `ansible_fulfillment_provider.py` logged through an
        undefined `logger`, so an unreadable job result raised `NameError` instead of
        being tolerated as documented.
      - Tests: `tests/unit/test_job_envelope_migration.py` (conversion, kinds, handles,
        host fallbacks, credential envelopes, dropped columns, the credentials foreign
        key kept, idempotent rerun); integration and unit readers updated.
      - Validation: provisioning service 930; `provisioning/compute` 187; bare-metal
        adapter 8; the VM adapter's `make test` file 39; e2e unit 236 with the known
        pre-existing failure.
      Corrected after the VM lane (2026-10-02): the engine routed by the contract's
      `action_kind`, so a VM teardown (contract action `teardown`, executor action
      `vm_remove`) found no executor. `JobRecord.executor_action` now holds the
      executed action the engine routes by and `JobRun.action` carries; the job
      migration fills it from parameters and labels converted results by it. Tests:
      `test_job_authority.py` adds a contract action running as a different
      executor action, and `test_fulfillment_api.py`'s teardown test now runs the
      dispatched job to success (it fails with the lane's error under the old
      routing).
      Engine:
      - `compute_provisioning/jobs/engine.py`: `JobEngine` (submission with operation
        and contract deduplication, `JobRetryPolicy` timing and counts, the retry
        scheduler, reads, `get_credentials`, `get_contract_job_record`, cancellation
        through the executor's handle, `process_job`, `wait_for_terminal`, and
        `add_terminal_observer`). It routes by the job's stored offering mode, action,
        and `host_id`, never by its parameters; the job migration also fills
        `offering_mode` and `action_kind` on rows that lacked them.
      - Cancellation: every change is applied by `_transition`, which re-reads the job
        and leaves a cancelled job alone; a job cancelled while queued never starts; a
        cancellation before the executor reported its handle is sent to the executor
        when the handle arrives; `cancel_job` commits before asking the executor.
      - `wait_for_terminal` is signalled in-process when the engine finishes a job and
        re-reads the job otherwise (a separate worker process may run it); the shared
        `/test/jobs/{id}/wait` route uses it, answering 404 and 408 as before.
      - `AsyncJobQueue` moved to `compute_provisioning/jobs/queue.py` and the rule and
        gate mechanism to `compute_provisioning/jobs/executor_mock.py` (old modules
        tombstoned); `MockRuleSet`'s job-done events, which nothing consumed, are gone
        with the VM mock's `notify_job_done` and `get_or_create_job_event`.
      - `vm_provisioning_adapter/services/job_service.py`: `AnsibleJobService` is a thin
        front holding a `JobEngine` (built from `retry_policy_from(settings)` and the
        host authority's `lookup`): it turns `AnsibleJobParams` into a submission and
        answers `reserved_var_keys`; the rest delegates. The lifespan runs
        `process_job`. Building the engine at the composition root moves with the
        routes (5B.8), as do the shared test drain and summary routes.
      Compatibility models: the VM operator client no longer re-exports the host, job,
      health, and version models; every caller imports them from `compute_provisioning`
      (the `Pool*` re-exports in its package root predate this change and are left).
      Tests: `provisioning/compute/tests/integration/test_job_authority.py` (8:
      envelopes stored and completion signalled, retry classification honoured, a late
      outcome after cancellation leaves `cancelled` and stores nothing, a cancellation
      before the handle reaches the executor, a cancelled queued job never runs, an
      unregistered host fails first, deduplication, waiting times out);
      `test_job_service.py` covers submissions and `retry_policy_from`;
      `test_retry_scheduler.py` drives the engine. Validation: `provisioning/compute`
      194; provisioning service 928; bare-metal adapter 8; the VM adapter's `make test`
      file 39; e2e unit 236 with the known pre-existing failure, and every e2e and smoke
      module collects (167); `make check-packaging` and comment hygiene pass.
- [x] 5B.6 The rest of the Ansible distribution. Behaviour-neutral.
      `compute_provisioning_ansible`: the runner and redaction from `ansible_service.py`,
      transport and Ansible failure classification, the codec protocol,
      `AnsibleJobExecutor` (moved from the VM adapter, consuming connections the `ssh`
      codec materializes: the codec decrypts a `private_key` just in time with the
      decryption key composition gives it, writes a transient owner-only key file, and
      removes it when execution ends; the runner's own decryption and the service-wide
      `ssh_decryption_key` read in `ansible_service.py` are removed), connectivity probes
      and readiness
      (with `AnsibleReadinessResponse`, `InventoryInfo`, `FileInfo`, `SshKeyInfo`, and
      `HostConnectivityResponse`) from `system_service.py`, and the mock executor over the
      gate mechanism with a contributed default-output hook (replacing
      `mock_ansible_service.py`). It depends on `compute_provisioning`; nothing in
      `compute_provisioning` depends on it.
      Progress, 2026-10-02 — slice A of three (the runner); slice B (the codec
      protocol, `AnsibleJobExecutor` in the distribution, and the VM and bare-metal
      codecs, absorbing 5B.7) and slice C (the mocks over the gate mechanism with a
      contributed default output, readiness, and connectivity probes) remain:
      - `compute_provisioning_ansible/runner.py`: `AnsibleRunner` (`start_playbook`,
        `wait_for_playbook`, `write_inventory`, `check_connectivity_with_inventory`,
        `extract_json_block`), `AnsibleRun`, `AnsibleResult`, `AnsibleError`,
        `ConnectivityResult`, `InventoryTarget`, `inventory_target`, and
        `redact_ansible_output`, moved from `ansible_service.py`,
        `models/ansible.py` (tombstoned), and `ansible_job_executor.py`.
      - `write_inventory` decrypts an embedded key through
        `SshConnectionCodec.decrypt_private_key`, just in time into an owner-only
        file; the runner holds no cryptography of its own.
      - VM's `AnsibleService` subclasses `AnsibleRunner` and keeps only the VM and
        bare-metal vars and result parsing; every import of the moved names now names
        `compute_provisioning_ansible.runner`.
      - `redact_ansible_output` still matches VM's relay token (`frp_auth_token`):
        slice B decides whether codecs contribute redaction patterns.
      - Tests: `provisioning/compute/ansible/tests/unit/test_runner.py` (decryption
        into an owner-only file, a key path referenced not read, only ssh connections
        reach an inventory, JSON extraction, redaction); the streaming-redaction test
        listens on the runner's logger. Validation: the distribution 21; provisioning
        service 928; bare-metal adapter 8; the VM adapter's `make test` file 39.
      Review round 2, 2026-10-02 (fixes before slice B; maintainer rulings on the
      contested findings are in `design.md`, "Maintainer rulings for review"):
      - VM stage 08a/08c: introduced by Section 4 (checkpoint 1's evaluate-settle fix),
        not pre-existing. The preview looked up the held reservation's host by the hold's
        `resource_id`, which the site strips from what reserving returns, so it always
        previewed no host. `market_storefront/services/admin_settle_service.py` now reads
        the reservation from the site the hold names (`site_client(site)
        .get_reservation`), whose record carries the host it pins;
        `test_admin_settle_service.py`'s held hold is shaped as the site returns it, and
        a reservation the site no longer has previews no host (both fail against the
        previous code). VM storefront unit 1063 (1 skipped); settle and admin
        integration 58.
      - Host reads: every ordinary `HostAuthority` read (`get_host`, `list_hosts`,
        register, update, enable, disable, `apply_inventory`) returns `HostResponse`,
        protected values by scheme only; the row never leaves `hosts/service.py`, and
        only `lookup` returns the protected envelope. `host_response` is private;
        `test_no_ordinary_read_carries_a_protected_value` covers every read.
      - Transient keys: `write_inventory` returns `MaterializedInventory` (the inventory
        and every decrypted key file, `cleanup()`, a context manager); the executor and
        the connectivity check clean it up in `finally`; key files are created
        owner-only (0600, then 0400) rather than restricted after writing; a failure part
        way removes what was written; the VM mock writes a unique inventory per call.
        Tests: the distribution's `test_runner.py` (exists during use, cleanup, partial
        failure, creation mode), `test_ansible_job_executor.py` (gone after success,
        failure, timeout, and cancellation), `test_host_operations_service.py` (gone
        after a connectivity probe). A key file the earlier runner test leaked in this
        environment was found and removed; reruns leave none.
      - Job transitions: `JobEngine._transition` and `cancel_job` are conditional
        `UPDATE`s on the expected status; `test_job_authority.py` adds two engines on one
        SQLite file (two worker processes) and a stale session, and its pre-handle
        cancellation test waits on the executor's cancel signal instead of
        `asyncio.sleep(0)`.
      - Spec deltas: the executor's "receives job-done notification"
        (physical-provisioning) and the mock mechanism's "job-done events"
        (market-composition) are removed.
      - Packaging: `compute_provisioning` declares `sqlalchemy>=2.0`; the distribution's
        dev group declares `cryptography`. Relocked: `provisioning/compute`,
        `provisioning/compute/ansible`, `domains/vms/provisioning/client`, both adapters,
        `domains/bare_metal/storefront`, `provisioning/compute/service`, `e2e-tests`.
        `domains/vms/storefront`, whose PyTorch index redirects to a host the implementing
        environment cannot reach, was relocked by the maintainer; the lock now records
        `sqlalchemy` for the family kit.
      - `reserved_var_keys`: `ReservesVariableKeys` (in `ansible_job_executor.py`) is an
        explicit capability the job service checks; an executor without it is refused
        with a `TypeError` naming the route. It moves into the VM codec in slice B.
      - Validation: `provisioning/compute` 198; the distribution 24; provisioning service
        935; bare-metal adapter 8; the VM adapter's `make test` file 39; e2e unit 236 with
        the known pre-existing failure, and every e2e and smoke module collects (167);
        comment hygiene passes.
      - Checkpoint (2026-10-02), after the maintainer relocked `domains/vms/storefront`:
        `make test` and `make check-packaging` pass; the bare-metal lane passes (11) and
        the VM lane passes in full (129, none skipped), with stage 08a previewing the
        held host and stage 08c and the teardown completion (11b) passing; no job-engine
        error or traceback in any service's logs.
      Progress, 2026-10-02 — slice B (the codec protocol, `AnsibleJobExecutor` in the
      distribution, and both domain codecs; absorbs 5B.7). The protocol's shape and the
      four decisions taken with the maintainer and reviewer are in `design.md`, "The
      Ansible job codec"; findings for review are under "Findings for review (5B.6
      slice B)". Slice C remains.
      - Distribution: `codec.py` (`AnsibleJobCodec`, `AnsibleJobPlan`,
        `AnsibleJobInterpretation`, `matches_any`, `render_extra_vars`,
        `write_extra_vars`); `executor.py` (`AnsibleJobExecutor`, `TRANSPORT_FAILURES`).
        `runner.py`: redaction is generic plus caller-named fields; `wait_for_playbook`
        takes the caller's redactor; `write_inventory(hosts, *, group)`;
        `extract_json_block` and `extract_fact` are module functions; no VM name remains.
      - VM adapter: `codec.py` (`VmAnsibleCodec`, `GoldenImageCredentials`,
        `vm_job_params`, VM facts, `build_result_payload`, `split_credentials`,
        `vm_result_kind`, VM failures, `kvm_hosts`, secret fields `ssh_key_path_host` and
        `frp_auth_token`). `AnsibleJobParams` is `VmJobParams`, without bare-metal fields,
        as is `AnsiblePreparedJobParameters`. `ansible_service.py` and
        `ansible_job_executor.py` are deleted (tombstoned); `ReservesVariableKeys` and
        the job service's `reserved_var_keys` are gone: the fulfillment provider and the
        legacy backfill take the codec's `reserved_var_keys`. The runtime builds the
        executor from the distribution and exposes `job_engine`. The VM mock keeps only
        the runner surface and matches rules on the job's stored parameters. The adapter
        no longer depends on `arkhai-bare-metal`.
      - Bare-metal adapter: `codec.py` (`BareMetalAnsibleCodec`, `BareMetalJobParams`,
        `bare_metal_nodes`, the reclaim policies and default, `reclaim_policy_from`);
        `BareMetalOperationsService` submits through `JobEngine` and validates its reclaim
        policy at composition; the fulfillment provider reads the access fact; the
        runtime builds the executor from the distribution and no longer imports the VM
        adapter's runner or executor. The mock still builds on VM's
        `ProgrammableMockAnsibleService` — the one remaining VM import on bare metal's
        path, intentionally, until slice C; "neither adapter imports the other" is not
        claimed until 5B.10. The adapter depends on the distribution.
      - Service: migration `20261002_003_bare_metal_job_shapes`; the reclaim-policy
        constants and property leave `config.py`; the container passes `job_engine` to
        bare metal; `non_retryable_errors` defaults to `[]` (additional patterns).
      - Playbooks: `node-access.yaml` (targeting `bare_metal_nodes`, no `vm_action`
        fallback) and `roles/bare-metal-access` are under
        `domains/bare_metal/provisioning/iac/ansible`; the VM tree's copies are deleted.
        `bare_metal_playbook_path` follows in `settings.toml`, `config-docker.yml`, and
        Helm `values.yaml`; the Dockerfile and its `.dockerignore` copy the bare-metal
        IaC; `domains/bare_metal/compose.yml` mounts it (and
        `scripts/tests/test_bare_metal_compose.py` checks the mount); the service's
        `serve` target sets the path.
      - Tests: the distribution's `test_codec.py`, `test_executor.py`, and new
        `test_runner.py` cases; the bare-metal adapter's `test_bare_metal_codec.py`
        (including the playbook contract), `execution.py` helpers, and the mock and
        provider tests driven through the real executor and codec; the service's
        `test_vm_codec.py` (replacing `test_ansible_service.py` and
        `test_ansible_job_executor.py`, both deleted) and
        `test_bare_metal_job_shape_migration.py`; the bare-metal integration tests
        assert the bare-metal shapes; `test_programmable_mock.py`'s gate test waits on
        the held signal instead of `asyncio.sleep(0)`. The service suite shrinks from
        935 to 915 because executor and bare-metal tests moved to the distribution
        (24 to 51) and the bare-metal adapter (8 to 22).
      - Validation: `provisioning/compute` 198; the distribution 51; provisioning
        service 915; bare-metal adapter 22; the VM adapter's `make test` file 39; VM
        IaC 65; e2e unit 236 with the known pre-existing failure, and every e2e and smoke
        module collects (167); comment hygiene passes. Relocked: the distribution, both
        adapters, the service; `domains/vms/storefront` is unaffected. Not run in the
        implementing environment (no container runtime): the compose rendering test and
        the e2e lanes.
      Progress, 2026-10-02 — slice C (the mock runner and the probes); 5B.6 is complete.
      Decisions and findings are in `design.md`, "The mock runner and the probes" and
      "Findings for review (5B.6 slice C)".
      - Distribution: `mock.py` (`MockAnsibleRunner`, `MockPlaybook`, `DefaultOutput`);
        `probes.py` (`probe_connectivity`, `ansible_readiness`, `ansible_version`,
        `collect_ssh_keys_from_hosts`, `sha256_file`, `PROBE_INVENTORY_GROUP`, and the
        models `AnsibleReadinessResponse`, `InventoryInfo`, `FileInfo`, `SshKeyInfo`);
        `runner.py`: `AnsibleRun.job_parameters` and `start_playbook(job_parameters=…)`;
        `executor.py`: passes the job's parameters explicitly, exposes the runner's
        `rules`, and refuses to signal a process id of zero or less.
      - VM adapter: `services/mock_output.py` (`vm_mock_output`) replaces
        `services/mock_ansible_service.py` (deleted); the runtime composes
        `MockAnsibleRunner` under the mock profile; the test controller reads the mock's
        rules and evaluates with `MockRuleSet.evaluate`; `system_service.py` delegates
        readiness, and `host_operations_service.py` connectivity, to the probes.
      - VM operator client: the readiness models and `ConnectivityResult` come from the
        distribution, which it now depends on; `HostConnectivityResponse` and the moved
        models are removed from `models.py` and the package's exports.
      - Bare-metal adapter: `services/mock_output.py` (`bare_metal_mock_output`) replaces
        `services/bare_metal_mock_executor.py` (deleted); the runtime composes
        `MockAnsibleRunner`. Neither the adapter's source nor its tests import the VM
        adapter; its declared dependency goes in 5B.10.
      - Tests: the distribution's `test_mock.py` (rules, gates, failure, the default
        output from the job and its registered host, the executor modes the family
        reports, cancelling a mocked run) and `test_probes.py`; the service's
        `test_programmable_mock.py` is deleted (moved); the bare-metal adapter's
        `test_bare_metal_mock_executor.py` becomes `test_bare_metal_mock_output.py`; the
        integration fixtures compose `MockAnsibleRunner` with each domain's output. The
        distribution's dev group gains `pytest-asyncio`.
      - Validation: `provisioning/compute` 198; the distribution 74; provisioning
        service 894 (the 21 mock tests moved to the distribution); bare-metal adapter 22;
        the VM adapter's `make test` file 39; VM IaC 65; e2e unit 236 with the known
        pre-existing failure, and every e2e and smoke module collects (167). Relocked: the
        distribution, the VM operator client, both adapters, the service, `e2e-tests`.
      Implementation-review corrections, 2026-10-03 (`design.md`, "Maintainer rulings on
      the 5B.6 implementation review"; 5B.6 was reopened for them and is checked again
      now they have landed):
      - Held mock cancellation: the runner owns cancellation (`AnsibleRunner`
        `execution_handle` and `cancel`, refusing pid ≤ 0; `MockAnsibleRunner` names a
        run and ends its gate wait as a cancelled playbook); `AnsibleJobExecutor.cancel`
        delegates. The family kit gains `MockRuleSet.wait_until_released` and
        `AsyncJobQueue.wait_until_idle`. Integration test in
        `test_bare_metal_mock_profile.py`; `TESTING.md` gains "Leave nothing held".
      - Inventory: `parse_inventory_ini` registers every host entry, skipping only
        `[group:vars]` and `[group:children]`; `HostAuthority.apply_inventory` logs the
        hosts it registers. VM's inventory directory: `inventory/hosts.example`
        (infrastructure; the `[kvms]` group the VM role writes),
        `inventory/provisioning-hosts.example` (new), `.gitignore`, `ansible.cfg`
        (`inventory_ignore_extensions`), the IaC `Makefile`,
        `domains/vms/provisioning/iac/scripts/run_acceptance_validation.sh`, `README.md`,
        `vm-vars-example.yaml`.
        `inventory_path` names `provisioning-hosts.ini` in `settings.toml`,
        `config-docker.yml`, `config-local.yml.example`, Helm `values.yaml`, and the
        service's `serve`. Docs: `seller-quickstart.md`, `bare-metal-seller-quickstart.md`,
        `VALIDATION_RUNBOOK.md`; `compose/seller.live.yml`'s comment; the VM
        host-import route's description.
      - Shared Ansible configuration: `compute_provisioning_ansible/ansible.cfg` and
        `DEFAULT_ANSIBLE_CONFIG`; `apply_ansible_config` uses it when `ansible_cfg` is
        empty, now the default in `settings.toml`; the docker and mock profiles and
        `serve` no longer name VM's. Bare metal's
        `provisioning/iac/ansible/requirements.yml`; the Dockerfile's collection list is
        the union, held by `tests/unit/test_image_collections.py`; the Dockerfile no
        longer copies VM's requirements. `domains/bare_metal/compose.yml` no longer
        mounts the VM tree (`scripts/tests/test_bare_metal_compose.py` asserts it).
      - `non_retryable_errors` is `additional_non_retryable_errors` (setting, executor
        parameter, fixtures).
      - The compute mock module's docstring no longer mentions job-done notification.
      - `test_job_envelope_migration.py` and `test_bare_metal_job_shape_migration.py`
        move to `tests/integration`.
      - Validation: `provisioning/compute` 202; the distribution 79; provisioning
        service 897; bare-metal adapter 22; VM IaC 65; VM's inventory directory loads
        only its two inventory files under VM's `ansible.cfg` (checked with
        `ansible-inventory`).
- [x] 5B.7 Domain codecs. Behaviour-neutral on the wire. Absorbed into slice B of 5B.6,
      with one amendment decided there: bare metal's stored parameters and results are
      bare-metal-shaped (`design.md`, "The Ansible job codec", decision 2), which changes
      what `JobStatusResponse` reports for bare-metal jobs; existing rows are migrated.
      `vm_provisioning_adapter/codec.py` (VM vars, golden-image credentials, VM facts,
      VM failure classification, credential meaning, VM parameter building) and
      `bare_metal_provisioning_adapter/codec.py` (access vars and facts, access
      parameters); both runtimes register the distribution's `AnsibleJobExecutor`s; move
      `iac/ansible/playbooks/bare-metal` and `roles/bare-metal-access` to
      `domains/bare_metal/provisioning/iac`, with `provisioning/compute/service/Dockerfile`
      and `settings.toml` following. Deleting `bare_metal_mock_executor.py`, replaced by
      bare metal's contributed default output, moves to slice C of 5B.6.
- [ ] 5B.8 Controls and routes. Decided with the maintainer on 2026-10-04: `design.md`,
      "Controls and routes (5B.8)", decisions 1–11, including the same day's design
      review. Four slices, A0 → A → B → C, each its own checkpoint. A slice ends with the
      provisioning-family suites green (`provisioning/compute`, its Ansible distribution,
      the provisioning service's unit and integration suites, both adapters, the client
      packages it touches), `make check-comment-hygiene`, and `make check-packaging`.
      Every package a slice changes is bumped per `docs/development/RELEASING.md` (minor
      for an incompatible change while below 1.0.0), exact pins move everywhere they
      appear, and changed projects are relocked with `scripts/uv_project.py lock`; the
      versions are recorded in that slice's implementation notes. Implementation
      re-verifies each named file by grep before moving it; a file found missing or a
      caller found unlisted is added to the slice, not skipped. Removed files are
      tombstoned in the checkpoint fileset.

      **Route ownership.** Every route the provisioning service serves, and the package
      that owns its contract and client after A0:

      | Routes | Owner | Contracts | Typed client |
      |---|---|---|---|
      | `/api/v1/fulfillment/*` (schedule, validate, begin, begin-teardown, status, result) | compute family | `compute_provisioning_contracts` | `compute_provisioning_client` |
      | `/api/v1/contract/leases*` (and, from B, list and release-oversight) | compute family | `compute_provisioning_contracts` | `compute_provisioning_client` |
      | `/api/v1/jobs`, `/api/v1/jobs/{id}`, its logs, credentials, cancel | compute family | `compute_provisioning_contracts` | `compute_provisioning_client` |
      | `/api/v1/hosts*` CRUD, enable, disable, connectivity | compute family | `compute_provisioning_contracts` | `compute_provisioning_client` |
      | `/api/v1/hosts/import` | Ansible implementation | `compute_provisioning_ansible` (declaration) | `compute_provisioning_ansible` (extension) |
      | `/api/v1/system/*` (health, status, version, readiness until C, worker controls), `/api/v1/identity/rotations/*` | provisioning service; contracts and client in the compute family's packages, the service being the family's deployable | `compute_provisioning_contracts` | `compute_provisioning_client` |
      | `/test/jobs/*` | compute family (mock profile) | `compute_provisioning_contracts` | e2e harness `ProvisioningTestClient` |
      | `/api/v1/pools*` | resource pools | `market_resource_pools_contracts` | `market_resource_pools_client` |
      | `/api/v1/capacity/definitions/import` | site | `kit/site-client` (its own table) | `kit/site-client` |
      | `/api/v1/capacity/*` (resources, projections, snapshot, probe, reservations, commit, releases, truncate-lease, events) | site | `kit/site/auth.py` table, assembled by the service; `kit/site-client` | `kit/site-client` |
      | `/api/v1/hosts/{host}/capacity`, `/api/v1/hosts/{host}/vms*` | VM | `vm_provisioning_operator` (declarations) | `vm_provisioning_operator` (extension) |
      | `/api/v1/relays*` | VM | `vm_provisioning_operator` (declarations) | `vm_provisioning_operator` (extension) |
      | `/api/v1/leases*`, `/api/v1/admin/leases*` (until B) | VM | `vm_provisioning_operator` | `vm_provisioning_operator` (extension) |
      | `/test/mock-rules*`, `/test/evaluate-job` | VM | `vm_provisioning_operator` | e2e harness `ProvisioningTestClient` |
      | `/api/v1/bare-metal/leases*` (until B) | bare metal | `arkhai_bare_metal` | `BareMetalLeaseClient` (until B) |
      | `/test/bare-metal/*` | bare metal | `arkhai_bare_metal` | none (finding) |
      | `/api/v1/actions`, `/api/v1/jobs/{id}/contract*` | deleted in A0.1 | — | — |

      The provisioning service's request authentication resolves against the table its
      composition root assembles from the family contracts, `kit/site`'s
      `CAPACITY_ROUTE_CONTRACTS`, the resource-pool declarations, the Ansible host-import
      declaration, and each adapter's declarations; the family table stops copying the
      site's capacity routes.

      **Slice A0: the action surface goes, and contracts and clients move to their owners.**
      Changes no wire beyond removing the action surface.

  - [ ] 5B.8.A0.1 Delete the generic action surface (decision 10). Remove
        `POST /api/v1/actions` and `GET /api/v1/jobs/{id}/contract`, `.../credentials`, and
        `.../cancel`: their contracts in `provisioning/compute/src/compute_provisioning/client.py`,
        their routes in
        `provisioning/compute/service/src/compute_provisioning_service/controllers/compute_contract_controller.py`,
        and the action and contract-job half of
        `services/compute_contract_service.py` (with `ReservationNotProvisionableError` and the
        `job_service` parameter; the lease half stays until B). Tombstone
        `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/compute_adapter.py` and
        `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/compute_adapter.py`.
        `provisioning/compute/src/compute_provisioning/adapters.py` loses `ExecutorAdapter`,
        `FunctionalExecutorAdapter`, `ExecutorAdapterRegistry`, `UnsupportedExecutorActionError`,
        and `ExecutorMismatchError` (keeping `JobExecutorResolver` and `JobExecutorTable`);
        `composition.py`'s `ExecutorAdapterContribution` becomes `offering_mode`,
        `job_executors`, and (until B) `release_executor`, `_validate_executor` checks those,
        and `ComposedComputeAdapters` loses `executor_registry`. Both adapters' `runtime.py`
        and `bundle.py` stop building compute adapters; `compute_provisioning/__init__.py` and
        `container.py` follow. `ComputeProvisioningClient` loses `submit_action`, the contract
        job methods, and `wait_for_job`-style helpers that read them. Tests:
        `provisioning/compute/service/tests/integration/test_compute_contract_api.py` keeps only
        its lease cases (moved to B's lease tests then); `provisioning/compute/tests/unit/test_composition.py`
        and `test_route_table.py`, `provisioning/compute/service/tests/unit/test_route_table_composition.py`
        and `unit/middleware/test_auth.py` drop the action routes and adapter registration;
        `unit/services/test_provider_registry.py` keeps its provider cases. Spec:
        `physical-provisioning` "Validated executor registration" and
        `compute-provisioning-contract` are already amended in this change's deltas.
  - [ ] 5B.8.A0.2 `VersionedEnvelope` to core (decision 8). Move
        `kit/fulfillment/src/market_fulfillment/envelopes.py` (`VersionedEnvelope`, `envelope`)
        to `core/src/market_core/envelopes.py`, exported from `market_core`; tombstone the old
        module; every importer takes it from `market_core` with no re-export from
        `market_fulfillment`: `kit/fulfillment`'s `__init__.py`, `db.py`, `fulfillment.py`,
        `fulfillment_persistence.py`, `provider.py`, `results.py`, `settlement_repository.py`;
        both providers and `vm_provisioning_adapter/fulfillment_results.py`;
        `compute_provisioning/client.py` and `contracts.py`; the service's
        `controllers/fulfillment_controller.py` and `services/fulfillment_convergence.py`; the
        VM storefront's `services/capacity_client.py`, `fulfillment_resume_runtime.py`,
        `fulfillment_service.py`; the bare-metal storefront's `fulfillment_service.py` and
        `hosted_lifecycle.py`; and their tests (`kit/fulfillment/tests/unit/test_envelopes.py`
        moves to `core/tests/unit/test_envelopes.py`). `kit/fulfillment/pyproject.toml` depends
        on `arkhai-core`.
  - [ ] 5B.8.A0.3 Compute contracts distribution (decision 8). New
        `provisioning/compute/contracts/` (`arkhai-compute-provisioning-contracts`,
        `compute_provisioning_contracts`; depends on `arkhai-core`, `arkhai-kit-identity`,
        pydantic) with `Makefile`, `pyproject.toml`, `py.typed`, and tests. It receives
        `compute_provisioning/contracts.py` whole, `hosts/models.py`, `jobs/models.py`,
        `system_models.py`, `ConnectivityResult` (from
        `provisioning/compute/ansible/src/compute_provisioning_ansible/runner.py`, which then
        imports it), and the route-contract half of `compute_provisioning/client.py`
        (`ProvisioningRouteContract`, `PROVISIONING_ROUTE_CONTRACTS` without the site's capacity
        routes and without the pool, capacity-definition, host-import, and relay routes,
        `_family_roles`, `ProvisioningRouteTable`, `assemble_provisioning_route_table`,
        `route_contract_from_declaration`, `resolve_provisioning_route`,
        `canonical_provisioning_request_body`). Tombstone the moved modules in
        `compute_provisioning`; `compute_provisioning/__init__.py` stops exporting wire models
        and drops the pool and capacity-definition re-exports. Every importer is repointed:
        `compute_provisioning`'s own modules (`hosts/service.py`, `hosts/connection.py`,
        `jobs/engine.py`, `jobs/executor.py`, `executor_leases.py`, `lease_lifecycle.py`,
        `composition.py`, `app.py`), the Ansible distribution, both adapters, the service
        (`middleware/auth.py`, `main.py`, every controller and service importing wire models),
        and the tests that import them. The service's `main.py` assembles the table from the
        family contracts, an adapter of `market_site.auth.CAPACITY_ROUTE_CONTRACTS`, the
        resource-pool declarations, the Ansible host-import declaration, and the adapters'
        declarations. Moved tests: `provisioning/compute/tests/unit/test_contracts.py`,
        `test_job_contract_values.py`, `test_route_table.py` to
        `provisioning/compute/contracts/tests/unit/`. Registered in the root `Makefile`
        (`dist-compute-provisioning-contracts`, ahead of `dist-compute-provisioning`),
        and `.github/workflows/publish-pypi.yml` and `docs/development/RELEASING.md` wherever
        its siblings are listed; the service image derives its internal packages from the
        lock, which `make check-packaging` confirms.
  - [ ] 5B.8.A0.4 Compute client distribution (decision 8). New
        `provisioning/compute/client/` (`arkhai-compute-provisioning-client`,
        `compute_provisioning_client`; depends on the contracts, `arkhai-kit-identity`, httpx)
        with `ComputeProvisioningClient` and `SyncComputeProvisioningClient` over one signing
        base merged from the family client's request signing and VM's
        `_ProvisioningClientBase`; one error hierarchy (`ComputeProvisioningError`,
        `ComputeProvisioningJobError`, `ComputeProvisioningTimeoutError`); `authenticated_request`
        in both variants; the polling helper; `ComputeProvisioningClientProtocol`. Methods:
        exactly the routes the matrix gives the compute family and the provisioning service —
        fulfillment, contract leases, admin jobs, hosts (no import), system health, status,
        version, readiness, the worker controls, identity rotation. Family methods return
        their contract models. Tombstone `compute_provisioning/client.py`.
        `provisioning/compute/pyproject.toml` drops httpx if nothing else needs it. Parity:
        `provisioning/compute/service/tests/unit/test_provisioning_client_contract.py` asserts
        the two variants' public methods and signatures match.
  - [ ] 5B.8.A0.5 Resource-pool contracts and client (decision 11). New
        `kit/resource-pools-contracts/` (`arkhai-kit-resource-pools-contracts`,
        `market_resource_pools_contracts`; pydantic and `arkhai-kit-capability-shape`)
        receiving `kit/resource-pools/src/market_resource_pools/pools.py` and `hints.py`, plus
        the pool route declarations as plain data (moved out of the family table). New
        `kit/resource-pools-client/` (`arkhai-kit-resource-pools-client`,
        `market_resource_pools_client`; the contracts only) with `ResourcePoolClient` and
        `SyncResourcePoolClient` over any transport offering `authenticated_request`, and a
        parity test in `kit/resource-pools-client/tests/unit/`. `hints.py` moves with the
        models because their validators call it. `market_resource_pools` imports models and
        hints from the contracts (`service.py`, `__init__.py`) and no longer exports them, so
        every importer of a pool model or a hint function is repointed, re-verified by grep:
        the service's `controllers/pools_controller.py`; `kit/fulfillment`'s `fulfillment.py`
        and `scheduler.py`; `kit/site`'s `ledger.py`; `domains/apicredits/service`'s
        `db/database.py`; the bare-metal storefront's `site_reading.py`; `domains/vms/listings`'
        `listing_shapes.py`, `reconciler.py`, `pricing_resolution.py`,
        `listing_cardinality_mode.py`, and `pool_descriptors.py`; the VM storefront's
        `services/listing_sources.py` and `negotiation_runtime.py`; and their tests
        (`kit/resource-pools`' `test_hints.py` and `test_pool_models.py` move to the contracts
        package). Each repointed package depends on the contracts. Registered in `kit/Makefile`
        (`dist-ci`, `test`).
  - [ ] 5B.8.A0.6 Capacity-definition import in `kit/site-client` (decision 11): its own
        request and response models in `market_site_client/models.py`, its route-table entry in
        `client.py`, an import method on the site client, and
        `kit/site/tests/unit/test_auth_route_parity.py` extended to compare the server's
        contract for the route with the client's. The server's contract is a separate
        `CAPACITY_DEFINITION_ROUTE_CONTRACTS` in `market_site.auth`, which the provisioning
        service assembles and a standalone site never mounts.
  - [ ] 5B.8.A0.7 VM and Ansible extension clients (decisions 8 and 4). `vm_provisioning_operator`
        keeps `models.py` and `routes.py` (gaining the relay route declarations, moved from the
        family table, and the relay models from `compute_provisioning/relays.py`, tombstoned);
        `client.py` becomes `VmOperatorClient` and `SyncVmOperatorClient` over the family
        client's `authenticated_request`: VM operations, host capacity, relays, and (until B)
        VM's `/api/v1/leases` methods. The generic `ProvisioningClient` and
        `SyncProvisioningClient` are deleted; `domains/vms/provisioning/client/pyproject.toml`
        depends on the compute contracts and client only, dropping `arkhai-compute-provisioning`
        and `arkhai-compute-provisioning-ansible`. The service's `relays_controller.py` and
        relay services import relay models from `vm_provisioning_operator`. The Ansible
        distribution gains `compute_provisioning_ansible/host_import.py` with the
        `/api/v1/hosts/import` declaration and an `AnsibleHostImportClient` (async and sync)
        over the family transport; `provisioning/compute/ansible/pyproject.toml` depends on the
        compute client. `arkhai_bare_metal`'s `BareMetalLeaseClient` imports its transport
        protocol from the compute client until B deletes it.
  - [ ] 5B.8.A0.8 Callers. Storefronts: `domains/vms/storefront` (`services/capacity_client.py`,
        `fulfillment_service.py`, `fulfillment_resume_runtime.py`, `system_service.py`, and
        `tests/unit/test_fulfillment_service.py`) and `domains/bare_metal/storefront`
        (`site_clients.py`, `fulfillment_service.py`, `hosted_lifecycle.py`) import from the
        compute contracts and client, and their `pyproject.toml` drop `arkhai-compute-provisioning`
        if grep finds nothing else imported from it. e2e: `e2e-tests/src/e2e_harness/provisioning_test_client.py`
        assembles from the compute contracts and the domain declarations;
        `tests/e2e/roles/scenarios/vms/conftest.py`, `host_registry.py`, `hosted/network.py`,
        `test_multi_registry.py`, `test_pool_declared_offering_modes.py`, `test_vm_introduction.py`,
        `scenarios/bare_metal/conftest.py`, `test_bare_metal_publication.py`,
        `test_bare_metal_introduction.py`, and `tests/smoke/test_provisioning_smoke.py` use
        `SyncComputeProvisioningClient` for family routes, `SyncResourcePoolClient` for pools,
        `SiteCapacityClient` (through `asyncio.run`, as bare-metal e2e already does) for
        capacity reads, and `SyncVmOperatorClient` only for VM operations and VM leases;
        `e2e-tests/pyproject.toml` follows. Service integration and unit tests move to the new
        clients' async variants: `integration/conftest.py`, `test_capacity_definitions_api.py`,
        `test_hosts_api.py`, `test_host_capacity_derivation_api.py`, `test_leases_api.py`,
        `test_pools_api.py`, `test_provisioning_client_endpoint_coverage.py`,
        `test_test_controller.py`, `test_vms_api.py`, `test_fulfillment_api.py`,
        `test_host_requirement_api.py`, `test_relays_api.py`, `test_bare_metal_mock_profile.py`,
        `unit/models/test_jobs_models.py`, `unit/services/test_host_operations_service.py`,
        `test_ledger_lease_lifecycle.py`, `test_vm_operations_service.py`,
        `unit/test_import_boundaries.py`, `unit/test_lease_models.py`;
        `provisioning/compute/tests/integration/test_fulfillment_client_opacity.py`.
  - [ ] 5B.8.A0.9 Gate. The slice's suites plus `kit/fulfillment`, `kit/resource-pools` and its
        two new packages, `kit/site`, `kit/site-client`, `core`, `domains/vms/listings`, both
        storefronts, and the e2e unit suite pass; `make check-packaging` passes. A boundary
        check in each new package's unit suite asserts its declared dependencies:
        `compute_provisioning_contracts` imports no SQLAlchemy, FastAPI, or other
        `compute_provisioning*` module; `market_resource_pools_client` imports no
        `compute_provisioning*` or SQLAlchemy module.

      **Slice A: the authorities at the root, and the job and host routes.**

  - [ ] 5B.8.A.1 Authorities at the root (decision 5). `container.py` builds one
        `HostAuthority` (codecs from `compute_provisioning_ansible`'s `SshConnectionCodec` with
        the decryption key, capacity derivation, merged pool-change hooks) and one `JobEngine`
        (the executor table, `host_authority.lookup`, the retry policy). `retry_policy_from`
        moves from VM's `services/job_service.py` to
        `provisioning/compute/service/src/compute_provisioning_service/services/job_retry.py`.
        VM exports its relay pool-change hook as `HOST_POOL_CHANGE_HOOKS` from
        `vm_provisioning_adapter/runtime.py`, merged by the root like `HOST_REQUIREMENT`. Both
        `runtime.py` files take `host_authority` and `job_engine` as parameters and build
        neither. VM's `services/job_service.py` is tombstoned in favour of
        `services/job_submitter.py` (`VmJobSubmitter`: `VmJobParams` into an engine submission,
        `default_host_id` passed as a value, no `config.Settings` import); the fulfillment
        provider, `vm_operations_service.py`, and `host_operations_service.py` read jobs from
        the engine. `app_runtime.py` runs `engine.process_job` and the engine's retry scheduler.
        The container's `resolved_job_service` and `resolved_host_service` become
        `resolved_job_engine` and `resolved_host_authority`. Tests:
        `unit/services/test_job_service.py` becomes `test_job_submitter.py`; new
        `provisioning/compute/service/tests/unit/test_authority_composition.py` asserts one
        engine and one host authority reach both runtimes; `test_retry_scheduler.py` follows.
  - [ ] 5B.8.A.2 Route services (decision 4). `compute_provisioning/route_errors.py` defines
        `ProvisioningRouteError(status_code, detail)`; `jobs/executor_mock.py`'s
        `MockRouteError` is folded into it, and both adapters' test controllers map it.
        New `compute_provisioning/jobs/route_service.py` (`JobRouteService`: list, get, logs,
        credentials, cancel; `JobTestRouteService`: summary, drain, wait) and
        `compute_provisioning/hosts/route_service.py` (`HostRouteService`: CRUD, enable,
        disable, connectivity through probes keyed by connection kind, refusing an unknown
        kind with 422). New `compute_provisioning_ansible/host_import.py`'s
        `AnsibleHostImportRouteService` over the host authority and `parse_inventory_ini`.
  - [ ] 5B.8.A.3 Bindings. New service controllers `controllers/jobs_controller.py`,
        `hosts_controller.py`, `test_jobs_controller.py` (mounted under the mock profile), and
        `host_import_controller.py`, mounted from `main.py` and resolving collaborators from the
        container. VM's `controllers/jobs_controller.py` is tombstoned; VM's
        `controllers/hosts_controller.py` keeps only `GET /api/v1/hosts/{host}/capacity`; VM's
        `controllers/test_controller.py` loses the shared `/test/jobs` routes; VM's
        `services/host_operations_service.py` keeps the capacity check and loses connectivity.
        The root builds the probe runner (`AnsibleRunner`, or `MockAnsibleRunner` under the mock
        profile) and registers `ssh` → `probe_connectivity` over it. Both adapters'
        `pyproject.toml` declare FastAPI and `fastapi-utils`, which they import.
  - [ ] 5B.8.A.4 Drift guard and tests. New
        `provisioning/compute/service/tests/unit/test_route_binding.py`: every route the app
        mounts resolves to exactly one contract in the assembled table, and every contract to a
        mounted route. Route services get unit tests in `provisioning/compute/tests/unit/`
        (`test_job_route_service.py`, `test_host_route_service.py`) and
        `provisioning/compute/ansible/tests/unit/test_host_import.py`; `test_hosts_api.py`,
        `test_system_api.py`, and `test_test_controller.py` cover the bound routes through the
        typed clients. Gate as above.

      **Slice B: the lease surface and mode-agnostic release** (decisions 1–3, 9, and 7.3).

  - [ ] 5B.8.B.1 Ledger (`kit/site/src/market_site/ledger.py`, `authority.py`):
        `attach_lease` writes the lease tail once (first attachment only on an unleased held
        reservation; an equal repeat returns it unchanged and never moves the end; a different
        target or start refused; `releasing`, `release_failed`, `unmanaged` refused; a recorded
        create handle never replaced); `truncate_lease` refuses `reserved`, `provisioning`,
        `releasing`, `release_failed`, `unmanaged`, and a later end, and never sets the state.
        Tests in `kit/site/tests/integration/test_ledger.py`.
  - [ ] 5B.8.B.2 Lease contract and route service. `compute_provisioning_contracts`'
        `LeaseRegistration` drops `offering_mode`; it gains `LeaseListResponse` and the
        release-oversight request; the family table gains list and release-oversight with the
        roles of decision 1 (register, get, terminate: seller and admin; list, oversight,
        retry, force: admin), the default for an unlisted operation becomes seller and admin,
        the dual-role set is removed, and `route_contract_from_declaration` refuses a
        declaration without `admin`. New `compute_provisioning/leases.py` (`LeaseRouteService`:
        register, get, list filtered by status and offering mode, terminate, release-oversight,
        retry-release, force-release) over `ExecutorLeaseService` (no mode scoping, no update)
        and `LeaseLifecycleService` (no `update_lease`). The service's
        `controllers/leases_controller.py` binds it at `/api/v1/contract/leases`;
        `compute_contract_controller.py` and `services/compute_contract_service.py` are
        tombstoned. The client gains `list_leases` and `release_lease_oversight`.
  - [ ] 5B.8.B.3 Release (decision 9, absorbing 7.3). `compute_provisioning/release.py`
        receives `FulfillmentTeardownPort`, `FulfillmentServiceTeardownPort`, and the release
        executor and status port from `vm_provisioning_adapter/release.py` (tombstoned) as
        `FulfillmentReleaseExecutor` and `FulfillmentReleaseJobPort`, and loses
        `ExecutorReleaseDispatcher` and `ReleaseJobDispatcher`. The executor decides by the
        aggregate's state: `active` begins teardown; absent or `assigned` with provenance
        proving no dispatch (no aggregate past `assigned`, no create handle on the reservation,
        no job for the reservation — `JobEngine` gains `has_job_for_reservation`) abandons an
        `assigned` aggregate through the settlement repository and returns a
        nothing-delivered outcome the lifecycle finishes as a completed release;
        `dispatch_pending` or `dispatching` returns a pending outcome; `failed`, or no proof,
        returns an unreleasable outcome. `lease_lifecycle.py`: the watchdog and terminate move a
        pending release to `releasing` with the fulfillment id as release handle; the
        releasing pass begins teardown once the aggregate is `active`, records `release_failed`
        if it ends `failed`, and skips the grace timeout while the create is in flight; the
        `direct-release` sentinel and its branch go; failure reasons become `teardown_failed`
        and `teardown_timeout`. `composition.py` drops `release_executor` from the contribution
        and `release_dispatcher` from the composed result; `container.py` builds the one
        executor and port. Tombstone
        `bare_metal_provisioning_adapter/release.py`. Tests:
        `provisioning/compute/tests/unit/test_release.py` (every aggregate state, the
        provenance proof's three parts), `test_lease_lifecycle.py` (pending release survives a
        restarted lifecycle; teardown begins at `active`; no grace timeout in flight),
        `provisioning/compute/service/tests/unit/services/test_release_executors.py`,
        `test_ledger_lease_lifecycle.py`, `integration/test_legacy_backfill_teardown.py`, and a
        new `integration/test_lease_release_api.py` covering a bare-metal expiry through the
        aggregate, a never-dispatched lease released directly, and a lease terminated while
        its create is in flight.
  - [ ] 5B.8.B.4 Deletions (decision 1). VM: `controllers/leases_controller.py` (tombstoned),
        the lease route declarations in `vm_provisioning_operator/routes.py`, the `Lease*`
        models in `vm_provisioning_operator/models.py`, and the extension client's lease
        methods. Bare metal: `controllers/bare_metal_leases_controller.py`,
        `services/bare_metal_lease_service.py` (tombstoned), `BARE_METAL_LEASE_ROUTES` and
        `BareMetalLeaseClient` in `arkhai_bare_metal/provisioning_client.py`, `BareMetalLeaseView`
        and `bare_metal_access_ref` in `arkhai_bare_metal`; `BareMetalLeaseCreate` renamed
        `BareMetalAccessGrant` in the provider and operations service. Both `routers.py`
        follow. Tests: `test_leases_api.py` becomes the family lease API test (list filters,
        roles, write-once registration, no update route);
        `integration/test_bare_metal_leases_api.py` and `unit/services/test_bare_metal_lease_service.py`
        are tombstoned; `test_bare_metal_mock_profile.py` drives grants through
        `begin_fulfillment`; `domains/bare_metal/tests/test_provisioning_client.py` keeps only
        the test-route declarations.
  - [ ] 5B.8.B.5 The VM storefront's uncommitted hold (decision 9).
        `domains/vms/storefront/src/market_storefront/settlement_composition.py`'s
        terminal-settlement path releases a `reserved` reservation through the capacity
        runtime's `release` instead of truncating it; `admin_controller.py`'s interruption keeps
        its 409 on refusal. Test: `tests/integration/test_abandon_truncation.py`.
  - [ ] 5B.8.B.6 e2e. `scenarios/vms/conftest.py`'s `DealLease` reads leases through
        `SyncComputeProvisioningClient` and backdates through `SiteCapacityClient.truncate_lease`
        signed as admin; `test_full_deal.py`, `test_full_deal_buyer_cli.py`, and
        `test_buy_oneshot_buyer_cli.py` follow. Gate as above, plus `kit/site` and the VM
        storefront.

      **Slice C: the system split and the last `container` reach** (decisions 4 and 7).

  - [ ] 5B.8.C.1 Status. `compute_provisioning_contracts` gains `SystemStatusResponse`
        (today's fields, `checks.execution`, `execution` with `mocked` and `executors`,
        `components` with versioned details); `JobExecutorTable.executor_modes()` becomes
        `mocked_by_offering_mode()`. New
        `provisioning/compute/service/src/compute_provisioning_service/services/system_status.py`
        (health, status, version; `resolve_identity_context` stays in the service's
        `identity.py`) and `controllers/system_controller.py` binding health, status, version,
        check-leases, and the convergence and lease-watchdog controls. The Ansible
        distribution's `probes.py` becomes a readiness component
        (`compute_provisioning_ansible/readiness.py`) reporting `ansible_version`, every Ansible
        executor's playbook found in the table, and SSH key references, composed by the root;
        `AnsibleReadinessResponse` and `InventoryInfo` go; the bundles' `readiness_checks`
        become this contribution. The readiness route and its contract are removed; the client
        drops `get_ansible_readiness`, and `get_system_status` returns `SystemStatusResponse`.
        Tombstone VM's `services/system_service.py` and `controllers/system_controller.py`.
  - [ ] 5B.8.C.2 Resource projections. The bundles carry a resource-projection contribution
        (VM's `project_ansible_pool_defaults`, bare metal's `project_bare_metal_resource`);
        `services/capacity_inventory.py` iterates it and imports neither runtime.
  - [ ] 5B.8.C.3 Router factories. VM's `vms_controller.py`, `hosts_controller.py` (capacity),
        and `test_controller.py`, and bare metal's `test_controller.py`, become router
        factories taking zero-argument accessors; each adapter's `routers.py` exposes them;
        `main.py` passes accessors resolving from the container. No adapter module imports
        `compute_provisioning_service.container`.
  - [ ] 5B.8.C.4 Boundary test. `provisioning/compute/service/tests/unit/test_import_boundaries.py`
        allowlists (file, module) pairs: `container.py` and `main.py` the adapters' runtimes and
        routers, `db/migrations.py` `legacy_backfill`, nothing else.
  - [ ] 5B.8.C.5 Callers. e2e mock-mode checks read `execution.mocked`
        (`scenarios/vms/test_full_deal.py`, `test_full_deal_buyer_cli.py`,
        `test_buy_oneshot_buyer_cli.py`, `test_non_erc20_settlement.py`); `tests/smoke/test_provisioning_smoke.py`
        asserts the status execution section and the Ansible component;
        `docs/development/VALIDATION_RUNBOOK.md`'s `jq` checks `.execution.mocked == false` and
        the Ansible component's `ready`. Tests: `test_system_api.py`,
        `provisioning/compute/ansible/tests/unit/test_probes.py` (becoming `test_readiness.py`),
        `test_job_executor_table.py`. Gate as above, plus the e2e unit suite.
- [ ] 5B.9 Relays to VM: `relay_rebinding.py`, `relay_port_allocator.py`, and
      `relay_execution.py` from the service's `services/` into the VM adapter; the relay,
      relay-port-lease, and Ansible pool-configuration table metadata into VM-owned
      metadata the service composes (the relay models, route declarations, and client
      methods already moved to `vm_provisioning_operator` in 5B.8.A0.7, and
      `relays_controller.py` moves with the services into the VM adapter as an
      accessor-taking router factory); VM's relay rebinding is the pool-change hook VM
      exports since 5B.8.A.1. Review
      the relay routes' seller-only roles while moving them. VM's
      `ansible_pool_config_handler.py` then imports `AnsiblePoolConfig`, `Relay`, and
      relay rebinding from VM's own modules, not the service's.
- [ ] 5B.10 Boundary check: remove `arkhai-compute-provisioning-service` from both
      adapters' dependencies, and `arkhai-vms-provisioning-adapter` and the unused
      `arkhai-vms-provisioning-operator-client` from bare metal's; add
      an import-boundary test asserting neither adapter imports
      `compute_provisioning_service` or the other adapter (including under
      `TYPE_CHECKING`), no neutral provisioning module imports
      `vm_provisioning_operator`, and `compute_provisioning.jobs` and
      `compute_provisioning.hosts` import no Ansible or SSH module. The test walks every
      `Import` and `ImportFrom` node of each module's syntax tree, relative imports
      included, so a function-local, `TYPE_CHECKING`, or `try`/`except` import fails it
      as a top-level one does (`ARCHITECTURE.md`, "Family kits"). The boundary covers
      deployment configuration as well as Python: a check asserts no domain's compose
      files, profiles, or inventory settings name another domain's tree, and the
      Ansible distribution names no domain's inventory group or playbook. The same test
      asserts the thin distributions' boundaries: `compute_provisioning_contracts` and
      `market_resource_pools_contracts` import no persistence, web-framework, or service
      module, and neither client distribution imports a kit or service beyond its
      contracts.
- [ ] 5B.11 **Gate.** All provisioning-family suites, `make check-packaging`, comment
      hygiene; the VM lane and the bare-metal publication lane pass.
- [ ] 5B.12 Job-backed fulfillment-provider helper: `compute_provisioning` gains the shared
      provider shape — prepare a domain job from the settlement resource, submit, map job
      status to fulfillment status, read the result and credential envelopes —
      implementing `kit/fulfillment`'s provider protocol over the job authority.
      `vm_provisioning_adapter/services/ansible_fulfillment_provider.py` and
      `bare_metal_provisioning_adapter/services/bare_metal_fulfillment_provider.py` keep
      only their job preparation and result mapping. Tests: the helper against fake
      preparation and mapping in `provisioning/compute/tests/unit/`; both providers'
      existing suites pass unchanged. Gate: the provisioning-family suites,
      `make check-packaging`, the VM lane, and the bare-metal publication lane.

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
      registers the lease (executor target and window; registration names no offering
      mode since 5B.8.B.2) once fulfillment is active; `site_clients.py`'s
      `SelectedSiteFulfillmentClient` gains `register_lease`, `terminate_lease`, and
      `get_lease` over `compute_provisioning_client`, routed by the reservation's recorded
      site.
- [x] 7.3 **Migrated** to 5B.8.B.3 (`design.md`, "Controls and routes (5B.8)", decision
      1): provider-neutral release lands with the mode-agnostic lease lifecycle.
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
      `domains/bare_metal/buyer/tests/test_buyer_composition.py`. The bare-metal expiry
      through the aggregate is proven in 5B.8.B.3's `test_lease_release_api.py`.
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

- [ ] 11.1 `docs/development/ARCHITECTURE.md`: the definition of a family kit, its
      placement tests, and the repository layers with family kits between domains and
      family vocabulary; the compute family's packages (`domains/compute`,
      `compute_provisioning`, the service as composition root) — promoted 2026-10-02 at
      the maintainer's request, as "Family kits" under "Package and dependency layers";
      when 5B.3 lands, name the Ansible distribution there as the compute family kit's
      optional Ansible implementation distribution. Still to do: kit layers gain the deal-control route
      services and the negotiation runtime's administrative acceptance and opening
      preview; the compute provisioning description gains the `(offering_mode, action)`
      executor table and the compute-family mock mechanism; "Release" states that every offering mode
      releases through the fulfillment aggregate and that storefront teardown goes
      through lease termination; the fulfillment-hook paragraph states that bare metal's
      settle path starts fulfillment. From 5B.8: the compute family's packages gain the
      contracts and client distributions, and kit layers the resource-pool contracts and
      client; `VersionedEnvelope` is named among `arkhai-core`'s contents and leaves the
      fulfillment kit's carrier list; "Release" says release follows the fulfillment
      aggregate's state. The route-contract section was promoted during design.
- [ ] 11.2 `docs/development/TESTING.md`: three lanes on images built once; the loop table
      gains the bare-metal publication preview; shared compute deal stages and the
      per-domain driver; the mock profile's per-adapter executors and rule routes; the
      "blocked—not mocked" bare-metal statement replaced by the pipeline deal and the
      protected lane's distinct role.
- [ ] 11.3 `docs/development/DEPLOYMENT_AND_CONFIG.md`: the compose file list names the
      per-market overlays.
- [ ] 11.4 Promote the deltas into `openspec/specs/test-compatibility/spec.md`,
      `market-composition/spec.md`, `physical-provisioning/spec.md`,
      `storefront-publication/spec.md`, `site-capacity/spec.md`, `fulfillment/spec.md`
      (and its ownership list, which names versioned envelopes),
      `compute-provisioning-contract/spec.md` (and its purpose statement, which names
      action submission), and `resource-pool-management/spec.md`.
- [ ] 11.5 `docs/development/RELEASING.md` and `docs/development/BUILD_AND_PACKAGING.md`
      name the four new distributions wherever their siblings are listed.

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
      Record the deferred stronger protection scheme for host connection secrets
      (design: "Deferred, not in this change") as an open gap with no owning change.
      Record the deferred classification of real-run failures (design: "Maintainer
      rulings on the 5B.6 implementation review", 4): structured terminal-failure
      evidence from the runner, so the transport, codec, and operator patterns classify
      real failures rather than only mocked ones. Record the repository-wide "an
      administrator can do everything" stance as an open gap beyond the provisioning
      service, and route the findings under "Controls and routes (5B.8)" (`kit/site`'s own
      router, VM's literal pool-override path, the site's duplicated server and client
      contracts, bare metal's untyped mock-rule routes, the unreachable `provisioning`
      state, path templates in the family contracts).
- [ ] 2.7 **Campaign index currency.** Update this change's row and the Goal 3, 4, and 7
      graphs in `openspec/changes/README.md`, and the rows of
      `bare-metal-and-credits-domain-stacks`, `kit-owned-storefront-shell`,
      `apicredits-end-to-end-lane`, and `unbacked-bare-metal-listings`, whose
      dependency on this change is satisfied.
- [ ] 2.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-mock-provisioned-deal` and resolve
      every match, including references to the tombstoned compose overlay, escrow
      helper, release, compute-adapter, lease-controller, and client modules.
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
| A family kit is the family-level owner of mechanism, authority, and persistence | `docs/development/ARCHITECTURE.md` — "Repository layers" and "Family kits" (promoted 2026-10-02) |
| The job authority persists result and credential envelopes and an opaque execution handle, owns retry timing while executors classify retryability and redact, and never lets a late outcome undo cancellation | `openspec/specs/physical-provisioning/spec.md` — "Compute provisioning owns the job and host authorities", "A cancelled job stays cancelled"; `docs/development/ARCHITECTURE.md` |
| The host authority is connection-neutral: a connection envelope with public fields and opaque protected values it never decrypts or discloses, an immutable `ExecutionHost`, per-kind codecs in implementation distributions that decrypt just in time (only `ssh` implemented) | `openspec/specs/physical-provisioning/spec.md` — "Host connections are typed by their implementation's codec", "Connection secrets stay protected"; `docs/development/ARCHITECTURE.md` "Family kits" compute example |
| Provisioning route contracts are contributed as plain data and assembled by the composition root | `openspec/specs/physical-provisioning/spec.md` — "Compute-owned caller contract"; `docs/development/ARCHITECTURE.md` |
| Compute provisioning owns jobs and hosts; executors are complete; adapters contribute preparation and meaning and import neither each other nor the deployed service | `openspec/specs/physical-provisioning/spec.md` — "Adapter-owned compute execution", "Compute-owned caller contract", "Compute provisioning owns the job and host authorities", "Provisioning adapters import neither each other nor the deployed service"; `docs/development/ARCHITECTURE.md` |
| A capability's HTTP surface is five pieces (wire models, route contract, typed client, route service, HTTP binding), the binding owned by whatever composes the process | `docs/development/ARCHITECTURE.md` — "Route contracts and their HTTP binding" (promoted 2026-10-04, during design, at the maintainer's request) |
| Leases have one family surface that records and releases and never delivers; leases are keyed by reservation id; the lease routes' roles | `openspec/specs/physical-provisioning/spec.md` — "Leases have one family surface that records and releases" |
| A lease's executor identity and evidence are fixed at registration; its end moves only through site truncation | `openspec/specs/physical-provisioning/spec.md` — "A lease's executor identity and evidence are fixed at registration"; `openspec/specs/site-capacity/spec.md` — "A reservation's lease tail is written once", "Lease truncation neither resurrects nor extends a lease" |
| The lease lifecycle is mode-agnostic: one provider-neutral release executor and status port | `openspec/specs/physical-provisioning/spec.md` — "Executor-dispatched lifecycle", "Site-backed release lifecycle", "Lease release delegates to durable fulfillment teardown"; `docs/development/ARCHITECTURE.md` "Release" |
| Every provisioning route admits the administrator (a repository-wide stance applied to this service) | `openspec/specs/physical-provisioning/spec.md` — "Every provisioning route admits the administrator"; `docs/development/ROADMAP.md` (the repository-wide gap) |
| The composition root builds the one job authority and the one host authority | `openspec/specs/physical-provisioning/spec.md` — "Compute provisioning owns the job and host authorities"; `docs/development/ARCHITECTURE.md` "Family kits" |
| Execution readiness is part of system status; connectivity is probed by connection kind | `openspec/specs/physical-provisioning/spec.md` — "Execution readiness is reported in system status", "Host connectivity is probed by connection kind" |
| The family's wire contract and client are thin distributions; VM keeps an extension client | `openspec/specs/physical-provisioning/spec.md` — "Compute-owned caller contract"; `docs/development/ARCHITECTURE.md` "Family kits" compute example |
| `VersionedEnvelope` lives in `arkhai-core` | `openspec/specs/fulfillment/spec.md` — "Versioned envelopes"; `docs/development/ARCHITECTURE.md` (the fulfillment kit's carrier modules) |
| Delivery happens only through fulfillment; the executor-action submission is removed | `openspec/specs/physical-provisioning/spec.md` — "Delivery happens only through fulfillment", "Validated executor registration"; `openspec/specs/compute-provisioning-contract/spec.md` (the removed requirement and the purpose statement) |
| An undelivered lease is released by what its fulfillment proves; an uncommitted hold is released, not truncated | `openspec/specs/physical-provisioning/spec.md` — "An undelivered lease is released by what its fulfillment proves"; `openspec/specs/site-capacity/spec.md` — "Lease truncation neither resurrects nor extends a lease" |
| Host import belongs to the implementation that reads its format | `openspec/specs/physical-provisioning/spec.md` — "Host import belongs to the execution implementation that reads its format" |
| Resource pools and capacity definitions keep thin surfaces of their own | `openspec/specs/resource-pool-management/spec.md` — "The pool wire contract and client are thin distributions"; `openspec/specs/site-capacity/spec.md` — "Capacity-definition import has a thin typed client"; `docs/development/ARCHITECTURE.md` kit layers |
| Findings recorded under "Controls and routes (5B.8)" | `docs/development/ROADMAP.md` or the change index, at closeout |
| Scope migrations, the real-host scenario's disposition, and why the scenario uses typed clients | This change's `design.md` |
