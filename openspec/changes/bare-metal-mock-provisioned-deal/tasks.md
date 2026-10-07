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
- [x] 5B.8 Controls and routes. Decided with the maintainer on 2026-10-04: `design.md`,
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
      Changes no wire beyond removing the action surface. Amended at the A0 checkpoint review
      (2026-10-04): it also admits `admin` on the site capacity routes the provisioning service
      serves, which were seller-only there, and relays admit seller and admin, under the
      maintainer's administrator ruling (`design.md`, "Slice A0 implementation findings").

  - [x] 5B.8.A0.1 Delete the generic action surface (decision 10). Remove
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
  - [x] 5B.8.A0.2 `VersionedEnvelope` to core (decision 8). Move
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
  - [x] 5B.8.A0.3 Compute contracts distribution (decision 8). New
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
        lock, which `make check-packaging` confirms. Amended at the A0 checkpoint review: neither
        file lists the siblings, so the new contracts distribution, like the compute client and
        the two resource-pool packages, is deliberately unpublished until closeout task 2.0
        fixes the published dependency graph as a whole.
  - [x] 5B.8.A0.4 Compute client distribution (decision 8). New
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
  - [x] 5B.8.A0.5 Resource-pool contracts and client (decision 11). New
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
  - [x] 5B.8.A0.6 Capacity-definition import in `kit/site-client` (decision 11): its own
        request and response models in `market_site_client/models.py`, its route-table entry in
        `client.py`, an import method on the site client, and
        `kit/site/tests/unit/test_auth_route_parity.py` extended to compare the server's
        contract for the route with the client's. The server's contract is a separate
        `CAPACITY_DEFINITION_ROUTE_CONTRACTS` in `market_site.auth`, which the provisioning
        service assembles and a standalone site never mounts.
  - [x] 5B.8.A0.7 VM and Ansible extension clients (decisions 8 and 4). `vm_provisioning_operator`
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
        protocol from the compute client until B deletes it. Amended at the A0 checkpoint
        review: as landed, `vm_provisioning_operator` and the Ansible host-import client depend
        on the compute contracts only and accept any transport offering `authenticated_request`
        (the `kit/pool-overrides` shape), not the client distribution; `BareMetalLeaseClient`
        already declared its own transport protocol and imports nothing.
  - [x] 5B.8.A0.8 Callers. Storefronts: `domains/vms/storefront` (`services/capacity_client.py`,
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
  - [x] 5B.8.A0.9 Gate. The slice's suites plus `kit/fulfillment`, `kit/resource-pools` and its
        two new packages, `kit/site`, `kit/site-client`, `core`, `domains/vms/listings`, both
        storefronts, and the e2e unit suite pass; `make check-packaging` passes. A boundary
        check in each new package's unit suite asserts its declared dependencies:
        `compute_provisioning_contracts` imports no SQLAlchemy, FastAPI, or other
        `compute_provisioning*` module; `market_resource_pools_client` imports no
        `compute_provisioning*` or SQLAlchemy module.

      Slice A0 done 2026-10-04. Order run: A0.1, A0.2, A0.5, A0.6, A0.3, A0.4, A0.7, A0.8,
      A0.9 (the family table's assembly needs the pool, capacity-definition, host-import, and
      relay declarations in their owners' packages first). Corrections to the plan are in
      `design.md`, "Slice A0 implementation findings".
      - A0.1: the four routes, their contracts and client methods, both `compute_adapter.py`,
        and `compute_contract_service.py` (whole: it had no lease half) are deleted;
        `ExecutorAdapterContribution` is `offering_mode`, `release_executor`, `job_executors`,
        and `compose_adapter_bundles` requires the engine's executor table.
        `UnsupportedExecutorActionError` stays, as the table's lookup error. The lease
        controller keeps a private 409 error for a reservation recording no mode until B.
        `test_fulfillment_api.py` reads dispatched job records from the composed engine.
      - A0.2: `market_core.envelopes`; 29 importers repointed, no re-export; `kit/fulfillment`'s
        boundary allowlist and this change's fulfillment "Dependency boundary" delta name
        `market_core` and the pool contracts.
      - A0.3: `provisioning/compute/contracts` (`contracts.py`, `hosts.py` with the neutral
        `ConnectivityResult`, `jobs.py`, `system.py`, `routes.py`). The family table holds the
        family's routes only. `compute_provisioning_service/route_table.py` assembles the
        service's table (family, site capacity and capacity definitions with roles named,
        pools, Ansible host import, adapters) and canonicalizes a site route by the site's rule.
        `test_job_contract_values.py` stays; the other two moved test files were split by owner.
      - A0.4: `provisioning/compute/client` (`ComputeProvisioningClient`,
        `SyncComputeProvisioningClient` over one call spec per operation and one signing base;
        `authenticated_request` with `route`, query, multipart, accepted statuses; system
        routes return dicts until C). `compute_provisioning/client.py` deleted, httpx dropped.
      - A0.5: `kit/resource-pools-contracts` (hints, pool models, route declarations) and
        `kit/resource-pools-client`; `kit/resource-pools` no longer exports models or hints;
        about 37 importers repointed.
      - A0.6: `CAPACITY_DEFINITION_ROUTE_CONTRACTS` in `market_site.auth`; the site client's
        import method, model copies, contract, and `caller_role`; parity test extended.
      - A0.7: `vm_provisioning_operator` holds `VmOperatorClient`, `SyncVmOperatorClient`,
        relay models, and relay declarations; the generic clients are deleted.
        `compute_provisioning_ansible.host_import` holds the import declaration and its clients.
        The service's relay controller imports VM's relay models under one named
        import-boundary exception until 5B.9.
      - A0.8: the service's integration suite drives every route through the canonical clients
        (family, VM, pools, host import, site, site admin); both storefronts depend on the client
        and not on `arkhai-compute-provisioning`; e2e uses the family sync client with VM, pool,
        and site fixtures, and the harness test client for VM's test routes.
      - A0.9 versions: arkhai-core 0.4.0; kit-fulfillment 0.4.0; kit-resource-pools 0.6.0;
        kit-site 0.7.0; kit-site-client 0.7.0; compute-provisioning 0.9.0;
        compute-provisioning-ansible 0.2.0; compute-provisioning-service 0.6.0;
        vms-provisioning-adapter 0.6.0; bare-metal-provisioning-adapter 0.4.0;
        vms-provisioning-operator-client 0.7.0; vms-listings 0.4.1; apicredits-service 0.4.1;
        e2e-tests 0.1.1; new at 0.1.0: compute-provisioning-contracts,
        compute-provisioning-client, kit-resource-pools-contracts, kit-resource-pools-client.
        Exact pins moved, with patch bumps: kit-settlement-runtime 0.2.1,
        kit-hosted-settlement 0.1.6, kit-contact-exchange 0.2.1, kit-config 0.1.4,
        core-registry-client 0.12.1, core-registry 0.3.1, core-buyer 0.3.4, vms-buyer 0.5.1,
        vms-storefront 0.9.1, bare-metal-buyer 0.4.1, bare-metal-storefront 0.7.1. Every project
        the implementation environment could lock was relocked with `scripts/uv_project.py
        lock`. Amended at the A0 checkpoint review: `domains/vms/storefront` and
        `domains/vms/buyer` could not be (the PyTorch index refused access), so their locks were
        hand-edited to the rebuilt wheels and are unverified by a real relock; `kit/policy`
        could not be relocked either, and nothing in its lock changed. Closeout task 2.2
        relocks all three where the index is reachable. The
        bare-metal adapter's unused dependency on VM's client is removed; its dependency on VM's
        adapter stays, because the service module it imports loads VM's adapter.
      - A0.9 validation: core 182 (2 skipped) + 44 and buyer, registry, registry-client;
        kit-fulfillment 172; pool contracts 143, pool authority 138, pool client 4; kit-site 261;
        kit-site-client 48; compute contracts 40, client 29, family kit 103, Ansible 79;
        service 676 unit and 286 integration; VM adapter 39; bare-metal adapter 22; bare-metal
        domain 136; bare-metal storefront 227; API-credit service 65; settlement-runtime 116;
        contact-exchange 123; config 140; bare-metal buyer 13; VM storefront 1101 unit and 345
        integration (the two known `test_alkahest` failures); e2e unit 236 (the known task-10.1
        failure), and the e2e and smoke suites collect (178). `make check-locks`, comment
        hygiene, documentation citations, OpenSpec strict, and `make check-packaging` pass.
      - A0.9 correction (checkpoint verification): the gate ran each touched project's suite,
        not the root `make test` aggregate, and missed
        `domains/apicredits/tests/test_distribution_install.py`. Its wheel fixture builds a
        listed set, which lacked `kit/resource-pools-contracts` (the API-credit service, the
        pool kit, and the site kit now depend on it); the fixture now builds it. The root
        aggregate then passes except where this environment cannot run a suite: `kit/policy`,
        the VM storefront, and the VM buyer cannot reinit (PyTorch index; their frozen-sync
        runs pass: 47, 1101 and 345, 206), and the Rust middleware needs Cargo. Later gates run
        the root aggregate.
      - A0 end-to-end evidence (checkpoint verification): the pipeline passed on the A0
        checkpoint, VM lane 135 passed and bare-metal lane 16 passed, with no traceback, 5xx,
        401, or 403 in either lane's service logs.

      **Slice A: the authorities at the root, and the job and host routes.**

  - [x] 5B.8.A.1 Authorities at the root (decision 5). `container.py` builds one
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
  - [x] 5B.8.A.2 Route services (decision 4). `compute_provisioning/route_errors.py` defines
        `ProvisioningRouteError(status_code, detail)`; `jobs/executor_mock.py`'s
        `MockRouteError` is folded into it, and both adapters' test controllers map it.
        New `compute_provisioning/jobs/route_service.py` (`JobRouteService`: list, get, logs,
        credentials, cancel; `JobTestRouteService`: summary, drain, wait) and
        `compute_provisioning/hosts/route_service.py` (`HostRouteService`: CRUD, enable,
        disable, connectivity through probes keyed by connection kind, refusing an unknown
        kind with 422). New `compute_provisioning_ansible/host_import.py`'s
        `AnsibleHostImportRouteService` over the host authority and `parse_inventory_ini`.
  - [x] 5B.8.A.3 Bindings. New service controllers `controllers/jobs_controller.py`,
        `hosts_controller.py`, `test_jobs_controller.py` (mounted under the mock profile), and
        `host_import_controller.py`, mounted from `main.py` and resolving collaborators from the
        container. VM's `controllers/jobs_controller.py` is tombstoned; VM's
        `controllers/hosts_controller.py` keeps only `GET /api/v1/hosts/{host}/capacity`; VM's
        `controllers/test_controller.py` loses the shared `/test/jobs` routes; VM's
        `services/host_operations_service.py` keeps the capacity check and loses connectivity.
        The root builds the probe runner (`AnsibleRunner`, or `MockAnsibleRunner` under the mock
        profile) and registers `ssh` → `probe_connectivity` over it. Both adapters'
        `pyproject.toml` declare FastAPI and `fastapi-utils`, which they import.
  - [x] 5B.8.A.4 Drift guard and tests. New
        `provisioning/compute/service/tests/unit/test_route_binding.py`: every route the app
        mounts resolves to exactly one contract in the assembled table, and every contract to a
        mounted route. Route services get unit tests in `provisioning/compute/tests/unit/`
        (`test_job_route_service.py`, `test_host_route_service.py`) and
        `provisioning/compute/ansible/tests/unit/test_host_import.py`; `test_hosts_api.py`,
        `test_system_api.py`, and `test_test_controller.py` cover the bound routes through the
        typed clients. Gate as above.

  - [x] 5B.8.A.5 Added at the A0 checkpoint review (2026-10-04, maintainer decision): the
        action surface's deletion left its job-record vocabulary in the thin contracts
        package. `ExecutorActionEnvelope` becomes `compute_provisioning.jobs.JobActionRequest`
        (`jobs/action_request.py`), the job authority's own correlation and idempotency record,
        which no route accepts; `ProvisioningErrorEnvelope` moves beside `JobFailure` in
        `jobs/executor.py`. `JobState`, `JobAccepted`, `ProvisioningJob`, and `LogsReference`,
        which only the deleted contract-job routes used, are deleted, as is
        `VmOperationsService.create_vm`'s `contract` argument, which only the deleted VM compute
        adapter supplied. The persisted `contract_version` keeps marking a job fulfillment
        submitted. compute-provisioning-contracts 0.2.0. Validation: the family suites and the
        service (885 unit, 287 integration) pass.
      Slice A done 2026-10-04.
      - A.1: the container builds one `HostAuthority` (`_make_host_authority`: the `ssh`
        codec with the decryption key, capacity derivation, `HOST_POOL_CHANGE_HOOKS` merged)
        and one `JobEngine` (`_make_job_engine`); `retry_policy_from` is
        `compute_provisioning_service/services/job_retry.py`. VM's `job_service.py` is replaced
        by `services/job_submitter.py` (`VmJobSubmitter`); the fulfillment provider submits
        through it and reads jobs from the engine; both runtimes receive the authorities. The
        container's `resolved_job_engine`, `resolved_host_authority`, and
        `resolved_connectivity_probes` replace the job and host services.
      - A.2: `compute_provisioning/route_errors.py` (`ProvisioningRouteError`, into which
        `MockRouteError` folds), `jobs/route_service.py` (`JobRouteService`,
        `JobTestRouteService`), `hosts/route_service.py` (`HostRouteService`, probes keyed by
        connection kind, 422 for a kind with none), and `AnsibleHostImportRouteService` in
        `compute_provisioning_ansible/host_import.py`. A duplicate host registration now answers
        409 naming the host; VM's controller formatted a field `HostCreate` lacks.
      - A.3: the service's `controllers/jobs_controller.py`, `hosts_controller.py`,
        `host_import_controller.py`, `test_jobs_controller.py` (mock profile), and
        `route_errors.py`; the container builds the probe runner (`AnsibleRunner`, or under the
        mock profile `MockAnsibleRunner`) and registers `ssh`. VM keeps only its capacity host
        route and its operations service only the capacity check; its test controller no
        longer serves `/test/jobs`. Both adapters declare FastAPI, fastapi-utils, and
        typing-inspect (imported by fastapi-utils, undeclared by it).
      - A.4: `tests/unit/test_route_binding.py` reads mounted routes from the app's OpenAPI
        document (FastAPI 0.139 keeps included routers lazily, so `app.routes` does not list
        them); `test_authority_composition.py`; route-service unit tests in
        `provisioning/compute/tests/unit/` and the Ansible distribution's `test_host_import.py`;
        a duplicate-registration integration test. The two host-operations connectivity unit
        tests were dropped: the Ansible probe tests cover the same behaviour.
      - Versions: compute-provisioning 0.10.0, compute-provisioning-ansible 0.3.0,
        compute-provisioning-service 0.7.0, vms-provisioning-adapter 0.7.0,
        bare-metal-provisioning-adapter 0.5.0; floors raised to match.
      - Validation (with A.5): compute contracts 40, client 29, family kit 125, Ansible 83, VM
        adapter 39, bare-metal adapter 22, service 885 unit and 287 integration, API-credit
        service 65. The root `make test` aggregate passes 44 suites; its only failures are
        environmental: `kit/policy`, the VM storefront, and the VM buyer cannot reinit (PyTorch
        index), and their frozen-sync runs pass (47; 1101 unit and 345 integration with the two
        known `test_alkahest` failures; 206), and the Rust middleware needs Cargo.
        `make check-locks`, `make check-packaging`, comment hygiene, documentation citations,
        and OpenSpec strict validation pass.
      - A end-to-end evidence (checkpoint verification, 2026-10-05): the root `make test`
        passed on the A checkpoint, and the pipeline passed, VM lane 135 passed and
        bare-metal lane 16 passed, with no traceback, 5xx, 401, or 403 in either lane's
        service logs (the only non-2xx statuses were the scenarios' expected 402, 404, and
        410).

  - [x] 5B.8.A.6 Added at the slice A implementation review (2026-10-05, maintainer decision;
        `design.md`, "Controls and routes (5B.8)", "Slice A implementation review").
        - Inventory pool moves:
          - `compute_provisioning/hosts/service.py`: `apply_inventory` moves an existing
            host through `_move_to_pool`; `_move_to_pool` runs the hooks only on a real move;
            new `PoolChangeRefusedError`, which a hook raises.
          - `hosts/route_service.py` and `compute_provisioning_ansible/host_import.py` answer
            a refused move with 409.
          - VM's `runtime.py` hook adapter translates `RelayRebindingRefused` into the
            family's refusal.
          - The service's integration `conftest.py` builds its host authority with the
            container's pool-change hooks.
        - Job list order: `compute_provisioning_contracts` gains `JobListSort`; both clients'
          `list_jobs` take `sort`; `JobRouteService` validates against `JobListSort`.
        - Job identity:
          - `jobs/action_request.py`: `JobActionRequest` is a plain frozen identity model
            without `parameters`.
          - `jobs/engine.py`: `JobIdentityConflictError` for a repeated `operation_id` or
            contract identity naming different parameters; `get_contract_job_record`
            deleted.
          - `jobs/db.py` drops `contract_version`; the service's migration
            `20261005_001_drop_job_contract_version` removes the column.
          - Both fulfillment providers stop passing `parameters`.
        - Tests:
          - `provisioning/compute/tests/integration/test_host_authority.py`: an import move
            runs the hooks; a refused import move leaves every named host unchanged;
            reassigning the current pool is not a move.
          - `test_job_authority.py`: a conflicting contract identity is refused; the identity
            record rejects job content.
          - `tests/unit/test_host_route_service.py` and the Ansible distribution's
            `test_host_import.py`: refusals answer 409.
          - The service's new `integration/test_host_pool_moves_api.py`, through the
            canonical clients: an import and an update that would move a tunnelled host to
            another relay answer 409 and change nothing, and a drained host moves by import.
            Reverting the `apply_inventory` fix fails exactly the import case.
          - `test_provisioning_client_endpoint_coverage.py`: the job list in both orders.
          - `unit/test_database.py`: the column is gone after migration, and a migration test
            shows job rows, their identity, and the contract-identity uniqueness survive the
            drop.
          - The client parity test covers `sort` through the signatures.
        - Versions:
          - compute-provisioning-contracts 0.3.0 and compute-provisioning-client 0.2.0
            (new public API);
          - compute-provisioning 0.11.0 and compute-provisioning-service 0.8.0
            (incompatible);
          - compute-provisioning-ansible 0.3.1, vms-provisioning-adapter 0.7.1, and
            bare-metal-provisioning-adapter 0.5.1;
          - floors raised where a consumer needs the new behaviour;
          - every affected project relocked (the VM storefront with the hand-lock tool, as
            before).
        - Validation: contracts 40, client 29, family kit 131, Ansible 84, VM adapter 39,
          bare-metal adapter 22, service 886 unit and 291 integration. The root `make test`
          aggregate passes its 44 suites; its only failures are the known environmental ones
          (`kit/policy`, the VM storefront, and the VM buyer cannot reinit from the PyTorch
          index, and the API-credit middleware needs Cargo). The VM storefront's frozen-sync
          run passes 1101 unit and 345 integration tests (the two `test_alkahest` failures
          need Node and Anvil); `kit/policy` and the VM buyer depend on no changed package.
          `make check-packaging`, comment hygiene, documentation citations, and OpenSpec
          strict validation pass.

      **Slice B: the lease surface and mode-agnostic release** (decisions 1–3, 9, and 7.3).
      Amended 2026-10-05 before implementation, after the slice B design review
      (`design.md`, "Controls and routes (5B.8)", "Slice B design review", points 1–5):
      registration keyed on the executor target, `commit`'s guards, registration with the
      committed window, release by every aggregate state, the release guard, and the plan
      corrections. A first draft of B.1's ledger and authority changes is in the previous
      session's working notes; it predates points 2 and 4.

  - [x] 5B.8.B.1 Ledger and lease windows (points 1, 2, and 4).
        - `kit/site/src/market_site/ledger.py`:
          - `attach_lease(*, capacity_reservation_id, executor_target, executor_ref=None,
            lease_start_utc=None, lease_end_utc=None, create_job_id=None)` registers by
            executor target (point 1): no `escrow_uid` lookup and no `offering_mode`; refusals
            raise `CapacityConflictError`; `None` for no live reservation. The registrable
            and refused states are module constants.
          - `commit` refuses `releasing`, `release_failed`, and `unmanaged` with
            `CapacityConflictError`, and returns a registered lease unchanged; before
            registration it re-records the window as today.
          - `truncate_lease` accepts only `leased` and an earlier or equal end, never sets
            the state, and returns `None` for every refusal.
          - `CapacityReleaseGuard` replaces `SettlementAbandonmentHook` (the constructor
            takes `release_guard=`). It is consulted with the ledger's session in `release`,
            `resize_reservation`'s supersede step, and TTL-hold expiry. A refused reclaim
            changes nothing: `release` and `resize_reservation` return `None`, and a lapsed
            hold waits for the next sweep. An already-released reservation is still offered
            to the guard and returned.
          - `update_lease_fields` and `update_lease_fields_in_session` become
            `record_create_handle_in_session(db, capacity_reservation_id, create_job_id)`,
            which never replaces a recorded handle.
        - `kit/site/src/market_site/authority.py`:
          - `SiteAuthorityPort` and `LedgerSiteAuthority` take the new `attach_lease_reservation`
            signature, lose `update_reservation_fields` and `get_reservation_by_escrow`, and
            gain `release` for the lifecycle's guarded release.
          - The ledger keeps `get_reservation_by_escrow` for the API-credit service.
        - `kit/site/src/market_site/router.py`: the release route documents a refused release
          as `reservation: null`; `commit`'s new refusals use the existing 409 mapping.
        - `kit/fulfillment/src/market_fulfillment/fulfillment_persistence.py`:
          `attach_executor_job` calls `record_create_handle_in_session`.
        - `provisioning/compute/service/src/compute_provisioning_service/container.py` passes
          `release_guard=`. Until B.3 composes the proof guard, the guard abandons an
          `assigned` aggregate and permits, which is today's behaviour.
        - VM storefront, registering with the committed window (point 2):
          - `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_service.py`
            registers with the window its post-provision commit returned, and skips
            registration when that commit failed.
          - `services/fulfillment_resume_runtime.py`: `_refresh_capacity_lease` returns the
            committed record, and `_register_recovered_vm_lease` registers with its window, or
            not at all.
          - `services/fulfillment_service.py`: `_register_vm_lease_with_settings` accepts the
            returned window in either stored form (ISO or minute precision).
        - Tests:
          - `kit/site/tests/integration/test_ledger.py`:
            - registration: first registration on `reserved` and on committed `leased`,
              equal repeat, never-moves-end after truncation, different target or start, the
              refused states, a create handle never replaced;
            - `commit`: refuses the lifecycle's states, returns a registered lease unchanged,
              moves an unregistered window;
            - truncation: refusals;
            - the guard: permits, refuses with nothing changed and nothing abandoned, a
              refused resize, a refused TTL lapse, an already-released reservation;
            - the existing abandonment-hook tests become guard tests;
              `test_update_lease_fields_*` become create-handle tests; the three tests calling
              the old `attach_lease` signature follow.
          - `kit/site/tests/unit/test_authority.py`.
          - `kit/fulfillment/tests/unit/test_fulfillment_persistence.py`.
          - The VM storefront's `tests/unit/test_fulfillment_resume_runtime.py`,
            `test_fulfillment_service.py`, `test_fulfillment_provisioning.py`, and
            `test_fulfill_vm_obligation_error_handling.py`: registration uses the committed
            window, and a failed commit skips registration.
  - [x] 5B.8.B.2 Lease contract and route service.
        - Contracts (`compute_provisioning_contracts`): `LeaseRegistration` drops
          `offering_mode`, and `LeaseView` declares it, reporting the reservation's mode.
          New `LeaseListResponse` and the release-oversight request.
        - Route table (`compute_provisioning_contracts/routes.py`):
          - list and release-oversight are added with decision 1's roles (register, get,
            terminate: seller and admin; list, oversight, retry, force: admin);
          - an unlisted operation defaults to seller and admin, and
            `DUAL_ROLE_PROVISIONING_OPERATIONS` is removed;
          - `route_contract_from_declaration` refuses a declaration without `admin`, enabled
            only after every existing declaration (VM's, bare metal's, the pool, host-import,
            and relay declarations) is verified to admit it (point 5).
        - New `compute_provisioning/leases.py`: `LeaseRouteService` (register, get, list
          filtered by status and offering mode, terminate, release-oversight, retry-release,
          force-release), mapping a registration refusal to 409 and a missing reservation to
          404.
        - `executor_leases.py`: `ExecutorLeaseService` loses mode scoping, the by-escrow
          lookup, and `update_lease`; `ExecutorLeaseRegistration` drops `escrow_uid` and
          `offering_mode`; `ExecutorLeaseUpdate` is deleted.
        - `lease_lifecycle.py`: `LeaseLifecycleService` loses `update_lease`,
          `get_lease_by_escrow`, `list_leases`, and `register_lease`.
        - The service's `controllers/leases_controller.py` binds the route service at
          `/api/v1/contract/leases`. `compute_contract_controller.py` and
          `services/compute_contract_service.py` are tombstoned.
        - The client gains `list_leases` and `release_lease_oversight`. The VM storefront's
          `fulfillment_service.py` stops sending `offering_mode`.
        - Tests:
          - `provisioning/compute/tests/unit/test_executor_leases.py`,
            `test_lease_lifecycle.py`, and new `test_lease_route_service.py`;
          - the contracts package's `tests/unit/test_route_table.py` (roles, the refused
            declaration);
          - the client's parity test;
          - the service's `tests/unit/test_route_binding.py` and
            `tests/integration/test_compute_contract_api.py`.
  - [x] 5B.8.B.3 Release (decision 9 and points 3 and 4, absorbing 7.3).
        - `compute_provisioning/release.py`:
          - It receives `FulfillmentTeardownPort` and `FulfillmentServiceTeardownPort` from
            `vm_provisioning_adapter/release.py`, and loses `ExecutorReleaseDispatcher` and
            `ReleaseJobDispatcher`.
          - New `FulfillmentReleaseGuard`, the site's `CapacityReleaseGuard` over the
            settlement repository and a session-accepting
            `job_bound_to_reservation(db, capacity_reservation_id)` beside the job rows in
            `compute_provisioning/jobs/db.py`. It abandons an `assigned` aggregate before
            checking the proof; it permits `torn_down`, and an absent, `assigned`, or
            `abandoned` aggregate when the proof holds; it refuses everything else.
          - `FulfillmentReleaseExecutor.submit_release` returns a typed outcome (teardown
            begun or adopted, released, create in flight, or unreleasable with its reason),
            following point 3's table. It frees capacity directly only through the site
            authority's guarded `release`, and reads the aggregate once more if the guard
            refuses.
          - `FulfillmentReleaseJobPort.get_job` reports:
            - `torn_down` as succeeded;
            - `teardown_failed` and `failed` as failed;
            - `active` as ready for teardown;
            - `dispatch_pending` and `dispatching` as create in flight;
            - every other teardown state as running.
        - `lease_lifecycle.py`:
          - The watchdog and terminate move a teardown or create-in-flight outcome to
            `releasing`, with the fulfillment id as release handle.
          - A released outcome reserves the outbox entry and delivers the capacity-released
            notification.
          - An unreleasable outcome records `release_failed`.
          - The releasing pass begins teardown once the aggregate is `active`, records
            `release_failed` at `failed` or `teardown_failed` (point 3(a)), and skips the grace
            timeout while the create is in flight.
          - The `direct-release` sentinel and its branch go.
          - Failure reasons become neutral: `teardown_failed`, `teardown_timeout`,
            `fulfillment_failed` (a `failed` aggregate), and `release_unproven` (no aggregate
            past `assigned` but the proof does not hold).
        - `composition.py` drops `release_executor` from the contribution and
          `release_dispatcher` from the composed result. `container.py` builds the guard (in
          place of B.1's interim one), the executor, and the port, and passes the guard to
          the ledger.
        - Bare metal:
          - `runtime.py` stops building a release delegate;
          - `services/bare_metal_operations_service.py` loses its reservation-shaped
            release-delegate method;
          - `reclaim_access` takes explicit parameters (point 5), which the provider's
            `dispatch_teardown` supplies.
        - Tombstone `vm_provisioning_adapter/release.py` and
          `bare_metal_provisioning_adapter/release.py` (with `get_physical_host_id`).
        - Tests, as implemented (this list was corrected by 5B.8.B.8; the plan had
          named a unit `test_release.py` and the deleted `test_release_executors.py`):
          - `provisioning/compute/tests/integration/test_release.py`, against real SQLite
            with a fake teardown port: every aggregate state in point 3's table, the
            proof's parts, and the guard writing nothing when it refuses; the race of a
            dispatch against the guard's compare-and-set was added by 5B.8.B.8;
          - `provisioning/compute/tests/unit/test_lease_lifecycle.py`, over fake ports: a
            refused direct release re-read once; a pending release survives a restarted
            lifecycle; teardown begins at `active`; no grace timeout in flight;
            `teardown_failed` while releasing ends `release_failed`, and retry-release then
            adopts `torn_down`;
          - the service's `tests/unit/services/test_ledger_lease_lifecycle.py` (the
            production guard, executor, and status port over real tables),
            `test_authority_composition.py` (the guard reaches the ledger), and
            `integration/test_legacy_backfill_teardown.py`;
          - `integration/test_capacity_api.py`: release of a committed reservation under the
            guard, both permitted and refused;
          - a new `integration/test_lease_release_api.py` covering:
            - a bare-metal expiry through the aggregate;
            - a never-dispatched lease released directly;
            - a lease terminated while its create is in flight;
            - a site release refused for an `active` aggregate;
            - a `failed` aggregate ending `release_failed`.
  - [x] 5B.8.B.4 Deletions (decision 1; point 5).
        - VM:
          - `controllers/leases_controller.py` (tombstoned);
          - the lease route declarations in `vm_provisioning_operator/routes.py`;
          - the `Lease*` models in `vm_provisioning_operator/models.py`;
          - the extension client's lease methods.
        - Bare metal:
          - `controllers/bare_metal_leases_controller.py` and
            `services/bare_metal_lease_service.py` (tombstoned, taking
            `bare_metal_access_ref` with it);
          - `BARE_METAL_LEASE_ROUTES` and `BareMetalLeaseClient` in
            `arkhai_bare_metal/provisioning_client.py`, and `BareMetalLeaseView` in
            `arkhai_bare_metal`;
          - `BareMetalLeaseCreate` is renamed `BareMetalAccessGrant` in `arkhai_bare_metal`,
            the provider, and the operations service;
          - `bare_metal_executor_ref` and `PHYSICAL_HOST_ID_REF_KEY` stay: they build the
            job's `executor_ref`.
        - Both `routers.py` follow.
        - Tests:
          - `test_leases_api.py` becomes the family lease API test (list filters, roles,
            write-once registration, no update route);
          - `integration/test_bare_metal_leases_api.py` and
            `unit/services/test_bare_metal_lease_service.py` are tombstoned;
          - `test_bare_metal_mock_profile.py` drives grants through `begin_fulfillment`;
          - `domains/bare_metal/tests/test_provisioning_client.py` keeps only the test-route
            declarations;
          - `test_schema.py` follows the rename;
          - the service's `tests/unit/test_lease_models.py` loses the deleted models;
          - `tests/integration/conftest.py` loses `BareMetalLeaseClient`.
  - [x] 5B.8.B.5 Storefronts (decision 9 and point 4).
        - VM:
          - `domains/vms/storefront/src/market_storefront/settlement_composition.py`'s
            terminal-settlement path asks the capacity runtime to `release` the reservation,
            and truncates only if the release returns `None`; its stage events say which
            happened.
          - `hosted_routes.py` follows.
          - `admin_controller.py`'s interruption keeps its 409 on refusal.
        - Bare metal: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/hosted_lifecycle.py`'s
          `_teardown` treats a `None` release as not released in its no-fulfillment branch,
          and raises so the lifecycle retries.
        - Unchanged code, changed behaviour (point 4): the VM admin bulk release and the VM
          failure-policy release no longer free a delivered lease.
        - Tests:
          - VM `tests/integration/test_abandon_truncation.py`: a `reserved` hold is released;
            a delivered lease is truncated;
          - the bare-metal storefront's `tests/test_hosted_lifecycle.py`: a refused release
            leaves the lifecycle unreleased.
  - [x] 5B.8.B.6 e2e.
        - `scenarios/vms/conftest.py`'s `DealLease` reads leases through
          `SyncComputeProvisioningClient`, and backdates through
          `SiteCapacityClient.truncate_lease` signed as admin.
        - `test_full_deal.py`, `test_full_deal_buyer_cli.py`, and
          `test_buy_oneshot_buyer_cli.py` follow.
        - Gate as above, plus `kit/site`, `kit/fulfillment`, both storefronts, and the
          API-credit service (which composes the site ledger without a guard).

  - [x] 5B.8.B.7 Added after the slice B checkpoint's end-to-end run (2026-10-05,
        maintainer decision; `design.md`, "Slice B implementation findings", last row).
        - `commit` returns the reservation as the site recorded it at every client layer:
          - `kit/site-client`'s `SiteCapacityClient.commit`;
          - core's `CapacityClient` protocol (`core_storefront/capacity.py`) and its
            `AggregateCapacityClient` (`aggregation.py`), tagged with the owning site;
          - `kit/capacity-publication`'s `CapacityRuntime.commit`, tagged with the bound
            site.
        - Tests:
          - the site client's and the aggregate client's unit tests, and the capacity
            runtime's;
          - the service's `test_capacity_api.py`: the commit answer, and a registered lease's
            unchanged window;
          - the VM storefront's new `tests/integration/test_committed_window.py`, through the
            real runtime and aggregate client against the fake site, which now keeps a
            registered lease's window (`registered`).
        - Versions: arkhai-core-storefront 0.8.0, kit-site-client 0.8.0,
          kit-capacity-publication 0.5.0 (exact pins moved), apicredits-storefront 0.6.1 (its
          pin moved); floors raised in kit-capacity-publication and the VM storefront.
  - [x] 5B.8.B.8 Fixes from the slice B implementation review (2026-10-05; findings 1–6,
        each agreed with the maintainer; `design.md`, "Slice B implementation review").
        - Release recorded before teardown (finding 1):
          - `FulfillmentReleaseExecutor.submit_release` decides and writes nothing;
          - the lease lifecycle records `releasing` with the fulfillment as its handle,
            then begins teardown; a failure to begin it is left to the releasing pass,
            which begins it while the aggregate reads `active`.
        - Bare metal registers its lease (finding 2): `hosted_lifecycle.py` registers at
          access readiness, the machine the grant reports as target, through
          `SelectedSiteFulfillmentClient.register_lease`; the Alkahest path stays 7.2's.
        - Registration contract (finding 3): `LeaseRegistration` forbids unknown fields and
          names no create handle; `LeaseView` is its own model carrying the lifecycle
          evidence. The window is optional. `deal_ref` is kept: registration records the
          escrow it names once, the only source of it for a hold placed before the deal had
          an escrow (found from the first end-to-end run's escrow lookups; A.6 had recorded
          it at registration, and 5B.8.B.1 had dropped that with the escrow lookup).
        - The committed window kept (finding 4): a first registration writes a window only
          where none is recorded.
        - Grace timed from the release (finding 5): `capacity_reservations` gains
          `release_requested_at`, recorded when a reservation enters `releasing` (a retry
          begins a new attempt), with migrations in the provisioning service
          (`20261005_002`) and the API-credit service (`20261005_005`); the releasing pass
          times a stalled teardown from it, or from the lease's end for a reservation that
          began releasing before it existed.
        - Evidence (finding 6): B.3's test list corrected above, and a race test added.
        - Tests:
          - `kit/site`: a late first registration after a truncation, a window written only
            where none is recorded, the escrow recorded once, the release start;
          - family kit: the release recorded before teardown, a teardown that fails to
            begin, both directions of the grace clock, the decision writing nothing, and a
            dispatch winning the race against the guard's compare-and-set (file-backed
            SQLite, a test-only repository committing the dispatch from a second
            connection);
          - contracts: a registration naming lifecycle evidence is invalid;
          - service integration: a release durable before teardown and resumed by a
            rebuilt lifecycle; a bare-metal lease registered and read through the family
            client (target, committed window, `bare_metal`); a hold found by its escrow once
            registered; migration ids and the migrated column;
          - bare-metal storefront: access readiness registers the lease before the deal is
            recorded access-ready;
          - API-credit service: the migration and a table from before the column.
        - Versions: arkhai-apicredits-service 0.4.2, for its migration, with its
          `arkhai-kit-site` floor raised to 0.8.0; every other package this touches was
          bumped in slice B and is unreleased.
        - Validation:
          - `kit/site` 273; compute contracts 51; family kit 171;
          - provisioning service 836 unit and 283 integration;
          - bare-metal storefront 230; API-credit service 66;
          - VM storefront by frozen sync: 1102 unit and 348 integration (the two known
            `test_alkahest` failures);
          - e2e unit 236 (the known 10.1 failure), and the scenarios collect.
          - The root aggregate passes its 44 suites, failing only where this environment
            cannot run a suite. `make check-packaging`, comment hygiene, documentation
            citations, and OpenSpec strict validation pass.
          - End-to-end (run 37298149909, with A.6, B, B.7, and B.8): the bare-metal lane
            passed 16 and the VM lane 135, nothing failed or skipped. The VM lease stages
            ran through the family surface for the first time: four leases registered, the
            escrow lookups found their reservations, and each expired lease went
            `releasing` under its fulfillment and was released on a later cycle with the
            storefront notified; none timed out.
  - [x] 5B.8.B.9 Fixes from the slice B re-review (2026-10-05; both findings agreed with
        the maintainer; `design.md`, "Slice B re-review").
        - Conditional lifecycle writes (high):
          - `kit/site`'s ledger gains `record_release_failed` and `record_unmanaged`, and
            `begin_releasing` becomes conditional. Entering `releasing` is allowed from
            `reserved`, `provisioning`, `leased`, and `release_failed`, idempotent under
            the same handle, refused under another. A failure is allowed from `reserved`,
            `provisioning`, `leased`, and `releasing` under the observed handle.
            `unmanaged` is allowed only from `leased`. An unforced release refuses
            `unmanaged`.
          - The site authority's failure and oversight writes use these, and no longer the
            unconditional `update_reservation_state`.
          - The lease lifecycle checks every write's result. A refused write re-reads the
            reservation and leaves it as recorded (counted as skipped), and a refused begin
            starts no teardown. Release oversight that loses the race answers a conflict.
        - VM lease registration made durable (medium; option A, which needed a deferred
          settlement outcome):
          - `kit/settlement-runtime`'s `FulfillmentOutcome` gains `deferred`, persisted
            without binding or waking servicing.
          - The VM main path returns `deferred` when the commit records no window, when
            registration fails, and when publishing the fulfillment evidence fails. The
            last was taken as the maintainer's "defer the on-chain submission failure"
            (rather than recording it for closeout).
          - `settlement_composition.py` maps it to a deferred outcome that leaves the
            escrow open.
          - The resume pass raises, rather than proceeds, when its commit records no window
            or registration fails, so no evidence is published before the lease is
            registered.
          - Hosted VM deals already retry a non-fulfilled outcome through the settlement
            runtime.
        - Tests:
          - `kit/site`, real SQLite:
            - a stale begin after oversight refused;
            - a stale failure after force-release refused, capacity unchanged;
            - an unforced release of `unmanaged` refused;
            - handle idempotency, and failures only for their own attempt;
            - oversight refused once releasing or released.
          - Family kit: the lifecycle under each race, through a collaborator that lets
            the operator act mid-cycle, over a fake enforcing the same transitions.
          - Settlement runtime: a deferred job persisted, not bound, not woken.
          - VM storefront:
            - the main path deferring in each case, and publishing nothing before
              registration;
            - the deferred outcome leaving the escrow open;
            - the resume pass blocking on each failure, then registering and publishing
              once provisioning answers.
          - Provisioning service: a repeated `begin` for the same reservation returns the
            accepted fulfillment with one create job, which a hosted retry relies on.
        - Versions:
          - arkhai-kit-settlement-runtime 0.3.0;
          - its exact pins moved, with patch bumps: kit-config 0.1.5, kit-hosted-settlement
            0.1.7, kit-contact-exchange 0.2.2, core-buyer 0.3.5, vms-buyer 0.5.2,
            bare-metal-buyer 0.4.2;
          - the VM and bare-metal storefronts keep their unreleased slice B versions, with
            the VM storefront's settlement-runtime floor raised to 0.3.0.
        - Validation:
          - `kit/site` 280; family kit 175; settlement runtime 117;
          - provisioning service 836 unit and 284 integration; bare-metal storefront 230;
          - VM storefront by frozen sync: 1109 unit and 348 integration (the two known
            `test_alkahest` failures);
          - e2e unit 236 (the known 10.1 failure), and 155 scenarios collect.
          - The root aggregate passes its 44 suites, failing only where this environment
            cannot run a suite. `make check-packaging`, comment hygiene, documentation
            citations, and OpenSpec strict validation pass.
          - End-to-end (run 37304872316, with every slice B fix through B.9): the
            bare-metal lane passed 16 and the VM lane 135, nothing failed or skipped, and
            neither lane's service logs show a traceback, a 5xx, a 401, or a 403. Each
            expired VM lease went `releasing` under its fulfillment and was released on
            the next cycle.
      Slice B done 2026-10-05 (`design.md`, "Slice B implementation findings", for what
      implementation settled or found).
      - B.1:
        - The ledger registers a lease once by executor target; `commit` refuses the
          lifecycle's states and leaves a registered window alone; truncation moves only a
          leased end, only earlier.
        - `CapacityReleaseGuard` replaces the abandonment hook at all three reclaim sites,
          and a forced release is not guarded, so `record_release_success` is the guarded
          release and the port gained no separate `release`.
        - The field writer narrowed to `record_create_handle_in_session`.
        - The VM storefront registers with the window `commit` returned, and skips
          registration when that commit fails.
      - B.2:
        - The lease contracts drop the offering mode and gain the list and the
          release-oversight request; the route table admits seller and admin by default,
          admin only for the list and release controls, and refuses a declaration without
          admin.
        - `compute_provisioning/leases.py` (`LeaseRouteService`, 404 and 409) is bound by
          the service's `controllers/leases_controller.py`; the client gained `list_leases`
          and `release_lease_oversight`.
        - `services/compute_contract_service.py` was already gone (A0).
      - B.3:
        - `compute_provisioning/release.py`: `FulfillmentReleaseGuard` (proof, then
          compare-and-set), `FulfillmentReleaseExecutor` (a typed decision per aggregate
          state), and `FulfillmentReleaseStatusPort`; `jobs/db.py`'s
          `job_bound_to_reservation`.
        - The lease lifecycle acts on decisions, with neutral failure reasons
          (`teardown_failed`, `teardown_timeout`, `fulfillment_failed`, `release_unproven`).
        - The dispatchers, the per-bundle release contribution, and both adapters'
          `release.py` are gone.
        - `kit/fulfillment`'s `abandon_if_assigned` reports whether it abandoned.
        - Bare metal's provider records its grant job as the create handle.
      - B.4:
        - VM's and bare metal's lease surfaces are deleted;
          `BareMetalLeaseCreate` is now `BareMetalAccessGrant`, and `reclaim_access` takes the
          grant.
        - `BareMetalLeaseView` and `receipt_from_lease_view` are deleted.
      - B.5: the VM storefront releases first and truncates on refusal; bare metal's hosted
        teardown treats a refused release as not released.
      - B.6: `DealLease` reads through the family client and backdates through the site's
        truncation as admin.
      - Tests:
        - New: the family lease API test (`test_leases_api.py`, rewritten);
          `test_lease_release_api.py`; the family kit's integration `test_release.py`,
          `test_lease_route_service.py`, and rewritten lifecycle and lease-registry unit
          tests; the service's `test_ledger_lease_lifecycle.py` over the production guard.
        - The bare-metal mock-profile tests grant through fulfillment, via
          `tests/integration/bare_metal_deal.py`, and the service's integration harness
          composes the guard, both providers, and create-handle recording as production
          does.
      - Versions:
        - kit-site 0.8.0, kit-fulfillment 0.5.0;
        - compute-provisioning-contracts 0.4.0, compute-provisioning-client 0.3.0,
          compute-provisioning 0.12.0, compute-provisioning-service 0.9.0;
        - vms-provisioning-adapter 0.8.0, bare-metal-provisioning-adapter 0.6.0,
          vms-provisioning-operator-client 0.8.0, bare-metal 0.7.0;
        - vms-storefront 0.10.0, bare-metal-storefront 0.8.0 (the VM storefront's exact pin
          moved), e2e-tests 0.1.2;
        - floors raised where a consumer needs the new behaviour.
      - Validation:
        - `kit/site` 269 and `kit/fulfillment` 172;
        - compute contracts 50, client 49, family kit 167, Ansible 84;
        - VM adapter 39 and bare-metal adapter 23; bare-metal domain package 132;
        - bare-metal storefront 229;
        - provisioning service 836 unit and 280 integration (with B.7);
        - VM storefront by frozen sync: 1102 unit and 348 integration (with B.7; the two
          known `test_alkahest` failures need Node and Anvil);
        - e2e: unit 236 (the one known failure is 10.1's), and the VM scenarios collect.
        - The root `make test` aggregate passes its 44 suites, failing only where this
          environment cannot run a suite (`kit/policy`, the VM storefront, and the VM buyer
          cannot reinit from the PyTorch index; the API-credit middleware needs Cargo).
        - `make check-packaging`, comment hygiene, documentation citations, and OpenSpec
          strict validation pass.
        - End-to-end, first run (with A.6): the bare-metal lane passed 16; the VM lane
          failed 4, all from no lease being registered (5B.8.B.7, and the escrow record in
          5B.8.B.8). Second run, with B.7 and B.8: both lanes green (5B.8.B.8's validation).

      **Reconciliation with other changes (2026-10-05, maintainer request before
      slice C).**
      - Every other active change was checked against this change's surfaces: vocabulary
        scans, cited paths this change moved, and a read of each hit.
      - Each affected change was given a dated note citing this change:
        - `remove-dead-storefront-physical-surfaces`: a rebase note on 3.5, and a new
          task 3.8 removing the dead expiry hook;
        - `contain-embedded-host-key-material`: where the moved code lives, and which of
          its tasks may already hold;
        - `relay-vm-access-without-a-dashboard`: two completed tasks amended to the
          moved code, and a pending-move note for 5B.9;
        - `refactor-e2e-fulfillment-lifecycle`: `DealLease`'s new clients, and run
          37298149909 as evidence for its task 2.6;
        - `project-an-authoritative-funding-loss`: the release-first terminal path, and
          bare metal's refused release;
        - `capacity-reservation-lifecycle-hardening`: `release_failed` is not terminal;
        - `kit-owned-listing-and-fulfillment-lifecycles`: the new convergence
          obligations;
        - `pools-7-storefront-fulfillment-cutover`: decisions not to promote;
        - `add-bare-metal-hosted-settlement`: registration and release in its remaining
          qualification lanes;
        - `negotiation-driven-capacity-resize`: the guard at resize;
        - `automate-seller-spot`: truncation only earlier, and the family lease surface;
        - `bring-host-inventory-under-definition-documents`: host import is the Ansible
          distribution's.
      - The capacity-hold changes (`negotiation-time-capacity-hold`,
        `billable-capacity-reservations`, `default-no-pre-settlement-capacity-hold`,
        `negotiation-capacity-feasibility-probe`, `add-harness-scenario-contract`) and the
        changes that only touch edited files (`multi-domain-storefront-composition`,
        `settle-capacity-claim-vocabulary`) needed no note.
      - 5B.9 now ends by updating `relay-vm-access-without-a-dashboard`.

      **Slice C: the system split and the last `container` reach** (decisions 4 and 7).
      Amended 2026-10-05 before implementation, after the slice C design review
      (`design.md`, "Controls and routes (5B.8)", "Slice C design review"): the dead bundle
      fields, inventory-view contributions, typed health and the 503/409 rule, the unlisted
      status callers, the expiry hook, and the neutral readiness component.

  - [x] 5B.8.C.1 Status (decision 7; review points 1, 3, 4, and 6).
        - Contracts (`compute_provisioning_contracts/system.py`): `HealthResponse` keeps
          `status` and `checks`; new `SystemStatusResponse` (`status`, `checks` with
          `execution`, the two contract-version fields, `execution` as `ExecutionStatus`
          with `mocked` and `executors` of `ExecutorStatus` `{offering_mode, mocked}`, and
          `components` of `SystemStatusComponent` `{name, ready, detail}`, the detail a
          `market_core` versioned envelope). `routes.py` loses the readiness contract.
        - Client: `get_health` and `get_system_health` return `HealthResponse`,
          `get_system_status` returns `SystemStatusResponse` (both accepting 503's body),
          `get_ansible_readiness` goes; the worker controls keep returning dicts.
        - Family kit (`compute_provisioning/adapters.py`): `executor_modes()` becomes
          `mocked_by_offering_mode()`; new `executors_by_offering_mode()` and
          `executor_is_mocked` (in `jobs/executor_mock.py`). `composition.py`: the
          bundle and composed result lose `readiness_checks` and `router_mounts`.
        - Ansible distribution: new `compute_provisioning_ansible/readiness.py`
          (`FileInfo`, `SshKeyInfo`, `AnsiblePlaybookInfo`, `AnsibleReadinessDetail`,
          `ANSIBLE_READINESS_KIND`, `ansible_readiness_component`, `ansible_version`,
          `sha256_file`, `collect_ssh_keys_from_hosts`): the `ansible` component reports
          Ansible's version, each Ansible executor's offering mode and playbook (path,
          existence, sha256), and the registered hosts' SSH key references, and is ready
          when every Ansible executor is mocked or has its playbook with Ansible on
          `PATH`. `probes.py` keeps `probe_connectivity`; `AnsibleReadinessResponse`,
          `InventoryInfo`, and `ansible_readiness` go.
        - Service: new `services/system_status.py` (`SystemStatusService`: health,
          status, version; storefront reachability and authentication through an injected
          identity resolver, `resolve_identity_context` staying in `identity.py`;
          components run off the event loop) and `controllers/system_controller.py`
          binding health (bare and versioned), status, version, check-leases, and the
          convergence and lease-watchdog controls, resolving collaborators through
          accessors; an uninitialised collaborator answers 503 and advance while
          convergence runs 409. `container.py` builds the status service from the executor
          table, the lease lifecycle, and the Ansible component provider (convergence is
          bound by the system controller, not the status service), and drops
          `system_service`; `app_runtime.py` and `main.py` follow.
        - VM adapter: tombstone `services/system_service.py` and
          `controllers/system_controller.py`; `runtime.py` loses `system_service()` and
          `readiness()`; `bundle.py` loses `readiness_check` and `router_mounts`. Bare
          metal's `runtime.py` and `bundle.py` likewise.
        - Tests: the service's `integration/test_system_api.py` through the canonical
          client against the mounted app (status execution section and Ansible component,
          health typed, the advance 409); new `unit/test_system_controller.py` (the 503
          matrix) and `unit/services/test_system_status.py`; the Ansible distribution's
          `tests/unit/test_readiness.py` (from `test_probes.py`, which keeps the
          connectivity tests); `provisioning/compute/tests/unit/test_job_executor_table.py`
          and `test_composition.py`; the Ansible `test_mock.py` case for modes; the client
          parity test; the contracts route-table test. The integration harness
          (`tests/integration/conftest.py`) composes the status service as production
          does.
  - [x] 5B.8.C.2 Inventory views (review points 2 and 7).
        - Family kit: new `compute_provisioning/inventory_views.py`
          (`InventoryViewProjection`: `resource_view_ids`, `pool_view_ids`,
          `consumed_attributes`, `resource_views(declaration, pool_id)`,
          `pool_views(db, pool_id, provider)`); the bundle and the composed result carry
          `inventory_views`, and composition refuses a view id or consumed attribute
          declared twice.
        - Bare metal: new `bare_metal_provisioning_adapter/inventory_views.py`
          (`BareMetalPublicationViews`: the `bare_metal_publication` attribute, host
          eligibility, whole-resource availability, `project_bare_metal_resource`), leaving
          `runtime.py`.
        - VM: new `vm_provisioning_adapter/inventory_views.py`
          (`AnsiblePoolDefaultsViews`: the `ansible` provider gate, the
          `AnsiblePoolConfig` read, `project_ansible_pool_defaults`), leaving `runtime.py`.
        - Service: `services/capacity_inventory.py` takes the composed views and imports
          neither adapter; `main.py`'s inventory and pool-directory accessors pass them.
        - Tests: the service's `unit/services/test_capacity_inventory.py` keeps the
          neutral projection and gains a fake third domain's projection; bare metal's view
          tests are `domains/bare_metal/provisioning/adapter/tests/test_inventory_views.py`,
          and VM's are the service-hosted `unit/services/test_vm_inventory_views.py` (VM's
          adapter has no test directory, and the view reads `AnsiblePoolConfig`, which
          5B.9.B moves to VM);
          `test_composition.py` covers the duplicate refusals;
          `integration/test_capacity_api.py` keeps proving both views through the site
          client.
  - [x] 5B.8.C.3 Router factories (decision 4). VM's `controllers/vms_controller.py`,
        `hosts_controller.py` (capacity), and `test_controller.py`, and bare metal's
        `controllers/test_controller.py`, become router factories taking zero-argument
        accessors, an uninitialised collaborator answering 503; each adapter's `routers.py`
        exposes them (`vm_router_mounts`, `vm_mock_router`, `bare_metal_mock_router`;
        bare metal's empty `bare_metal_router_mounts` goes); `main.py` and the integration
        harness pass accessors resolving from the container. No adapter module imports
        `compute_provisioning_service.container`, asserted by a source scan in each
        adapter's tests (`test_service_boundary.py`).
  - [x] 5B.8.C.4 Boundary test. `provisioning/compute/service/tests/unit/test_import_boundaries.py`
        allowlists (file, module) pairs: `container.py` the adapters' runtimes, `main.py`
        their routers, `db/migrations.py` `legacy_backfill`, and A0's
        `controllers/relays_controller.py` exception until 5B.9; nothing else.
  - [x] 5B.8.C.5 Callers (review point 4). e2e mock-mode checks read `execution.mocked`
        and the provisioning check reads the Ansible component's readiness
        (`scenarios/vms/test_full_deal.py`, `test_full_deal_buyer_cli.py`,
        `test_buy_oneshot_buyer_cli.py`, `test_non_erc20_settlement.py`); the contract-pin
        check of `test_full_deal.py` and the storefront checks of `test_full_deal.py` and
        `test_full_deal_buyer_cli.py` read the typed status; `test_non_erc20_settlement.py`'s health check reads the typed
        health; `tests/smoke/test_provisioning_smoke.py` asserts the status execution
        section and the Ansible component; `docs/development/VALIDATION_RUNBOOK.md`'s `jq`
        checks `.execution.mocked == false` and the Ansible component's `ready`.
  - [x] 5B.8.C.6 The VM storefront's dead expiry hook (review point 5). Remove
        `_do_shutdown` from `services/fulfillment_service.py`, and the `schedule_shutdown`
        parameter, `ScheduleShutdownFn`, and `_schedule_shutdown_best_effort` (with the
        module's background-task set if nothing else uses it) from
        `services/vm_fulfillment_service.py`; update `tests/unit/test_fulfillment_provisioning.py`,
        `test_fulfillment_service.py`, and `test_fulfill_vm_obligation_error_handling.py`.
        Mark `remove-dead-storefront-physical-surfaces` task 3.8 delivered here.
  - [x] 5B.8.C.7 Gate. Every provisioning-family suite, both adapters, the root `make test`,
        the VM storefront by frozen sync, the e2e unit suite and scenario collection,
        `make check-packaging`, comment hygiene, documentation citations, and OpenSpec
        strict validation. Versions bumped per slice, exact pins moved, changed projects
        relocked.
  - [x] 5B.8.C.8 Fixes from the slice C implementation review (2026-10-05; findings 1–4,
        each agreed with the maintainer; `design.md`, "Slice C implementation review").
        Built on 5B.9.A, which preceded the review.
        - Readiness (finding 1): `compute_provisioning_ansible.readiness` makes the
          component ready only with a readable host registry, whatever runs, and, once any
          Ansible executor is real, Ansible on `PATH`, every real executor's playbook, and
          every key file an enabled host names; `AnsibleReadinessDetail` gains
          `not_ready_reasons`.
        - Component boundary (finding 2): `services/system_status.py`'s
          `StatusComponentProvider` (name and `collect`); a provider that raises or reports
          another name is reported under its own name, not ready, with a
          `COMPONENT_FAILURE_KIND` detail naming only the exception's type. `container.py`
          registers `ansible` that way.
        - Records (finding 3): C.1's and C.2's bullets corrected.
        - OpenAPI (finding 4): `main.py`'s description and the hosts and jobs tags
          describe the compute family's service; the declared version reads
          `SERVICE_VERSION`.
        - Tests: Ansible `test_readiness.py` (an unreadable registry not ready, mocked or
          real; a missing key blocking real execution and not mocked; a mixed deployment;
          the reasons for a missing playbook and a missing Ansible; the case that had
          codified the false ready rewritten); the service's
          `unit/services/test_system_status.py` (a raising provider, a mislabelled one) and
          `integration/test_system_api.py` (a raising component degrades status through
          the route and the typed client, rather than failing it).
        - Versions: none; every package touched was bumped in slice C or 5B.9.A, both
          unreleased.
        - Validation: Ansible 92; provisioning service 864 unit and 277 integration.
          The root `make -k test` aggregate passes its 44 suites, failing only where this
          environment cannot run a suite; the four locks its reinit rewrites were
          restored. `make check-locks`, `make check-packaging`, comment hygiene,
          documentation citations, and OpenSpec strict validation pass.
        - End-to-end (run 37338996200, on the C.8 checkpoint: service 0.11.0, VM adapter
          0.9.0): the bare-metal lane passed 16 and the VM lane 135, nothing failed or
          skipped, and neither lane's service logs show a traceback, a 5xx, a 401, or a
          403. Provisioning's status answered 200 throughout, so the stricter readiness
          rule leaves the mocked lane ready; expired leases were released.

      Slice C done 2026-10-05 (`design.md`, "Slice C design review", for the rulings and
      the plan corrections).
      - C.1:
        - `compute_provisioning_contracts.system`: a lean `HealthResponse`, and
          `SystemStatusResponse` with `ExecutionStatus`, `ExecutorStatus`, and
          `SystemStatusComponent`; the readiness route contract is gone. The client types
          health and status and accepts a degraded 503 body; the worker controls still
          return dicts.
        - The executor table's `mocked_by_offering_mode()` and
          `executors_by_offering_mode()`, and `executor_is_mocked` beside the mock
          mechanism; the bundle and the composed result lost `readiness_checks` and
          `router_mounts`.
        - `compute_provisioning_ansible.readiness` builds the `ansible` component, with the
          version probe injectable; `probes.py` keeps only the connectivity probe.
        - The service's `services/system_status.py` and `controllers/system_controller.py`
          (a router factory over accessors; 503 for an uncomposed collaborator, 409 for an
          advance while convergence runs). A database error in health reports only its
          type, since its message can carry the URL.
        - VM's system service and controller are deleted, with the runtime's
          `system_service()`, `readiness()`, and `job_executors`.
      - C.2: `compute_provisioning.inventory_views` (`InventoryViewProjection`,
        `InventoryViews`, `compose_inventory_views`); bare metal's
        `BareMetalPublicationViews` and VM's `AnsiblePoolDefaultsViews` own their views,
        source data, and eligibility; `capacity_inventory.py` names neither.
      - C.3: VM's VM-operations, host-capacity, and mock routes and bare metal's mock
        routes are router factories over accessors, sharing the family's
        `require_composed`. `main.py` imports the adapters' entry points at module top,
        since no adapter module reads the container any longer. Bare metal's adapter
        imports no service module at all, so its dependencies on the service, VM's
        adapter, `fastapi-utils`, and `typing-inspect` were removed: bare metal's half of
        5B.10, done early because the comment justifying them had become false.
      - C.4: the service's `test_import_boundaries.py` allowlists (file, module) pairs and
        also scans both adapters' sources for imports of the service's composition
        modules. The plan placed that scan in each adapter's tests; the VM adapter has no
        test directory (its target runs tests the service suite hosts), so it lives beside
        the service's own boundary check.
      - C.5: the four mock-mode checks read `execution.mocked`, the provisioning-health
        stages read the Ansible component, and the pin and storefront checks read the
        typed status; the smoke test checks execution and the component; the runbook's
        `jq` reads status.
      - C.6: the hook is removed; `remove-dead-storefront-physical-surfaces` task 3.8 and
        its proposal record it as delivered here.
      - Tests:
        - Family kit: inventory-view composition (duplicate claims at each attachment
          point, an identifier shared across attachment points, merge, an undeclared
          view) and the table's two readers.
        - Ansible: `test_readiness.py` (every mode's playbook, a missing playbook, real
          executors without Ansible, mocked executors, an unreadable registry, no key
          material).
        - Service unit: `test_system_controller.py` (the 503 matrix and the 409),
          `services/test_system_status.py`, `services/test_vm_inventory_views.py`, the
          neutral and third-domain cases of `services/test_capacity_inventory.py` (its
          frozen projections kept, with production's views), the rewritten
          `test_fulfillment_convergence_wiring.py` (the mounted routers reach the
          composed workers), and the boundary test.
        - Service integration: the harness now composes both bundles through
          `compose_adapter_bundles` into an empty executor table, builds a real
          convergence watchdog, and composes the status service with the production
          components. `test_system_api.py` covers typed health, the status's execution
          and its Ansible component reporting both modes' playbooks, the advance 409,
          pause, advance, and resume, and a mocked-execution case.
        - Bare-metal adapter: `tests/test_inventory_views.py`.
      - Versions:
        - compute-provisioning-contracts 0.5.0, compute-provisioning-client 0.4.0,
          compute-provisioning 0.13.0, compute-provisioning-ansible 0.4.0 (now declaring
          `arkhai-core`), compute-provisioning-service 0.10.0;
        - vms-provisioning-adapter 0.9.0, bare-metal-provisioning-adapter 0.7.0;
        - e2e-tests 0.1.3, vms-storefront 0.10.1;
        - floors raised where a consumer needs the new behaviour; no exact pin names
          these packages.
        - Relocked with `scripts/uv_project.py lock`: the contracts, client, family kit,
          Ansible distribution, VM operator client, both adapters, the service, the
          bare-metal storefront, and e2e-tests; the VM storefront by hand from the
          wheelhouse, as before (three entries moved).
      - Validation:
        - compute contracts 51, client 49, family kit 180, Ansible 88, bare-metal adapter
          31;
        - provisioning service 859 unit and 276 integration (24 readiness and status
          cases replaced by 16);
        - VM storefront by frozen sync: 1109 unit and 348 integration (the two known
          `test_alkahest` failures);
        - e2e unit 236 (the known 10.1 failure), and 178 e2e and smoke tests collect.
        - Comment hygiene, documentation citations, and OpenSpec strict validation pass.
        - VM adapter target 45 (the two service-hosted VM test files).
        - The root `make -k test` aggregate passes its 44 suites, failing only where this
          environment cannot run a suite (`kit/policy`, the VM storefront, and the VM
          buyer cannot reinit from the PyTorch index; the API-credit middleware needs
          Cargo). The locks its reinit rewrites without a project change were restored:
          `kit/alkahest`, `kit/config`, `kit/settlement-runtime`, and this time also
          `domains/apicredits/storefront` (platform markers only). `make check-locks` and
          `make check-packaging` pass.
        - End-to-end (run 37334863741, with slice C and 5B.9.A): the bare-metal lane
          passed 16 and the VM lane 135, nothing failed or skipped, and neither lane's
          service logs show a traceback, a 5xx, a 401, or a 403. The typed-status stages
          (00c, 00c2, 00e, 00h, and the buyer-CLI equivalents) passed, provisioning's
          status answered 200 throughout, expired leases were released, and "Failed to
          schedule VM expiry" no longer appears.
- [x] 5B.9 Relays to VM. Amended 2026-10-05 before implementation, after the design review
      (`design.md`, "Relays to VM (5B.9)", points A–D): the relay code, its tables, and its
      routes move to VM's adapter, behind three contribution seams the move needs. Two
      slices, each its own checkpoint, gated like 5B.8's.
  - [x] 5B.9.A Seams (points A and B). Behaviour-neutral: the service still contributes
        the relay release, the relay document kind, and the reconciliation task itself.
        - Family kit (`provisioning/compute/src/compute_provisioning/`):
          - new `fulfillment_terminal.py`: `FULFILLMENT_TERMINAL_STATES`,
            `fulfillment_is_terminal(db, capacity_reservation_id)`, the
            `FulfillmentTerminalHook` shape (session, reservation id, terminal state), and
            the `FulfillmentTerminalHooks` registry (register, freeze, run in order;
            nothing registers once frozen);
          - new `definition_documents.py`: `DefinitionDocumentContribution` (kind, label,
            path, `apply(db, yaml_text)` returning its summary);
          - `composition.py`: the bundle gains `fulfillment_terminal_hooks`,
            `definition_documents`, and `background_tasks`; `compose_adapter_bundles`
            takes the registry, registers every hook, and freezes it; the composed result
            carries the document kinds and tasks, refusing a kind declared twice or one
            the service reserves (`pools`, `capacity`);
          - `release.py`: `FulfillmentReleaseGuard` takes the registry and runs it in the
            ledger's session after it abandons an aggregate, never when it refuses.
        - Service (`provisioning/compute/service/src/compute_provisioning_service/`):
          - `services/fulfillment_convergence.py`: `terminal_hooks` replaces
            `port_allocator`; every terminal transition runs the hooks in its transaction;
          - `services/definition_documents.py`: the importer runs contributed kinds before
            pools, each under the existing digest guard, and loses its relay step;
          - `container.py`: one registry, passed to the guard, convergence, and
            composition; until B it registers the service's relay-port release itself;
          - `app_runtime.py`: one `import-contributed-definitions` startup step replaces
            the relay step; composed background tasks start with the service's; the
            reconciliation's predicate is the family kit's; until B the relay document
            kind and reconciliation task are built here.
        - Tests:
          - family kit unit: the registry, and composition's new contributions and
            refusals;
          - family kit integration `tests/integration/test_release.py`: an abandoning
            guard runs the hooks in its session, a refusing one runs none;
          - service unit `services/test_fulfillment_convergence.py`: hooks run in each
            terminal transaction, and a failing hook leaves the record unchanged;
            `services/test_definition_document_restart_safety.py`: contributed kinds run
            before pools under their digests.
        Done 2026-10-05.
        - `compute_provisioning.fulfillment_terminal` (`FULFILLMENT_TERMINAL_STATES`,
          `fulfillment_is_terminal`, `FulfillmentTerminalHook`, `FulfillmentTerminalHooks`)
          and `compute_provisioning.definition_documents`
          (`DefinitionDocumentContribution`). The bundle's three new fields; composition
          registers hooks and freezes the registry with the executor table, refuses a
          contributed hook with no registry to receive it, a document kind the service
          imports itself or one declared twice, and a background task declared twice.
        - The release guard runs the hooks after it abandons an aggregate, in the
          ledger's session; a failing hook aborts the reclaim. Convergence runs them on
          every terminal transition it writes, and names no relay. A registry stays
          optional on both, absent meaning no domain effects, as the port allocator was.
        - The service: one registry (`fulfillment_terminal_hooks`) reaching the guard,
          convergence, and composition, with the relay-port release
          (`release_fulfillment_ports`, beside the allocator) registered by the service; the
          importer runs contributed kinds, the relay document becoming one
          (`relay_definitions_document`, kind `relays` kept); composition's documents and
          tasks are resolved at startup (`resolved_definition_documents`,
          `resolved_background_tasks`); one `import-contributed-definitions` step; the
          reconciliation predicate reads the family kit's `fulfillment_is_terminal`.
        - Tests: family kit `test_fulfillment_terminal.py` and six composition cases;
          `tests/integration/test_release.py` (an abandoning guard's effect commits with
          the reclaim, a failing effect aborts it and abandons nothing, no effect when
          nothing is abandoned); the service's convergence suite on the registry and a
          failing effect leaving the record unchanged, the contributed step's order, and
          one registry reaching both writers (`test_authority_composition.py`). The
          integration harness composes the registry as production does.
        - Versions: compute-provisioning 0.14.0, compute-provisioning-service 0.11.0
          (its family-kit floor raised); the family kit, Ansible distribution, both
          adapters, and the service relocked.
        - Validation: family kit 203 (unit and integration); Ansible 88; bare-metal
          adapter 31; VM adapter target 45; provisioning service 862 unit and 276
          integration. The root `make -k test` aggregate passes its 44 suites, failing
          only where this environment cannot run a suite (as in slice C); the four locks
          its reinit rewrites were restored. `make check-locks`, `make check-packaging`,
          comment hygiene, documentation citations, and OpenSpec strict validation pass.
          End-to-end: run 37334863741 (slice C's record) included 9.A.
  - [x] 5B.9.B The move (points A–D).
        - VM adapter (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/`):
          - new `db.py`: VM's metadata with `Relay`, `RelayPortLease`, and
            `AnsiblePoolConfig`;
          - from the service's `services/`: `relay_rebinding.py`,
            `relay_port_allocator.py`, `relay_execution.py`, `relay_service.py`, and
            `relay_definitions.py`, into `services/`;
          - `controllers/relays_controller.py`, a router factory over an accessor for the
            relay service; `routers.py`'s `vm_router_mounts` takes it;
          - `runtime.py` builds one port allocator and the relay service and contributes
            the relay-port terminal hook, the `relays` document kind, and the
            reconciliation task (its settings keys unchanged); `bundle.py` carries them;
          - `ansible_pool_config_handler.py`, `inventory_views.py`, and
            `services/ansible_fulfillment_provider.py` import from VM's own modules.
        - VM operator client: the relay route declarations admit only `admin`.
        - Service: tombstone the five relay services and `controllers/relays_controller.py`;
          `db/models.py` loses the three models; `db/database.py` creates VM's metadata
          after the pool tables, and `db/migrations.py` reads the models from VM's
          `db.py`; `container.py`, `app_runtime.py`, `main.py`, and `config.py` lose their
          relay wiring.
        - Boundary test: the (file, module) allowlist gains `db/database.py` and
          `db/migrations.py` reading `vm_provisioning_adapter.db` and loses
          `relays_controller.py`'s exception.
        - Tests: the service-hosted relay tests import VM's modules
          (`unit/services/test_relay_administration.py`, `test_relay_port_allocator.py`,
          `test_relay_port_leases.py`, `test_ansible_pool_config_handler.py`,
          `test_definition_document_restart_safety.py`, `test_fulfillment_convergence.py`,
          `test_capacity_inventory.py`, `test_vm_inventory_views.py`; `unit/test_database.py`,
          `test_pool_offering_mode_migration.py`; `integration/conftest.py`,
          `test_relays_api.py`, `test_capacity_api.py`, `test_fulfillment_api.py`,
          `test_host_pool_moves_api.py`, `test_pool_declaration_startup.py`,
          `test_pools_api.py`, `test_test_controller.py`). The plan had VM's adapter
          target run the relay files the service hosts; they build their databases
          through the service's migrations, so they stay in the service's suite. The
          seller's refusal is a middleware case over the assembled table, since the
          typed client will not sign a role the contract does not admit.
        - Spec delta (`physical-provisioning`): fulfillment terminal effects run in the
          terminal transaction, and relay administration admits only the administrator.
        - When done, update `relay-vm-access-without-a-dashboard` (its "Pending move" note
          and its open tasks) to the relay code's new paths, as the reconciliation of
          2026-10-05 recorded there.
        Done 2026-10-05 (`design.md`, "Relays to VM (5B.9)", "5B.9.B implementation
        findings").
        - VM's adapter holds `db.py` (`Relay`, `RelayPortLease`, `AnsiblePoolConfig`) and
          the five relay services; `controllers/relays_controller.py` is the router factory
          `make_relays_router`, mounted through `vm_router_mounts(relay_service=…)`. The
          runtime builds one port allocator and the relay service; the bundle contributes
          `release_fulfillment_ports` as a terminal hook, the `relays` document kind (its
          path resolved by VM from the unchanged `relay_definitions_path`), and the
          reconciliation task, whose predicate (`fulfillment_lease_owner_is_terminal`)
          reads the family kit's `fulfillment_is_terminal`. VM's adapter imports no service
          module, and its dependency on the service is gone.
        - The service: `db/models.py` loses the three models; `db/database.py` creates VM's
          metadata after the pool tables; `db/migrations.py` reads VM's models (two new
          allowlisted pairs; the relay controller's exception is gone); `container.py`,
          `app_runtime.py`, `main.py`, and `config.py` lose relay implementation
          ownership (they still compose VM's relay service into VM's router, as a
          composition root must), and the terminal-effect registry starts empty. Its runtime dependency on VM's operator
          client is gone.
        - The relay route declarations admit only `admin`.
        - `relay-vm-access-without-a-dashboard`'s pending-move note now records the new
          paths; none of its open tasks named a moved file.
        - Tests: the service-hosted relay, pool-configuration, convergence, inventory, and
          database tests import VM's modules and create VM's metadata; the relay API suite
          signs as the administrator; `unit/middleware/test_auth.py` refuses a
          seller-signed relay request and admits the administrator's, over the table
          `main.py` assembles; the fulfillment API's port checks read the leases through
          an allocator over the service's database.
        - Versions: vms-provisioning-adapter 0.10.0 (its family-kit floor 0.14.0),
          vms-provisioning-operator-client 0.9.0, compute-provisioning-service 0.12.0 (its
          adapter floors 0.10.0); VM's adapter and client, the service, and e2e-tests
          relocked.
        - Validation: family kit 203; VM adapter target 45; bare-metal adapter 31;
          provisioning service 870 unit and 277 integration; e2e unit 236 (the known 10.1
          failure), and 178 e2e and smoke tests collect. The root `make -k test` aggregate
          passes its 44 suites, failing only where this environment cannot run a suite;
          the four locks its reinit rewrites were restored. `make check-locks`,
          `make check-packaging`, comment hygiene, documentation citations, and OpenSpec
          strict validation pass.
        - End-to-end (run 37342659408, on the 9.B checkpoint): the archive holds the two
          lanes' service logs but not the run's `actions.log`, so its pass counts are not
          recorded here. The logs identify 9.B's composition: VM's relay reconciliation
          starts after the service's own workers, as a contributed task, where before it
          started ahead of convergence. Neither lane's service logs show a traceback, a
          5xx, a 401, or a 403; the relay document kind and the reconciliation task ran
          at startup, and both expired VM leases were released.
- [x] 5B.10 Boundary check. Amended 2026-10-05: the dependency removals this task named
      are done (bare metal's in 5B.8.C, VM's in 5B.9.B), each when its adapter stopped
      importing the service; what remains is the check. Add
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
      Done 2026-10-05 (`design.md`, "Boundary check (5B.10)").
      - Every Python boundary the task names already held; one deployment rule did not:
        API credits' compose mounted the dev chain's Alkahest address book from VM's
        storefront package. The maintainer chose the move (option (a)): the address book
        is now `kit/alkahest/src/market_alkahest/data/alkahest_anvil_addresses.json`, with
        `market_alkahest.dev_chain.anvil_address_book_path()`; the generator and
        `make build-anvil-state` run in the kit's environment; the VM, API-credit, and
        root bare-metal compose files mount it from the kit at the unchanged
        `/app/alkahest_anvil_addresses.json`; the Helm fixture names that path (it named
        one no image contains); the VM storefront's two tests, the e2e buyer CLI helper,
        the escrow helper, and four scenarios read it from the kit.
      - The service's `tests/unit/test_import_boundaries.py` resolves every import of each
        module (relative ones resolved, function-local, `TYPE_CHECKING`, and guarded ones
        counted) and asserts: neither adapter imports the service or the other adapter; no
        neutral provisioning package imports `vm_provisioning_operator`; the family's job
        and host authorities import no Ansible or SSH module; no domain's deployment files
        name another domain's tree; the Ansible distribution names no domain's inventory
        group or playbook. It replaces the narrower composition-module scan. Each check was
        shown to fail on a real violation (the old mount line; function-local, relative,
        and `TYPE_CHECKING` imports). The compute client gains its own allowlist test,
        beside the contracts' and the resource-pool packages' existing ones.
      - Versions: kit-alkahest 0.3.0 (the address book and its accessor), vms-storefront
        0.11.0 (its package data no longer carries the address book; its kit floor
        0.3.0), e2e-tests 0.1.4 (kit floor 0.3.0). Relocked with `uv_project.py`: the kit,
        `kit/storefront`, API credits' four projects, bare metal's buyer and storefront,
        and e2e-tests; by hand from the wheelhouse: the VM storefront and VM buyer.
      - Validation: Alkahest kit 182; compute client 50; provisioning service 874 unit and
        277 integration; VM storefront by frozen sync 1109 unit and 348 integration (the
        two known `test_alkahest` failures); e2e unit 236 (the known 10.1 failure), and
        178 e2e and smoke tests collect. The root `make -k test` aggregate ran its 44
        suites; one provisioning integration test failed once
        (`test_a_bare_metal_lease_is_registered_on_the_family_surface`, a harness race
        routed to closeout task 2.6) and passed in five isolated and three full-suite
        reruns; otherwise only the environmental failures. The locks its reinit rewrote
        were restored. `make check-locks`, `make check-packaging`, comment hygiene, and
        documentation citations pass. OpenSpec strict validation passes under 1.14.0,
        the version `openspec/README.md` now pins: 1.14.1, published 2026-10-05 23:28
        UTC, fails `--strict` on requirement text over 500 characters (19 of this
        change's requirements, 21 of the 22 permanent specs). The maintainer chose the
        pin, with `shorten-long-requirements` opened to restructure the permanent specs
        and move it forward; this change's own long deltas are restructured at its
        closeout (task 2.6). The Helm render
        tests were not run (no `helm` binary in this environment); none asserts the
        changed value.
      - End-to-end (run 37431438099, on the 5B.10 checkpoint: service 0.12.0, VM adapter
        0.10.0, kit-alkahest 0.3.0, VM storefront 0.11.0): the bare-metal lane passed 16
        and the VM lane 135, nothing failed or skipped, and neither lane's service logs
        show a traceback, a 5xx, a 401, or a 403; expired leases were released.
- [x] 5B.10.D Fixes from the implementation review of 5B.9 and 5B.10 (2026-10-06;
      `design.md`, "Implementation review of 5B.9 and 5B.10"). Supersedes 5B.9.A's
      terminal hooks.
      - Release effects (finding 1): `kit/site`'s `CapacityLedgerService` takes
        `release_effect`, run before commit in every transaction that releases capacity
        (`release`, guarded or forced; the lapsed-hold sweep; `resize_reservation`'s
        supersede); `compute_provisioning/release_effects.py` (`ReleaseEffects`,
        `reservation_is_released`) replaces `fulfillment_terminal.py`; the bundle's
        `release_effects`; the release guard and fulfillment convergence run no effects;
        the container hands the registry to the ledger; VM's `release_reservation_ports`
        and `fulfillment_lease_owner_is_released`, with the allocator's and
        `RelayPortLease`'s docstrings; the spec delta's requirement rewritten and the
        permanent "Relay port leases are unique per relay" modified.
      - Task names (finding 2): `app_runtime.background_tasks()` refuses a name used twice
        across the service's workers and the contributions.
      - Classification (finding 3): the convergence suite's database tests, and the relay
        administration, port allocator, port lease, and pool-configuration suites, move to
        `provisioning/compute/service/tests/integration/`; the backoff test is
        `unit/services/test_fulfillment_convergence_backoff.py`.
      - Records (finding 4): 5B.9.B's note corrected.
      - Tests: `kit/site`'s ledger suite (the effect on a guarded, a forced, and a lapsed
        release and a resize's supersede; none on a refusal or a retry; a failing effect
        aborting the release); the family's `test_release_effects.py`, composition cases,
        and `test_release.py` (an abandoning release's effect in its transaction, a
        failing effect, a failed fulfillment holding until forced); the service's
        convergence suite (a failed create, a created guest whose identity cannot be
        resolved, and a successful create all keep their port; reconciliation follows the
        reservation's state), `test_authority_composition.py` (the ledger runs the
        registry composition fills), `test_worker.py` (a contribution named
        `lease-watchdog` refused).
      - Versions: kit-site 0.9.0, compute-provisioning 0.15.0 (kit-site floor 0.9.0),
        compute-provisioning-service 0.13.0 (floors: kit-site 0.9.0, family kit 0.15.0, VM
        adapter 0.11.0), vms-provisioning-adapter 0.11.0 (family-kit floor 0.15.0);
        relocked: `kit/site`, `kit/fulfillment`, the family kit, the Ansible
        distribution, both adapters, the service, the API-credit service, the bare-metal
        storefront, e2e-tests; the VM storefront by hand.
      - Validation: `kit/site` 286; family kit 196; provisioning service 726 unit and
        421 integration. The root `make -k test` aggregate passes its 44 suites, failing
        only where this environment cannot run a suite; an earlier aggregate run hit the
        recorded harness race once more (closeout task 2.6). The four locks its reinit
        rewrites were restored. `make check-locks`, `make check-packaging`, comment
        hygiene, documentation citations, and OpenSpec strict validation (1.14.0) pass.
      - End-to-end: run 37437827289 on this tree passed both lanes (recorded at 5B.11).
- [x] 5B.11 **Gate.** All provisioning-family suites, `make check-packaging`, comment
      hygiene; the VM lane and the bare-metal publication lane pass.
      Done 2026-10-06 on the 5B.10.D tree. The suites, packaging, and comment hygiene are
      5B.10.D's. End-to-end run 37437827289 installed compute-provisioning-service 0.13.0,
      compute-provisioning 0.15.0, kit-site 0.9.0, and vms-provisioning-adapter 0.11.0
      (with kit-alkahest 0.3.0 and vms-storefront 0.11.0). The bare-metal lane passed 16 and
      the VM lane 135; nothing failed or was skipped. Neither lane's service logs show a
      traceback, a 5xx, a 401, or a 403: the 404s are the scenarios' existence probes, the
      402s API-credit exhaustion, the 410s introduction retention. Expired leases were
      released. The VM lane runs no relay, so 5B.10.D's port path is proven by the
      integration suites, not by this run.
- [ ] 5B.12 Job-backed fulfillment. Re-planned 2026-10-05 before implementation, after the
      design review (`design.md`, "Job-backed fulfillment (5B.12)"): the family owns the
      whole job-backed provider and one delivery contract; domains contribute preparation
      and their codec's output. Amended 2026-10-06 by the implementation audit (`design.md`,
      "5B.12 implementation audit (2026-10-06)"): typed delivery evidence validated before a
      create succeeds, teardown prepared from the create job's parameters, a family job
      submission service, jobs correlated on the capacity reservation, and lease
      registration removed behind a decision gate. Four slices, each keeping both end-to-end
      lanes green, so a domain's producer and its storefront consumer move together.
  - [x] 5B.12.A The family provider, job submission, and delivery contracts; bare metal
        moved onto them.
        - Contracts (`provisioning/compute/contracts/src/compute_provisioning_contracts/`):
          new `delivery.py`: `AccessEndpoint` (protocol, host, port, user),
          `DeliveryEvidence` (endpoints, timezone-aware `ready_at`; a create job's result,
          under a family result kind), `DeliveredCredential` (role, password, key type), and
          `AccessDelivery` (endpoints, credentials, `ready_at`; no resource list) under its
          own kind and schema version. `jobs.py`: `JobStatusResponse` loses `escrow_uid`;
          the jobs list filters by `capacity_reservation_id`.
        - Family job authority (`provisioning/compute/src/compute_provisioning/jobs/`): new
          `submission.py`, `JobSubmissionService`: the route key, a registered-host check
          for every job, contract and operation identity, the queue, and
          `JobEngine.submit`. `action_request.py`: `JobActionRequest` loses `deal_ref`.
          `engine.py`: submission records no escrow or deal reference; the list filters by
          capacity reservation. `db.py` and `route_service.py` follow.
        - Family kit: new `job_fulfillment.py`:
          - the prepared job (offering mode, executor action, `host_id`,
            `executor_target`, opaque parameters);
          - the domain's plan protocol: prepare a create from the request, the resource,
            and the pool configuration (honouring `allocate`); prepare a teardown from the
            settlement result, the create job's parameters, and the pool configuration;
          - the fulfillment metadata (`create_job_id`, `teardown_job_id`,
            `current_job_id`, `operation`, `host_id`, `executor_target`);
          - `JobFulfillmentProvider`, implementing `kit/fulfillment`'s provider protocol:
            - submission through `JobSubmissionService`, with contract identity
              `<reservation>:create` or `<reservation>:teardown`, action kind the
              operation, and the operation id derived from the contract;
            - a disabled host refused for a create only;
            - status on `JobStatus`, a succeeded create reported only with valid
              `DeliveryEvidence`, `failed` with a detail naming it otherwise;
            - one provisioned resource, `executor_target`, and `resolve_executor_job_id`;
            - teardown preparation reading the create job's parameters, a missing create
              job a `ProviderConfigInvalidError`;
            - the delivery from the create job's evidence and its credentials' allowlist.
        - Service (`provisioning/compute/service/src/compute_provisioning_service/`):
          `db/migrations.py` drops the jobs table's `escrow_uid` and `deal_ref`;
          `controllers/jobs_controller.py` filters by capacity reservation; `container.py`
          and `app_runtime.py` build the submission service and lose the bare-metal
          operations service. The compute client's `list_jobs`, async and sync, filters by
          capacity reservation.
        - VM, until 5B.12.B moves it: `services/job_submitter.py` passes no escrow;
          `services/ansible_fulfillment_provider.py`'s contracts carry no `deal_ref`.
        - Bare-metal adapter: `services/bare_metal_fulfillment_provider.py` becomes the plan
          (`services/bare_metal_fulfillment_plan.py`: publication and resource binding,
          `physical_host_id` checked against the declaration, grant parameters, reclaim
          parameters from the grant job's, the reclaim policy); the provider file and
          `services/bare_metal_operations_service.py` tombstoned (only the provider uses
          the latter); `codec.py` emits `DeliveryEvidence` for a grant; `runtime.py` and
          `bundle.py` build the family provider over the plan.
        - `arkhai_bare_metal`: `schema.py`'s `BareMetalAccessResult` becomes the domain's
          buyer result (access method, user, `ready_at`, lease end; no endpoint);
          `domain_runtime.py`'s result codec and `__init__.py` follow; `evidence.py`'s
          `BareMetalLeaseReadyResult` loses `access_grant_ref`.
        - Bare-metal storefront: `hosted_lifecycle.py` reads the access delivery, treats an
          active fulfillment naming an endpoint as access-ready, and takes `ready_at` from
          the delivery and `expires_at` from its materialization; `fulfillment_service.py`
          stores the buyer result and serves `/access` from the live delivery and its
          materialization; `api.py`, `models.py`, and `sqlite_client.py` follow. Lease
          registration still passes `host_id` until 5B.12.C.
        - e2e: `tests/e2e/roles/scenarios/vms/test_listing_shapes.py` filters jobs by
          capacity reservation.
        - During A, check whether scheduling places on a disabled host; if it does, a
          create there waits in dispatch until the host is re-enabled, and the finding is
          routed to closeout task 2.6.
        - Tests:
          - `provisioning/compute/tests/unit/test_job_fulfillment.py`, the provider against
            a fake plan and job authority: dispatch, contract identity, the operation id,
            the host checks for a create and a teardown, status for every `JobStatus`, a
            succeeded create with missing or invalid evidence, an undecodable envelope,
            teardown from the create job's parameters, a missing create job, the
            credentials' allowlist (`ssh_key_path_host` and unknown fields refused);
          - `provisioning/compute/tests/unit/test_job_submission.py`, absorbing
            `service/tests/unit/services/test_bare_metal_operations_service.py`'s host
            cases (that file tombstoned);
          - the contracts' delivery test;
          - `tests/integration/test_job_authority.py` (the reservation filter);
          - the service's job-column migration (integration);
          - the service's bare-metal fulfillment through the real orchestrator and
            convergence (`integration/bare_metal_deal.py` and the suites using it,
            `integration/conftest.py`);
          - the bare-metal adapter's tests rewritten to the plan;
          - `domains/bare_metal/tests/test_schema.py`, `test_evidence.py`, and
            `test_domain_runtime.py`;
          - the bare-metal storefront's `test_hosted_lifecycle.py`,
            `test_hosted_lifecycle_repository.py`, `test_fulfillment_service.py`,
            `test_http_settlement.py`, `test_persistence.py`, and its other tests building
            lease-ready results.
        - End to end: neither lane exercises bare metal's provisioned fulfillment (the
          bare-metal lane runs publication and introduction; the deal scenario comes with
          Section 9), so A's bare-metal evidence is the service's integration suite. Both
          lanes still run, VM's covering the job-list filter.
        Done 2026-10-06, as planned:
        - Delivery contracts and job authority:
          - `compute_provisioning_contracts.delivery` holds `AccessEndpoint`,
            `DeliveryEvidence` (result kind `compute.delivery-evidence.v1`),
            `DeliveredCredential`, and `AccessDelivery` (`compute.access-delivery` v1).
          - Jobs record no escrow or deal reference. `JobStatusResponse` names a
            fulfillment job's capacity reservation, and the jobs list, its route, both
            clients, and the controller filter by it.
          - Migration `20261006_001_drop_job_deal_correlation` drops the two columns and
            the escrow index.
        - `JobSubmissionService` (`jobs/submission.py`):
          - every job needs a registered host, and a create also needs it enabled;
          - a contract job takes a UUIDv5 operation id derived from its contract;
          - an operator's job keeps its own operation id.
        - `JobFulfillmentProvider` (`job_fulfillment.py`):
          - contract identity is `<reservation>:<operation>`;
          - a create is succeeded only with valid evidence, otherwise `failed`;
          - the provisioned resource is `executor_target`;
          - teardown is prepared from the create job's parameters, and a missing create
            job is a configuration error;
          - the delivery is the create job's evidence plus allowlisted credentials.
        - Bare metal:
          - `BareMetalFulfillmentPlan` replaces its provider and operations service (both
            tombstoned). Its codec reports a grant as delivery evidence, or the raw fact
            under its own kind when the fact cannot say where to connect.
          - `BareMetalResult` (account, `ready_at`, lease end, no endpoint) replaces
            `BareMetalAccessResult`, and the lease-ready result loses `access_grant_ref`.
          - The storefront reads the access delivery (`access_delivery.py`); `/access`
            serves the endpoint live, with the lease end from its materialization.
        - Interim VM changes until 5B.12.B: VM's submitter and provider pass no escrow or
          deal reference, and its `test_fulfillment_api.py` and provider test drop the job's
          deal reference.
        - `storefront-publication`'s delta scenario "Bare-metal result is returned" now names
          the buyer result and the live endpoint.
        - Tests:
          - family kit: `test_job_fulfillment.py`, `test_job_submission.py`, and the
            reservation filter in `test_job_authority.py`;
          - contracts: `test_delivery.py`;
          - bare-metal adapter: `test_bare_metal_fulfillment_plan.py`, including a mock
            grant delivered and reclaimed through the family provider; the old provider
            test is tombstoned;
          - service: `test_bare_metal_mock_profile.py` drives a grant to `active` through
            convergence, reads the delivery through the result route, and reclaims from
            the grant's parameters to `torn_down`; also `test_job_deal_correlation_migration.py`
            (integration), the integration harness composing bare metal as the container
            does, and `test_database.py` and `test_authority_composition.py` updated;
          - bare-metal domain and storefront suites on the new shapes, with the hosted
            evidence's readiness and expiry sources asserted;
          - e2e `test_listing_shapes.py` filters jobs by reservation.
        - Versions:
          - contracts 0.6.0, client 0.5.0, family kit 0.16.0, service 0.14.0;
          - bare-metal adapter 0.8.0, arkhai-bare-metal 0.8.0, bare-metal storefront 0.9.0;
          - vms-provisioning-adapter 0.11.1;
          - vms-storefront 0.11.1, whose exact bare-metal storefront pin moved to 0.9.0;
          - e2e-tests 0.1.5;
          - floors raised to match.
        - Relocking: by `uv_project.py`, except the VM storefront and the bare-metal
          storefront, which were locked by hand. The latter keeps the snapshot's platform
          markers, which a relock flips.
        - Validation:
          - contracts 60; family kit 224; compute client 50; Ansible distribution 92;
          - bare-metal domain 132, adapter 39, buyer 13, storefront 230; VM adapter 45;
          - provisioning service 719 unit and 424 integration;
          - VM storefront by frozen sync 1109 unit and 348 integration (the two known
            `test_alkahest` failures);
          - e2e unit 236 (the known 10.1 failure), and 178 e2e and smoke tests collect;
          - the root `make -k test` aggregate: its 44 suites pass, failing only where this
            environment cannot run a suite; the four locks its reinit rewrote were
            restored;
          - `make check-locks`, `make check-packaging`, comment hygiene, documentation
            citations, and OpenSpec strict validation (1.14.0) pass.
        - End-to-end: run 37453176468, on this checkpoint,
          installed compute-provisioning-service 0.14.0, compute-provisioning 0.16.0,
          contracts 0.6.0, bare-metal adapter 0.8.0, VM adapter 0.11.1, vms-storefront
          0.11.1, and bare-metal storefront 0.9.0. The VM lane passed 135 (its listing-shapes
          scenario filtering jobs by capacity reservation) and the bare-metal lane 16;
          nothing failed or was skipped; neither lane's service logs show a traceback, a
          5xx, a 401, or a 403; expired leases were released. Neither lane exercises
          bare-metal fulfillment, so that path's evidence is the integration suite above.
        - Scheduling and admission do not read a host record's enabled flag, so a create can
          be placed on a disabled host; its dispatch then retries until the host is
          re-enabled. Routed to closeout task 2.6.
  - [x] 5B.12.B VM end to end, with the migration. Amended 2026-10-06 by the 5B.12.B
        implementation audit (`design.md`, "5B.12.B implementation audit (2026-10-06)").
        - Contracts (`compute_provisioning_contracts/delivery.py`): `CreateJobResult`
          (`compute.create-result.v1`): the `DeliveryEvidence` or none, and a non-secret
          `detail` mapping. It replaces `DELIVERY_EVIDENCE_RESULT_KIND` as a create job's
          result. Family kit (`job_fulfillment.py`): a create succeeds only on a
          `CreateJobResult` carrying valid evidence; the detail is never read or delivered.
        - Bare metal, onto the one shape: `codec.py` reports a grant as a `CreateJobResult`
          with the access fact as its detail, and with no evidence when the fact cannot
          say how to connect (replacing the raw-fact fallback under its own kind).
        - VM adapter:
          - `services/ansible_fulfillment_provider.py` becomes the plan
            (`services/vm_fulfillment_plan.py`: the relay-port lease, playbook override,
            and extra-vars validation; teardown from the metadata's target, the lease's
            relay, and the pool's playbook); the provider file is tombstoned.
          - `services/job_submitter.py` is tombstoned. `services/vm_operations_service.py`
            and `services/host_operations_service.py` submit through
            `JobSubmissionService`, keeping their request operation ids;
            `models/vm_request_model.py`, `models/fulfillment_model.py`, `runtime.py`, and
            `bundle.py` follow.
          - `fulfillment_results.py` is tombstoned.
          - `codec.py` reports a create as a `CreateJobResult`: the evidence endpoint is
            the relay's address and the leased port when the job leased one (a reported
            port that disagrees yields no evidence), else the host's buyer-facing address
            and external port; the detail is VM's named operator fields, the guest's
            internal address included, without the raw fact.
          - `legacy_backfill.py` builds the family's prepared teardown and metadata from
            VM's plan directly.
        - Service: a migration in `db/migrations.py` rewriting, for every VM fulfillment in
          every state, its prepared create and teardown operations, `provider_metadata`
          and `teardown_provider_metadata` (`vm_target` becomes `executor_target`), and
          each create-job result it references, into the family's shapes.
          - A create result becomes a `CreateJobResult`: the evidence by the relay rule,
            from its stored relay facts; every other field kept in its detail.
          - VM's job parameters are re-wrapped unchanged.
          - A record naming no target takes it from its create job's parameters, and the
            migration aborts atomically when neither names one.
          - Bare metal is not live and is not migrated.
        - VM storefront:
          - `services/fulfillment_service.py`, `services/fulfillment_resume_runtime.py`,
            and `services/vm_fulfillment_service.py` read the access delivery: tenant
            credentials to the buyer, root to the seller's own store; no key path,
            internal address, or guest name.
          - `connection_details` becomes `arkhai_vms.VmConnectionDetails` (`host`,
            `port`, `user`, `ready_at`, the provisioned-resource ids), the one model the
            storefront writes and the buyer reads.
          - A data migration in `utils/migrations.py` rewrites stored `connection_details`
            (escrows) and `fulfillment_resource` (listings) into that shape: `host` from
            `host_ip` where a row has one, otherwise omitted.
        - VM buyer: `buy_cli.py`'s quiet output reads `VmConnectionDetails` and prints the
          connect line when host, port, and user are all present; version bumps and
          hand-locks for the buyer and `arkhai_vms`.
        - Spec deltas, written with the audit: `physical-provisioning`'s "A create
          succeeds only with readable delivery evidence" names the create result, its
          detail, and the relay endpoint; the `vm-storefront-fulfillment` delta adds "A VM
          deal records only how to reach its VM".
        - Tests:
          - `provisioning/compute/service/tests/integration/test_job_fulfillment_migration.py`:
            - each stored shape rewritten (the states proven are those 5B.12.B.D lists);
            - a relay-backed result taking the relay's endpoint;
            - operator data kept in the detail;
            - a record with a metadata target; a blank target taken from the create job;
              the abort when neither names one;
            - a legacy prepared teardown dispatched after its create job is gone;
            - a relay port disagreeing with the leased one yielding no evidence;
            - a retried dispatch of a migrated in-flight create returning the existing
              job;
            - idempotent on a second run.
          - VM's codec on both endpoint paths, the stored tenant command agreeing with
            the endpoint, a reported relay port disagreeing with the lease, and an
            operator create keeping its projected detail.
          - `test_legacy_vm_fulfillment_backfill.py` and
            `test_fulfillment_convergence_after_legacy_backfill.py` on the new shapes;
            `unit/services/test_ansible_fulfillment_provider.py` rewritten to the plan;
            `integration/test_fulfillment_api.py`.
          - Bare metal's codec, plan, and mock-profile tests on `CreateJobResult`; the
            family kit's and contracts' tests likewise.
          - The VM storefront's `tests/fulfillment_fixtures.py`,
            `unit/test_fulfillment_provisioning.py`,
            `unit/test_fulfillment_resume_runtime.py`, `unit/test_fulfillment_service.py`,
            `unit/test_loop_gate_wiring.py`, `integration/test_committed_window.py`, and
            its data migration (integration).
          - The VM buyer's quiet output.
          - `e2e-tests/tests/unit/test_domain_deal_helper.py` and the VM scenarios
            reading delivered credentials or connection details.
        Done 2026-10-06, as amended:
        - Create results:
          - `CreateJobResult` (`compute.create-result.v1`) is every create's result, and
            `DELIVERY_EVIDENCE_RESULT_KIND` is gone.
          - The family provider fails a create without valid evidence, and exports
            `teardown_operation` for a teardown prepared without reading a job.
          - Bare metal's grant reports one, with its fact's named fields as detail.
        - VM adapter:
          - `VmFulfillmentPlan` replaces VM's provider; the provider, `VmJobSubmitter`,
            and `fulfillment_results.py` are tombstoned.
          - The operator services submit through `JobSubmissionService`, and the
            operation routes answer 404 for an unregistered host.
          - The codec reports a create as `CreateJobResult` under the relay rule (the
            leased port is authoritative), with `VM_CREATE_DETAIL` as its projected
            detail; the legacy backfill writes the family's shapes.
          - Finding fixed: a relay-backed VM had always been delivered with its KVM
            host's address and the relay's port.
          - Its `make test` now runs `test_vm_fulfillment_plan.py`.
        - Service migration `20261006_002_vm_job_backed_fulfillment`, in plain JSON (the
          boundary test admits only VM's `db` and `legacy_backfill` there).
        - VM storefront:
          - it records the delivery as `arkhai_vms.VmConnectionDetails` and stores only
            the delivered credential fields;
          - migration `20261006_011_connection_details_to_delivery` rewrites escrows and
            listings, `host` from `host_ip` or omitted.
        - VM buyer: the quiet output prints `VmConnectionDetails.connect`. The "connect"
          line never printed before; it now does.
        - Five VM scenarios' mock creates print the playbook's create fact with its
          forwarded port and time, without which a create now fails.
        - Spec deltas:
          - `physical-provisioning` removes "VM fulfillment result payload";
          - two permanent evidence lines that cited the tombstoned provider test now cite
            `test_vm_fulfillment_plan.py` (`physical-provisioning` and
            `storefront-publication`).
        - Tests:
          - new: `test_vm_fulfillment_plan.py` (16),
            `integration/test_job_fulfillment_migration.py` (7), `test_vm_codec.py`'s
            `TestCreateResult`, the contracts' create-result test, the VM storefront's
            `integration/test_connection_details_migration.py`, and `arkhai_vms`'s
            `test_connection_details.py`;
          - harnesses register their delivery hosts;
          - an operator job on an unregistered host is refused at submission;
          - `test_legacy_backfill_teardown.py` proves a persisted teardown dispatches
            with no job authority;
          - tombstoned: `test_ansible_fulfillment_provider.py` and `test_job_submitter.py`.
        - Versions:
          - contracts 0.7.0, family kit 0.17.0, service 0.15.0;
          - bare-metal adapter 0.9.0, VM adapter 0.12.0;
          - arkhai-vms 0.6.0, vms-storefront 0.12.0, vms-buyer 0.6.0;
          - e2e-tests 0.1.6;
          - floors raised to match.
        - Relocking: by `uv_project.py`, except the VM storefront, the VM buyer, and the
          bare-metal storefront, which were locked by hand. The 5B.12.A checkpoint had
          shipped the bare-metal storefront's lock with its platform markers flipped from
          the snapshot's form (same packages). This slice hand-locked it back, but the
          storefront's `make test` reinit rewrote it again before packaging, so this
          checkpoint shipped the flipped form too; 5B.12.B.D restores it.
        - Validation:
          - contracts 61; family kit 225; compute client 50; Ansible distribution 92;
          - bare-metal domain 132, adapter 39, storefront 230, buyer 13; VM adapter 22;
          - provisioning service 1119, unit and integration together;
          - VM storefront by frozen sync 1109 unit and 348 integration (the two known
            `test_alkahest` failures);
          - VM buyer 206; arkhai-vms 47;
          - e2e unit 236 (the known 10.1 failure), and 178 e2e and smoke tests collect;
          - the root `make -k test` aggregate passes its 44 suites, failing only where
            this environment cannot run a suite; the four locks its reinit rewrote were
            restored;
          - `make check-locks`, `make check-packaging`, comment hygiene, the change's
            documentation citations, and OpenSpec strict validation (1.14.0) pass.
          - Unscoped citations fail on the same 11 pre-existing references as the
            baseline.
        - End-to-end: run 37464569194, on this checkpoint, installed
          compute-provisioning-service 0.15.0, compute-provisioning 0.17.0, contracts 0.7.0,
          bare-metal adapter 0.9.0, VM adapter 0.12.0, vms-storefront 0.12.0, vms-buyer
          0.6.0, arkhai-vms 0.6.0, and e2e-tests 0.1.6. The VM lane passed 135, through this slice's delivery
          path, and the bare-metal lane 16; nothing failed or was skipped; neither lane's
          service logs show a traceback, a 5xx, a 401, or a 403, or a create failed for
          want of delivery evidence; expired leases were released.
  - [x] 5B.12.B.D Fixes from the implementation review of 5B.12.B (2026-10-06;
        `design.md`, "Implementation review of 5B.12.B").
        - Provisioning migration (`20261006_002_vm_job_backed_fulfillment`):
          - an `active` VM fulfillment aborts the migration atomically unless its create
            job exists and its result converts into valid evidence (findings 1 and 4);
          - a record naming no create job finds it by the engine's contract identity,
            rewriting its prepared parameters from the job and converting its result,
            with the metadata left empty (finding 2);
          - its evidence requires the tenant account.
        - Codecs: VM's and bare metal's SSH evidence requires a non-empty tenant account
          (finding 4).
        - VM storefront migration (`20261006_011_connection_details_to_delivery`): a
          relayed record takes its host and port from its relay record, and omits the
          host when that record lacks either (finding 3).
        - Test placement: `test_vm_fulfillment_plan.py` moved to
          `domains/vms/provisioning/adapter/tests/unit/` (the service's copy tombstoned),
          and VM's adapter target runs its own tests; the two permanent evidence lines
          follow; the service-hosted VM codec suite is routed to closeout task 2.6
          (finding 6).
        - Records: 5B.12.B's note gains its end-to-end run and corrects its lock and
          migration-state claims (finding 5).
        - Bare-metal storefront lock: back in the snapshot's marker form, hand-locked after
          the last suite run, with every lock's markers checked against the snapshot
          before packaging.
        - Tests:
          - `integration/test_job_fulfillment_migration.py` (15), proving:
            - `dispatch_pending` with no metadata and no job;
            - `dispatch_pending` with no metadata and a queued, or succeeded, old-shape
              job, found by contract and named again by a redispatch;
            - `dispatching` with metadata, and with a disagreeing relay port (no
              evidence);
            - `active` with valid evidence, and `active` with a disagreeing relay port,
              no tenant account, no result, or a missing create job, each refused;
            - a blank target from the create job, and the abort when none names one;
            - a teardown-side row's prepared teardown in the family's shape;
            - a second run changing nothing;
          - missing-account cases for both codecs;
          - the storefront migration's relayed and unprovable-relay records;
          - the migration chain's fixtures (`test_database.py`,
            `test_host_identity_migration.py`) give their active VM fulfillment a
            complete create job, since the chain now refuses one without.
        - Versions: compute-provisioning-service 0.15.1 (adapter floors 0.12.1 and 0.9.1),
          vms-provisioning-adapter 0.12.1, bare-metal-provisioning-adapter 0.9.1,
          vms-storefront 0.12.1; relocked by `uv_project.py`, and the VM storefront by
          hand.
        - Validation:
          - provisioning service 1121, unit and integration together;
          - VM adapter 22; bare-metal adapter 40;
          - contracts 61; family kit 225; compute client 50; Ansible distribution 92;
          - bare-metal domain 132, storefront 230, buyer 13; arkhai-vms 47;
          - VM storefront by frozen sync 1109 unit and 350 integration (the two known
            `test_alkahest` failures);
          - the root `make -k test` aggregate passes its 44 suites, failing only where
            this environment cannot run a suite; the four locks its reinit rewrote were
            restored;
          - `make check-locks`, `make check-packaging`, comment hygiene, the change's
            documentation citations, and OpenSpec strict validation (1.14.0) pass.
        - End-to-end: run 37471339897, on this checkpoint, installed
          compute-provisioning-service 0.15.1, vms-provisioning-adapter 0.12.1,
          bare-metal-provisioning-adapter 0.9.1, vms-storefront 0.12.1,
          compute-provisioning 0.17.0, contracts 0.7.0, vms-buyer 0.6.0, arkhai-vms 0.6.0,
          and e2e-tests 0.1.6. The VM lane passed 135 and the bare-metal lane 16; nothing
          failed or was skipped. Neither lane's logs show a traceback, a 5xx, a 401, or a
          403, or a create failed for want of delivery evidence; the only 4xx responses are
          the API-credit lane's 402s on an exhausted grant and the scenarios' 404 host checks
          before registering a host. Expired leases were released. The lanes run no active
          VM fulfillment across the provisioning migration, so its refusal of an unreadable
          active delivery is proven by the integration suite only.
  - [x] 5B.12.C Provisioning names the guest. Amended 2026-10-06 by the 5B.12.C
        implementation audit (`design.md`, "5B.12.C implementation audit (2026-10-06)").
        - VM adapter (`domains/vms/provisioning/adapter/`):
          - `services/vm_fulfillment_plan.py` names the guest: `tenant-` and the first 24
            hex characters of a UUIDv5 of the capacity reservation id, under a namespace
            the module fixes. `prepare_create` sets it as `VmJobParams.vm_target` and so
            the prepared job's `executor_target`, on the validation path too. Teardown is
            unchanged: it takes the target from the metadata.
          - `models/fulfillment_model.py`: `VmFulfillmentRequirements` loses `vm_target` and
            refuses unknown fields, so a request naming a guest is refused. Every producer
            of the request (both VM storefront builders, the e2e harness, the tests) sends
            only declared fields.
          - The name's derivation and its validation are one VM-owned helper the plan
            calls, refusing a name that breaks any rule below.
          - `iac/README.md`: `vm_target`'s description states what the name must satisfy
            (hostname label, a login of at most 32 characters once stripped to letters and
            digits, shell-safe, and not contained in another guest's name).
            `iac/ansible/roles/vm-management/tasks/vm-create.yml`: a comment at the tenant
            login's derivation states that constraint.
        - Contracts (`provisioning/compute/contracts/`): `contracts.py`'s `LeaseRegistration`
          loses `executor_target`, and its docstring says the target is the fulfillment's.
        - Family kit (`provisioning/compute/`):
          - `job_fulfillment.py` decodes a job-backed fulfillment's executor target from
            its provider metadata, over `JobFulfillmentMetadata`, refusing empty or foreign
            metadata;
          - one family operation, `executor_target_for(capacity_reservation_id)`, over the
            fulfillment kit's settlement repository and a session factory, returning the
            target of an `active` job-backed fulfillment and refusing otherwise (a module
            of its own beside `leases.py`, since 5B.12.D reuses it);
          - `leases.py`: `LeaseRouteService` takes it, and `register` records that target;
            no fulfillment, one not `active`, or no job-backed target is a 409.
            `executor_leases.py` is unchanged: the site still records a target.
        - Service (`provisioning/compute/service/`):
          - `container.py` builds the resolver over the settlement repository and session
            factory it already holds, and passes it to `LeaseRouteService`;
          - `db/migrations.py`: a migration removing `vm_target` from every VM settlement
            record's stored `fulfillment_request`, in every state, idempotent. Prepared
            operations and metadata are untouched: they keep the name a create was
            prepared with.
        - VM storefront (`domains/vms/storefront/src/market_storefront/`):
          - the three generators go: `services/vm_fulfillment_service.py` (its fulfillment
            context and request carry no target), `services/vm_job_spec_service.py` (the
            factory and the spec's target), and `services/admin_settle_service.py` (the dry
            run reports none);
          - `services/fulfillment_service.py`: `_do_provision`'s request carries no target,
            and `_register_vm_lease_with_settings` loses its target, host, and resource
            parameters;
          - the registration gates in `services/vm_fulfillment_service.py` and
            `services/fulfillment_resume_runtime.py` test the reservation and the settlement
            resource only;
          - `models/capacity_admin_models.py`'s usage-started request loses `vm_target`, and
            `controllers/admin_controller.py` stops passing it and the host, with the comment
            claiming the host is recorded;
          - `utils/migrations.py`: a data migration removing `vm_target` from every escrow's
            stored fulfillment request (`fulfillment_context`), idempotent, so a replay
            still equals provisioning's migrated copy;
          - the `compute_allocations.vm_target` column is left as it is (no code writes or
            reads it); `remove-dead-storefront-physical-surfaces` freezes that table.
        - Core: `core/storefront-client/src/storefront_client/client.py`'s
          `notify_usage_started`, async and sync, loses `vm_target`, and `evaluate_settle`'s
          docstrings stop promising one; `core/storefront/src/core_storefront/models/settle_models.py`'s
          `EvaluateSettleResponse` loses `vm_target`.
        - Bare-metal storefront: `hosted_lifecycle.py` registers without a target; it still
          loads its materialization for the evidence's `expires_at`.
        - e2e (`e2e-tests/`): stage 08a of `tests/e2e/roles/scenarios/vms/test_full_deal.py`
          and `test_non_erc20_settlement.py` stop carrying the dry run's target into the
          evaluate-job call; `tests/e2e/roles/scenarios/vms/conftest.py` loses
          `_evaluate_settle_vm_target`.
        - Spec deltas, written with the audit: `physical-provisioning`'s "Provisioning names
          what it provisions" states the name's derivation, its constraints, and the
          refusal of a request naming a guest; its "A lease's executor identity and evidence are fixed at
          registration" takes the target from the fulfillment. `vm-storefront-fulfillment`
          removes the permanent "Versioned fulfillment context", whose scenario has the
          storefront generate the target and register with it, and adds "The fulfillment
          context records the exact request, naming no guest" in its place (the validator
          refuses a modification that drops a scenario). At promotion,
          `pools-7-storefront-fulfillment-cutover`'s `design.md` promotion record links to
          the removed requirement's anchor; repoint it to the replacement.
        - Tests:
          - VM adapter, `tests/unit/test_vm_fulfillment_plan.py`: the name is stable per
            reservation and distinct across reservations, is 31 characters, is a valid
            hostname label, gives a login of at most 32 characters starting with a letter,
            and uses only shell-safe characters; a create prepared with or without
            allocation carries it; a request naming a guest is refused;
          - family kit: `tests/unit/test_lease_route_service.py` (the target from the
            resolver), `test_job_fulfillment.py` (the decoding), and the resolver against a
            real embedded database under `tests/integration/` (active, not active, no
            fulfillment, foreign metadata);
          - contracts: `tests/unit/test_contracts.py`, a registration naming a target
            refused;
          - service integration:
            - registration over a real active fulfillment records exactly its target, for
              VM and bare metal; no fulfillment, and one not yet active, are refused; a body
              naming a target is refused at the route (a rejection-path test, status only)
              (`test_leases_api.py`, `test_lease_release_api.py`,
              `test_compute_contract_api.py`); tests that only need a lease take it from
              commit;
            - the request migration (a new `integration/` test): every state's stored
              request loses `vm_target` and nothing else changes; a replayed migrated
              request for an accepted fulfillment returns it with its prepared name; a
              migrated request provisioning never accepted takes the derived name; a second
              run changes nothing;
          - VM storefront: the request the storefront sends and records names no guest;
            the context migration (integration), idempotent;
            `unit/test_fulfillment_provisioning.py`,
            `unit/test_fulfillment_resume_runtime.py` (registration with a delivery naming no
            host), `unit/test_fulfillment_service.py`,
            `unit/test_fulfill_vm_obligation_error_handling.py`,
            `unit/services/test_admin_settle_service.py`, `integration/test_settle_controller.py`,
            and `integration/test_admin_api.py`;
          - core: the storefront client's and storefront's suites run; `notify_usage_started`
            has no core test, and is exercised through the VM storefront's
            `integration/test_admin_api.py`;
          - bare-metal storefront: `tests/test_hosted_lifecycle.py`;
          - e2e: the unit suite, collection, and both lanes.
        - Versions: contracts 0.8.0, family kit 0.18.0, service 0.16.0, VM adapter 0.13.0,
          core storefront 0.9.0, core storefront client 0.24.0, VM storefront 0.13.0,
          bare-metal storefront 0.9.1, e2e-tests 0.1.7; by exact pins,
          kit-capacity-publication 0.5.1 and apicredits-storefront 0.6.2; floors on the
          contracts raised to 0.8.0 wherever a package builds or serves
          `LeaseRegistration`, and a package whose only change is a floor takes a patch
          bump. Every bump logged.
        - The wire break is accepted (audit row 8): both storefronts and provisioning move
          in this slice, and the completion note records the end-to-end run as the evidence
          that both sides moved together.
        Done 2026-10-06, as amended:
        - Naming: `vm_provisioning_adapter.guest_names` derives `tenant-` and 24 hex
          characters of a UUIDv5 of the reservation id and checks the hostname, login, and
          shell rules; the plan names every create's guest with it. VM's requirement model
          has no `vm_target` and refuses unknown fields.
        - Registration: `LeaseRegistration` has no `executor_target`.
          `FulfillmentTargets.executor_target_for` (`fulfillment_targets.py`) reads the
          target of an `active` job-backed fulfillment, through `fulfillment_executor_target`
          in `job_fulfillment.py`. `LeaseRouteService` records it, answering 404 for no
          reservation (a reservation read added to `ExecutorLeaseService`, so the 404 is not
          lost to the resolver's 409) and 409 for no target. The service's container and its
          integration harness compose the resolver.
        - Migrations: provisioning `20261006_003_vm_fulfillment_request_names_no_guest` and
          VM storefront `20261006_012_fulfillment_context_names_no_guest`.
        - Storefronts: the VM storefront's three generators are gone, its requests carry
          only `ssh_pubkey`, and registration names no target or host and is gated on the
          reservation and resource; usage-started and the settle dry run name no guest; bare
          metal registers without a target. Core's client and settle model follow.
        - e2e: stages 08a and 08c and the non-ERC-20 scenario carry no guest name, 08a
          asserting the preview names none; the scenarios' lease row reader takes the target
          from the neutral lease view rather than the ledger's stray `vm_target` key.
        - Knowledge: `domains/vms/provisioning/iac/README.md` gains "Guest names", and
          `vm-create.yml` a comment at the login's derivation.
        - Tests:
          - new: `TestGuestName` (VM adapter); `TestExecutorTarget` and
            `integration/test_fulfillment_targets.py` (family kit);
            `integration/test_vm_fulfillment_request_migration.py` (service);
            `integration/test_fulfillment_context_migration.py` (VM storefront);
          - registration over an active job-backed fulfillment, refused before activation,
            with a body naming a target refused at the route (422), and a recorded target
            other than the fulfillment's refused (409); bare metal's registration records its
            real grant's host;
          - a fresh VM acceptance takes the derived name, and a request naming a guest is
            invalid (`test_fulfillment_api.py`);
          - the storefront records, sends, and registers no guest name; resume registers a
            delivery naming no host;
          - the service's migration chain lists the new migration (`test_database.py`).
        - Versions: as planned; logged with every bump.
        - Relocking: by `uv_project.py`, except the VM storefront, the bare-metal storefront,
          and the API-credit storefront, which were hand-locked from their snapshot form.
          A relock flips the API-credit storefront's platform markers as it does the
          bare-metal storefront's; it joins the hand-locked set. Every lock's markers were
          checked against the snapshot before packaging.
        - Validation:
          - contracts 61; family kit 238; compute client 50; VM adapter 27; bare-metal
            adapter 40;
          - provisioning service 682 unit and 451 integration;
          - bare-metal storefront 230; core storefront 182; core storefront client 44;
            capacity publication 66;
          - VM storefront by frozen sync 1110 unit and 353 integration (the two known
            `test_alkahest` failures);
          - e2e unit 236 (the known 10.1 failure), and 178 e2e and smoke tests collect;
          - the root `make -k test` aggregate passes its 44 suites, failing only where this
            environment cannot run a suite; the three locks its reinit rewrote were restored;
          - `make check-locks`, `make check-packaging`, comment hygiene, the change's
            documentation citations, and OpenSpec strict validation (1.14.0) pass.
        - End-to-end: run 37581956819, on the 5B.12.D checkpoint that carries this slice;
          see 5B.12.D's note.
  - [x] 5B.12.D Lease registration removed. The gate was decided on 2026-10-06
        (`design.md`, "5B.12.D decision gate (2026-10-06)"): a lease with no negotiated
        start begins at commit, for every domain; the storefront owns the rule as policy,
        and only "at commit" is built; commit records the deal's escrow where a hold lacks
        one; provisioning records the target when a fulfillment becomes active.
        - Site (`kit/site/src/market_site/`):
          - `ledger.py`: `commit` is write-once (a repeat on a leased reservation returns it
            unchanged, whatever window it names) and takes the deal's correlation,
            recording an escrow the reservation lacks; `attach_lease` and the registration
            refusal set give way to an in-session write of the executor target, like
            `record_create_handle_in_session`, which records a target where none is,
            skips a terminal reservation, and keeps a different recorded target (as built;
            the activation's handling of a failed write is amended by 5B.12.D.D);
          - `authority.py`: the registration port goes; `router.py` and `http_models.py`:
            commit's request carries the deal's correlation.
        - Commit's other layers carry the correlation: `kit/site-client`,
          `kit/capacity-publication` (`capacity.py`), and `core/storefront` (`capacity.py`,
          `aggregation.py`), and the bare-metal storefront's `site_clients.py`.
        - Contracts and client: `LeaseRegistration` and its exports go;
          `ComputeProvisioningClient.register_lease` goes.
        - Family kit (`provisioning/compute/src/compute_provisioning/`): `leases.py` loses
          `register`; `executor_leases.py` loses `ExecutorLeaseRegistration` and
          `register_lease`; `fulfillment_targets.py` goes, its decoder
          (`job_fulfillment.fulfillment_executor_target`) staying.
        - Service (`provisioning/compute/service/`): `controllers/leases_controller.py`
          loses the registration route; `services/fulfillment_convergence.py`'s
          `_apply_create_success` records the target in its transaction; `container.py`
          and the integration harness drop the resolver; `db/migrations.py` records the
          target for every active job-backed fulfillment whose reservation has none.
        - VM storefront: `services/fulfillment_service.py` loses
          `_register_vm_lease_with_settings`; `services/vm_fulfillment_service.py` loses
          the post-provision commit, the registration step and its deferral, passing the
          escrow at its pre-provision commits; `services/fulfillment_resume_runtime.py`
          loses its re-commit and registration steps, keeping evidence publication.
        - Bare-metal storefront: `hosted_lifecycle.py` loses its registration and takes its
          materialization's window from the reservation commit returned;
          `fulfillment_service.py`'s evidence `expires_at` follows.
        - e2e: scenarios that waited on registration read the lease the activation recorded.
        - Specs: the permanent requirements describing registration, commit's refresh, and
          VM's post-delivery commit are modified or removed by the deltas; `grep` finds them
          in `compute-provisioning-contract`, `physical-provisioning`, `site-capacity`,
          `vm-storefront-fulfillment`, and `storefront-publication`, and in the companions
          of `physical-provisioning`, `fulfillment`, and `settlement-servicing`. Each
          match is read, since several capabilities use "register" in other senses.
        - Tests: commit write-once and its escrow rule (site); the target recorded at
          activation, in the same transaction, refused where a different target is recorded
          (service integration); the migration; both storefronts with no registration, VM's
          window from settlement, bare metal's evidence carrying the site's window; the
          registration route's absence.
        - Closeout: the 2.6 finding about a commit re-recording a truncated window is
          retired; 2.6 records the deferred "on activation" start rule, as storefront policy
          with an optional pool listing hint, as an open gap.
        - The exact file list is re-read against the code when D starts, as for every slice.
        Done 2026-10-06, as planned, with these findings from re-reading the code:
        - The VM resume pass never committed a recovered deal's reservation before its
          fulfillment began; the post-delivery refresh committed it first. Under the
          decision that commit is now made before the fulfillment begins
          (`_commit_recovered_reservation`), and a reservation committed earlier keeps
          its first window.
        - Bare metal's escrow-based path (`fulfillment_service.py`) reserved but never
          committed, leaving a `reserved` reservation the watchdog never expires. It now
          commits with the deal's escrow before the fulfillment begins. Both bare-metal
          paths commit until the fulfillment begins and take their window from what
          commit returns (`lease_window.py`); a saved materialization keeps its window,
          since it is the fulfillment request and a retry repeats it exactly.
        - The activation write is best-effort, as the create handle is, not a refusal: it
          records a target where none is, skips terminal reservations, and keeps a
          different recorded target with a warning, because activation must not fail a
          running workload and teardown addresses the fulfillment's own metadata.
          Convergence takes the ledger as an optional collaborator, as the fulfillment
          kit's transaction does; production and the integration harness pass it.
        - The family's route-contract table (`routes.py`) declared the registration route
          and goes with it.
        - Two closeout findings routed to 2.6: no production path writes `executor_ref`
          any more; an authenticated request matching no route contract answers 500.
        - Files beyond the plan's list: the contracts' `routes.py`; bare metal's
          `site_clients.py` and new `lease_window.py`; the VM storefront's test fake site,
          now write-once; e2e's lease checks, renamed from "registered" to "recorded".
        - Tests:
          - site: the activation write (once, moving nothing, none on a terminal
            reservation, rolled back with its caller); commit records the escrow once,
            on a repeat too; a repeat commit never moves the window, even after a
            truncation;
          - service: convergence records the target through the activation's own session
            (the record already reads `active` through it), and a ledger error, foreign
            metadata, or a different recorded target never fails activation; bare metal's
            lease reports its machine after real convergence; no route writes a lease; a
            hold is found by the escrow its commit recorded, over the wire; the migration;
          - VM storefront: the foreground path commits once, before provisioning, with
            the escrow, and writes nothing after; the resume pass commits before beginning
            a recovered fulfillment; a resumed deal never moves its lease, through the
            real capacity runtime;
          - bare metal: the escrow path's retry commits with the escrow and states the
            first commit's window; access readiness writes no lease. The hosted path's
            commit-then-materialize has no unit test, the existing tests stubbing its
            physical steps: the bare-metal end-to-end lane proves it;
          - core: the aggregate passes the deal to the owning site.
        - Spec deltas: `physical-provisioning` rewrites the lease-tail requirement ("fixed
          once recorded"), adds "A committed allocation's lease records its executor
          target" in place of the removed "Allocation-backed executor registration", and
          removes "Lease registration tolerates omitted identity hints";
          `site-capacity` rewrites both of its lease requirements ("Commit begins a lease
          once and never resurrects one"); `compute-provisioning-contract` modifies
          "Allocation-backed lease control"; `vm-storefront-fulfillment` rewrites its
          deferral requirement and modifies "Full settlement convergence ownership";
          `storefront-publication`'s bare-metal lifecycle scenario says the commit begins
          the lease. The proposal and the promotion record follow.
        - Versions: kit-site 0.10.0, kit-site-client 0.9.0, core storefront 0.10.0,
          capacity publication 0.6.0, contracts 0.9.0, compute client 0.6.0, family kit
          0.19.0, service 0.17.0, VM storefront 0.14.0, bare-metal storefront 0.10.0,
          e2e-tests 0.1.8; by exact pins, apicredits-storefront 0.6.3. Every bump logged.
        - Validation:
          - kit-site 281; site client 48; core storefront 182; capacity publication 66;
            contracts 60; family kit 222; compute client 46;
          - provisioning service 677 unit and 451 integration;
          - bare-metal storefront 230;
          - VM storefront by frozen sync 1102 unit and 353 integration (the two known
            `test_alkahest` failures);
          - e2e unit 236 (the known 10.1 failure), and 178 e2e and smoke tests collect;
          - the root `make -k test` aggregate passes its 44 suites, failing only where this
            environment cannot run a suite; its run caught the compute client's signing
            test still listing the registration route, fixed and rerun (46); the locks its
            reinit rewrote were restored, and the bare-metal and API-credit storefronts
            re-hand-locked from their snapshot form;
          - `make check-locks`, `make check-packaging`, comment hygiene, the change's
            documentation citations, and OpenSpec strict validation (1.14.0) pass.
        - End-to-end: run 37581956819, on this checkpoint (5B.12.C and 5B.12.D together),
          installed compute-provisioning-service 0.17.0, compute-provisioning 0.19.0,
          contracts 0.9.0, compute client 0.6.0, vms-provisioning-adapter 0.13.0,
          bare-metal-provisioning-adapter 0.9.1, vms-storefront 0.14.0,
          bare-metal-storefront 0.10.0, kit-site 0.10.0, kit-site-client 0.9.0, core
          storefront 0.10.0, and e2e-tests 0.1.8. The VM lane passed 135 and the bare-metal
          lane 16; nothing failed or was skipped. Neither lane's logs show a traceback, a
          5xx, a 401, or a 403, and no request reached the removed registration route; the
          4xx responses are the API-credit lane's 402s on an exhausted grant, scenarios'
          404 checks for pools and listings before creating them, and the bare-metal
          introduction scenario's 410s once an operator deleted the payloads. Stage 09c
          found both full deals' leases by their escrow, active, which an acceptance hold
          learns only at commit now. Expired leases were released. Both storefronts and
          provisioning moved together, as the accepted wire break requires. The bare-metal
          lane is the only exercise of the hosted path's commit-then-materialize.
  - [x] 5B.12.D.D Fixes from the implementation review of 5B.12.C and 5B.12.D (2026-10-07;
        `design.md`, "Implementation review of 5B.12.C and 5B.12.D").
        - Lease targets (finding 1), in the provisioning service's
          `services/fulfillment_convergence.py`:
          - `_record_executor_target` catches only `ProviderConfigInvalidError` and
            `CapacityConflictError`, which keep the activation and are logged; any other
            failure escapes, the activation rolls back, and `_converge_create_record`'s
            retry leaves the record `dispatching` for the next cycle;
          - `run_cycle` ends with a sweep (`reconcile_lease_targets`): in one write
            transaction, the active fulfillments on non-terminal reservations, joined to
            their reservations; each whose reservation records no target is recorded
            through `record_executor_target_in_session` where it now succeeds; the cycle's
            diagnostics log event gains counts of targets repaired, of those it could not
            record by reason, and of reservations recording a different target, never
            overwritten. A composition with no ledger sweeps nothing.
        - Guest name (finding 2): `domains/vms/provisioning/adapter/tests/unit/test_vm_fulfillment_plan.py`
          pins `fulfillment_guest_name("alloc-1") == "tenant-ea780533c5915a9b85ba26b9"`.
        - Deltas (finding 3), written with this plan: `physical-provisioning`'s "Leases have one family surface
          that records and releases" lists get, list, terminate, and the release controls,
          its bare-metal scenario has the target recorded at activation, and the admin-route
          scenario's example becomes lease termination; "A lease's executor identity and
          evidence are fixed once recorded" states finding 1's rule (a data failure keeps
          the activation, any other failure retries it, and convergence keeps recording
          a missing target and reports what it cannot); `site-capacity` says "once
          committed". 5B.12.D's task text states the write as built.
        - Escrow (finding 4): the VM storefront's
          `controllers/admin_controller.py` fulfillment-failed handler takes the request's
          escrow, else the reservation's `escrow_uid`, else its `deal_ref`'s.
        - Closeout task 2.6 gains: the fulfillment-failed callback has no production
          sender; a deliberate operation to resolve a reservation whose recorded target
          differs from its fulfillment's is needed once anything acts on the site's
          target.
        - Tests:
          - service integration (`tests/integration/test_fulfillment_convergence.py`,
            over the settlement database and a ledger stand-in, as 5B.12.D's activation
            tests):
            - a ledger failure other than a data error leaves the record `dispatching`
              and records nothing; the next cycle activates it and records the target;
            - a data error keeps the activation;
          - service integration against the real site ledger (a new
            `tests/integration/test_lease_target_reconciliation.py`, both kits' tables in
            one SQLite database): an active fulfillment whose reservation records no
            target is repaired by the sweep; a second sweep changes nothing; a different
            recorded target is never overwritten and is counted; a fulfillment whose
            target cannot be recorded is counted by reason; a terminal reservation and a
            fulfillment that is not active are left alone;
          - VM adapter: the fixed vector;
          - VM storefront (`tests/integration/test_admin_api.py`): a fulfillment-failed
            callback naming no escrow, on a hold whose commit recorded one, reaches the
            failure policy with that escrow.
        - Versions: compute-provisioning-service 0.17.1 and vms-storefront 0.14.1; no
          other package changes behaviour.
        - Validation: the provisioning service, the VM adapter, the VM storefront by
          frozen sync, the root aggregate, `make check-packaging`, comment hygiene,
          citations, OpenSpec, and both end-to-end lanes.
        Done 2026-10-07, as planned:
        - The sweep's counts join the cycle's `fulfillment_recovery_diagnostics` log event
          as `lease_targets`; a sweep that raises is logged and does not stop the cycle.
          A reservation the sweep finds missing for an active fulfillment counts as
          `no_reservation`, so the outer join keeps such fulfillments in the report.
        - The retry test expires the record's claim rather than waiting for its backoff.
        - The fulfillment-failed test stands in for the failure policy to observe the
          escrow it receives.
        - Beyond the plan: `e2e-tests`' lock, which pins the VM storefront's wheel, was
          relocked.
        - Validation:
          - VM adapter 28; provisioning service 677 unit and 456 integration;
          - VM storefront by frozen sync 1102 unit and 354 integration (the two known
            `test_alkahest` failures);
          - the root `make -k test` aggregate passes its 44 suites, failing only where this
            environment cannot run a suite; the locks its reinit rewrote were restored,
            and the bare-metal and API-credit storefronts re-hand-locked from their
            snapshot form, every lock's markers matching the snapshot;
          - `make check-locks`, `make check-packaging`, comment hygiene, the change's
            documentation citations, and OpenSpec strict validation (1.14.0) pass.
        - Not yet run end to end.
  - Each slice's gate: the provisioning-family suites, both adapters, both storefronts (the
    VM storefront by frozen sync), the e2e unit suite and collection, the root aggregate,
    `make check-packaging`, comment hygiene, documentation citations, OpenSpec strict
    validation (1.14.0), and both end-to-end lanes. Versions per slice, recorded in its
    completion note.

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
      registers the lease once fulfillment is active, as `hosted_lifecycle.py` does since
      5B.8.B.8 (the machine as executor target; the site keeps the committed window, so
      the registration need name none); `site_clients.py`'s
      `SelectedSiteFulfillmentClient`, which gained `register_lease` in 5B.8.B.8, gains
      `terminate_lease` and `get_lease` over `compute_provisioning_client`, routed by the
      reservation's recorded site. Once both settlement paths register, the family lease
      reads should count only registered leases (an executor target recorded), not every
      reservation with a lease end (implementation review of slice B, finding 2).
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
      aggregate's state, and that capacity is freed only behind the release guard the
      provisioning composition supplies to the site authority. The route-contract section was promoted during design.
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
- [ ] 2.0 **Published dependency graph.** Ruled at the A0 checkpoint review (`design.md`,
      "Findings recorded for closeout"): before closeout, every package
      `.github/workflows/publish-pypi.yml` publishes must depend only on published packages.
      Enumerate the published packages' internal dependency closure, add each unpublished
      member (the four thin packages from 5B.8.A0 among them) to the workflow's `PACKAGES`
      table and path filters and to `docs/development/RELEASING.md`'s table, and list for the
      maintainer the trusted-publisher setup each new package needs before its first release.
      A check that fails when a published package depends on an unpublished one belongs beside
      the workflow, if it can run without network access.
- [ ] 2.2 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration. Relock with `scripts/uv_project.py lock` the projects whose locks
      could not be regenerated in the implementation environment (the PyTorch index refused
      access): `domains/vms/storefront` and `domains/vms/buyer`, whose locks were hand-edited
      and are unverified by a real relock, and `kit/policy`; confirm each relock produces no
      diff, or commit the diff it produces.
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
      state, path templates in the family contracts, the uncalled
      `find_active_lease_by_vm_target` and the `vm_target` key the site ledger's
      reservation payload still emits for VM reservations). The VM storefront's dead `schedule_shutdown` hook,
      first recorded here, was routed on 2026-10-05 to
      `remove-dead-storefront-physical-surfaces` task 3.8, and removed by 5B.8.C.6 on the
      maintainer's ruling at the slice C design review; that task is marked delivered.
      Found in 5B.12.D: no production path writes a reservation's `executor_ref` any
      more (only registration did, and since 5B.12.C no storefront sent one), so the
      column and `find_active_lease_by_vm_target`'s match on it are dead; and the
      provisioning service's authentication middleware raises on an authenticated
      request whose method and path match no route contract, so such a request answers
      500 rather than 404 or 405.
      Found in the review of 5B.12.C and 5B.12.D: the VM storefront's fulfillment-failed
      callback has no production sender, as usage-started has none; decide whether the
      route stays. Nothing acts on a reservation's recorded executor target today; should
      something come to (reclaiming by target, or `find_active_lease_by_vm_target`), a
      deliberate operation to resolve a reservation whose recorded target differs from
      its fulfillment's is needed with it, since convergence only reports that case.
      Found at 5B.12.D's gate: a storefront's rule for when a lease with no negotiated
      start begins, set as storefront policy like its service agreements, with an optional
      pool listing hint taking second place; only "at commit" exists, and "on activation"
      would be carried out by provisioning in the activation transaction (`design.md`,
      "5B.12.D decision gate (2026-10-06)", row 2). Record it as an open gap tied to
      capacity-reservation pricing.
      Found in 5B.10.D: the relay administration, port allocator, port lease, and
      pool-configuration suites are integration tests in the service's suite; they test
      VM-owned behavior and belong in VM's adapter, with schema fixtures of VM's own
      rather than the service's migrations. Found in 5B.12.B's implementation review: so
      does the service-hosted VM codec suite,
      `provisioning/compute/service/tests/unit/services/test_vm_codec.py`.
      Found in 5B.12's design review: every VM guest attaches to libvirt's `default` NAT
      network, one bridge per host, with no isolation rule, so guests on one host,
      including different buyers', share a layer-2 segment; route to VM's provisioning
      owner.
      Found in 5B.12's implementation audit (`design.md`, "5B.12 implementation audit
      (2026-10-06)", rows 6 and 9): the site ledger keys reservation idempotency and
      release-by-escrow on the escrow, a settlement identity hosted deals lack, while jobs
      now correlate on the capacity reservation; weigh the site's storefront-facing
      correlation the same way. And what a storefront keeps of a delivery, and when it
      stops serving it, differs by domain with no domain requiring it: the VM storefront
      stores the endpoint in its escrow record and on its listing and submits it with an
      Alkahest fulfillment, while bare metal serves it live through `/access`. Open a
      change at closeout, under Goal 4 ("Make a domain a composition of kit"), to make it
      one kit mechanism.
      Found in 5B.12.C's audit (rows 6 and 10): the VM storefront's admin usage-started
      event has no production sender and records nothing of its `host_id`; decide whether
      the route stays, and drop the field either way. VM's operator `create_vm` route checks
      no guest name against the rules provisioning's own names satisfy, so an operator's
      name whose login exceeds 32 characters fails at `useradd`; check it at the route.
      Found in 5B.12.B's audit (row 7): no end-to-end lane runs a relay-backed pool, which
      is why a relay-backed VM's wrong delivered address went unnoticed; add a VM lane
      scenario with a relay.
      Found in 5B.12.A: site admission and settlement scheduling never read a host
      record's enabled flag, so a create can be admitted and placed on a disabled host,
      and its dispatch then retries until an operator re-enables the host. Disabling a host
      should keep new deliveries off it at admission.
      Found in 5B.10: this change's 19 delta requirements over 500 characters, which
      the validator release after the pinned one fails under `--strict`, are restructured
      here (moving examples and edge cases into scenarios, or splitting) before promotion.
      Found in 5B.10: the provisioning integration harness runs every session on one
      shared in-memory SQLite connection (`StaticPool`), so a job the bare-metal `begin`
      dispatches can end the transaction the authentication middleware is about to
      commit; `test_a_bare_metal_lease_is_registered_on_the_family_surface` failed once
      that way ("cannot commit - no transaction is active") and passed on every rerun;
      in 5B.10.D, `test_a_release_is_durable_before_teardown_and_a_restart_resumes_it`
      failed the same way once, in the authentication middleware's replay-record commit
      during a bare-metal `begin`, and passed on the rerun.
      Production uses a file database with a connection per session. The harness needs
      the same, or an equivalent that gives each session its own connection.
      Found in slice C: the system worker controls' response bodies are untyped dicts
      (review point 3), and `openspec/specs/site-capacity/spec.md`'s evidence line for
      the pool-metadata provider gate should cite
      `provisioning/compute/service/tests/unit/services/test_vm_inventory_views.py`,
      where that test now lives, at promotion.
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
| No caller writes a lease: commit begins it, once, recording its window and the deal's escrow; provisioning records its executor target when the fulfillment becomes active, in that transaction; its end moves only through site truncation; `commit` refuses the lifecycle's states | `openspec/specs/physical-provisioning/spec.md` — "A lease's executor identity and evidence are fixed once recorded", "A committed allocation's lease records its executor target"; `openspec/specs/site-capacity/spec.md` — "A reservation's lease tail is written once", "Commit begins a lease once and never resurrects one", "Lease truncation neither resurrects nor extends a lease"; `openspec/specs/compute-provisioning-contract/spec.md` — "Allocation-backed lease control"; `openspec/specs/vm-storefront-fulfillment/spec.md` — "Full settlement convergence ownership" |
| The lease lifecycle is mode-agnostic: one provider-neutral release executor and status port | `openspec/specs/physical-provisioning/spec.md` — "Executor-dispatched lifecycle", "Site-backed release lifecycle", "Lease release delegates to durable fulfillment teardown"; `docs/development/ARCHITECTURE.md` "Release" |
| Every provisioning route admits the administrator (a repository-wide stance applied to this service) | `openspec/specs/physical-provisioning/spec.md` — "Every provisioning route admits the administrator"; `docs/development/ROADMAP.md` (the repository-wide gap) |
| The composition root builds the one job authority and the one host authority | `openspec/specs/physical-provisioning/spec.md` — "Compute provisioning owns the job and host authorities"; `docs/development/ARCHITECTURE.md` "Family kits" |
| Execution readiness is part of system status; connectivity is probed by connection kind | `openspec/specs/physical-provisioning/spec.md` — "Execution readiness is reported in system status", "Host connectivity is probed by connection kind" |
| The family's wire contract and client are thin distributions; VM keeps an extension client | `openspec/specs/physical-provisioning/spec.md` — "Compute-owned caller contract"; `docs/development/ARCHITECTURE.md` "Family kits" compute example |
| `VersionedEnvelope` lives in `arkhai-core` | `openspec/specs/fulfillment/spec.md` — "Versioned envelopes"; `docs/development/ARCHITECTURE.md` (the fulfillment kit's carrier modules) |
| Delivery happens only through fulfillment; the executor-action submission is removed | `openspec/specs/physical-provisioning/spec.md` — "Delivery happens only through fulfillment", "Validated executor registration"; `openspec/specs/compute-provisioning-contract/spec.md` (the removed requirement and the purpose statement) |
| An undelivered lease is released by what its fulfillment proves; an uncommitted hold is released, not truncated | `openspec/specs/physical-provisioning/spec.md` — "An undelivered lease is released by what its fulfillment proves"; `openspec/specs/site-capacity/spec.md` — "Lease truncation neither resurrects nor extends a lease" |
| Release follows every fulfillment aggregate state; capacity is freed only behind a composition-supplied release guard, which replaces the settlement-abandonment hook | `openspec/specs/physical-provisioning/spec.md` — "An undelivered lease is released by what its fulfillment proves"; `openspec/specs/site-capacity/spec.md` — "Reservation supersede and the release guard"; `docs/development/ARCHITECTURE.md` "Release" |
| Host import belongs to the implementation that reads its format | `openspec/specs/physical-provisioning/spec.md` — "Host import belongs to the execution implementation that reads its format" |
| Resource pools and capacity definitions keep thin surfaces of their own | `openspec/specs/resource-pool-management/spec.md` — "The pool wire contract and client are thin distributions"; `openspec/specs/site-capacity/spec.md` — "Capacity-definition import has a thin typed client"; `docs/development/ARCHITECTURE.md` kit layers |
| Provisioning names the VM guest from the capacity reservation, a name the playbooks can use as hostname, tenant login (at most 32 characters), and `/tmp` match; the lease's target is the one the fulfillment recorded | `openspec/specs/physical-provisioning/spec.md` — "Provisioning names what it provisions", "A lease's executor identity and evidence are fixed at registration"; `openspec/specs/physical-provisioning/architecture.md` — the guest-name constraints and why they bind (at promotion); `openspec/specs/vm-storefront-fulfillment/spec.md` — "The fulfillment context records the exact request, naming no guest"; `domains/vms/provisioning/iac/README.md` (with 5B.12.C) |
| Findings recorded under "Controls and routes (5B.8)" | `docs/development/ROADMAP.md` or the change index, at closeout |
| Scope migrations, the real-host scenario's disposition, and why the scenario uses typed clients | This change's `design.md` |
