# Tasks — unify compute delivery

Design-stage implementation plan. No implementation or validation task below is
claimed complete by the reconciliation edit. Preserve completed history when tasks
are later amended.

## Dependency gates and validation scope

- Before sections 1–3 execute: land `agreed-evidence-and-early-termination`'s seller
  half, final-request admission, joint end/self-filing journal and end-domain port;
  land `renewable-compute-lease-deadlines`' activation half. Do not recreate missing
  dependency interfaces locally. Preserve the VM recovery/admission baseline from
  the archived `resolve-compute-family-findings` while rebinding its seams.
- Section 4's rate qualification additionally waits for
  `spot-deals-through-arkhai-payments`' rate adapter and
  `converge-ongoing-compute-leases`' rate hook. The prepaid path can land independently;
  rate publication/materialization must stay fail-closed until composed.
- `kit-owned-listing-and-fulfillment-lifecycles` must consume this path for the
  transitions it owns here; no dependency on its wider extraction is needed.
- Follow `docs/development/TESTING.md`: pure window/decision transformations at unit
  level; durable interleavings in family-library integration; route and contribution
  wiring in application integration through canonical typed clients; cross-service
  activation/recovery in the lanes. Exercise existing tests and deterministic drive
  controls, not sleeps or a full-suite audit. New permanent tests require explicit
  maintainer approval of the property and system; the candidates below name that
  scope, not approval. Temporary crash/interleaving drives can establish evidence.

`src/` below denotes a named package's source root. New modules may be grouped under
`delivery/` without changing their ownership. The design's recommendations (family
module, separate delivery record, shared transaction/revision port) are the default
plan; a dependency's equivalent durable seam may replace the technique, not the
ordering contract.

## 1. Shared delivery record, phases and admission ports

Files: new `provisioning/compute/src/compute_provisioning/delivery/` (contracts,
repository, window derivation and orchestration); `provisioning/compute/pyproject.toml`
(declare actual imports); both storefronts' persistence bindings and migrations.
Do not change provisioning's physical aggregate schema to hold commercial state.

- [ ] 1.1 Define the shared record keyed by negotiation, exact accepted window/site,
      reservation/fulfillment IDs, phase decisions, stable effect intents/acks and
      delivery checkpoints. Keep credentials and payment balances out. Adapt/migrate
      domain progress rows so they cannot compete as writers. Verify: family-library
      integration against a real storefront-style database for idempotent record
      creation/reload and conflicting window rejection.
- [ ] 1.2 Implement exact Agreement-window derivation and repair-required handling;
      preserve identity for old in-flight rows with inconsistent timing. Verify:
      unit-level window transformations plus the existing VM recovery fixtures and
      bare-metal materialization tests, covering late settlement and missing duration.
- [ ] 1.3 Define `authorize_delivery(deal, phase)` with durable allow/refuse/pending
      records and evidence references, the prepaid no-financial-action hook, and the
      provisioning-evidence input for the rate hook. Inject lifecycle admission and
      seller-half ports. Verify: family-library integration that an end admitted
      before dispatch defeats financial allow and unknown hook results stay pending.
- [ ] 1.4 Coordinate local end admission and checkpoint/disclosure CAS through the
      dependency's transaction/revision port. Persist effect intents before external
      I/O and checkpoint only on acknowledgement; no transaction spans I/O. Verify:
      independent-session integration/temporary interleaving drive for end versus
      dispatch and a required-write failure; no effect may escape without its intent.

Focused targets: `provisioning/compute/tests` through `make test-compute-provisioning`
and the touched storefront persistence suites. Candidate permanent property, if
approved: all restart/interleaving histories preserve one physical effect identity
and refuse protected effects after the locally admitted end. No e2e claim at this step.

## 2. Both compute domains use the path

Files: VM `domains/vms/storefront/src/market_storefront/payment_settlement.py`,
`services/fulfillment_service.py`, `services/fulfillment_provisioning.py`,
`services/fulfillment_resume_runtime.py`, `settlement_composition.py`, delivery
repositories/access route bindings and startup; bare metal
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/fulfillment_service.py`,
`settlement_stages.py`, `settlement_composition.py`, `sqlite_client.py`, `api.py` and
its access/result adapters. Reverify actual filenames against the dependency tree.

- [ ] 2.1 Replace VM's protected transitions with shared-path calls for hosted and
      Alkahest delivery, foreground and recovery. Remove both 3600-second defaults,
      preserve accepted selected-site routing and exact-request adoption. Verify:
      existing `test_fulfillment_resume_runtime.py`, `test_fulfillment_service.py`,
      `test_fulfillment_provisioning.py` and integration `test_payment_settlement.py`.
- [ ] 2.2 Replace bare metal's commit-from-now and protected transitions with the
      same path, retaining domain preparation and public access models. Verify:
      existing `test_fulfillment_service.py` and integration
      `test_payment_settlement_client.py` with canonical clients; delayed settlement
      must preserve the original end in both domains.
- [ ] 2.3 Wire every capacity commit caller, including fresh/recovered holds and
      Alkahest, to activation after the start gate and before availability. Always
      name the Agreement end, never a funded horizon; persist/retry the call and
      use the site's active instant. Verify: application integration/drive with the
      provisioning client, including lost activation acknowledgement and expiry winning.
- [ ] 2.4 Route buyer credential/result reads through the shared local admission
      check, live fetch and final revision/time check before response authorization.
      Do not alter provisioning's read-only result contract or fetch payment
      snapshots on these reads. Verify: both storefronts' access/result integration
      through canonical clients, with an end deliberately admitted during the fetch
      and a future end reached while physical teardown is delayed.
- [ ] 2.5 Preserve delivery priority by retrying persistence and adopting already
      running work while deferring unjournaled protected effects; remove VM credential
      persistence once active migrated records can fetch live. Verify: existing VM
      checkpoint-failure/recovery coverage follows the amended requirement, plus
      old-row recovery through its recorded fulfillment, not a replacement.

Focused targets: `make test-storefront`, `make test-bare-metal` (limit to the named
files during iteration using the package's existing runner), plus affected family
integration. Do not add per-domain copies of the shared state-machine test. API-credit
application/issuance coverage remains unchanged and is exercised at section 4.

## 3. Undelivered handoff, with no second end or money engine

Files: family delivery orchestration and the same domain composition/recovery adapters.
`kit/deal-servicing` owns the final-request journal; consume its interface rather than
implement its internals in this change. No edits to the payment authority contract.

- [ ] 3.1 Wire terminal hook refusal, elapsed window, provisioning failure and
      awaiting-activation site expiry into a local final request plus the seller
      half's `exceptional_end(Agreement.start_utc)` handoff. Carry actor/cause/source
      and evidence refs; retain signed site bytes in the existing evidence store.
      Verify: family-library integration with the real lifecycle journal and injected
      adapters for no dispatch, dispatched-but-pending and started-but-unavailable.
- [ ] 3.2 Use end service for proof-driven no-dispatch release or adoption/termination
      of dispatched work. Keep physical progress independent of authority availability.
      Verify: existing release/admission integration at
      `provisioning/compute/tests/integration/test_release.py`, plus application
      drive after the storefront restarts with a due site-end report.
- [ ] 3.3 Reuse the joint end/filing journal across a crash, retaining the same filing
      key. Display pending/unsupported/repair-required outcomes honestly; an Alkahest
      deal with no dispute adapter retains its accepted failure/reclaim behavior.
      Verify: library/application integration against payments and mediation doubles
      that the path supplies an intent and no correction amounts, direct stop or
      alternate refund log; filing retries are the lifecycle owner's operation.

Acceptance property: recovery cannot lose the self-filing obligation after recording
the local end; the correction instant is Agreement start for never-available delivery,
not payment start or discovery time. Financial amounts and authority ruling policy
are qualified by the lifecycle/rate changes, not duplicated here.

## 4. First-use and cross-service qualification

Files: `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py` and existing VM and
bare-metal deal role modules/markers; reuse their typed clients, loop controls and
fixtures. Setup/double control changes belong with their existing owners, not a
parallel deployment script. Do not change publication's servicing gate to make a test
pass. New persisted scenarios remain subject to the explicit approval gate above.

- [ ] 4.1 Prepare reproducible, checkout-owned VM and bare-metal lane targets with
      deterministic public development personas, seeded pool allowance and complete
      deal entry points. Record exact startup/ready/stop commands and target selectors;
      inspect selectors before seeding or teardown. Use the existing lane readiness
      check and stop on not-ready. No private service credentials or raw private logs
      enter the repository.
- [ ] 4.2 Drive a reserved deal in each domain through activation, then beyond the
      provisioning allowance but before Agreement end, observing the site's active
      instant and unchanged end. Drive settlement delayed within and beyond the
      absolute window. Record exact deal/lease evidence and outcomes, not just health.
- [ ] 4.3 Drive crash/restart at every adjacent delivery checkpoint and every
      external intent/acknowledgement gap with deterministic controls. Drive a crash
      before activation until the site's awaiting-activation expiry, recover and
      observe physical release plus the journaled exceptional-end filing. Keep
      authority-application results distinct from local filing evidence.
- [ ] 4.4 After the rate dependencies are ready, compose their hook and drive
      start/stop races before disclosure and a started-but-undelivered activation
      failure in both domains against the in-lane payments and mediation doubles.
      Name this client qualification against the double, not proof of live authority
      behavior. Keep live contract qualification with the activation campaign gate.
- [ ] 4.5 Run the relevant complete-deal markers in the ready lanes:
      `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_payment_deal` and `e2e_credits_payment_deal` as configured;
      readiness-gate unavailable public payment targets explicitly. Stop the owned
      lane resources and commit reproducible setup/evidence, not resident servers.

Entry targets: `make -C e2e-tests test-e2e-vm`, `test-e2e-bare-metal` and
`test-e2e-apicredits`, with the existing marker selection variables. Run only in
verified owned lane projects; default selectors are not permission to destroy a
shared target. The reserved and crash drives may use existing loop/mock controls
without new permanent test cases. An independent driver starts from committed setup.

## 5. Closeout

Documentation-only after implementation review. A code defect returns to
implementation, including a comment/import repair. Follow
`openspec/README.md#plan-closeout-requirements` in order.

- [ ] 5.1 **Comment hygiene:** run `make check-comment-hygiene` and confirm touched
      comments describe current invariants, not the change or its tasks.
- [ ] 5.2 **Import placement:** confirm touched imports are module-level unless a
      demonstrated cycle or deliberate lazy-load reason was recorded during implementation.
- [ ] 5.3 **Documentation compliance:** check D1–D7 against ownership/placement;
      authority policy remains context, and end service is referenced, not specified twice.
- [ ] 5.4 **Narrative compression:** retain final behavior, material evidence,
      deferred rate/renewal work and destinations; move reasoning to the design.
- [ ] 5.5 **Roadmap currency:** update Goal 8's shared-delivery gap/current state in
      `docs/development/ROADMAP.md`; name the update in the promotion record.
- [ ] 5.6 **Campaign index currency:** update this row and dependencies in
      `openspec/changes/README.md` without prematurely removing dependencies from
      other rows; run `make check-change-index` and record the disposition.
- [ ] 5.7 **Packaging:** run `make check-packaging` and
      `make check-architecture-change CHANGE=unify-compute-delivery-path`; resolve
      all failures and leave no architecture exception owned by this change.
- [ ] 5.8 **End-to-end pipeline:** record the pipeline run/result and section 4's
      named scenario outcomes and readiness blockers. No blocked/unrun rate or live
      qualification is counted as passing or silently removed from acceptance.
- [ ] 5.9 **Promotion:** create `compute-delivery`'s permanent spec (by archive) and
      architecture companion under `openspec/specs/`; amend
      `openspec/specs/README.md`, `openspec/specs/vm-storefront-fulfillment/architecture.md`,
      `openspec/specs/fulfillment/architecture.md` (physical/delivery boundary), and
      `docs/development/ARCHITECTURE.md` (Family kits, authority boundaries,
      Fulfillment, Fulfillment status and results, Release). Archive promotes the
      VM spec delta. Complete each row of the design-promotion record with its exact
      destination/heading; reference the owning lifecycle/site contracts without
      reintroducing their requirements.
- [ ] 5.10 **Documentation citations:** run
      `make check-doc-citations CHANGE=unify-compute-delivery-path`, then the pinned
      `bunx @fission-ai/openspec@1.14.0 validate unify-compute-delivery-path --strict`
      and `make check-change CHANGE=unify-compute-delivery-path`; resolve all failures.
- [ ] 5.11 **Archival:** run
      `bunx @fission-ai/openspec@1.14.0 archive unify-compute-delivery-path -y`, merging
      deltas; point the index row at the archive. Closeout review reads the archived
      change and promoted current-state documentation.
