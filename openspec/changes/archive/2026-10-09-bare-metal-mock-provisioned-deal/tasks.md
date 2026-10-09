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
      and integration suites, and the permanent documentation destinations, ordered so
      every lane stays green at each step. Planned as Sections 4–11. The planning checks
      (generic lease routes for bare-metal reservations, the identity overlay split,
      `multi_registry`'s registry use) and one new finding (the Alkahest path never
      commits or registers its lease) are recorded in `design.md`.
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
      pipeline run and shared ("Lanes run on images built once"). Superseded 2026-10-09
      ("Section 10 design: each lane builds and composes its own stack", decision 1):
      each lane builds the images its stack runs.
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
      delivery crosses it; the kit settlement-servicing worker starts and retries
      bare-metal fulfillment. Sections 4–7 were replanned, each ending at its own gate,
      after verifying the premises against code (composition already refused duplicate
      keys; the worker needed `service_obligation`; VM and API credits hold only at
      acceptance; `preview_opening` can stop before `start`'s first write).
- [x] 1.17 **Decision gate.** Resolve the 2026-10-02 implementation and layering reviews.
      Decided with the maintainer: provisioning execution leaves the VM adapter into
      `compute_provisioning` and an Ansible family-kit distribution, with domains
      contributing codecs, playbooks, preparation, and result meaning; no adapter imports
      another adapter or the deployed service; relays and VM pool configuration stay VM's;
      the fulfillment-provider helper is deferred (timed by 1.19).
      The review's Section 4–5 fixes are accepted ("Implementation-review fixes for
      Sections 4–5"). Planned as Sections 5A and 5B.
- [x] 1.18 **Decision gate.** Define the layer `compute_provisioning` belongs to. Decided
      with the maintainer: a family kit ("Compute provisioning is a family kit"),
      promoted to `ARCHITECTURE.md` in 11.1.
- [x] 1.19 **Decision gate.** Confirm the Ansible distribution and the fulfillment-provider
      helper's timing. Decided with the maintainer: the Ansible mechanics are a sibling
      family-kit distribution, `provisioning/compute/ansible`; the job-backed
      fulfillment-provider helper lands in this change as 5B.12, after the boundary is
      proven ("Compute provisioning is a family kit").

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
- [x] 3.5 **Restart recovery.** (Closed by 9.0c.) Bare-metal storefront integration tests rebuild the
      application over the same database file and a fake site after settlement commit
      and after teardown acceptance; the buyer retrieves the same operation with no
      second obligation, mechanism selection, or teardown, and duplicate polling and
      result reads are idempotent. Planned in 7.7.
- [x] 3.6 **Withdrawn** 2026-10-07 (`design.md`, "Section 6 design: bare metal on the
      negotiation runtime (2026-10-07)", decision 4): the trading pause is process-local
      in every storefront, so nothing requires it to survive a restart, and its scenario
      is dropped from the `test-compatibility` delta.

## 4. Executor selection and the compute mock mechanism

Decision: "Executors are selected by offering mode and action, and each adapter owns its
mock". Reviewable alone: provisioning only, no storefront or scenario change. Sections 4
and 5 are reshaped by 5B; their notes below record what each step built at the time.

- [x] 4.1 Extend composition with job executors keyed by `(offering_mode, action)` under
      the same duplicate refusal as contract actions; the `JobExecutorResolver` protocol
      in `provisioning/compute/src/compute_provisioning/adapters.py`. As built, the
      contribution carries one `JobExecution` per action, and `JobExecutorTable` refuses to
      resolve before composition freezes it. Tests in
      `provisioning/compute/service/tests/unit/test_composition.py`.
- [x] 4.2 Add `compute_provisioning/executor_mock.py`: the rule model, store, and matching,
      pause gates, the evaluate-job dry run, and a framework-free route service, extracted
      from VM's mock. Tests in `provisioning/compute/tests/unit/test_executor_mock.py`;
      VM-output cases stay in `test_programmable_mock.py`.
- [x] 4.3 VM's job service selects each job's executor and playbook from its persisted
      `offering_mode` and action; the `bare_metal` playbook special case and
      `_BARE_METAL_ACTIONS` are removed. Tests in
      `provisioning/compute/service/tests/unit/services/test_job_service.py`.
- [x] 4.4 Rebuild VM's mock on the mechanism, binding its route service at the unchanged
      `/test/mock-rules` paths;
      `provisioning/compute/service/tests/integration/test_test_controller.py`
      passes unchanged.
- [x] 4.5 Add the bare-metal mock (`bare_metal_mock_executor.py`, its own rule store and
      bare-metal default output: `node_grant_access_data` and `node_reclaim_access_data`),
      registered for `(bare_metal, NODE_GRANT_ACCESS_ACTION)` and
      `(bare_metal, NODE_RECLAIM_ACCESS_ACTION)`, with its rules at
      `/test/bare-metal/mock-rules`. Tests in
      `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_mock_executor.py`
      parse its output through the real parser and result payload (not
      `fetch_credentials`, added by 5A.4); a bare-metal rule never matches a VM job and the
      reverse. Replaced by 5B.7.
- [x] 4.6 Compose it: `container.py` builds the table from both bundles; `main.py` mounts
      the bare-metal test router under the mock profile; readiness reports each offering
      mode's executor mode. Integration test
      `provisioning/compute/service/tests/integration/test_bare_metal_mock_profile.py`
      registers a bare-metal lease and proves its grant job runs through the bare-metal
      mock, held and released by a bare-metal rule, failed by another, with an unknown
      rule's resume refused. Convergence and reclaim are the Section 9 scenario's.
- [x] 4.7 Typed clients: route contracts for `/test/bare-metal/mock-rules*` and the
      bare-metal rule methods on `e2e-tests/src/e2e_harness/provisioning_test_client.py`.
      Endpoint coverage in
      `provisioning/compute/service/tests/integration/test_provisioning_client_endpoint_coverage.py`
      was added by 5A.4.
- [x] 4.8 **Gate.** Relock the changed projects (`make lock PROJECTS=...` for
      `provisioning/compute`, `provisioning/compute/service`, and both adapters); the
      provisioning, provisioning-service, and both adapters' suites pass; the VM lane
      passes unchanged.
      Local part done 2026-10-01 (the four suites and `make check-packaging` pass).
      Closed 2026-10-07: run 101918963768 passed the VM lane (135).
- **Section 4 implementation notes (2026-10-01).** `domains/vms/storefront/uv.lock`
  could not be resolved in the implementing environment (PyTorch index); its internal
  entry was set by hand to what the other relocks produced (closeout task 2.2). A
  baseline failure in the hosted public-boundary unit test (removed with hosted
  settlement by `settle-through-arkhai-payments`) is 10.1's.

## 5. Negotiation runtime operations and deal-control route services

Decisions: "Deal controls are kit-owned route services", "Administrative acceptance goes
through the runtime", "Evaluate-negotiate previews the real opening". Reviewable alone:
kits, core, and the VM and API-credit storefronts; bare metal binds in Sections 6–7.

- [x] 5.1 `kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py`: add
      `accept_administratively` (the administrator's amount and message through the domain
      hooks and `_commit_acceptance`) and `preview_opening` (`start`'s checks, evaluation,
      terms, and artifacts, factored into one function `start` also calls, stopping before
      the first write). Unit tests in
      `kit/negotiation-runtime/tests/unit/test_administrative_acceptance.py` and
      `test_opening_preview.py`: hooks run on administrative acceptance; preview refuses
      every opening `start` refuses and writes nothing.
- [x] 5.2 `kit/storefront/src/market_storefront_kit/deal_control_routes.py`: the
      stage-event read, evaluate-negotiate over `preview_opening`, and force-accept over
      `accept_administratively`. Unit tests in
      `kit/storefront/tests/unit/test_deal_control_routes.py`.
- [x] 5.3 `kit/settlement-runtime/src/market_settlement_runtime/servicing.py`:
      `SettlementServicingWorker.service_obligation(obligation_ref)`, the per-record body
      of `run_once`. `admin_routes.py`: settle verify, evaluate-settle over a
      `FulfillmentPreviewHook` port, and settle wait as a bounded long-poll. Unit tests in
      `kit/settlement-runtime/tests/unit/test_admin_routes.py` and `test_servicing.py`
      (immediate start, retry of a failed start by the worker's schedule, refusal of an
      unknown obligation; the concurrent-pass case is 5A.5's).
- [x] 5.4 `kit/capacity-publication/src/market_capacity_publication/admin_routes.py`:
      admin reserve through a listing's capacity binding, and the capacity-released
      callback dispatching to an injected domain release hook. Unit tests in
      `kit/capacity-publication/tests/unit/test_admin_routes.py`.
- [x] 5.5 Wire models and client: `EvaluateNegotiateRequest` becomes the opening request
      and the response reports refusals before policy; both `evaluate_negotiate` client
      variants take it; every caller sends the opening body
      (`domains/vms/storefront/tests/integration/test_listings_api.py`,
      `test_publication_loop.py`, and e2e `scenarios/vms/test_full_deal_buyer_cli.py` and
      `test_non_erc20_settlement.py`; `test_full_deal.py` in 5.10).
- [x] 5.6 Prove the hold path after force-accept (VM's and API credits' holds run only at
      acceptance). VM's test
      (`domains/vms/storefront/tests/integration/test_negotiations_api.py`) proves the
      settlement plan, terminal state, and the hold's reservation request at the site.
      API credits
      deliberately grants no unfunded quota hold; its test proves force-accept records
      what a negotiated acceptance records — credit terms, agreed price, and no hold. The
      successful path through `StorefrontClient` is 5A.1's.
- [x] 5.7 Rebind VM: events, evaluate-negotiate over the preview, force-accept, settle
      verify, evaluate, and wait, and admin reserve and capacity-released through the kit
      route services; VM's evaluate-settle job-spec build becomes its
      `FulfillmentPreviewHook`; `ListingService.evaluate_negotiate` is removed.
- [x] 5.8 Rebind API credits: events, force-accept, and settle wait.
- [x] 5.9 Remove `NegotiationService.force_accept` from
      `core/storefront/src/core_storefront/services/negotiation_service.py`, and its cases
      from `domains/vms/storefront/tests/unit/services/test_negotiation_service.py`;
      `test_negotiations_api.py` covers force-accept through the route service.
- [x] 5.10 VM's stage 05a in `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py`
      sends the opening request it later sends to `negotiate_new`.
- [x] 5.11 **Gate.** Bump and relock the changed kits, core packages, and consumers; the
      kit, core, VM storefront, and API-credit storefront suites pass; the VM lane passes,
      including 05a on the new body and 06b with the runtime acceptance.
      Local part done 2026-10-02 (every touched suite, `make check-packaging`, and
      comment hygiene pass, apart from the pre-existing VM failures below and
      `test_alkahest.py`, which needs Node and Anvil).
      Closed 2026-10-07: run 101918963768 passed the VM lane (135), including 05a on the
      new body and 06b with the runtime acceptance.
- **Section 5 implementation notes (2026-10-02).**
  - Design-review option A ("Settlement starts fulfillment"): the kit's due-obligation
    query lists a ready obligation whose fulfillment never started.
  - Deviations: settle verify, admin reserve, and the capacity-released callback are kit
    route services over per-domain hooks, since their requests and effects are
    domain-shaped; verify and evaluate hooks are optional, so API credits binds only wait.
  - Found and fixed: API credits' force-accept called core `force_accept` without the
    administrator principal it requires and failed on every call.
  - Checkpoint 1: the e2e run failed VM stage 08a, since force-accept now places VM's
    hold and evaluate-settle probed only free capacity. Evaluate-settle now takes the
    `negotiation_id` and reports a held reservation and its host
    (`EvaluateSettleRequest.negotiation_id`, `EvaluateSettleResponse.capacity_reservation_id`).
  - Pre-existing VM failures, not caused here and not compared against a true baseline:
    `test_amountless_exact_escrow_can_start_and_accept` and
    `test_an_unbacked_listing_negotiates_to_acceptance_without_the_site` in
    `test_negotiate_controller.py`, and five term-refresh and shape-priced tests in
    `test_publication_loop.py` (publication pricing, which this change does not touch).
  - VM's `uv.lock` files were set from built wheel metadata (closeout task 2.2).

## 5A. Implementation-review fixes for Sections 4–5

Decision: "Implementation-review fixes for Sections 4–5". Reviewable alone: tests, one
client method, and the gate signal; no behaviour change. Lands before 5B so 5B moves
code that is already correctly covered.

- [x] 5A.1 Typed force-accept. VM: `TestAdministrativeAcceptance` in
      `domains/vms/storefront/tests/integration/test_negotiate_controller.py` (whose fixture
      already had the chain configuration, a fake site, and a projection-backed listing)
      force-accepts a real countered negotiation through an administrator
      `StorefrontClient`, asserting the plan, terminal state at the forced amount, and the
      hold's reservation request. API credits:
      `domains/apicredits/storefront/tests/integration/test_force_accept_api.py` drives
      force-accept, its refusals, the stage-event read, and settle wait through
      `StorefrontClient`.
      - Found and fixed: API credits' force-accept, events, and settle-wait routes
        authenticated their own route name and path rather than the contract the canonical
        client signs, so no client call could succeed; they now authenticate the client's
        operations and resources.
      - Unresolved, recorded for the maintainer's decision: API credits' advance and
        listing-administration routes keep the same mismatch, outside this change's
        controls, and the kit route services do not yet own their signed contracts.
- [x] 5A.2 Typed lease registration. Amended 2026-10-02 with the maintainer (a
      bare-metal-typed method would make the family kit depend on `arkhai_bare_metal`):
      `ComputeProvisioningClient` gains a market-neutral `authenticated_request`, and
      `domains/bare_metal/src/arkhai_bare_metal/provisioning_client.py` adds
      `BareMetalLeaseClient` over any transport offering it, with unit tests in
      `domains/bare_metal/tests/test_provisioning_client.py` (later deleted by 5B.8.B.4).
      The integration fixture in `provisioning/compute/service/tests/integration/conftest.py`
      mounts both adapters' test routers, so the suite no longer depends on
      `ACTIVE_PROFILES=mock` being set when `main.py` is imported (plain `pytest` had
      returned 404 for every bare-metal rule route).
- [x] 5A.3 Deterministic gates: `MockRuleSet` signals when a job reaches a rule's gate and
      reports how many wait (`hold`, `wait_until_held`, `waiting` in `list()`); the
      bare-metal tests wait on that signal and `AsyncJobQueue.on_job_started` instead of
      sleeping. Unit tests in `provisioning/compute/tests/unit/test_executor_mock.py`.
- [x] 5A.4 Coverage claimed but missing: the five bare-metal test routes in
      `test_provisioning_client_endpoint_coverage.py`; a test in
      `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_fulfillment_provider.py`
      feeding the mock's job result to `BareMetalFulfillmentProvider.fetch_credentials`.
- [x] 5A.5 `service_obligation` concurrency: a worker pass running while
      `service_obligation` holds the fulfillment lease sees the obligation busy and
      starts no second fulfillment. The lease is the `on_ready` hook's
      (`SettlementRuntime.reserve_fulfillment`), not the worker's, so every domain's hook
      must reserve; `service_obligation`'s docstring says so.
- [x] 5A.6 Test placement: `kit/settlement-runtime/tests/unit/test_servicing.py` and
      `domains/apicredits/storefront/tests/unit/test_sync_negotiation.py` were split by
      level rather than moved whole — the
      real-SQLite tests are in `kit/settlement-runtime/tests/integration/test_servicing.py`
      and `domains/apicredits/storefront/tests/integration/test_sync_negotiation.py`, with
      loop-ordering and decoding tests left in `tests/unit/`; API credits' shared fixtures
      are in `tests/integration/conftest.py` and `tests/integration/credit_negotiation.py`,
      and `kit/settlement-runtime` gains `tests/integration/__init__.py` and its test
      paths.
- [x] 5A.7 **Gate.** The touched suites pass; `make check-packaging` passes.
      Done 2026-10-02: every touched suite, under both plain `pytest` and
      `ACTIVE_PROFILES=mock` for the provisioning service, failing only the seven known
      pre-existing VM cases (`test_publication_loop.py` is SIGKILLed when run whole in the
      sandbox and was run test by test); `make check-packaging`, comment hygiene, and
      `openspec validate --strict` pass. The VM lane was unrun (no container runtime
      here).

## 5B. Provisioning execution boundary

Maintainer rulings that review findings have contested are recorded in `design.md`,
"Maintainer rulings for review": plaintext secret submission (option A) stands, with
on-wire protection out of scope; `ARCHITECTURE.md` describes the target ownership
because the branch merges whole.

Decisions: "Compute provisioning is a family kit", "Provisioning execution leaves the VM
adapter", "Pre-release wire and schema changes are accepted", "Job and host authority
shape". Steps ran in the order listed (5B.2a before 5B.3); each schema change carries
migration tests (fresh database, upgrade with conversion, idempotent rerun). 5B.11 is the
lane gate. Package versions bumped at each step are in the packages and git history.

Recurring environment notes, stated once for the whole section: the implementing
environment could not reinit `kit/policy`, the VM storefront, or the VM buyer (their
PyTorch index was unreachable), so those ran by frozen sync and their locks were set by
hand from the built wheels, which `make check-locks` accepts (closeout task 2.2 relocks
them where the index is reachable); the bare-metal and API-credit storefront locks were
hand-kept in their snapshot platform-marker form, which a relock flips; the API-credit
middleware needs Cargo; the VM storefront's two `test_alkahest` failures need Node and
Anvil; the e2e unit suite's one known failure is 10.1's. "The root aggregate passes"
below means `make -k test` passes its 44 suites except those environmental cases.

- [x] 5B.1 Neutral contracts first: the composition contract types and
      `compose_adapter_bundles` move to
      `provisioning/compute/src/compute_provisioning/composition.py`; the host, job, and
      aggregate health and version wire models move from
      `vm_provisioning_operator/models.py` to `compute_provisioning`, classified by owner
      (readiness models to the Ansible distribution in 5B.6; `VmActionRequest` and
      `CreateVmRequest` stay VM's). Added 2026-10-02 with the maintainer: the route-contract
      table becomes contributable — the family kit keeps the contract type, its own routes,
      and assembly; each domain declares its routes beside its client; the service
      assembles them for authentication.
      - Done 2026-10-02: `ProvisioningRouteContract` carries `roles`; VM declares
        `VM_PROVISIONING_ROUTES`, bare metal `BARE_METAL_PROVISIONING_ROUTES`; `main.py`
        assembles the table `ProvisioningAuthMiddleware` now requires; the composition unit
        test moved to `provisioning/compute/tests/unit/test_composition.py`. A one-off
        comparison found all 108 operations unchanged in method, path, roles, and resources. Later
        steps removed the re-exports and credential DTOs (5B.5), replaced the host models
        (5B.4), and deleted the `Lease*` models (5B.8.B.4).
      - Evidence: `provisioning/compute/contracts/tests/unit/test_route_table.py`,
        `provisioning/compute/service/tests/unit/test_route_table_composition.py`,
        `domains/bare_metal/tests/test_provisioning_client.py`.
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
      `compute_provisioning/jobs/executor.py` (`JobExecutor`, `JobRun`, `JobSuccess`,
      `JobFailure`, `JobRetryPolicy`), `compute_provisioning/hosts/execution.py`
      (`ExecutionHost`), and `hosts/connection.py` (`ConnectionEnvelope`, brought forward
      from 5B.3); `JobExecutorTable` resolves executors. A transitional
      `AnsibleJobExecutor` in VM's adapter holds the Ansible half of `_process_job`.
      - Done 2026-10-02: the job service routes, looks up the host, runs the executor, and
        stores its handle; cancellation is async. The executor-side job-done notification
        is dropped (nothing consumed it).
      - Evidence: `provisioning/compute/tests/unit/test_job_executor_table.py`,
        `test_job_contract_values.py`, `test_composition.py`; the service's
        `tests/unit/services/test_job_service.py` and `test_ansible_job_executor.py`
        (handle, outcome, credentials, classification, non-`ssh` refusal, real-process
        cancellation).
- [x] 5B.3 Ansible distribution skeleton with the `ssh` connection codec. Behaviour-neutral.
      `provisioning/compute/ansible/` (`compute_provisioning_ansible`) with `connection.py`'s
      `ssh` codec; the `ConnectionCodec` protocol beside `ConnectionEnvelope`.
      - Done 2026-10-02: no Ansible Python package is needed (Ansible runs as a
        subprocess). Root `Makefile` gains `dist-compute-provisioning-ansible` and
        `test-compute-provisioning-ansible`; the layout and lock checks discover the
        project from its lock. Evidence:
        `provisioning/compute/ansible/tests/unit/test_ssh_connection.py`.
      - Corrected for 5B.4: an embedded key is submitted in plaintext and encrypted with
        the service's Fernet key; settled with the maintainer (option A) that the codec
        protects and decrypts (design: "The host authority is connection-neutral, and
        connection secrets stay protected").
- [x] 5B.4 Host authority. Changes the host wire format and schema. `ConnectionEnvelope`
      carries `public` and `protected` (`ProtectedValue` never shows its ciphertext); the
      `ssh` codec takes public fields and an optional `fernet-v1` `private_key` it
      protects; `compute_provisioning/hosts/` holds the host record, `HostAuthority`, and
      the models, with write-only `secrets`; INI import moves to the Ansible distribution;
      one forward migration converts the `ssh_*` columns, key ciphertext byte for byte.
      - Done 2026-10-02: `HostAuthority` (CRUD through codecs, `lookup` returning
        `ExecutionHost`, `apply_inventory` with capacity derivation, pool-change hooks); an
        update's `connection` replaces the whole connection, keeping a stored secret it
        still needs; `HostUpdate.enabled` is now applied. Migration
        `20261002_001_host_connection_envelope`; `_drop_columns_via_table_rebuild` now
        recreates outbound foreign keys and refuses to drop a column one uses. VM's
        `host_service.py` is tombstoned; `render_inventory_ini` and
        `get_decrypted_key_value` had no production caller and are removed.
        `docs/development/VALIDATION_RUNBOOK.md` and
        `tools/issue-discovery/config/phases/local.yaml` show the new request body.
      - Evidence: `provisioning/compute/tests/integration/test_host_authority.py`; the
        distribution's `test_ssh_connection.py` and `test_inventory.py`; the service's
        `tests/unit/test_host_connection_migration.py`; `TestEmbeddedKey` in
        `test_hosts_api.py` (the suite's Fernet key is a deterministic all-zero
        development value).
- [x] 5B.5 Job authority. Changes job wire formats and the schema, and fixes the
      cancellation race. `compute_provisioning/jobs/`: the engine, queue, rule and gate
      mechanism, `ansible_jobs` and `credentials` metadata, and route services; results and
      credentials stored as envelopes; `host_id` first-class; JSON `execution_handle`.
      - Done 2026-10-02: `JobEngine` (`jobs/engine.py`) routes by stored offering mode,
        action, and `host_id`, never by parameters; every change goes through
        `_transition`, which re-reads the job and leaves a cancelled job alone (made a
        conditional `UPDATE` in review round 2, 5B.6), so a cancelled job stays cancelled,
        a queued one never
        starts, and a pre-handle cancellation reaches the executor when the handle
        arrives; `wait_for_terminal` backs `/test/jobs/{id}/wait`. `AsyncJobQueue` is
        `jobs/queue.py`, the mock mechanism `jobs/executor_mock.py`. Migration
        `20261002_002_job_envelopes`. `CredentialResponse`, `CredentialListResponse`, and
        the operator client's re-exports are deleted.
      - Corrected after the VM lane: the engine routed by the contract's `action_kind`, so
        a VM teardown (`vm_remove`) found no executor; `JobRecord.executor_action` now
        holds the executed action.
      - Found and fixed: `ansible_fulfillment_provider.py` logged through an undefined
        `logger`, so an unreadable result raised `NameError` instead of being tolerated.
      - Evidence: `provisioning/compute/tests/integration/test_job_authority.py`,
        `tests/unit/test_job_envelope_migration.py`, `test_retry_scheduler.py`; every e2e
        and smoke module collects.
- [x] 5B.6 The rest of the Ansible distribution. Behaviour-neutral. Landed in three slices
      and a review round; decisions and findings are in `design.md`, "The Ansible job
      codec (5B.6 slice B, absorbing 5B.7)", "Findings for review (5B.6 slice B)", "The
      mock runner and the probes (5B.6 slice C)", "Findings for review (5B.6 slice C)",
      and "Maintainer rulings on the 5B.6 implementation review".
      - Slice A: `compute_provisioning_ansible/runner.py` (`AnsibleRunner` and the run,
        result, inventory, and redaction helpers); an embedded key is decrypted just in
        time into an owner-only file. Evidence:
        `provisioning/compute/ansible/tests/unit/test_runner.py`,
        `test_host_operations_service.py` (no key file left after a probe).
      - Review round 2 (2026-10-02): VM stage 08a/08c had been broken by Section 4's
        evaluate-settle fix — the preview looked up the held host by a `resource_id` the
        site strips; `admin_settle_service.py` now reads the reservation the hold names
        (`test_admin_settle_service.py`). Every ordinary `HostAuthority` read returns
        `HostResponse` (`test_no_ordinary_read_carries_a_protected_value`); transient key
        files are created 0600/0400 and removed on every ending; `_transition` and
        `cancel_job` are conditional `UPDATE`s, proven with two engines on one SQLite file;
        `compute_provisioning` declares `sqlalchemy>=2.0`. Checkpoint: both lanes passed
        (VM 129, bare metal 11).
      - Slice B: the codec protocol (`codec.py`), `AnsibleJobExecutor` in the distribution
        (`executor.py`, `TRANSPORT_FAILURES`), VM's `VmAnsibleCodec` and bare metal's
        `BareMetalAnsibleCodec`; bare metal submits through `JobEngine`; migration
        `20261002_003_bare_metal_job_shapes`; the bare-metal playbook and role move to
        `domains/bare_metal/provisioning/iac/ansible` (`scripts/tests/test_bare_metal_compose.py`
        checks the mount). Evidence: the distribution's `test_codec.py`,
        `test_executor.py`; the bare-metal adapter's `test_bare_metal_codec.py`; the
        service's `test_vm_codec.py` and `test_bare_metal_job_shape_migration.py`.
      - Slice C: `mock.py` (`MockAnsibleRunner`, with a contributed default output) and
        `probes.py`; VM's and bare metal's `services/mock_output.py` replace both domain
        mocks; the readiness models leave the VM operator client. Evidence: the
        distribution's `test_mock.py` and `test_probes.py`;
        `test_bare_metal_mock_output.py`.
      - Implementation-review corrections (2026-10-03): the runner owns cancellation, so a
        held mock run is cancellable (`test_bare_metal_mock_profile.py`; `TESTING.md` gains
        "Leave nothing held"); `parse_inventory_ini` registers every host entry and VM's
        inventory becomes a directory with `inventory/provisioning-hosts.example`; the
        distribution ships `ansible.cfg` and bare metal its own `requirements.yml`
        (`tests/unit/test_image_collections.py`); `non_retryable_errors` becomes
        `additional_non_retryable_errors`; both job-row migration tests move to
        `tests/integration`.
      - Deferred: real-run failure classification reads only the runner's terminal message
        (ruling 4; follow-up is structured terminal-failure evidence from the runner).
- [x] 5B.7 Domain codecs. Behaviour-neutral on the wire. Absorbed into slice B of 5B.6,
      with one amendment decided there: bare metal's stored parameters and results are
      bare-metal-shaped (`design.md`, "The Ansible job codec", decision 2), which changes
      what `JobStatusResponse` reports for bare-metal jobs; existing rows are migrated.
      Deleting `bare_metal_mock_executor.py` moved to slice C of 5B.6.
- [x] 5B.8 Controls and routes. Decided with the maintainer on 2026-10-04: `design.md`,
      "Controls and routes (5B.8)", decisions 1–11, including the same day's design
      review; the route-ownership matrix is decision 8's. Four slices, A0 → A → B → C,
      each its own checkpoint gated by the provisioning-family suites, comment hygiene,
      and `make check-packaging`; removed files are tombstoned in the checkpoint fileset.

      **Slice A0: the action surface goes, and contracts and clients move to their owners.**
      Amended at the A0 checkpoint review (2026-10-04): it also admits `admin` on the site
      capacity routes the provisioning service serves, and relays admit seller and admin,
      under the maintainer's administrator ruling (`design.md`, "Slice A0 implementation
      findings").

  - [x] 5B.8.A0.1 Delete the generic action surface (decision 10): `POST /api/v1/actions`
        and the contract-job routes, both domains' `compute_adapter.py`, and the adapter
        registry types in `compute_provisioning/adapters.py`. Done: `compute_contract_service.py`
        is deleted whole (it had no lease half); `UnsupportedExecutorActionError` stays as
        the table's lookup error; `unit/services/test_provider_registry.py` keeps its
        provider cases, and
        `provisioning/compute/service/tests/integration/test_compute_contract_api.py` its
        lease cases.
  - [x] 5B.8.A0.2 `VersionedEnvelope` to core (decision 8):
        `core/src/market_core/envelopes.py`, no re-export from `market_fulfillment`
        (29 importers repointed); `core/tests/unit/test_envelopes.py` moves to
        `core/tests/unit/test_envelopes.py`.
  - [x] 5B.8.A0.3 Compute contracts distribution (decision 8): `provisioning/compute/contracts/`
        (`compute_provisioning_contracts`: `contracts.py`, `hosts.py`, `jobs.py`,
        `system.py`, `routes.py`); the family table holds the family's routes only, and
        `compute_provisioning_service/route_table.py` assembles the service's table.
        Of the moved tests (`provisioning/compute/contracts/tests/unit/test_contracts.py`,
        `test_job_contract_values.py`, `test_route_table.py`), the first and last were split
        by owner into `provisioning/compute/contracts/tests/unit/`.
        Amended at the A0 checkpoint review: the new distribution, like the compute client
        and the two resource-pool packages, is deliberately unpublished until closeout
        task 2.0 fixes the published dependency graph as a whole.
  - [x] 5B.8.A0.4 Compute client distribution (decision 8): `provisioning/compute/client/`
        (`ComputeProvisioningClient`, `SyncComputeProvisioningClient`, one signing base, one
        error hierarchy, `authenticated_request`); `compute_provisioning/client.py` deleted.
        Parity: `provisioning/compute/service/tests/unit/test_provisioning_client_contract.py`.
  - [x] 5B.8.A0.5 Resource-pool contracts and client (decision 11):
        `kit/resource-pools-contracts/` (pool models, hints, route declarations) and
        `kit/resource-pools-client/` over any `authenticated_request` transport; about 37
        importers repointed (`test_hints.py` and `test_pool_models.py` move to the contracts
        package); registered in `kit/Makefile`.
  - [x] 5B.8.A0.6 Capacity-definition import in `kit/site-client` (decision 11): its
        models, contract, and import method; the server's contract is
        `CAPACITY_DEFINITION_ROUTE_CONTRACTS` in `market_site.auth`;
        `kit/site/tests/unit/test_auth_route_parity.py` compares them.
  - [x] 5B.8.A0.7 VM and Ansible extension clients (decisions 8 and 4):
        `vm_provisioning_operator` holds `VmOperatorClient`, `SyncVmOperatorClient`, relay
        models, and relay declarations; the generic clients are deleted;
        `compute_provisioning_ansible/host_import.py` holds the import declaration and its
        clients. Amended at the A0 checkpoint review: both depend on the compute contracts
        only and accept any `authenticated_request` transport (the `kit/pool-overrides`
        shape).
  - [x] 5B.8.A0.8 Callers. Both storefronts depend on the compute client, not on
        `arkhai-compute-provisioning`; e2e uses `SyncComputeProvisioningClient`,
        `SyncResourcePoolClient`, `SiteCapacityClient`, and `SyncVmOperatorClient` by owner;
        the service's integration suite drives every route through the canonical clients
        (`integration/conftest.py`, `test_capacity_definitions_api.py`, `test_hosts_api.py`,
        `test_host_capacity_derivation_api.py`, `test_leases_api.py`, `test_pools_api.py`,
        `test_provisioning_client_endpoint_coverage.py`, `test_test_controller.py`,
        `test_vms_api.py`, `test_fulfillment_api.py`, `test_host_requirement_api.py`,
        `test_relays_api.py`, `test_bare_metal_mock_profile.py`; unit
        `unit/models/test_jobs_models.py`, `unit/services/test_host_operations_service.py`,
        `test_ledger_lease_lifecycle.py`, `test_vm_operations_service.py`,
        `unit/test_import_boundaries.py`, `unit/test_lease_models.py`;
        `provisioning/compute/client/tests/unit/test_fulfillment_client_opacity.py`), as do
        e2e's `test_multi_registry.py`, `test_pool_declared_offering_modes.py`,
        `test_vm_introduction.py`, `test_bare_metal_publication.py`,
        `test_bare_metal_introduction.py`, and `tests/smoke/test_provisioning_smoke.py`.
  - [x] 5B.8.A0.9 Gate. The slice's suites plus `kit/fulfillment`, `kit/resource-pools` and its
        two new packages, `kit/site`, `kit/site-client`, `core`, `domains/vms/listings`, both
        storefronts, and the e2e unit suite pass; `make check-packaging` passes. A boundary
        check in each new package's unit suite asserts its declared dependencies.

      Slice A0 done 2026-10-04 (order A0.1, A0.2, A0.5, A0.6, A0.3, A0.4, A0.7, A0.8, A0.9;
      corrections in `design.md`, "Slice A0 implementation findings").
      - The bare-metal adapter's unused dependency on VM's client was removed.
      - Correction at checkpoint verification: the gate had run each project's suite, not
        the root aggregate, and missed `domains/apicredits/tests/test_distribution_install.py`,
        whose wheel fixture lacked `kit/resource-pools-contracts`; fixed. Later gates run
        the root aggregate.
      - Validation: every touched suite, the root aggregate, `make check-locks`,
        `make check-packaging`, comment hygiene, citations, and OpenSpec strict pass.
        End-to-end on the A0 checkpoint: VM lane 135 and bare-metal lane 16 passed, no
        traceback, 5xx, 401, or 403.

      **Slice A: the authorities at the root, and the job and host routes.**

  - [x] 5B.8.A.1 Authorities at the root (decision 5): `container.py` builds one
        `HostAuthority` and one `JobEngine`; `retry_policy_from` moves to
        `compute_provisioning_service/services/job_retry.py`; VM's `job_service.py` becomes
        `services/job_submitter.py` (`VmJobSubmitter`, no `config.Settings` import); both
        runtimes receive the authorities. Evidence:
        `provisioning/compute/service/tests/unit/test_authority_composition.py`.
  - [x] 5B.8.A.2 Route services (decision 4): `compute_provisioning/route_errors.py`
        (`ProvisioningRouteError`, absorbing `MockRouteError`), `jobs/route_service.py`,
        `hosts/route_service.py` (probes keyed by connection kind, 422 for none), and
        `AnsibleHostImportRouteService`. A duplicate host registration now answers 409
        naming the host (VM's controller had formatted a field `HostCreate` lacks).
  - [x] 5B.8.A.3 Bindings: the service's `jobs_controller.py`, `hosts_controller.py`,
        `host_import_controller.py`, and `test_jobs_controller.py` (mock profile); VM keeps
        only its host-capacity route; the container builds the probe runner. Both adapters
        declare FastAPI, `fastapi-utils`, and `typing-inspect` (imported by `fastapi-utils`,
        undeclared by it).
  - [x] 5B.8.A.4 Drift guard: `provisioning/compute/service/tests/unit/test_route_binding.py`
        (every mounted route resolves to exactly one contract and the reverse; it reads
        routes from the OpenAPI document, since FastAPI 0.139 keeps included routers
        lazily); route-service unit tests (`test_job_route_service.py`,
        `tests/unit/test_host_route_service.py`,
        `provisioning/compute/ansible/tests/unit/test_host_import.py`).

  - [x] 5B.8.A.5 Added at the A0 checkpoint review (2026-10-04, maintainer decision):
        `ExecutorActionEnvelope` becomes `compute_provisioning.jobs.JobActionRequest`
        (`jobs/action_request.py`), the job authority's own identity record, which no route
        accepts; `ProvisioningErrorEnvelope` moves beside `JobFailure`; the contract-job
        vocabulary only the deleted routes used is deleted.
      Slice A done 2026-10-04. Validation (with A.5): every touched suite, the root
      aggregate, `make check-locks`, `make check-packaging`, comment hygiene, citations,
      and OpenSpec strict pass. End-to-end on the A checkpoint (2026-10-05): VM lane 135
      and bare-metal lane 16 passed, no traceback, 5xx, 401, or 403.

  - [x] 5B.8.A.6 Added at the slice A implementation review (2026-10-05, maintainer decision;
        `design.md`, "Controls and routes (5B.8)", "Slice A implementation review").
        - Inventory pool moves: `apply_inventory` moves an existing host through
          `_move_to_pool`, whose hooks run only on a real move and may raise
          `PoolChangeRefusedError` (409 at both routes; VM translates
          `RelayRebindingRefused`).
        - Job list order: `JobListSort`, and `sort` on both clients' `list_jobs`.
        - Job identity: `JobActionRequest` carries no parameters; `JobIdentityConflictError`
          refuses a repeated identity naming different parameters; migration
          `20261005_001_drop_job_contract_version`.
        - Evidence: `test_host_authority.py`, `test_job_authority.py`, the service's
          `integration/test_host_pool_moves_api.py` (reverting the fix fails exactly the
          import case), `unit/test_database.py`. Validation: the section's suites, the root
          aggregate, packaging, hygiene, citations, and OpenSpec strict pass.

      **Slice B: the lease surface and mode-agnostic release** (decisions 1–3, 9, and 7.3).
      Amended 2026-10-05 before implementation, after the slice B design review
      (`design.md`, "Controls and routes (5B.8)", "Slice B design review", points 1–5).

  - [x] 5B.8.B.1 Ledger and lease windows (points 1, 2, and 4): `kit/site`'s ledger
        registers a lease once by executor target; `commit` refuses the lifecycle's states
        and leaves a registered window alone; truncation moves only a leased end, only
        earlier; `CapacityReleaseGuard` replaces `SettlementAbandonmentHook` at all three
        reclaim sites (a forced release is not guarded); the field writer narrows to
        `record_create_handle_in_session`; the VM storefront registers with the window
        `commit` returned. Evidence: `kit/site/tests/integration/test_ledger.py`,
        `kit/site/tests/unit/test_authority.py`,
        `kit/fulfillment/tests/unit/test_fulfillment_persistence.py`, and the VM
        storefront's `tests/unit/test_fulfillment_resume_runtime.py`,
        `test_fulfillment_service.py`, `test_fulfillment_provisioning.py`, and
        `test_fulfill_vm_obligation_error_handling.py` (registration uses the committed
        window; a failed commit skips it).
  - [x] 5B.8.B.2 Lease contract and route service: `LeaseView` reports the offering mode;
        list and release-oversight added; an unlisted operation admits seller and admin;
        `route_contract_from_declaration` refuses a declaration without `admin`;
        `compute_provisioning/leases.py` (`LeaseRouteService`, 404 and 409) bound at
        `/api/v1/contract/leases`. Evidence:
        `provisioning/compute/tests/unit/test_executor_leases.py`, `test_lease_lifecycle.py`,
        `tests/unit/test_lease_route_service.py`, the contracts'
        `tests/unit/test_route_table.py`, `test_compute_contract_api.py`.
  - [x] 5B.8.B.3 Release (decision 9 and points 3 and 4, absorbing 7.3):
        `compute_provisioning/release.py`'s `FulfillmentReleaseGuard` (proof, then
        compare-and-set abandonment), `FulfillmentReleaseExecutor` (a typed decision per
        aggregate state, point 3's table), and the status port; `jobs/db.py`'s
        `job_bound_to_reservation`; the lease lifecycle acts on decisions with neutral
        failure reasons (`teardown_failed`, `teardown_timeout`, `fulfillment_failed`,
        `release_unproven`); the dispatchers and both adapters' `release.py` are tombstoned;
        bare metal's provider records its grant job as the create handle.
        - Evidence (corrected by 5B.8.B.8):
          `provisioning/compute/tests/integration/test_release.py` (every aggregate state,
          the proof, the guard writing nothing on refusal, the dispatch race);
          `provisioning/compute/tests/unit/test_lease_lifecycle.py`; the service's
          `tests/unit/services/test_ledger_lease_lifecycle.py`,
          `test_authority_composition.py`, `integration/test_legacy_backfill_teardown.py`,
          `integration/test_capacity_api.py`, and `integration/test_lease_release_api.py`.
  - [x] 5B.8.B.4 Deletions (decision 1; point 5): VM's and bare metal's lease surfaces
        (controllers, declarations, `Lease*` models, `BareMetalLeaseClient`,
        `BareMetalLeaseView`, `receipt_from_lease_view`); `BareMetalLeaseCreate` is renamed
        `BareMetalAccessGrant`; `bare_metal_executor_ref` stays. `test_leases_api.py` becomes
        the family lease API test; `test_bare_metal_mock_profile.py` grants through
        `begin_fulfillment`; `test_schema.py` follows the rename.
  - [x] 5B.8.B.5 Storefronts (decision 9 and point 4): the VM terminal-settlement path
        releases and truncates only on refusal; bare metal's hosted `_teardown` treats a
        `None` release as not released. The VM admin bulk release and failure-policy
        release no longer free a delivered lease. Evidence: VM
        `tests/integration/test_abandon_truncation.py`; bare metal
        `tests/test_hosted_lifecycle.py`.
  - [x] 5B.8.B.6 e2e: `scenarios/vms/conftest.py`'s `DealLease` reads leases through
        `SyncComputeProvisioningClient` and backdates through
        `SiteCapacityClient.truncate_lease` signed as admin; `test_full_deal.py`,
        `test_full_deal_buyer_cli.py`, and `test_buy_oneshot_buyer_cli.py` follow.

  - [x] 5B.8.B.7 Added after the slice B checkpoint's end-to-end run (2026-10-05,
        maintainer decision; `design.md`, "Slice B implementation findings", last row):
        `commit` returns the reservation as the site recorded it through `SiteCapacityClient`,
        core's `CapacityClient` and `AggregateCapacityClient`, and `CapacityRuntime`.
        Evidence: those layers' unit tests, `test_capacity_api.py`, and the VM storefront's
        `tests/integration/test_committed_window.py`.
  - [x] 5B.8.B.8 Fixes from the slice B implementation review (2026-10-05; findings 1–6,
        each agreed with the maintainer; `design.md`, "Slice B implementation review").
        - Release is recorded (`releasing`, fulfillment as handle) before teardown begins;
          bare metal registers its lease at access readiness; `LeaseRegistration` forbids
          unknown fields and keeps `deal_ref`, recording the escrow once; a first
          registration writes a window only where none is recorded; the grace timeout runs
          from `release_requested_at` (migrations `20261005_002` provisioning and
          `20261005_005` API credits).
        - Evidence: `kit/site`, family-kit (including the dispatch-versus-guard race on
          file-backed SQLite), contracts, service integration, bare-metal storefront, and
          API-credit migration tests. The section's suites, the root aggregate, packaging,
          hygiene, citations, and OpenSpec strict pass.
        - End-to-end (run 37298149909, with A.6, B, B.7, and B.8): bare-metal lane 16 and
          VM lane 135 passed; the VM lease stages ran through the family surface for the
          first time, each expired lease released on a later cycle.
  - [x] 5B.8.B.9 Fixes from the slice B re-review (2026-10-05; both findings agreed with
        the maintainer; `design.md`, "Slice B re-review").
        - Conditional lifecycle writes: `kit/site` gains `record_release_failed` and
          `record_unmanaged`, and `begin_releasing` is conditional (allowed source states,
          idempotent under the same handle); the lifecycle checks every write's result and
          a refused write re-reads and skips.
        - Durable VM lease registration (option A): `kit/settlement-runtime`'s
          `FulfillmentOutcome` gains `deferred`, persisted without binding or waking
          servicing; the VM main path defers when commit records no window, registration
          fails, or evidence publication fails; the resume pass raises rather than proceeds.
        - Evidence: `kit/site` real-SQLite race tests, family-kit lifecycle race tests,
          settlement-runtime deferred-job test, VM storefront deferral and resume tests, and
          a repeated `begin` returning one create job. The section's suites, the root
          aggregate, packaging, hygiene, citations, and OpenSpec strict pass.
        - End-to-end (run 37304872316): bare-metal lane 16 and VM lane 135 passed, no
          traceback, 5xx, 401, or 403; each expired VM lease released on the next cycle.
      Slice B done 2026-10-05 (`design.md`, "Slice B implementation findings"). New tests:
      the family lease API test, `test_lease_release_api.py`, the family kit's integration
      `test_release.py` and `test_lease_route_service.py`, the service's
      `test_ledger_lease_lifecycle.py`, and `tests/integration/bare_metal_deal.py`, a helper
      taking bare-metal grants through fulfillment. The first end-to-end run (with A.6)
      failed 4 VM stages for want of a registered lease, fixed by 5B.8.B.7 and 5B.8.B.8.

      **Reconciliation with other changes (2026-10-05, maintainer request before
      slice C).** Every other active change was checked against this change's surfaces,
      and each affected one was given a dated note citing this change:
      `remove-dead-storefront-physical-surfaces` (rebase note on 3.5; new 3.8 removing the
      dead expiry hook), `contain-embedded-host-key-material`,
      `relay-vm-access-without-a-dashboard` (pending-move note for 5B.9),
      `refactor-e2e-fulfillment-lifecycle` (run 37298149909 as evidence for its 2.6),
      `project-an-authoritative-funding-loss`, `capacity-reservation-lifecycle-hardening`,
      `kit-owned-listing-and-fulfillment-lifecycles`, `pools-7-storefront-fulfillment-cutover`,
      `add-bare-metal-hosted-settlement`, `negotiation-driven-capacity-resize`,
      `automate-seller-spot`, and `bring-host-inventory-under-definition-documents`. The
      capacity-hold changes and those only touching edited files needed no note.

      **Slice C: the system split and the last `container` reach** (decisions 4 and 7).
      Amended 2026-10-05 before implementation, after the slice C design review
      (`design.md`, "Controls and routes (5B.8)", "Slice C design review").

  - [x] 5B.8.C.1 Status (decision 7; review points 1, 3, 4, and 6): a lean `HealthResponse`
        and `SystemStatusResponse` (`ExecutionStatus`, `ExecutorStatus`,
        `SystemStatusComponent`) in `compute_provisioning_contracts.system`; the readiness
        route goes; `compute_provisioning_ansible/readiness.py` builds the `ansible`
        component; the service's `services/system_status.py` and
        `controllers/system_controller.py` (503 for an uncomposed collaborator, 409 for an
        advance while convergence runs; a database error reports only its type); VM's
        system service and controller are tombstoned. Evidence: the service's
        `integration/test_system_api.py`, `unit/test_system_controller.py`,
        `unit/services/test_system_status.py`; the distribution's
        `tests/unit/test_readiness.py`.
  - [x] 5B.8.C.2 Inventory views (review points 2 and 7):
        `compute_provisioning/inventory_views.py` (`InventoryViewProjection`, duplicate
        claims refused); bare metal's `inventory_views.py` (`BareMetalPublicationViews`) and
        VM's (`AnsiblePoolDefaultsViews`); `capacity_inventory.py` names neither. Evidence:
        `unit/services/test_capacity_inventory.py` (a fake third domain),
        `domains/bare_metal/provisioning/adapter/tests/test_inventory_views.py`,
        `unit/services/test_vm_inventory_views.py`, `integration/test_capacity_api.py`.
  - [x] 5B.8.C.3 Router factories (decision 4): VM's and bare metal's controllers become
        factories over accessors (`vm_router_mounts`, `vm_mock_router`,
        `bare_metal_mock_router`), sharing `require_composed`. Bare metal's adapter imports
        no service module, so its dependencies on the service, VM's adapter,
        `fastapi-utils`, and `typing-inspect` were removed early (bare metal's half of
        5B.10).
  - [x] 5B.8.C.4 Boundary test: `provisioning/compute/service/tests/unit/test_import_boundaries.py`
        allowlists (file, module) pairs and scans both adapters' sources (VM's adapter has
        no test directory, so the scan lives beside the service's check).
  - [x] 5B.8.C.5 Callers (review point 4): the e2e mock-mode, provisioning-health, pin, and
        storefront checks read the typed status (`scenarios/vms/test_full_deal.py`,
        `test_full_deal_buyer_cli.py`, `test_buy_oneshot_buyer_cli.py`,
        `test_non_erc20_settlement.py`); `tests/smoke/test_provisioning_smoke.py` and
        `docs/development/VALIDATION_RUNBOOK.md`'s `jq` follow.
  - [x] 5B.8.C.6 The VM storefront's dead expiry hook (review point 5): `_do_shutdown` and
        `schedule_shutdown` removed (`tests/unit/test_fulfillment_provisioning.py`,
        `test_fulfillment_service.py`, and `test_fulfill_vm_obligation_error_handling.py`
        updated); `remove-dead-storefront-physical-surfaces` task 3.8
        and its proposal record it as delivered here.
  - [x] 5B.8.C.7 Gate. Every provisioning-family suite, both adapters, the root `make test`,
        the VM storefront by frozen sync, the e2e unit suite and scenario collection,
        `make check-packaging`, comment hygiene, documentation citations, and OpenSpec
        strict validation. Versions bumped per slice, exact pins moved, changed projects
        relocked.
  - [x] 5B.8.C.8 Fixes from the slice C implementation review (2026-10-05; findings 1–4,
        each agreed with the maintainer; `design.md`, "Slice C implementation review").
        Built on 5B.9.A. The `ansible` component is ready only with a readable host registry
        and, once any executor is real, Ansible, every real playbook, and every enabled
        host's key file (`not_ready_reasons`); `StatusComponentProvider` reports a raising
        or mislabelled provider as not ready under its own name; OpenAPI describes the
        compute family's service. Evidence: the distribution's `test_readiness.py`; the
        service's `unit/services/test_system_status.py` and `integration/test_system_api.py`.
        The section's suites, the root aggregate, packaging, hygiene, citations, and
        OpenSpec strict pass. End-to-end (run 37338996200): bare-metal lane 16 and VM lane
        135 passed, no traceback, 5xx, 401, or 403; status answered 200 throughout.

      Slice C done 2026-10-05 (`design.md`, "Slice C design review"). End-to-end (run
      37334863741, with slice C and 5B.9.A): bare-metal lane 16 and VM lane 135 passed, no
      traceback, 5xx, 401, or 403; the typed-status stages passed and "Failed to schedule VM
      expiry" no longer appears. The service integration harness composes both bundles,
      convergence, and the status service as production does, and the rewritten
      `test_fulfillment_convergence_wiring.py` proves the mounted routers reach the
      composed workers.
- [x] 5B.9 Relays to VM. Amended 2026-10-05 before implementation, after the design review
      (`design.md`, "Relays to VM (5B.9)", points A–D): the relay code, its tables, and its
      routes move to VM's adapter, behind three contribution seams. Two slices, each its
      own checkpoint.
  - [x] 5B.9.A Seams (points A and B). Behaviour-neutral. Done 2026-10-05:
        `compute_provisioning.fulfillment_terminal` (superseded by 5B.10.D's release
        effects) and `compute_provisioning.definition_documents`; the bundle carries
        terminal hooks, definition documents, and background tasks, and composition refuses
        duplicates and reserved document kinds; one `import-contributed-definitions`
        startup step. Evidence: family-kit `test_fulfillment_terminal.py`,
        `services/test_definition_document_restart_safety.py` (contributed kinds before
        pools, under their digests),
        `tests/integration/test_release.py`, the service's
        `services/test_fulfillment_convergence.py` (hooks run in each terminal transaction;
        a failing hook leaves the record unchanged) and `test_authority_composition.py`.
        The section's suites, the root aggregate,
        packaging, hygiene, citations, and OpenSpec strict pass; end-to-end run
        37334863741 included 9.A.
  - [x] 5B.9.B The move (points A–D). Done 2026-10-05 (`design.md`, "Relays to VM
        (5B.9)", "5B.9.B implementation findings").
        - VM's adapter holds `db.py` (`Relay`, `RelayPortLease`, `AnsiblePoolConfig`), the
          five relay services, and `controllers/relays_controller.py`
          (`make_relays_router`); its bundle contributes the relay effect, the `relays`
          document kind, and the reconciliation task. VM's adapter imports no service
          module and no longer depends on the service. The relay route declarations admit
          only `admin`.
        - The service's `db/database.py` and `db/migrations.py` read VM's models (two
          allowlisted pairs); the relay tests build their databases through the service's
          migrations, so they stay in the service's suite and import VM's modules
          (`unit/services/test_relay_administration.py`, `test_relay_port_allocator.py`,
          `test_relay_port_leases.py`, `test_ansible_pool_config_handler.py`,
          `test_definition_document_restart_safety.py`, `test_fulfillment_convergence.py`,
          `test_capacity_inventory.py`; `unit/test_database.py`,
          `test_pool_offering_mode_migration.py`; `integration/test_relays_api.py`,
          `test_capacity_api.py`, `test_fulfillment_api.py`, `test_host_pool_moves_api.py`,
          `test_pool_declaration_startup.py`, `test_pools_api.py`, `test_test_controller.py`);
          the seller's refusal is a middleware case (`unit/middleware/test_auth.py`).
        - Spec delta (`physical-provisioning`): relay administration admits only the
          administrator. `relay-vm-access-without-a-dashboard`'s pending-move note records
          the new paths.
        - Validation: the section's suites, the root aggregate, packaging, hygiene,
          citations, and OpenSpec strict pass. End-to-end (run 37342659408): the archive
          lacks the run's `actions.log`, so pass counts are not recorded; the logs show the
          reconciliation starting as a contributed task, no traceback, 5xx, 401, or 403, and
          both expired VM leases released.
- [x] 5B.10 Boundary check. Amended 2026-10-05: the dependency removals this task named
      are done (bare metal's in 5B.8.C, VM's in 5B.9.B). The test walks every `Import` and
      `ImportFrom` node, so function-local, `TYPE_CHECKING`, and guarded imports count
      (`ARCHITECTURE.md`, "Family kits"), and covers deployment configuration as well as
      Python. Done 2026-10-05 (`design.md`, "Boundary check (5B.10)").
      - `provisioning/compute/service/tests/unit/test_import_boundaries.py` asserts:
        neither adapter imports the service or the other adapter; no neutral package
        imports `vm_provisioning_operator`; the job and host authorities import no Ansible
        or SSH module; no domain's deployment files name another domain's tree; the Ansible
        distribution names no domain's inventory group or playbook. Each check was shown to
        fail on a real violation. The compute client gains its own allowlist test.
      - The one violation found: API credits' compose mounted the Alkahest address book
        from VM's storefront. Maintainer chose option (a): it is now
        `kit/alkahest/src/market_alkahest/data/alkahest_anvil_addresses.json` with
        `market_alkahest.dev_chain.anvil_address_book_path()`, mounted from the kit at the
        unchanged `/app/alkahest_anvil_addresses.json`.
      - Validation: the section's suites, the root aggregate, packaging, hygiene, and
        citations pass. One provisioning integration test
        (`test_a_bare_metal_lease_is_registered_on_the_family_surface`) failed once — a
        harness race routed to closeout task 2.6 — and passed on eight reruns. OpenSpec
        strict passes under the pinned 1.14.0 (1.14.1 fails `--strict` on long
        requirements; `shorten-long-requirements` owns the permanent specs, and this
        change's own long deltas are restructured at closeout task 2.6). Helm render tests
        were not run (no `helm` binary); none asserts the changed value.
      - End-to-end (run 37431438099): bare-metal lane 16 and VM lane 135 passed, no
        traceback, 5xx, 401, or 403.
- [x] 5B.10.D Fixes from the implementation review of 5B.9 and 5B.10 (2026-10-06;
      `design.md`, "Implementation review of 5B.9 and 5B.10"). Supersedes 5B.9.A's
      terminal hooks.
      - Release effects: `kit/site`'s `CapacityLedgerService` runs `release_effect` before
        commit in every transaction that releases capacity;
        `compute_provisioning/release_effects.py` (`ReleaseEffects`,
        `reservation_is_released`) replaces `fulfillment_terminal.py`; VM contributes
        `release_reservation_ports`; the permanent "Relay port leases are unique per relay"
        is modified by the delta.
      - `app_runtime.background_tasks()` refuses a duplicate task name; database-backed
        convergence and relay suites move to `provisioning/compute/service/tests/integration/`,
        and the backoff test is `unit/services/test_fulfillment_convergence_backoff.py`.
      - Evidence: `kit/site`'s ledger suite, the family's `test_release_effects.py` and
        `test_release.py`, the service's convergence suite, `test_authority_composition.py`,
        `test_worker.py`. The section's suites, the root aggregate (one more hit of the
        recorded harness race, closeout task 2.6), packaging, hygiene, citations, and
        OpenSpec strict (1.14.0) pass.
      - End-to-end: run 37437827289 on this tree passed both lanes (recorded at 5B.11).
- [x] 5B.11 **Gate.** All provisioning-family suites, `make check-packaging`, comment
      hygiene; the VM lane and the bare-metal publication lane pass.
      Done 2026-10-06 on the 5B.10.D tree: end-to-end run 37437827289 passed the
      bare-metal lane (16) and VM lane (135), nothing failed or skipped, no traceback, 5xx,
      401, or 403 (the 404s are existence probes, 402s API-credit exhaustion, 410s
      introduction retention); expired leases were released. The VM lane runs no relay, so
      5B.10.D's port path is proven by the integration suites only.
- [x] 5B.12 Job-backed fulfillment. Re-planned 2026-10-05 before implementation, after the
      design review (`design.md`, "Job-backed fulfillment (5B.12)"): the family owns the
      whole job-backed provider and one delivery contract; domains contribute preparation
      and their codec's output. Amended 2026-10-06 by the implementation audit (`design.md`,
      "5B.12 implementation audit (2026-10-06)"). Four slices, each keeping both end-to-end
      lanes green.
  - [x] 5B.12.A The family provider, job submission, and delivery contracts; bare metal
        moved onto them. Done 2026-10-06, as planned:
        - `compute_provisioning_contracts.delivery` (`AccessEndpoint`, `DeliveryEvidence`,
          `DeliveredCredential`, `AccessDelivery`); jobs record no escrow or deal reference
          and the jobs list filters by capacity reservation (migration
          `20261006_001_drop_job_deal_correlation`).
        - `JobSubmissionService` (`jobs/submission.py`): a registered host for every job,
          enabled for a create; a contract job's UUIDv5 operation id.
        - `JobFulfillmentProvider` (`job_fulfillment.py`): contract identity
          `<reservation>:<operation>`; a create succeeds only with valid evidence; teardown
          prepared from the create job's parameters; the delivery is the evidence plus
          allowlisted credentials.
        - Bare metal: `BareMetalFulfillmentPlan` replaces its provider and operations
          service; `BareMetalResult` replaces `BareMetalAccessResult`; the storefront reads
          the access delivery (`access_delivery.py`) and serves `/access` live.
        - Evidence: `provisioning/compute/tests/unit/test_job_fulfillment.py`,
          `provisioning/compute/tests/unit/test_job_submission.py`, the contracts'
          `test_delivery.py`,
          `test_bare_metal_fulfillment_plan.py`, the service's `test_bare_metal_mock_profile.py`
          (grant to `active` through convergence, delivery read, reclaim to `torn_down`) and
          `test_job_deal_correlation_migration.py`, `test_database.py`,
          `test_authority_composition.py`; `domains/bare_metal/tests/test_schema.py`,
          `test_evidence.py`, `test_domain_runtime.py`; the storefront's
          `test_hosted_lifecycle.py`, `test_fulfillment_service.py`, `test_http_settlement.py`,
          and `test_persistence.py`; e2e
          `tests/e2e/roles/scenarios/vms/test_listing_shapes.py`. The section's suites, the root
          aggregate, packaging, hygiene, citations, and OpenSpec strict (1.14.0) pass.
        - End-to-end (run 37453176468): VM lane 135 (listing shapes filtering jobs by
          reservation) and bare-metal lane 16 passed; neither lane exercises bare-metal
          fulfillment, so that path's evidence is the integration suite.
        - Routed to closeout task 2.6: scheduling and admission do not read a host's
          enabled flag, so a create can be placed on a disabled host and its dispatch
          retries until the host is re-enabled.
  - [x] 5B.12.B VM end to end, with the migration. Amended 2026-10-06 by the 5B.12.B
        implementation audit (`design.md`, "5B.12.B implementation audit (2026-10-06)").
        Done 2026-10-06, as amended:
        - `CreateJobResult` (`compute.create-result.v1`) is every create's result; a create
          succeeds only on valid evidence, and the detail is never delivered.
        - VM: `VmFulfillmentPlan` replaces VM's provider (provider, `VmJobSubmitter`, and
          `fulfillment_results.py` tombstoned); operator services submit through
          `JobSubmissionService` (404 for an unregistered host); the codec applies the relay
          rule (the leased port is authoritative) with `VM_CREATE_DETAIL`. Finding fixed: a
          relay-backed VM had always been delivered with its KVM host's address and the
          relay's port.
        - Migrations: provisioning `20261006_002_vm_job_backed_fulfillment` (plain JSON);
          VM storefront `20261006_011_connection_details_to_delivery`, recording
          `arkhai_vms.VmConnectionDetails`.
        - VM buyer: quiet output prints `VmConnectionDetails.connect`, which never printed
          before. Five VM scenarios' mock creates print the create fact a create now needs.
        - Spec deltas: `physical-provisioning`'s "A create succeeds only with readable
          delivery evidence" and removal of "VM fulfillment result payload";
          `vm-storefront-fulfillment` adds "A VM deal records only how to reach its VM";
          two permanent evidence lines repointed to `test_vm_fulfillment_plan.py`.
        - Evidence: `test_vm_fulfillment_plan.py`,
          `provisioning/compute/service/tests/integration/test_job_fulfillment_migration.py`,
          `test_vm_codec.py`'s `TestCreateResult`, the VM storefront's
          `integration/test_connection_details_migration.py`, `arkhai_vms`'s
          `test_connection_details.py`, `test_legacy_backfill_teardown.py`,
          `test_legacy_vm_fulfillment_backfill.py`,
          `test_fulfillment_convergence_after_legacy_backfill.py`,
          `integration/test_fulfillment_api.py`; the VM storefront's
          `tests/fulfillment_fixtures.py`, `unit/test_fulfillment_provisioning.py`,
          `unit/test_fulfillment_resume_runtime.py`, `unit/test_fulfillment_service.py`,
          `unit/test_loop_gate_wiring.py`, `integration/test_committed_window.py`; and
          `e2e-tests/tests/unit/test_domain_deal_helper.py`. The section's
          suites, the root aggregate, packaging, hygiene, citations, and OpenSpec strict
          (1.14.0) pass; unscoped citations fail only on the 11 pre-existing references.
        - End-to-end (run 37464569194): VM lane 135, through this slice's delivery path,
          and bare-metal lane 16 passed; no traceback, 5xx, 401, or 403, and no create failed
          for want of delivery evidence.
  - [x] 5B.12.B.D Fixes from the implementation review of 5B.12.B (2026-10-06;
        `design.md`, "Implementation review of 5B.12.B").
        - The provisioning migration aborts atomically on an `active` VM fulfillment
          without a create job whose result converts to valid evidence, finds a record's
          create job by contract identity, and requires the tenant account; both codecs'
          SSH evidence requires one; the storefront migration takes a relayed record's host
          and port from its relay record.
        - `test_vm_fulfillment_plan.py` moved to
          `domains/vms/provisioning/adapter/tests/unit/`; the service-hosted VM codec suite
          is routed to closeout task 2.6.
        - Evidence: `integration/test_job_fulfillment_migration.py` (15 cases across every
          state), missing-account codec cases, the storefront migration's relayed records;
          the chain's fixtures (`test_database.py`, `test_host_identity_migration.py`) give
          their active VM fulfillment a complete create job, since the chain now refuses
          one without.
          The section's suites, the root aggregate, packaging, hygiene, citations, and
          OpenSpec strict (1.14.0) pass.
        - End-to-end (run 37471339897): VM lane 135 and bare-metal lane 16 passed; no
          traceback, 5xx, 401, or 403. The lanes run no active VM fulfillment across the
          migration, so its refusal is proven by the integration suite only.
  - [x] 5B.12.C Provisioning names the guest. Amended 2026-10-06 by the 5B.12.C
        implementation audit (`design.md`, "5B.12.C implementation audit (2026-10-06)").
        The wire break is accepted (audit row 8): both storefronts and provisioning move
        together. Done 2026-10-06, as amended:
        - `vm_provisioning_adapter.guest_names` derives `tenant-` and 24 hex characters of a
          UUIDv5 of the reservation id and checks the hostname, login, and shell rules; VM's
          requirement model has no `vm_target` and refuses unknown fields.
          `domains/vms/provisioning/iac/README.md` gains "Guest names", and `vm-create.yml` a
          comment at the login's derivation.
        - `LeaseRegistration` has no `executor_target`; the target came from the active
          fulfillment (superseded by 5B.12.D).
        - Migrations: provisioning `20261006_003_vm_fulfillment_request_names_no_guest` and
          VM storefront `20261006_012_fulfillment_context_names_no_guest`.
        - The VM storefront's three name generators are gone; usage-started and the settle
          dry run name no guest; core's client and settle model follow; stages 08a and 08c
          and the non-ERC-20 scenario carry no guest name, 08a asserting the preview names
          none (`tests/e2e/roles/scenarios/vms/conftest.py` loses
          `_evaluate_settle_vm_target`).
        - Spec deltas: `physical-provisioning`'s "Provisioning names what it provisions";
          `vm-storefront-fulfillment` replaces "Versioned fulfillment context" with "The
          fulfillment context records the exact request, naming no guest". At promotion,
          `pools-7-storefront-fulfillment-cutover`'s `design.md` promotion record links to
          the removed requirement's anchor; repoint it to the replacement.
        - Evidence: `TestGuestName`, `TestExecutorTarget`,
          `integration/test_vm_fulfillment_request_migration.py`, the contracts'
          `tests/unit/test_contracts.py`, `test_leases_api.py`, `test_lease_release_api.py`,
          `test_compute_contract_api.py`, `test_database.py`, `test_fulfillment_api.py`; the
          VM storefront's `integration/test_fulfillment_context_migration.py`,
          `unit/test_fulfillment_provisioning.py`, `unit/test_fulfillment_resume_runtime.py`,
          `unit/test_fulfill_vm_obligation_error_handling.py`,
          `unit/services/test_admin_settle_service.py`, `integration/test_settle_controller.py`,
          and `integration/test_admin_api.py`. The section's suites, the root aggregate, packaging,
          hygiene, citations, and OpenSpec strict (1.14.0) pass.
        - End-to-end: run 37581956819, on the 5B.12.D checkpoint that carries this slice;
          see 5B.12.D's note.
  - [x] 5B.12.D Lease registration removed. The gate was decided on 2026-10-06
        (`design.md`, "5B.12.D decision gate (2026-10-06)"): a lease with no negotiated
        start begins at commit, for every domain; commit is write-once and records the
        deal's escrow where a hold lacks one; provisioning records the target when a
        fulfillment becomes active. Done 2026-10-06:
        - Registration is gone end to end (`LeaseRegistration`, `register_lease`, the route
          and its contract, `fulfillment_targets.py`); convergence's `_apply_create_success`
          records the target in its transaction, best-effort like the create handle (it
          never fails a running workload; teardown reads the fulfillment's own metadata); a
          migration records the target for existing active job-backed fulfillments.
        - Found and fixed: the VM resume pass never committed a recovered deal's reservation
          before its fulfillment began (now `_commit_recovered_reservation`); bare metal's
          escrow path reserved but never committed. Both bare-metal paths take their window
          from what commit returns (`lease_window.py`).
        - Spec deltas: `physical-provisioning` ("fixed once recorded"; "A committed
          allocation's lease records its executor target"; removes "Lease registration
          tolerates omitted identity hints"), `site-capacity` ("Commit begins a lease once and
          never resurrects one"), `compute-provisioning-contract`, `vm-storefront-fulfillment`,
          and `storefront-publication`.
        - Evidence: site write-once and escrow tests; service convergence and migration
          tests; VM storefront commit-once and resume tests. The hosted path's
          commit-then-materialize has no unit test; the bare-metal lane proves it. The
          section's suites, the root aggregate, packaging, hygiene, citations, and OpenSpec
          strict (1.14.0) pass.
        - Routed to closeout task 2.6: no production path writes `executor_ref`; an
          authenticated request matching no route contract answers 500; the deferred "on
          activation" start rule (storefront policy with an optional pool listing hint) is an
          open gap. The 2.6 finding about a commit re-recording a truncated window is retired.
        - End-to-end (run 37581956819, 5B.12.C and 5B.12.D together): VM lane 135 and
          bare-metal lane 16 passed; no traceback, 5xx, 401, or 403, and no request reached
          the removed route; stage 09c found both full deals' leases by escrow, active.
  - [x] 5B.12.D.D Fixes from the implementation review of 5B.12.C and 5B.12.D (2026-10-07;
        `design.md`, "Implementation review of 5B.12.C and 5B.12.D").
        - `_record_executor_target` catches only `ProviderConfigInvalidError` and
          `CapacityConflictError`; anything else rolls the activation back for the next
          cycle. `run_cycle` ends with `reconcile_lease_targets`, whose counts join the
          `fulfillment_recovery_diagnostics` log event as `lease_targets` (a raising sweep
          is logged and does not stop the cycle).
        - The guest name is pinned in
          `domains/vms/provisioning/adapter/tests/unit/test_vm_fulfillment_plan.py`:
          `fulfillment_guest_name("alloc-1") == "tenant-ea780533c5915a9b85ba26b9"`.
        - The VM fulfillment-failed handler takes the request's escrow, else the
          reservation's `escrow_uid`, else its `deal_ref`'s.
        - Routed to closeout task 2.6: the fulfillment-failed callback has no production
          sender; a deliberate operation to resolve a differing recorded target is needed
          once anything acts on the site's target.
        - Evidence: `tests/integration/test_fulfillment_convergence.py`,
          `tests/integration/test_lease_target_reconciliation.py`, the VM adapter's fixed
          vector, the VM storefront's `tests/integration/test_admin_api.py`. The section's
          suites, the root aggregate, packaging, hygiene, citations, and OpenSpec strict
          (1.14.0) pass.
        - End-to-end (run 37590585800): VM lane 135 and bare-metal lane 16 passed; no
          traceback, 5xx, 401, or 403, and no "diagnostics query failed". The lanes' log
          format omits structured fields, so the run proves the sweep never failed a cycle,
          not what it counted.
  - Each slice's gate: the provisioning-family suites, both adapters, both storefronts (the
    VM storefront by frozen sync), the e2e unit suite and collection, the root aggregate,
    `make check-packaging`, comment hygiene, documentation citations, OpenSpec strict
    validation (1.14.0), and both end-to-end lanes.

## 6. Bare metal on the kit negotiation runtime

Decisions: "Bare metal negotiates through the kit runtime", refined by "Section 6 design:
bare metal on the negotiation runtime (2026-10-07)" (decisions 1–13 below are that
section's). Replanned 2026-10-07 after the design and its review. 6A builds in kit what
the compute storefronts share and rebinds VM and API credits to it; 6B then moves bare
metal onto it. Each keeps both lanes green. Implementation findings are in that design
section's "Implementation findings (6A and 6B)".

The original tasks, kept for their history:

- [x] 6.1 **Superseded.** The re-verification was done in the 2026-10-07 audit
      (`negotiation_service.py`, `negotiation.py`, the negotiate routes, and
      `persist_bare_metal_opening` are domain-local; nothing imports the runtime).
- [x] 6.2 **Superseded** by 6B.2 and 6B.3: bare metal places no hold (decision 1), and
      the listing recheck is the runtime's (decision 2), not `validate_opening`'s.
- [x] 6.3 **Superseded** by 6B.4 and 6B.5.
- [x] 6.4 **Superseded** by 6B.6. Its conformance-matrix item needs nothing: the domain
      conformance suite already runs under the bare-metal contract and does not cover
      negotiation.
- [x] 6.5 **Superseded** by 6A.8 and 6B.8.

### 6A. Shared negotiation behaviour, with VM and API credits rebound

Decisions 2, 3, 4, 8, and 12. Reviewable alone: the policy, negotiation-runtime, and
storefront kits, and the VM and API-credit storefronts; bare metal changes only its pins.

- [x] 6A.1 Policy kit (`kit/policy`): `src/market_policy/listing_source.py`
      (`ListingSourceVerdict`, `ListingSourceRefusal`, and `classify_listing_source`, the
      one pure classifier: a declared mismatch is `no_matching_declaration`, an
      unavailable listing `no_matching_inventory`, an unverifiable one a retryable
      `listing_source_unverifiable`), and `has_matching_inventory_guard`, registered there
      under its existing name with no `gpu_model` condition; `NegotiationContext` and
      `SellerRoundHook` carry `listing_source`. Tests: `tests/unit/test_listing_source.py`,
      run in the negotiation runtime's environment (the policy kit's own needs the PyTorch
      index).
- [x] 6A.2 Negotiation runtime (`kit/negotiation-runtime`): `NegotiationUnavailableError`;
      the optional `check_listing_source` hook, asked after an opening's pause and liveness
      checks, before a counter's evaluation, and after resumption in both acceptances,
      never on exit; a refusal rejects (or raises `OfferUnfulfillableError`), a retryable
      one raises `NegotiationUnavailableError`, before any write; success is written last,
      after `_commit_acceptance` (decision 8); a thread holding an `accept_offer`,
      `agreed_at`, or `settlement_plan` refuses resumption except exit. Tests:
      `tests/unit/test_runtime.py`, `tests/unit/test_listing_source.py`,
      `tests/unit/test_opening_preview.py`, `tests/unit/test_administrative_acceptance.py`.
- [x] 6A.3 Storefront kit (`kit/storefront`): `src/market_storefront_kit/trading_pause.py`
      (`TradingPause`, one process-local flag separate from the lifecycle pause, and
      `TradingPauseRouteService`); `StageEventRouteService.signed_resource(query)` builds the
      resource the canonical client signs and refuses an unknown or repeated parameter or a
      stream request (400); force-accept maps `OfferUnfulfillableError` to 409 and
      `NegotiationUnavailableError` to 503. Tests: `tests/unit/test_trading_pause.py`,
      `tests/unit/test_deal_control_routes.py`.
- [x] 6A.4 VM: the guard leaves VM's policies for the policy kit; `listing_source_check.py`
      returns a verdict (an unloaded projection or unreadable snapshot is `unverifiable`);
      the runtime composes `check_listing_source` and reads the process's `TradingPause`
      (`_GLOBALLY_PAUSED` goes); the kit's `signed_resource` replaces VM's own; the
      negotiate routes map 409 and 503. `docs/configuration.md` describes the recheck.
      Tests: `tests/unit/test_listing_source_check.py`,
      `tests/unit/test_sync_negotiation_seller_round_hook.py`,
      `tests/unit/test_order_pause_state.py`,
      `tests/integration/test_negotiate_controller.py` (a buyer's accept after the source
      changed answers 409, after it became unreadable 503),
      `tests/integration/test_admin_api.py`; the guard's name resolves from the policy kit
      in `tests/integration/test_publication_loop.py`,
      `tests/unit/test_file_policy_discovery.py`, and `tests/unit/test_config_loader.py`.
- [x] 6A.5 API credits: `server.py` holds the process's `TradingPause`; a new
      `controllers/trading_pause_controller.py` binds pause and resume as `admin_pause` and
      `admin_resume`, the canonical client's contract; the system controller uses the kit's
      `signed_resource`; the negotiate routes map 409 and 503. Tests:
      `tests/integration/test_sync_negotiation.py` (paused refuses with 503 until resumed),
      `tests/integration/test_force_accept_api.py`.
- [x] 6A.6 Deltas, written with this plan: `market-composition`'s "Kit-owned synchronous
      negotiation runtime" (the source check, the retryable refusal, success last, and the
      resumption rule), its "Storefront deal controls are kit-owned route services" (the
      event read's signed resource and force-accept's refusals), and a new "The trading
      pause is one process-local kit mechanism"; `storefront-publication`'s "The seller's
      inventory guard checks a listing against its own source".
- [x] 6A.7 Versions and locks: bumped and cascaded through `cascade_pins.py`; the
      wheelhouse rebuilt cleanly; relocked, with the hand-locked projects locked by hand.
- [x] 6A.8 **Gate.** The policy kit's new tests (in the runtime's environment), the
      negotiation-runtime and storefront kits, VM negotiation, the VM storefront by frozen
      sync, the API-credit storefront, the bare-metal storefront (pins only), the e2e unit
      suite and collection, the root aggregate, `make check-packaging`, comment hygiene,
      documentation citations, OpenSpec strict validation (1.14.0), pyflakes on edited
      modules, and both end-to-end lanes.
  - Done 2026-10-07: every suite above passes (the policy kit's 60 in the runtime's
    environment), the root aggregate fails only the known environmental cases, and
    packaging, hygiene, citations, OpenSpec strict, and pyflakes pass.
  - End-to-end: run 101918963768, on the 6B checkpoint (6A and 6B together), passed the
    VM lane (135) and the bare-metal lane (16); no traceback, 5xx, source refusal, or
    interrupted acceptance.

### 6B. Bare metal on the runtime

Decisions 1, 5, 6, 7, 9, 10, and 11. Reviewable alone: the bare-metal domain and
storefront.

- [x] 6B.1 Domain (`domains/bare_metal`): `inventory_guard.py`'s
      `recheck_bare_metal_listing_source` reports a taken Physical Resource as its own
      outcome, read from the resource-pool projection the recheck already fetches;
      `tests/test_inventory_guard.py` covers it.
- [x] 6B.2 Runtime hooks: a new
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/negotiation_runtime.py`
      building the `NegotiationRuntime`: the continuation requires the listing's current
      binding to equal the thread's (decision 9); `decode_terms` reads the closed
      `bare_metal.v1` message; `check_listing_source` runs the recheck (moved to
      `listing_source_check.py`); an exact-option opening is accepted at the trusted
      option's amount without price policy (decision 6); `agreement_terms` names no start,
      so the lease begins at commit; `build_artifacts` builds the escrow plan with the
      seller wallet and chain configuration verify uses (decision 7); no hold (decision 1);
      `BareMetalNegotiationRefusal` carries the domain's 400, 404, and 409 (decision 10).
- [x] 6B.3 Seller policy: `negotiation.py` runs the domain's checks ahead of a chain read
      from `BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES`, defaulting to `escrow_shape_guard`
      and `listed_price`, with `has_matching_inventory_guard` prepended (decision 11);
      `docs/configuration.md` documents the variable.
- [x] 6B.4 Composition and routes: `runtime.py` composes the negotiation runtime, the
      `TradingPause`, and the chain; `api.py` serves `negotiate/new` and `negotiate/{id}`
      over the runtime (domain refusals at their status, pause and unverifiable 503,
      unfulfillable 409, unknown negotiation 404) and binds the stage-event read,
      evaluate-negotiate, force-accept, and pause and resume over the kit route services.
- [x] 6B.5 Removal and migration: tombstone `negotiation_service.py`;
      `sqlite_client.py` loses `persist_bare_metal_opening`, `is_global_paused`, and
      `set_global_paused`; `migrations.py` gains one migration that marks every
      non-terminal thread `abandoned` (decision 5) and drops `bare_metal_operator_state`.
- [x] 6B.6 Tests (`domains/bare_metal/storefront/tests`): `test_negotiation_runtime.py`
      (the plan builder's inputs, the recorded terms); `test_negotiation.py`;
      `test_http_negotiation.py` through the canonical client (multi-round under a
      countering chain; force-accept records terms and plan and reserves nothing;
      evaluate-negotiate refuses what `negotiate/new` refuses; source mismatch, taken
      machine 409, and unreadable site 503 at every path; the response's plan, the
      committed plan, and settle verify's rebuild equal, run against the development
      chain's address book; the domain's own refusal statuses kept, while seller-policy
      outcomes follow the configured chain — an opening below the listed rate under the
      default chain is an `exit`, 200; amended 2026-10-07 after the implementation
      review); `test_migrations.py`; `test_http_system.py`; `test_runtime_environment.py`
      (the chain configuration, planned for `test_app_composition.py`);
      `tests/seeded_threads.py` seeds threads with the runtime's writes for
      `test_persistence.py` and `test_http_settlement.py`; `test_selection_dispatch.py`
      dispatches through the runtime hooks.
- [x] 6B.7 Versions and locks: `arkhai-bare-metal-storefront` 0.11.0 and the domain's
      bump, cascaded through `cascade_pins.py`; the bare-metal storefront relocked and
      hand-locked from its snapshot form.
- [x] 6B.8 **Gate.** The bare-metal domain and storefront suites, the e2e unit suite and
      collection, the root aggregate, `make check-packaging`, comment hygiene,
      documentation citations, OpenSpec strict validation (1.14.0), pyflakes on edited
      modules, and both end-to-end lanes (the bare-metal lane's publication scenario
      unchanged).
  - Done 2026-10-07: every suite above passes; packaging, hygiene, citations, OpenSpec
    strict, and pyflakes pass.
  - Routed to closeout task 2.6: the policy kit's refusal of an unknown middleware name
    tells the operator to import "the VM policy package". The Compose wrapper does not
    forward `BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES`; 9.5 sets it for the lane.
  - End-to-end: run 101918963768 (6A and 6B together) passed the VM lane (135) and the
    bare-metal lane (16); the publication scenario ran unchanged over the runtime.

### 6C. Fixes from the implementation review of 6A and 6B

Decided with the maintainer (`design.md`, "Implementation review of 6A and 6B
(2026-10-07)"). Reviewable alone: the negotiation runtime's resumption rule and the
bare-metal storefront's force-accept and continuation.

- [x] 6C.1 Runtime: `_refuse_incomplete_thread` refuses a counter, accept, or force-accept
      on a non-terminal thread unless its transcript ends with the seller's counter, as well
      as one whose agreed terms or plan are recorded; exit is still served.
      `tests/unit/test_runtime.py` covers each action and exit.
- [x] 6C.2 Bare metal: force-accept answers a `BareMetalNegotiationRefusal` as
      `negotiate/{id}` does (also covering a listing whose payload no longer decodes); a
      continuation with no recorded opening message is refused.
      `tests/test_http_negotiation.py` covers both (409, thread still open).
- [x] 6C.3 Documents: the `market-composition` and `storefront-publication` deltas state
      the implemented precedence (a seller decision that would counter or accept, and
      every acceptance, is refused as retryable for an unconfirmable source; an
      independent rejection or exit keeps its reason), with a scenario for it; the
      runtime requirement's resumption rule and a scenario for a round interrupted before
      the seller answers; 6B.6's status-code wording; the promotion record's row.
- [x] 6C.4 **Gate.** The negotiation-runtime and storefront kits, the VM storefront by
      frozen sync, the API-credit and bare-metal storefronts, the e2e unit suite and
      collection, the root aggregate, `make check-packaging`, comment hygiene,
      documentation citations, OpenSpec strict validation (1.14.0), pyflakes on edited
      modules, and both end-to-end lanes.
  - Done 2026-10-07: every suite and check above passes.
  - End to end: run 37748279841, on the Section 7 build (which carries 6C), passed
    the VM lane (135) and the bare-metal lane (16).

## 7. Bare-metal settlement, fulfillment, and release

**Planned 2026-10-07.** Decisions: "Section 7 design: one explicit settlement composition
(2026-10-07)" (composition decisions 1 to 7) and "Section 7 design: bare-metal Alkahest
delivery, scope narrowed (2026-10-07)" (decisions 8 to 13), on top of the decisions named
above. The unified fulfillment path those designs considered belongs to
`kit-owned-listing-and-fulfillment-lifecycles`. 7A to 7D each end with a gate and a
checkpoint; the order is 7A, 7B, 7C, 7D.

- [x] 7.1 **Superseded** by 7B.1 (the worker composed inside the runtime) and 7C.3 to
      7C.5 (the dispatch tables, verify stepping the worker, `begin` removed).
- [x] 7.2 **Superseded** by 7C.1 (the lease client) and 7C.4 (verify registers the
      committed plan).
- [x] 7.3 **Migrated** to 5B.8.B.3 (`design.md`, "Controls and routes (5B.8)", decision
      1): provider-neutral release lands with the mode-agnostic lease lifecycle.
- [x] 7.4 **Superseded** by 7D.1 and 7D.2.
- [x] 7.5 **Superseded** by 7D.3.
- [x] 7.6 **Superseded** by the test tasks of 7A to 7D.
- [x] 7.7 **Superseded** by 7D.4.
- [x] 7.8 **Superseded** by the gates of 7A to 7D.

### 7A. Kit: parked fulfillment, the Alkahest publisher, and the status count

Decisions 11 and 13. Reviewable alone: `kit/settlement-runtime`, `kit/alkahest`, and
`core/storefront-client`; no domain uses the new surfaces yet.

- [x] 7A.1 Settlement runtime (`kit/settlement-runtime`): under the held `fulfill` lease,
      `record_fulfillment_submission` and `record_fulfillment_publication` (first-write-wins:
      the same value is a no-op, a different one raises), `clear_fulfillment_submission`
      (an intent with no reference only), and `park_fulfillment` (`manual_required` with its
      reason in the mechanism state, kept by a later status write, since a fulfillment has
      no lifecycle column); `reserve_fulfillment`'s pending outcome carries the intent,
      reference, and attempt count; `count_manual_required()` counts each obligation once.
- [x] 7A.2 Alkahest kit (`kit/alkahest`): `src/market_alkahest/fulfillment_publisher.py`'s
      `AlkahestFulfillmentPublisher.publish(*, condition_anchor, data)` submits a string
      obligation and classifies the result as `published`, `not_submitted`, `rejected`, or
      `outcome_unknown`. The pinned client reports failures only as messages: a refusal or
      revert (`revert`, `insufficient funds`, `nonce too low`, the gas refusals) is
      rejected; `already known` is deliberately not, since that transaction may still be
      mined; anything else is outcome unknown. Discovery of an existing attestation is
      `add-alkahest-attestation-reference-query`'s.
- [x] 7A.3 Storefront client (`core/storefront-client`): `HealthResponse` gains
      `settlement_manual_required` (on `/api/v1/system/status` only).
- [x] 7A.4 Tests: `kit/settlement-runtime/tests/integration` (intent and reference
      survive an expired lease; first-write-wins; clearing; no write without the lease; a
      parked fulfillment is not due; the count);
      `kit/alkahest/tests/unit/test_fulfillment_publisher.py`
      (each outcome, exact submitted data); `core/storefront-client/tests`.
- [x] 7A.5 Delta: `specs/settlement-servicing/spec.md` adds "A fulfillment submission with
      an unknown outcome is never repeated" (written with this plan). It states the
      invariant for any external publication; hosted publication already satisfies it
      through its stable operation identity and changes nothing.
- [x] 7A.6 Versions and locks: the three bumps, cascaded through `cascade_pins.py`;
      hand-locked projects relocked by `handlock.py`; `e2e-tests` relocked.
- [x] 7A.7 **Gate.** The settlement-runtime, Alkahest, and storefront-client suites, the
      root aggregate, `make check-packaging`, comment hygiene, documentation citations,
      OpenSpec strict validation (1.14.0), pyflakes on edited modules, and the VM and
      bare-metal lanes unchanged.
  - Done 2026-10-07: the suites (9 new settlement-runtime integration tests), the root
    aggregate (known failures only), packaging, hygiene, and pyflakes pass. Lanes: run
    37839861525 (7F.4).

### 7B. Bare metal: one explicit settlement composition and its deployment inputs

Composition decisions 1, 2, 3, 6, and 7. Reviewable alone: the bare-metal storefront's
startup and composition, its Helm chart, its Compose files, and their documentation; the
Alkahest path still waits for `begin`.

- [x] 7B.1 `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py`:
      startup refuses without `BARE_METAL_STOREFRONT_SETTLEMENT`; Alkahest resources are
      required whenever the Alkahest section is configured, enabled or not, and refused
      without one; the hosted callbacks are built whenever the Stripe section is
      configured (checked at the composition's `configures`); `__post_init__` composes the
      `SettlementServicingWorker` whenever there is a settlement composition; with none,
      dispatch is empty and settlement reports unavailable (the
      `default_hosted_selection_dispatch()` fallback goes).
- [x] 7B.2 Helm chart (`helm/charts/bare-metal-storefront`, chart 0.1.0 → 0.2.0): drops
      `alkahestEnabled`; gains `chains`, `walletKeySecret`, and `alkahestAddressBook`;
      renders the three Alkahest variables only when the group is set and fails rendering
      on a partial group.
- [x] 7B.3 Compose: `compose.bare-metal.yml` forwards
      `BARE_METAL_STOREFRONT_CHAINS=${BARE_METAL_STOREFRONT_CHAINS_JSON:-}` and reads an
      optional wallet credential file (`BARE_METAL_STOREFRONT_WALLET_ENV_FILE`);
      `compose.bare-metal-local.yml` stops setting the chains and key; the root
      `Makefile`'s `e2e-bare-metal-dev-env` writes the lane's wallet file.
- [x] 7B.4 Tests: `tests/test_runtime_environment.py`; `tests/test_http_settlement.py`
      (including its restart test) and `tests/test_settlement.py` over the real composition
      (`tests/settlement_compositions.py`); `tests/test_app_composition.py`;
      `tests/test_http_negotiation.py`, `tests/test_http_system.py`, and
      `tests/test_selection_dispatch.py` (a composition where they relied on the hosted
      fallback);
      `helm/charts/bare-metal-storefront/tests/test_render.py`;
      `scripts/tests/test_bare_metal_compose.py`;
      `e2e-tests/tests/unit/test_domain_stack_configuration.py`.
- [x] 7B.5 Documentation: `docs/development/DEPLOYMENT_AND_CONFIG.md` (the settlement
      root is required; the chart's and Compose's Alkahest inputs);
      `docs/bare-metal-seller-quickstart.md` (the Alkahest inputs are required while the
      section is configured; the wallet file; Compose 2.24 or later for the optional
      file).
- [x] 7B.6 Versions and locks: `arkhai-bare-metal-storefront` 0.11.2 → 0.12.0, cascaded;
      the storefront hand-locked; `e2e-tests` relocked.
- [x] 7B.7 **Gate.** The bare-metal storefront suite, the chart's render tests (or, if
      `helm` cannot run here, recorded as unrun), the Compose and e2e unit tests, the root
      aggregate, `make check-packaging`, comment hygiene, documentation citations,
      OpenSpec strict validation, pyflakes, and both lanes.
  - Done 2026-10-07: the bare-metal storefront, VM storefront, and e2e unit suites pass.
    Unrun at the time: the chart's render tests (no `helm`) and
    `scripts/tests/test_bare_metal_compose.py` (no Compose; it skips); 7F.4's local
    evidence includes the Helm render checks. Lanes: run 37839861525 (7F.4).

### 7C. Bare metal: Alkahest delivery through the worker

Composition decisions 4 and 5, and decisions 8 to 13. Reviewable alone: bare-metal
settlement, fulfillment, and evidence; teardown still releases directly.

- [x] 7C.1 `site_clients.py`: `SelectedSiteFulfillmentClient` gains `get_lease` and
      `terminate_lease` over `compute_provisioning_client`, routed by the reservation's
      recorded site.
- [x] 7C.2 Domain (`domains/bare_metal`): the lease-ready evidence takes either accepted
      binding, `bare_metal.accepted-hosted-binding.v1` (unchanged) or a new
      `bare_metal.accepted-alkahest-binding.v1` with the escrow as condition anchor.
- [x] 7C.3 The Alkahest step, `alkahest_lifecycle.py`: by what the reservation reports, an
      intent and a UID completes with it; an intent and no UID parks
      (`alkahest_submission_outcome_unknown`); neither starts or finds the fulfillment,
      defers until the lease is active, then stores the evidence once (first-write-wins),
      records the intent, and publishes the digest. `not_submitted` retries; `rejected`
      retries to a bound of three, then parks (`alkahest_submission_rejected`);
      `outcome_unknown` parks. The evidence and its unique digest are stored on
      `bare_metal_fulfillment_lifecycle`; the UID lives only in the kit journal and the
      obligation's fulfillment reference.
- [x] 7C.4 Dispatch and settlement: `runtime.py`'s ready and terminal tables (an
      uncollected Alkahest obligation whose fulfillment started terminates its lease;
      anything unknown raises); the hosted lifecycle, the Alkahest step, and the worker are
      composed in `__post_init__`, not constructor fields, so a copied runtime composes its
      own. `settlement_service.py`'s `verify` reads the plan committed at acceptance,
      registers it, adopts the obligation, and steps the worker once.
- [x] 7C.5 Routes: `POST /api/v1/fulfillments/begin` and `BareMetalFulfillRequest` are
      removed (and the buyer's `begin()`); the evidence route requires a signed request
      (unsigned is 401) and admits by binding; status adds `settlement_manual_required`.
      Nothing in this repository calls the evidence route, so the hosted authority's signed
      read is unexercised here.
- [x] 7C.6 Delta: `specs/storefront-publication/spec.md`'s "Complete bare-metal seller
      lifecycle" gains the startup, evidence, unknown-outcome, resolution, and
      uncollected-terminal scenarios (written with this plan).
- [x] 7C.7 Tests: `tests/test_http_settlement.py` (verify registers exactly the committed
      plan, refuses a thread with none, steps the worker once; a failed attempt retried
      only by the worker's schedule); `tests/test_alkahest_lifecycle.py` (every outcome
      and restart case, through the real composition with the publisher's chain client
      doubled); `tests/test_hosted_lifecycle.py`; `tests/test_site_clients.py`;
      `domains/bare_metal/tests/test_evidence.py`;
      `domains/bare_metal/buyer/tests/test_buyer_composition.py`. Corrected 2026-10-08: the
      evidence-route coverage lacked the claimant, which the route did not admit; both
      fixed in 7E.2.
- [x] 7C.8 Versions and locks: `arkhai-bare-metal` 0.10.0,
      `arkhai-bare-metal-storefront` 0.13.0, `arkhai-bare-metal-buyer` 0.5.0, cascaded;
      the storefront hand-locked; `e2e-tests` relocked.
- [x] 7C.9 **Gate.** The bare-metal domain, storefront, and buyer suites, the root
      aggregate, `make check-packaging`, comment hygiene, documentation citations,
      OpenSpec strict validation, pyflakes, and both lanes.
  - Done 2026-10-07: the bare-metal storefront (13 in `test_alkahest_lifecycle.py`),
    domain, buyer, and e2e unit suites pass; pyflakes reports nothing new. Lanes: run
    37839861525 (7F.4).

### 7D. Bare metal: teardown, deal controls, the publication dry run, and restart

The rest of the original Section 7. Reviewable alone: release and deal controls.

- [x] 7D.1 Teardown through lease termination: teardown and an uncollected Alkahest
      settlement both go through `BareMetalFulfillmentService.end_lease`, which terminates
      the lease at the reservation's site and records the lifecycle `terminating`; the
      teardown route still returns the lifecycle projection. The lifecycle records
      `released` only from the capacity-released callback, which requires the authority of
      the site the event names.
- [x] 7D.2 Deal controls: `deal_controls.py` supplies the hooks for settle verify,
      evaluate-settle (no writes), settle wait, and admin reserve, bound through the kit's
      route services under the contracts the canonical client signs.
- [x] 7D.3 Publication dry run: `BareMetalPublicationCycle.run(dry_run=True)` writes and
      publishes nothing and reports the publishes, closes, refreshes, reopens, and holds a
      pass would make; the publication step registers it as its preview.
- [x] 7D.4 Restart integration tests (task 3.5; 3.6 is withdrawn):
      `tests/test_restart_recovery.py` rebuilds the application over the same database file
      with the same site and chain doubles, after verification, after a recorded
      publication, and after teardown (`tests/loopback.py` serves the application).
- [x] 7D.5 Tests: `tests/test_fulfillment_service.py` (teardown through terminate, a
      repeated teardown returns the same lease, release only on the callback);
      `tests/test_publication_cycle.py` (the preview applies nothing);
      `test_deal_controls.py`. The bare-metal expiry through the aggregate is proven in
      5B.8.B.3's `test_lease_release_api.py`.
- [x] 7D.6 Versions and locks: `arkhai-bare-metal-storefront` 0.14.0, cascaded.
- [x] 7D.7 **Gate.** The bare-metal storefront, buyer, provisioning, and
      provisioning-service suites, the root aggregate, `make check-packaging`, comment
      hygiene, documentation citations, OpenSpec strict validation, pyflakes, and both
      lanes.
  - Done 2026-10-07: the suites, the root aggregate (covering 7C too; known failures
    only), packaging, hygiene, citations, OpenSpec strict (1.14.0), and pyflakes pass.
    Lanes: run 37839861525 (7F.4).

### 7E. Fixes from the implementation review of Section 7

The implementation review of 7A to 7D (2026-10-08), with the maintainer's dispositions.

- [x] 7E.1 The Alkahest publisher takes `chain_tx_lock(None)`, the lock every other
      Alkahest submission from the wallet takes (materialize, collect, reclaim, VM's
      fulfillment and listing submissions), so it cannot race them for a nonce and
      misread the result as a rejection; its unused `chain_name` argument goes.
      `kit/alkahest/tests/unit/test_fulfillment_publisher.py` holds the lock as
      another operation would and checks the publication waits.
- [x] 7E.2 The evidence route admits the evidence's claimant, signing as `seller`, as
      the `storefront-publication` delta says; a role with no reader is refused by
      authentication itself, so the refusal is signed.
- [x] 7E.3 The evidence route follows the five-piece route pattern
      (`docs/development/ARCHITECTURE.md`, "Route contracts and their HTTP binding"):
      `arkhai_bare_metal/evidence_routes.py` holds its wire model, route contract, route
      service, and typed clients over the storefront client's `authenticated_request`;
      `api.py` only binds it; every response, refusals included, is signed. Evidence:
      `test_alkahest_lifecycle.py` (through the typed client per principal, stranger and
      wrong-binding refusals, 404) and `domains/bare_metal/tests/test_evidence_routes.py`.
      The pre-closeout review replaced a first form (a `core_buyer` helper and a client in
      the bare-metal buyer); both are reverted.
- [x] 7E.4 The rejection bound counts refusals, not reservations: migration `0013`
      adds `evidence_rejections` to `bare_metal_fulfillment_lifecycle` (it had not been
      released), `record_bare_metal_evidence_rejection` counts one, and the step parks
      at the third. A new test defers on a provisioning lease three times before the
      first refusal, which does not park.
- [x] 7E.5 `commercial_settlement` follows VM's and API credits' convention: `ok` while
      Alkahest or hosted settlement is enabled, `unconfigured` when the settlement
      root enables no payment mechanism (none, or contact exchange only), and
      `unavailable` with no composition; `status` counts `unconfigured` as healthy,
      as theirs does.
- [x] 7E.6 Versions and locks: arkhai-kit-alkahest 0.4.1, arkhai-bare-metal 0.11.0,
      arkhai-bare-metal-storefront 0.14.2, cascaded; arkhai-core-buyer and
      arkhai-bare-metal-buyer unchanged (0.3.6 and 0.5.0).
- [x] 7E.8 From the pre-closeout review (2026-10-08): `design.md` decision 11 now
      states the refusal count rather than the operation's journal attempts, and
      decision 12 records the evidence route's placement; the wallet-lock test yields
      to the event loop instead of sleeping on the wall clock.
- [x] 7E.7 **Gate.** The core buyer, Alkahest kit, and bare-metal storefront and buyer
      suites, the VM storefront and buyer, the root aggregate, `make check-packaging`,
      comment hygiene, documentation citations, OpenSpec strict validation, pyflakes,
      and both lanes; then 7A.7, 7B.7, 7C.9, and 7D.7 close with the same run.
  - Before 7E, run 37748279841 passed both lanes on 7A to 7D's build (VM 135, bare metal
    16), the bare-metal storefront starting with the required settlement configuration.
  - Done: every suite above passes; the root aggregate passed 53 suites with only VM's
    known `test_alkahest` failures. An earlier aggregate hit the shared in-memory SQLite
    race recorded in 2.6 ("cannot commit - no transaction is active"); the provisioning
    integration suite then passed four consecutive runs. Packaging, hygiene, citations,
    OpenSpec strict, and pyflakes pass. Lanes: run 37839861525 (7F.4).

### 7F. Reconcile the Arkhai payments merge

- [x] 7F.1 Preserve explicit configuration, committed-plan verification, and the
      Alkahest servicing step in bare-metal `runtime.py` and
      `settlement_service.py`; retain payment receipt settlement and reconciliation.
      Keep Agreement timestamps and opaque settlement data in the negotiation
      runtimes. Resolve the client and test callers to `settle_evm`.
- [x] 7F.2 Retain Alkahest `evidence.py`, `evidence_routes.py`, the storefront
      resolver and evidence persistence, removing their hosted dependencies and
      authority reader. Reconcile `migrations.py`, `models.py`, and
      `deal_controls.py`; remove the retired hosted lifecycle and tests.
- [x] 7F.3 Reuse existing wheel versions in the affected `pyproject.toml` files
      and regenerate locks through `make lock`. Reconcile the aggregate Make
      targets, deployment reference, seller quickstart, and this change's deltas.
      Align `helm/Chart.yaml` with the existing bare-metal chart version, and add
      the storefront-client wheel to the API-credit distribution-test fixture.
- [x] 7F.4 Validate the merged tree: focused suites, the root aggregate, typing where
      supported, packaging, hygiene, citations, and strict OpenSpec validation; record
      failures and unrun checks; confirm end-to-end evidence separately.
      - Local evidence (2026-10-08): every root unit and integration target passed,
        including the Python, TypeScript, and Rust middleware suites, e2e unit tests,
        deployment scripts, and Helm render checks; `make check-packaging`, comment
        hygiene, scoped citations, and strict OpenSpec 1.14.0 passed. Registry-client
        typing passed; core typing reports its existing `query_dsl.py:487`
        `ValidatedComparison`/`QueryComparison` assignment error (unchanged on both merge
        parents). The merge adds no function-local imports. Section 7's promotion remains
        with 11.4.
      - End-to-end (2026-10-08): run 37839861525, on the merged tree with Section 8,
        passed both lanes — VM 135 passed with 3 skipped (the payment deal's three
        scenarios, blocked without a reachable payments target, as designed), bare
        metal 16 passed. It is the lane evidence 7A.7, 7B.7, 7C.9, 7D.7, and 7E.7
        name, and closes them with this task. Alkahest delivery, digest publication, and
        collection were first exercised live by Section 9's scenario.

## 8. Shared compute deal stages and the VM scenario

Decisions: "Compute deal stages are shared" and "Section 8 design: the shared stages
against the code (2026-10-08)", decisions 1–7, and its implementation-review fixes.
Behaviour-neutral for VM's happy path: no assertion is weakened, and stage IDs, test
names, and markers are unchanged. 00c checks the family's execution readiness instead of
Ansible's component, 04a reads through the typed registry client, and dependent stages
skip on more failed readiness checks than before (decision 2). Reviewable alone:
e2e-tests only.
Paths below are under `e2e-tests/tests/`.

- [x] 8.1 Move the shared helpers (decisions 4 and 7): `e2e/roles/helpers/escrow.py` (the
      escrow helper, `ensure_ws_rpc_url` public; `e2e/roles/scenarios/vms/escrow_helper.py`
      tombstoned) and `e2e/roles/helpers/compute_deal.py` (`SiteCapacity`, `DealLease`,
      `advance_fulfillment_to`, `wait_for_stage_event`, `delete_mock_rules_if_present`,
      `advance_storefront`, `dry_run_storefront`, `pause_storefront`,
      `convergence_paused`), with no re-export from VM's `conftest.py`; every importer
      (found by an AST scan: `test_full_deal_buyer_cli.py`, `test_buy_oneshot_buyer_cli.py`,
      `test_compute_dynamic_listings.py`, `test_listing_shapes.py`, `test_multi_registry.py`,
      `test_vm_introduction.py`, `test_non_erc20_settlement.py`,
      `unit/test_escrow_helper_rpc_url.py`) repointed and its function-level imports moved
      to module level.
- [x] 8.2 Add `e2e/roles/helpers/compute_deal_stages.py` (decisions 1–3 and 5): VM's deal
      terms, `ComputeDealState`, the `ComputeDealDriver` and `LeaseView` protocols, and one
      base class per shared stage (00 through 11b), each keeping VM's method name,
      docstring, dry-run-then-advance shape, and assertions, with the driver in place of
      VM's settings. The only changes are decisions 2 and 3's: 00c's family readiness,
      04a's typed `get_listing`, and the readiness prerequisites.
- [x] 8.3 Rewrite VM's scenario onto the shared stages (decisions 2, 3, and 5):
      `e2e/roles/scenarios/vms/compute_deal_driver.py` (`VmComputeDealDriver`); VM's
      `DealState(ComputeDealState)` and the `buyer_principal` and `deal_driver` fixtures in
      `conftest.py`; `test_full_deal.py` as one empty `TestStage…(Stage…)` subclass per
      shared stage in VM's order, with VM's own 00f, 02b, 03a, 03b, and 09a2 in place.
- [x] 8.4 Unit test `unit/test_compute_deal_stages.py` (decision 6), reading source with
      `ast`: no shared stage class is collected; each domain subclasses every shared stage
      once, in order, with an empty body; every declared field is read and every required
      field produced and declared. The domain list is one table, so Section 9 adds bare
      metal to it.
- [x] 8.5 **Gate.** The e2e unit suite; identical collection node IDs for both lanes'
      selections before and after; pyflakes; the VM lane with the rewritten scenario.
  - Done 2026-10-08: e2e unit suite 29 passed (7 structural; each of five rules broken
    once failed alone); node IDs identical, in order (VM 138, bare metal 16, all
    `tests/e2e` 165); `pytest --setup-plan` resolves every VM fixture; an AST comparison
    finds every prior assertion in a shared stage, VM's own stage, or VM's driver except
    the two decision 3 changes; pyflakes reports nothing new.
  - Lanes: run 37839861525 passed. VM 135 passed and 3 skipped (the payment deal, no
    payments target); all 32 stages of `test_full_deal.py` passed through the shared
    stages. Bare metal 16 passed.
- [x] 8.6 **Section closeout** (`openspec/README.md#plan-closeout-requirements`, scoped
      to Section 8). Done: comment hygiene (a direct read restated four moved comments that
      narrated earlier failures, and the escrow helper no longer cites a commit); import
      placement (every function-level import the section moved is module level, no cycle);
      documentation compliance (destinations pending for 11.2 `TESTING.md` and 11.4 the
      `test-compatibility` delta); narrative compression; roadmap currency (no change from
      Section 8); campaign index currency (the row names Sections 4–8 implemented);
      citations (no permanent document names a moved helper); packaging (no lock changed);
      end-to-end run 37839861525; promotion pending at 11.2 and 11.4.

- [x] 8.7 Implementation-review fixes (2026-10-08; "Section 8 design", implementation
      review): 10b writes `teardown_fulfillment_id`, which 11a and 11b require, and
      `lease_status` leaves the shared state; 00 sets `_lifecycle_paused`, required by
      00f1 and VM's 00f; 07 requires `_alkahest_configured`; the structural test checks
      producers in each domain's run order, one producer per shared field, and a reader
      after it; the change directory's `design.md:Zone.Identifier` and
      `tasks.md:Zone.Identifier` are tombstoned.
  - Done: e2e unit suite 31 passed (each new rule broken once failed alone); node IDs
    identical; pyflakes reports nothing new. The VM lane ran on these fixes in 9.0b's
    gate.
  - `e2e_non_erc20_settlement` is in neither lane, so its import changes are proven by
    `--setup-plan` and its helper's unit tests, not a lane run.

## 9. The bare-metal mock-provisioned deal

Decisions: "The scenario is VM's deal, stage for stage" and "Section 9 design: the
bare-metal deal on the shared stages (2026-10-08)", decisions 1–7. Depends on Sections
4–8. Reviewable in three parts: the bare-metal storefront (9.0a, 9.0c), the shared
stages' hooks with VM's driver (9.0b, gated by VM's lane), and bare metal's scenario and
lane (9.1–9.5).

- [x] 9.0 **Decision gate** ("Section 8 design: the shared stages against the code
      (2026-10-08)", decision 8). Decided 2026-10-08 in "Section 9 design: the bare-metal
      deal on the shared stages": the bare-metal storefront reports what the shared
      readiness stages read (decision 1); four shared stages gain driver hooks
      (decision 2); 09bb is each domain's own (decision 3).
- [x] 9.0a Bare-metal storefront (decision 1): `BareMetalStorefrontRuntime.status()` adds
      `registry` (through the registry's `reachability`), `negotiation_strategy`
      (`seller_chain_check`, VM's probe and values), and `alkahest`, judged per key as VM's
      are, with `/health` unchanged; `/api/v1/system/status` reports
      `provisioning_contract_version` and admits a bound site's authority principal as
      `service`; the capacity-released hook records a `fulfillment/capacity_released` stage
      event; the buyer's fulfillment status names `evidence_digest` (decision 3, the delta's
      "Evidence is resolved" scenario). Evidence: `tests/test_http_system.py`,
      `tests/test_deal_controls.py`, `tests/test_runtime_environment.py`,
      `test_alkahest_lifecycle.py`. Found: an unsigned registry reply reads as `http_502`,
      since the client verifies a reply before reporting its status; the test pins it.
- [x] 9.0b Shared stage hooks (decisions 2 and 3): `ComputeDealDriver` gains
      `release_create_gate()`, `release_teardown_gate()`, `settle_dispatched(...)`,
      `assert_delivery(deal_state)`, and `release_reserved(reservation)`, which 09a, 08b,
      09b, and 11b call; `Stage09bb_ClaimSubmittedForTheFulfilledEscrow` leaves the shared
      set and becomes VM's own stage; VM's driver keeps VM's current behaviour.
      - Done: the e2e unit suite passes; both lanes' node IDs unchanged; the AST
        comparison finds every VM assertion in place; VM's lane passed in run 37850683369.
- [x] 9.0c Restart recovery (task 3.5; decision 6): `tests/test_restart_recovery.py`'s
      `test_a_restart_while_the_lease_is_active_reads_the_same_delivery`, and the teardown
      restart compares the negotiation, state, reservation, and fulfillment. 3.5 is closed.
      - Found: a restarted process whose site reports a different delivery fails the
        status read as an unhandled 500 (the write-once result conflicts), fail-closed as
        decision 6 records; the untyped error is recorded for 2.6.
- [x] 9.1 Add `scenarios/bare_metal/compute_deal_driver.py`: pool, host, and whole-host
      declaration; bare-metal terms; the bare-metal mock rules and their release;
      `BareMetalDealLease`, reading a whole machine's hold from its declaration's `units`;
      `SiteCapacity.release` in `helpers/compute_deal.py`. Each run's pool, host, resource,
      and rules carry a run suffix, and the rules match on the deal's host.
      - Found: the storefront's begin checks the scheduled resource's
        `bare_metal_publication.host_id` and `physical_host_id`, while the site treats a
        nested `physical_host_id` as legacy; the driver declares it nested and top-level.
        Whether the site keeps the nested field is first seen in 9.6's run; recorded for
        2.6.
- [x] 9.2 Extend `scenarios/bare_metal/conftest.py` with the fixtures the shared stages
      request (Section 8 design, decision 3), plus `site_capacity` and
      `convergence_advanced_explicitly`. `BareMetalDealState` adds the fields bare metal's
      own stages need. `storefront_service_client` is not added: no bare-metal stage or
      hook uses it, so the shared stages no longer name it.
- [x] 9.3 Add `scenarios/bare_metal/test_bare_metal_mock_deal.py`
      (`pytestmark = pytest.mark.e2e_bare_metal_mock_deal`): the shared stages in order,
      with bare metal's own (decision 4) — 03a and 03b (publication dry run and publish),
      09a2 (the listing closes), its own 09bb, and the second deal's stages from 12
      (reopen, second deal, teardown twice returning the same operation, capacity released
      once) — added to `unit/test_compute_deal_stages.py`'s domain table.
      - Done: 35 stages collect; the structural test passes over both domains;
        `pytest --setup-plan` resolves every fixture. Bare metal's 09bb resolves the
        evidence as the buyer through `SyncBareMetalEvidenceClient`.
- [x] 9.4 Register `e2e_bare_metal_mock_deal` in `e2e-tests/pyproject.toml` and add it to
      `E2E_BARE_METAL_MODULE` in `e2e-tests/Makefile`; `e2e_bare_metal_deal` stays in no
      lane. Add `arkhai-bare-metal-buyer` to `e2e-tests/pyproject.toml`, raise
      `arkhai-bare-metal` to 0.11.0 (the evidence route's clients), bump
      `arkhai-e2e-tests`, and relock.
- [x] 9.5 Lane configuration (decision 5): `e2e-tests/config/config-docker.yml`'s
      `bare_metal_lane` gains the buyer's wallet and RPC URL and the seller's wallet
      address, each a well-known development value; `e2e-bare-metal-dev-env` lists the
      publication clause at `10` tokens an hour; the lane's overlay
      (`compose.bare-metal-local.yml`) sets `BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES` to
      `["escrow_shape_guard", "bisection"]` (Section 6 decision 11), since the Compose
      wrapper does not forward that variable (2.6), so stage 05b's round zero counters and
      06b force-accepts an open thread; asserted by
      `scripts/tests/test_bare_metal_compose.py`. The status admission and the callback
      both use the site bindings, so no service-role credential is added (design,
      "Section 9 design", implementation findings).
- [x] 9.6 **Gate.** Both lanes pass: the bare-metal lane with publication, introduction,
      and the mock deal, and the VM lane with 9.0b's hooks. Also: the bare-metal
      storefront, domain, and buyer suites, the VM storefront suite (the exact pin), the
      e2e unit suite, `make check-packaging`, comment hygiene, documentation citations,
      OpenSpec strict validation, and pyflakes.
    - Runs 37850683369 and 37853584444 failed at 05a and 08b: bare metal priced an
      opening naming no escrow contract from nothing, and the driver declared its
      machine as `compute.gpu`, which bare-metal scheduling never places. Both are
      fixed and recorded in design, "Section 9 design", implementation findings. Run
      37896157446 timed out at 09b; 9.6a fixed it.
    - Run 37899278727, on commit 6cfa4650 with 9.6a: both lanes pass, VM 135 passed and
      3 skipped, bare metal 51 passed (publication 11, introduction 5, and all 35
      mock-deal stages). The suites and checks above pass; the VM storefront's two
      Alkahest integration tests need a local Node and Anvil chain the workspace
      lacks.
    - Run 37910886195, on commit ab4a1284 with 9.6b (the code tested here since): both
      lanes pass, VM 135 passed and 3 skipped (the payment deal, with no payments
      target), bare metal 51 passed. 09bb read the escrow's fulfillment attestation
      from the chain rather than inferring it from the stored digest. Jobs took 5m44s
      (VM) and 4m16s (bare metal).
- [x] 9.6a Settlement wait and the repeated teardown (design, "Settlement wait observes
      the selected site (2026-10-09)"). Run 37896157446 timed out at 09b: with servicing
      held, the administrator wait read the storefront's cached dispatch state. The wait
      now reads a begun fulfillment through `BareMetalFulfillmentService.status` and, on the
      transition to active, wakes the escrow's adopted obligation.
      `tests/test_deal_controls.py` has a paused-worker, pending-to-active regression that
      fails without the fix. 12d accepts `teardown_dispatch_pending` on the repeated
      teardown, since termination can dispatch teardown synchronously; 12e still proves one
      release.
    - Checks: route tests, the bare-metal storefront suite, the e2e unit suite, both lanes
      locally (VM 135 passed, 3 skipped; bare metal 51), packaging, chart render, hygiene,
      citations, strict OpenSpec, and pyflakes. The wait scenario is in the
      `storefront-publication` delta, promoted at 11.4.
- [x] 9.6b Pre-closeout review (design, "Section 9 pre-closeout review (2026-10-09)"):
      - 09bb reads publication from the chain: the buyer's fulfillment status names
        `evidence_attestation_uid`; `helpers/escrow.py`'s `read_string_obligation` loads
        it, and 09bb asserts it references the escrow, carries the digest, and is not
        revoked (`test_alkahest_lifecycle.py`).
      - A site authority's status read carries the readiness checks and contract
        version only (`api.py`; `test_http_system.py`; the delta's "A site checks its link
        to the storefront").
      - `ROADMAP.md`: Goal 4's pipeline gap is closed and its state names the lane's
        deal.
      - Checks: the bare-metal storefront suite, the e2e unit suite, fixture resolution,
        packaging, hygiene, citations, strict OpenSpec, and pyflakes.
- [x] 9.7 **Section closeout** (`openspec/README.md#plan-closeout-requirements`, scoped
      to Section 9): comment hygiene, with a direct read of the new modules; import
      placement for every function-level import the section adds or touches;
      documentation compliance against decisions 1–7; narrative compression of
      Section 9's notes; roadmap currency (`ROADMAP.md`'s gap that no bare-metal deal
      runs in the pipeline is closed by 9.6's run, and Goal 7's state names it);
      campaign index currency (this change's row); documentation citations; `make
      check-packaging`; 9.6's run recorded; and promotion pending at 11.2 and 11.4 for
      the `storefront-publication` and `test-compatibility` deltas.
    - Done: roadmap currency (the gap is Goal 4's, closed, and Goal 4's state names
      the lane's deal), narrative compression of 9.6, citations, comment hygiene, and
      packaging, with 9.6b; 9.6's run recorded (37910886195); a direct read of the
      comments and docstrings in `scenarios/bare_metal/compute_deal_driver.py`,
      `test_bare_metal_mock_deal.py`, and `conftest.py` and of every comment the
      section adds elsewhere, each describing present behaviour; import placement,
      where the section adds no function-level import (the function-level imports in
      `vms/conftest.py` and `test_http_negotiation.py` predate it); and this change's
      index row. Section 9's implementation and live gate are complete; its closeout
      stays open only for the 11.2 and 11.4 promotions, since this change promotes
      every delta in Section 11.
    - Closed: the `storefront-publication` and `test-compatibility` deltas are promoted
      at 11.4, and `TESTING.md` at 11.2.
## 10. Pipeline: three lanes, each building and composing its own stack

Decisions: "Section 10 design: each lane builds and composes its own stack
(2026-10-09)", decisions 1–7, refining "API credits runs in its own lane" and "Lane
composition files", and "Section 10 design review: mock provisioning and the plan
against the code (2026-10-09)", decisions 8 and 9. Reviewable alone: compose files, Make
targets, the workflow, the lane settings, the VM storefronts' development configuration,
and the credits scenario's settings; no service code or package version changes.

- [x] 10.1 Split the overlay (decision 3): `compose.vms-local.yml` and
      `compose.apicredits-local.yml` (new, services moved verbatim from
      `compose.local-identities.yml`, which is deleted, since the change commits directly);
      `compose.apicredits.yml` includes only `compose.dev.yml` and
      `domains/apicredits/compose.yml`; `dev-env/identities/api-credits-buyer.config.toml`
      (a development fixture, stated inline); `.gitignore` gains the two lane env files.
      References updated: `dev-env/identities/README.md` (an "API-credit lane" section),
      `scripts/tests/test_multi_storefront_compose.py`,
      `e2e-tests/tests/e2e/roles/README.md`, and
      `openspec/changes/repair-storefront-alkahest-configuration/tasks.md`. The full stack
      renders as before but for the VM storefronts' unread mode variables (10.2a).
- [x] 10.2 The API-credit lane's own topology (decisions 4 and 9):
      `compose.apicredits-lane.yml` (new) adds `compute-registry` with the inputs the
      registry refuses to start without (development values; credential
      `registry-a.eip191`); the root `Makefile`'s `e2e-vms-dev-env` and
      `e2e-apicredits-dev-env`, sharing one internal `e2e-apicredits-stack-env` with the
      full stack, which requires nothing new; `e2e-tests/config/config-docker.yml`'s
      `api_credits` compute-registry settings; `test_credits_deal_buyer_cli.py` reads the
      lane's registries, pins, and buyer settings through `_required` (no storefront
      setting, since discovery finds it); `test_credits_payment_deal.py` keeps its skip
      without a payments target. Render test: `scripts/tests/test_lane_compose.py` (skips
      without Compose).
- [x] 10.2a Mock provisioning chosen per run (decision 8): `PROVISIONING_MODE ?= mock`; the
      environment targets refuse anything but `mock` or `real` and print
      `VMS_PROVISIONING_ACTIVE_PROFILES` and `BARE_METAL_PROVISIONING_ACTIVE_PROFILES`
      (`mock` or `docker`), which the provisioning services' `ACTIVE_PROFILES` read; the VM
      storefronts lose `ARKHAI_PROVISIONING_MODE`, `MOCK_PROVISIONING_SUCCESS`, and
      `PROVISIONING_MODE` from compose and their development configuration (the shipped
      `settings.toml` key is 2.6's); `tools/issue-discovery/config/phases/local.yaml`,
      `targeted_repros.yaml`, and `docs/development/VALIDATION_RUNBOOK.md` follow. Tests:
      `e2e-tests/tests/unit/test_domain_stack_configuration.py`,
      `scripts/tests/test_bare_metal_compose.py`, `test_lane_compose.py`. A full-stack
      render before and after differs only in the removed storefront variables.
- [x] 10.3 Lane builds and targets (decisions 1, 2, and 5): root `Makefile`
      `build-e2e-vm`, `build-e2e-bare-metal`, and `build-e2e-apicredits` over a shared
      `build-e2e-base` (none needs `build-buyer`); `e2e-tests/Makefile` per lane an
      environment file, an explicit compose project, and `test-e2e-<lane>`,
      `e2e-<lane>-down`, and `e2e-<lane>-logs`, with one bring-up recipe (`e2e_up`)
      carrying the failure diagnostics; `E2E_APICREDITS_MODULE` takes both credits markers
      from `E2E_MODULE`; `test-e2e` runs the lanes in turn.
- [x] 10.4 Workflow and diagnostics (decisions 6 and 8): `.github/workflows/e2e.yml` runs
      `e2e-vm`, `e2e-bare-metal`, and `e2e-apicredits` jobs, each uploading its
      `e2e-<lane>-logs` artifact, with `PROVISIONING_MODE: mock` at workflow level and no
      `COMPOSE_PROJECT_NAME`; `scripts/fetch-e2e-logs.py` and
      `scripts/tests/test_fetch_e2e_logs.py` cover the three artifacts;
      `docs/development/TESTING.md` describes three lanes.
- [x] 10.5 **Gate.** The three live jobs pass concurrently, the API-credit lane reporting
      exactly one passed (`e2e_credits_deal`) and three skipped
      (`e2e_credits_payment_deal`, with no payments target). 10.2's render test, 10.2a's
      tests, and the log-fetch tests pass; `pytest --collect-only` with each lane's
      marker expression collects that lane's scenarios and no other's (VM's without the
      credits scenarios, API credits' exactly them). Record each job's wall-clock time
      beside runs 37899278727 (VM 6m55s, bare metal 4m25s) and 37910886195 (VM 5m44s,
      bare metal 4m16s), as an observation, not a threshold. Also: the release-tooling
      suite (`scripts/tests`), the e2e unit suite, `make check-packaging`, comment
      hygiene, citations, and strict OpenSpec validation.
    - Run 37919102415, on commit d30bd2ae: the three jobs pass concurrently. VM 134
      passed, with no credits scenario and no skip; bare metal 51 passed; API credits 1
      passed (`e2e_credits_deal`, through the lane's own compute registry) and 3
      skipped (the payment deal, with no payments target). The bare-metal job builds no
      API-credit image. Job times, an observation: VM 3m48s, bare metal 3m26s, API
      credits 2m31s.
    - Local checks: the render tests (21), `scripts/tests` (208), the e2e unit suite (38),
      each lane's marker expression collecting its own modules only, packaging, hygiene,
      scoped citations, strict OpenSpec (1.14.0), and pyflakes. The repository-wide
      citation check's 15 misses are all in other changes or the validation runbook's
      `scripts/validate/` paths, none new.
- [x] 10.5a Implementation-review fixes (design, "Section 10 implementation review
      (2026-10-09)"):
      - Ordering: `test-e2e`, `build-e2e-base`, `build`, and `build-dev` are recipes of
        recursive calls; `make -n -j6` shows the lanes strictly in turn and the wheels
        before every image.
      - `scenarios/apicredits/conftest.py`'s `lane_setting`, used by both credits
        scenarios; a blanked lane setting fails each scenario, and the payment deal still
        skips without a payments target.
      - Documentation: `domains/bare_metal/compose.yml`'s header,
        `openspec/changes/apicredits-end-to-end-lane/design.md`'s context, and
        `docs/development/VALIDATION_RUNBOOK.md` (compose commands through `$SCM_COMPOSE`;
        a nonexistent `contracts-deploy` service dropped).
      - The root and inventory `.DS_Store` files removed; `.gitignore` ignores them.
      - Checks: the e2e unit suite (38), `scripts/tests` (208), the credits lane's
        collection, hygiene, citations for this change and `apicredits-end-to-end-lane`,
        and packaging.
      - Run 37935829083, on commit 6e1d03c9: the three jobs pass on fresh runners with the
        reordered builds: VM 134 passed, bare metal 51, API credits 1 passed and 3 skipped.
        Jobs took 5m04s, 3m16s, and 2m33s.
- [x] 10.6 **Section closeout** (`openspec/README.md#plan-closeout-requirements`, scoped to
      Section 10): comment hygiene over the compose files, Makefiles, and the VM
      storefronts' development configuration; documentation compliance against
      decisions 1–9; roadmap currency (`ROADMAP.md`'s Goal 4 gap that API credits has no
      lane of its own, which this section closes for the lane and
      `apicredits-end-to-end-lane` keeps for its loops and integration tests); campaign
      index currency (this change's row and `apicredits-end-to-end-lane`'s);
      documentation citations; `make check-packaging`; 10.5's run recorded; the proposal
      for a change isolating the lanes' host ports and networks, so they run
      concurrently on one host (design, "Section 10 design", decision 2), written and
      given its index row; and promotion pending at 11.2, 11.3, and 11.4.
    - Done: comment hygiene, with a direct read of the compose files' and Makefiles'
      new comments; documentation compliance against decisions 1–9, completed by
      10.5a, which corrected three documents this note first passed (decision 9's
      fixture reads no storefront setting, which its discovery finds); roadmap
      currency (Goal 4's gap closed for the lane, the loops and integration tests left
      to `apicredits-end-to-end-lane`); campaign index currency (this change's row,
      `apicredits-end-to-end-lane`'s, and its proposal's stated gap); citations;
      packaging; 10.5's run recorded; and `isolate-end-to-end-lane-stacks` proposed
      with its index row. Section 10's implementation and live gate are complete; its
      closeout stays open only for the 11.2, 11.3, and 11.4 promotions.
    - Closed: `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, and the `test-compatibility`
      delta are promoted at 11.2, 11.3, and 11.4.
## 11. Permanent documentation

- [x] 11.1 `docs/development/ARCHITECTURE.md`: the definition of a family kit, its
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
      From Section 6: "Discovery and negotiation" states that the runtime rechecks a
      listing against its source before every seller decision and every acceptance,
      through a check each domain contributes, and that a thread is successful only once
      its agreement and plan are recorded; "Operator lifecycle controls" names the kit's
      process-local trading pause beside the loop pause.
      From Section 7: the fulfillment-hook paragraph states that both bare-metal
      mechanisms start fulfillment through the servicing worker, that an Alkahest
      fulfillment publishes only its evidence's digest, and that an evidence submission
      whose outcome is unknown parks its obligation for an operator.
    - Done in `ARCHITECTURE.md`: "Family kits" names the Ansible distribution and the
      thin contracts and client distributions, the `(offering_mode, action)` executor
      table, and `compute_provisioning.jobs.executor_mock`; the kit layers gain the
      deal-control route services, the trading pause, the runtime's
      `preview_opening` and `accept_administratively`, and the resource-pool
      contracts and client; `VersionedEnvelope` is core's; "Release" states the
      aggregate-driven release behind the composition's release guard; the
      fulfillment-hook paragraph, "Discovery and negotiation", and "Operator lifecycle
      controls" as listed. Two items are stated as the code has them, not as worded
      above: Alkahest fulfillment starts through the servicing worker, while Arkhai
      payments starts it from the settle path and its reconciliation once the receipt
      verifies (as the `storefront-publication` delta has it); and teardown through
      lease termination is stated for the bare-metal storefront, the only storefront
      with a buyer teardown (VM's admin expiry and abandonment truncate the lease).
- [x] 11.2 `docs/development/TESTING.md`: three lanes, each building and composing its own stack, with the
      compute lanes' mock profile chosen per run by `PROVISIONING_MODE`; the loop table
      gains the bare-metal publication preview; shared compute deal stages and the
      per-domain driver; the mock profile's per-adapter executors and rule routes; the
      "blocked—not mocked" bare-metal statement replaced by the pipeline deal and the
      protected lane's distinct role.
    - Done: the loop table's publication preview, the shared stages and both drivers,
      the mock profile's per-adapter executors and `/test` rule routes, the bare-metal
      mock deal, and the real-host scenario's protected-lane role in place of the
      "blocked—not mocked" statement.
- [x] 11.3 `docs/development/DEPLOYMENT_AND_CONFIG.md`: the compose file list names the
      per-market overlays and the API-credit lane's compute registry; each compute
      stack's provisioning profile is chosen per run (`PROVISIONING_MODE`, defaulting to
      real in the base files as Helm's `mockMode` does), never a storefront setting. (The bare-metal settlement root and Alkahest inputs land with
      7B.5.)
    - Done: the full stack, the per-market overlays and what each binds,
      `compose.apicredits-lane.yml`, the environment targets, and the per-run
      provisioning profile.
- [x] 11.4 Promote the deltas into `openspec/specs/test-compatibility/spec.md`,
      `market-composition/spec.md`, `physical-provisioning/spec.md`,
      `storefront-publication/spec.md`, `site-capacity/spec.md`, `fulfillment/spec.md`
      (and its ownership list, which names versioned envelopes),
      `compute-provisioning-contract/spec.md` (and its purpose statement, which names
      action submission), `resource-pool-management/spec.md`, and
      `settlement-servicing/spec.md`.
    - Done at archival by the pinned OpenSpec CLI, which applied every delta: 47
      requirements added, 20 modified, and 7 removed across the ten capabilities, with
      strict validation of every specification passing. Outside the requirements:
      `fulfillment/spec.md`'s ownership list names its use of core's
      `VersionedEnvelope` rather than owning it, `compute-provisioning-contract`'s
      purpose no longer names action submission, and `site-capacity`'s evidence line
      cites `test_vm_inventory_views.py` for the pool-metadata provider gate.
- [x] 11.5 `docs/development/RELEASING.md` and `docs/development/BUILD_AND_PACKAGING.md`
      name the four new distributions wherever their siblings are listed.
    - Done: `RELEASING.md`'s table rebuilt from the workflow and each `pyproject.toml`,
      naming the four thin distributions and the Ansible distribution (it also lacked
      six packages the workflow already published, and most internal-dependency
      entries were stale). `BUILD_AND_PACKAGING.md` lists no sibling distributions, so
      it needs no edit.
## 2. Closeout

- [x] 2.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match,
      then read the comments this change adds for references to the review or
      migration that introduced them. Amended 2026-10-01 from a placeholder.
    - Done: `make check-comment-hygiene` passes; each section's closeout read its own
      comments directly.
- [x] 2.0 **Published dependency graph.** Ruled at the A0 checkpoint review (`design.md`,
      "Findings recorded for closeout"): before closeout, every package
      `.github/workflows/publish-pypi.yml` publishes must depend only on published packages.
      Enumerate the published packages' internal dependency closure, add each unpublished
      member (the four thin packages from 5B.8.A0 among them) to the workflow's `PACKAGES`
      table and path filters and to `docs/development/RELEASING.md`'s table, and list for the
      maintainer the trusted-publisher setup each new package needs before its first release.
      A check that fails when a published package depends on an unpublished one belongs beside
      the workflow, if it can run without network access.
    - Done. Fourteen published packages depended on seventeen unpublished repository
      distributions. Eighteen are added to the workflow's table and path filters, the
      push trigger gains `provisioning/compute/**` and `domains/compute/**`, and
      `RELEASING.md` and `manifests/published-distributions.json` list them; the
      manifest, which broke its own dependency-order rule, now holds 51 entries in
      dependency order. `scripts/tests/test_publish_matrix.py` fails when a published
      package (through an extra too) depends on an unlisted repository distribution, in
      the workflow or the manifest, when the manifest's order violates dependency order,
      when a package lacks its filter or push path, or when `RELEASING.md` disagrees.
      Each new package needs a PyPI trusted publisher before its first release (owner
      `arkhai-io`, repository `simple-compute-market`, workflow `publish-pypi.yml`,
      environment `pypi-<dist>`, and a repository environment of that name):
      `arkhai-kit-capability-shape`, `-kit-capability-pricing`,
      `-kit-capacity-publication`, `-kit-contact-exchange`, `-kit-delivery`,
      `-kit-delivery-apprise`, `-kit-fulfillment`, `-kit-pool-overrides`,
      `-kit-resource-pools`, `-kit-resource-pools-contracts`,
      `-kit-resource-pools-client`, `-kit-storefront`, `arkhai-compute`,
      `-compute-provisioning`, `-compute-provisioning-contracts`,
      `-compute-provisioning-client`, `-compute-provisioning-ansible`,
      `arkhai-vms-provisioning-operator-client`, and `arkhai-bare-metal-buyer`, which
      the maintainer ruled is published as every buyer role is.
- [x] 2.2 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration. Relock with `scripts/uv_project.py lock` the projects whose locks
      could not be regenerated in the implementation environment (the PyTorch index refused
      access): `domains/vms/storefront` and `domains/vms/buyer`, whose locks were hand-edited
      and are unverified by a real relock, and `kit/policy`; confirm each relock produces no
      diff, or commit the diff it produces.
    - `make check-packaging` passes. The relock cannot run here: the environment's
      network policy refuses `download.pytorch.org`, which the three projects' resolution
      reaches, so the locks of `domains/vms/storefront`, `domains/vms/buyer`, and
      `kit/policy` were relocked by the maintainer outside it, on 2026-10-09: `make
      lock` produced no lock change, so every lock is current.
- [x] 2.3 **Import placement.** For each function-level import this change adds or
      touches, move it to module level unless a verified circular import or a documented
      lazy-load reason keeps it; verify each move against the real suites.
    - Done change-wide, over the function-level imports the change added across its two
      merges to `dev` and this branch: 24 distinct production imports, 16 moved and 8
      kept, and all ~150 test imports moved. Kept: the bare-metal storefront's
      `lifecycle_steps` import of `publication_composition` (a verified cycle through
      `runtime`), the compute service's `vm_provisioning_adapter.db` (the optional
      `adapters` extra), and the VM listings' five `market_resource_pools_contracts`
      imports (the optional `pools` extra), each with its reason in a comment. Suites:
      `kit/site`, `kit/fulfillment`, `provisioning/compute` and its Ansible, client, and
      contracts distributions, both provisioning adapters, the compute service (unit
      and integration, also against the edited sources), the bare-metal and API-credit
      storefronts, the VM storefront (its two Node-backed Alkahest tests need a Node
      the workspace lacks), the e2e unit suite and collection, and `make
      check-packaging`.
- [x] 2.4 **Documentation compliance.** Re-check every accepted decision in `design.md`
      against `openspec/README.md`'s placement rules.
    - Done: every accepted decision has its permanent location in the promotion record
      below; scope migrations, superseded decisions, and the real-host scenario's
      disposition stay in this design, as `openspec/README.md` places change history.
- [x] 2.5 **Narrative compression.** Compress completed-task notes to final behaviour,
      validation evidence, deferred work, and permanent destinations.
    - Done: completed-task notes shortened to final behaviour, evidence, deferred work,
      and destinations (5,328 lines to about 2,260); 6A and 6B's implementation findings
      moved to design, "Section 6 design", as "Implementation findings (6A and 6B)".
      Task ids, checkbox states, headings, and every run ID are unchanged.
- [x] 2.6 **Roadmap currency.** Update Goal 7's current state (and Goal 4's, for the
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
      correlation the same way. What a storefront keeps of a delivery, and when it stops
      serving it, belongs to `kit-owned-listing-and-fulfillment-lifecycles`, whose design
      now carries the access rule; confirm at closeout that its design still does.
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
      In 7E, `test_a_grant_is_delivered_through_convergence_and_reclaimed_from_its_parameters`
      and `test_a_bare_metal_lease_expires_through_its_fulfillment` failed the same way
      in one root aggregate and passed on every rerun.
      Production uses a file database with a connection per session. The harness needs
      the same, or an equivalent that gives each session its own connection.
      Found in 6B: the policy kit's refusal of an unknown middleware name tells the
      operator to import "the VM policy package", which misleads a bare-metal operator.
      Found in Section 6's design (`design.md`, "Section 6 design: bare metal on the
      negotiation runtime (2026-10-07)"): bare metal's listing recheck and publication
      fetch each site's projection live, where VM reads the projections its storefront
      holds; reading cached projections belongs with unifying publication. API credits'
      `credit_quota_guard` reads availability its storefront computes ahead of the round,
      as VM's inventory guard did, and could move onto the kit's listing-source verdict.
      The fulfillment convergence sweep's counts are logged as structured fields, which
      the end-to-end lanes' plain-text log format does not print.
      Found in Section 7's design (`design.md`, "Section 7 design: one explicit
      settlement composition (2026-10-07)"): an interrupted contact-exchange reveal is
      finished only by the buyer retrying the start, though the servicing worker could
      finish it from the persisted introduction record; the seller's EVM address and
      wallet key are separate inputs nothing checks against each other, in VM's
      `[Wallet]` as in bare metal; and the Alkahest address book is named both by the
      settlement section's `address_config_path`, which the Alkahest runtime client
      applies to every chain, and by each chain's `alkahest_address_config_path`, which
      publication and the chain clients read.
      Found in slice C: the system worker controls' response bodies are untyped dicts
      (review point 3), and `openspec/specs/site-capacity/spec.md`'s evidence line for
      the pool-metadata provider gate should cite
      `provisioning/compute/service/tests/unit/services/test_vm_inventory_views.py`,
      where that test now lives, at promotion.
      Found in Section 9 (`design.md`, "Section 9 design", implementation findings):
      the bare-metal Compose wrapper and Helm chart forward no seller chain
      (`BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES`), so only the lane's overlay sets
      one; a restarted bare-metal storefront whose site reports a different delivery
      for an active lease answers the buyer's status read with an unhandled 500 rather
      than a typed refusal; and the storefront's begin reads a scheduled resource's
      nested `bare_metal_publication.physical_host_id`, a shape the site treats as
      legacy, so the two should agree on one place for it. An escrow proposal naming
      no contract is priced, in every compute domain, from the listing's first accepted
      escrow; which escrow prices it, or whether it is refused, is an open gap with no
      owning change. The bare-metal storefront's settlement servicing worker is
      composed with no event callback, so a servicing step that fails (a refused
      schedule, say) is retried with no stage event or log line at the storefront.
      Found in Section 10's design review: the VM storefront wheel's shipped
      `[provisioning] mode` (`settings.toml`) has no reader, and neither has the
      validation runbook's Helm override `storefront.agents[0].config.provisioning.mode`;
      both go with the storefront's next release.
      Found in 9.6a: only the administrator's settlement wait wakes servicing when it
      observes a lease become active, so a buyer's status read that observes it first
      leaves evidence publication to the pending retry; the wake belongs where
      `BareMetalFulfillmentService.status` records the transition. And the wait now
      reads the site on every poll, so a site error fails the wait rather than being
      polled through.
    - Done in `ROADMAP.md`: Goal 4's state and Goal 3's and Goal 4's gap rows say bare
      metal negotiates through the kit runtime, its own routes over it the remaining
      gap; Goal 7's state names the lane's backed bare-metal deal; Goal 4 closes the
      API-credit lane gap (Section 10). Open gaps recorded, each unowned: sealed or
      managed protection of host connection secrets, structured terminal-failure
      evidence from the real runner, VM guest network isolation, disabled-host
      admission, a relay-backed lane scenario, and the repository-wide administrator
      stance (Goal 1); the lease-start rule (Goal 5); and pricing an escrow that names
      no contract (Goal 6). The remaining findings above are owned by the new proposal
      `resolve-compute-family-findings`, with its index row; two were stale against the
      code and are recorded as it has them (a reservation's `executor_ref` is written,
      carrying the host; `find_active_lease_by_vm_target` and its `executor_target`
      match are what is uncalled). The 500-character requirements belong to
      `shorten-long-requirements`, whose scope is every permanent requirement; the
      site-capacity evidence path is corrected at 11.4; and
      `kit-owned-listing-and-fulfillment-lifecycles`' design still carries the access
      rule (its decision 5).
- [x] 2.7 **Campaign index currency.** Update this change's row and the Goal 3, 4, and 7
      graphs in `openspec/changes/README.md`, and the rows of
      `bare-metal-and-credits-domain-stacks`, `kit-owned-storefront-shell`,
      `apicredits-end-to-end-lane`, and `unbacked-bare-metal-listings`, whose
      dependency on this change is satisfied.
    - Done at archival: this change's row records the archive, the promotions, and run
      37953045615; the Goal 3, 4, and 7 graphs mark it archived; the rows of
      `bare-metal-and-credits-domain-stacks`, `kit-owned-storefront-shell`,
      `apicredits-end-to-end-lane`, `unbacked-bare-metal-listings`, and
      `market-platform-compute-40-multi-domain-proof` record their dependency on it as
      satisfied; `isolate-end-to-end-lane-stacks` and `resolve-compute-family-findings`
      have rows; and the roadmap's links point at the archive.
- [x] 2.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-mock-provisioned-deal` and resolve
      every match, including references to the tombstoned compose overlay, escrow
      helper, release, compute-adapter, lease-controller, and client modules.
    - Done: `make check-doc-citations CHANGE=bare-metal-mock-provisioned-deal` passes; the
      unscoped run's misses are all in other changes and the validation runbook's
      `scripts/validate/` paths.
- [x] 2.9 **End-to-end pipeline.** Confirm all three lanes pass, each building its own
      stack, and record the run, its result, and the scenarios exercising this change: VM's
      `test_full_deal.py` on the shared stages, `test_bare_metal_mock_deal.py`, and
      `test_credits_deal_buyer_cli.py` in its own lane.
    - Done: run 37935829083, on commit 6e1d03c9, passes all three lanes on fresh runners,
      each building its own stack. VM 134 passed, including `test_full_deal.py` on the
      shared compute deal stages; bare metal 51, including all 35 stages of
      `test_bare_metal_mock_deal.py`; API credits `test_credits_deal_buyer_cli.py`
      through the lane's own compute registry, with the payment deal's three scenarios
      blocked without a payments target. Run 37953045615, on commit 26c2848e after the
      import placement, passes the same: VM 134, bare metal 51, API credits 1 passed
      and 3 skipped.
- [x] 2.10 **Promotion.** Complete the design-promotion record below.
    - Done: every accepted decision below has its permanent location, the closeout's
      roadmap, index, publication, and findings rows included.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A deployable domain's deal runs on every pipeline run, holding, previewing, and advancing each transition | `openspec/specs/test-compatibility/spec.md` — "A deployable domain's deal runs on every end-to-end run"; `docs/development/TESTING.md` |
| The canonical compute deal's shared stages are defined once, with a per-domain driver | `openspec/specs/test-compatibility/spec.md` — "The canonical compute deal's shared stages are defined once"; `docs/development/TESTING.md` |
| Each domain runs in its own lane, building and composing its own stack | `openspec/specs/test-compatibility/spec.md` — "Each domain runs in its own lane"; `docs/development/TESTING.md` |
| Bare-metal restart recovery is proven at integration level | `openspec/specs/test-compatibility/spec.md` — "Bare-metal storefront restart recovery is proven at integration level" |
| Deal controls are kit-owned route services | `openspec/specs/market-composition/spec.md` — "Storefront deal controls are kit-owned route services"; `docs/development/ARCHITECTURE.md` kit layers |
| Compute mock executors share `compute_provisioning.executor_mock`; job execution resolves its executor by `(offering_mode, action)` | `openspec/specs/market-composition/spec.md` — "Compute mock executors share one compute-family mechanism"; `openspec/specs/physical-provisioning/spec.md` — "Job execution resolves its executor by offering mode and action"; `docs/development/ARCHITECTURE.md`; `docs/development/TESTING.md` |
| Administrative acceptance and opening previews go through the negotiation runtime | `openspec/specs/market-composition/spec.md` — "Kit-owned synchronous negotiation runtime" and "Storefront deal controls are kit-owned route services"; `docs/development/ARCHITECTURE.md` kit layers |
| Bare metal composes the kit negotiation runtime | `openspec/specs/market-composition/spec.md` — "Kit-owned synchronous negotiation runtime" |
| Lease release delegates to durable fulfillment teardown for every offering mode; storefront teardown goes through lease termination | `openspec/specs/physical-provisioning/spec.md` — "Lease release delegates to durable fulfillment teardown", "Storefront teardown goes through lease termination"; `docs/development/ARCHITECTURE.md` "Release" |
| Settlement starts bare-metal fulfillment through one mechanism-neutral servicing worker whose ready and terminal hooks dispatch by mechanism; the Alkahest path commits its lease | `openspec/specs/storefront-publication/spec.md` — "Complete bare-metal seller lifecycle"; `docs/development/ARCHITECTURE.md` |
| A fulfillment submission whose outcome is unknown is never repeated; it parks the obligation, which status counts | `openspec/specs/settlement-servicing/spec.md` — "A fulfillment submission with an unknown outcome is never repeated" |
| Bare-metal Alkahest delivery publishes only its evidence's digest on chain, and evidence resolution authenticates its caller | `openspec/specs/storefront-publication/spec.md` — "Complete bare-metal seller lifecycle"; `docs/development/ARCHITECTURE.md` |
| The unified fulfillment path, VM's plan rebuild, and the unconfigured-mechanism startup refusal are another change's | `openspec/changes/kit-owned-listing-and-fulfillment-lifecycles/design.md`; nothing permanent from this change |
| The bare-metal storefront requires its settlement configuration, requires a configured mechanism's recovery resources whether or not it is enabled, and its Helm chart and Compose file carry the Alkahest chain and wallet inputs once each | `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Bare-metal role configuration"; `docs/bare-metal-seller-quickstart.md`; enforces `openspec/specs/settlement-configuration/spec.md` — "Peer mechanism configuration hierarchy", "Mechanism configuration cannot reinterpret durable plans", with no new requirement |
| Lane composition files split per market | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/TESTING.md` |
| Mock provisioning is the provisioning service's profile, chosen per run by `PROVISIONING_MODE`; no storefront carries a provisioning mode | `openspec/specs/test-compatibility/spec.md` — "Each domain runs in its own lane" (its mock-profile scenario); `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/TESTING.md` |
| The API-credit lane's scenario fails on a missing lane setting | `docs/development/TESTING.md` (the existing rule, applied); nothing new |
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
| The runtime rechecks a listing against its source before every seller decision and every acceptance, never on exit, through a check each domain contributes; one classifier in `kit/policy` maps the verdict, used by the runtime and by `has_matching_inventory_guard` | `openspec/specs/market-composition/spec.md` — "Kit-owned synchronous negotiation runtime"; `openspec/specs/storefront-publication/spec.md` — "The seller's inventory guard checks a listing against its own source"; `docs/development/ARCHITECTURE.md` "Discovery and negotiation"; `docs/configuration.md` |
| A source the seller cannot confirm is refused as retryable (503); every negotiation route maps both source refusals | `openspec/specs/market-composition/spec.md` — "Kit-owned synchronous negotiation runtime", "Storefront deal controls are kit-owned route services" |
| A thread is successful only once its agreed terms, any hold, and its plan are recorded; a thread is resumed only when it ends with the seller's counter and records no agreement or plan | `openspec/specs/market-composition/spec.md` — "Kit-owned synchronous negotiation runtime"; `openspec/specs/storefront-publication/spec.md` — "Complete bare-metal seller lifecycle"; `docs/development/ARCHITECTURE.md` "Discovery and negotiation" |
| The trading pause is one process-local kit mechanism, separate from the loop pause; bare metal's durable pause is reversed | `openspec/specs/market-composition/spec.md` — "The trading pause is one process-local kit mechanism"; `docs/development/ARCHITECTURE.md` "Operator lifecycle controls" |
| Bare metal holds nothing at negotiation, commits its plan at acceptance, and that plan is the agreement settlement verifies; its seller chain is configured | `openspec/specs/storefront-publication/spec.md` — "Complete bare-metal seller lifecycle"; `docs/configuration.md` |
| Findings recorded under "Controls and routes (5B.8)" and in later sections | The substantive gaps in `docs/development/ROADMAP.md`'s Goal 1, 5, and 6 tables (unowned); the rest in `openspec/changes/resolve-compute-family-findings/proposal.md`; requirements over 500 characters with `shorten-long-requirements` |
| Every published package depends only on published packages | `docs/development/RELEASING.md`; `manifests/published-distributions.json`; enforced by `scripts/tests/test_publish_matrix.py` |
| Roadmap currency | `docs/development/ROADMAP.md`: Goal 3's and Goal 4's negotiation gap rows, Goal 4's state and closed API-credit lane gap, Goal 7's state, and the open gaps above |
| Campaign index currency | `openspec/changes/README.md`: this change's row (archived) and the Goal 3, 4, and 7 graphs; the rows of `bare-metal-and-credits-domain-stacks`, `kit-owned-storefront-shell`, `apicredits-end-to-end-lane`, `unbacked-bare-metal-listings`, and `market-platform-compute-40-multi-domain-proof`; new rows for `isolate-end-to-end-lane-stacks` and `resolve-compute-family-findings` |
| Scope migrations, the real-host scenario's disposition, and why the scenario uses typed clients | This change's `design.md` |
| Administrator settlement wait observes already-started fulfillment at its selected site and wakes deferred servicing when delivery becomes active | `openspec/specs/storefront-publication/spec.md` — "Administrator waits while settlement servicing is held", through this change's delta, at 11.4 |
