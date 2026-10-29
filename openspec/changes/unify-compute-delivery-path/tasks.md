# Tasks — unify compute delivery

Design-stage implementation plan. No implementation or validation task below is
claimed complete by the reconciliation edit. Preserve completed history when tasks
are later amended.

## Dependency gates and validation scope

- Before sections 1–3 execute: land `agreed-evidence-and-early-termination`'s seller
  half, final-request admission, joint end/filing journal and end-domain port;
  neutral delivery authorization/effect protocols and opaque evidence envelope;
  land `renewable-compute-lease-deadlines`' activation half with its composition
  safeguard off (transitively gated by `inject-site-pool-authority`).
  Sections 1–2 also require the negotiation-keyed exact-request reserve replay slice
  of `capacity-reservation-lifecycle-hardening`, not its whole implementation.
  Do not recreate missing dependency interfaces locally. Preserve the VM recovery/admission baseline from
  the archived `resolve-compute-family-findings` while rebinding its seams.
- Tasks 3.3/4.3/4.4's HTTP lane drives wait for
  `add-arkhai-payments-lane-double`. Library integration uses the shared clock-injected
  payments authority engine in kit/arkhai-payments fixtures directly; HTTP wraps
  that engine. Mediation's in-process fake keeps triage plus the sole qualifying seller self-penalty ruling;
  kits never import runnable tooling.
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
distribution, additive projection cutover, separate delivery record and the
foundation-owned transaction/revision port) are the default
plan; a dependency's equivalent durable seam may replace the technique, not the
ordering contract.

## 1. Shared delivery record, phases and admission ports

Files: new `domains/compute/delivery/` distribution (source `compute_delivery`:
repository, window derivation, orchestration and compute evidence adapter), its
`pyproject.toml` (existing path classification, no checker edit/override);
both storefronts' persistence bindings
and migrations. Import neutral protocol types from `kit/deal-lifecycle` and `kit/deal-servicing`;
confirm downward scope/kind edges without moving protocols into the family package.
Do not change provisioning's physical aggregate schema to hold commercial state.

- [ ] 1.1 Define the shared record keyed by negotiation, exact accepted window/site,
      reservation/fulfillment IDs, servicing-decision references, delivery-owned effect intents/acks,
      end-service billing-start intent reference, and delivery checkpoints authorized/dispatched/activated/started/available/converged.
      Keep credentials and balances out. Apply D1's additive migration: preserve exact
      evidence/requests, reconcile recorded resources, turn domain progress rows into
      read-only projections. First deploy D1's bridge release enforcing the writer floor,
      record actual bridge artifacts as the oldest supported rollback binaries, stop
      unbridged writers and obtain the operator acknowledgement before migration.
      Raise the floor at cutover; qualify refusal with both domains' actual pre-cutover
      bridge binaries against migrated copies. Never claim unbridged code reads it. Ambiguous rows remain
      repair-required. Never infer availability or activation from stored credentials.
      Verify: family-library
      integration against a real storefront-style database for idempotent record
      creation/reload and conflicting window rejection.
- [ ] 1.2 Implement exact Agreement-window derivation and repair-required handling;
      preserve identity for old in-flight rows with inconsistent timing. Verify:
      unit-level window transformations plus the existing VM recovery fixtures and
      bare-metal materialization tests, covering late settlement and missing duration.
      Commit forward reservations at settlement, persist wake at accepted start, and
      defer dispatch/activation/billing/disclosure until then. Verify restart before
      wake and the max(commit,start)+allowance deadline with renewable. Keep pre-dispatch
      work awaiting-delivery in the existing mechanism runtime journal (Alkahest
      each cycle; hosted payment reconciliation), not deferred. Drive a future-start
      Alkahest deal through restart to availability without buyer polling.
- [ ] 1.3 Consume neutral `authorize_delivery(deal, phase)` with servicing-owned durable pure
      decisions; retain only their references. Explicitly compose no-financial-action
      for prepaid/current Alkahest after selected-stage evidence validation; a missing
      required adapter blocks. Consume foundation's shared phase enum (unknown refuses).
      Separately call end service's
      `begin_billing(operation_key, activated_delivery_ref)` after activation. End service owns the sole durable
      billing-start intent/key; store only its reference and acknowledged checkpoint. Supply foundation's ActivatedDeliveryRef: negotiation/commitment/reservation/
      fulfillment IDs, verified activation reference/active instant and ready digest/
      versioned envelope, never credentials. Spot implements payment authorize/
      start_billing; converge composes/drives the neutral journals.
      Inject foundation-owned admission and single end-plus-filing ports.
      Verify: family-library integration that an end admitted
      before dispatch defeats financial allow and unknown hook results stay pending.
- [ ] 1.4 Coordinate local end admission and checkpoint/disclosure CAS through the
      dependency's transaction/revision port. Persist effect intents before external
      I/O and checkpoint only on acknowledgement; no transaction spans I/O. Verify:
      independent-session integration/temporary interleaving drive for end versus
      dispatch and a required-write failure; no effect may escape without its intent.

Focused targets: the new delivery distribution's declared library target and the
touched storefront persistence suites (do not invent an existing target for it).
Candidate permanent property, if
approved: all restart/interleaving histories preserve one physical effect identity
and refuse protected effects after the locally admitted end. No e2e claim at this step.

## 2. Both compute domains use the path

Files: VM `domains/vms/storefront/src/market_storefront/payment_settlement.py`,
`services/fulfillment_service.py`, `services/vm_fulfillment_service.py`,
`services/fulfillment_resume_runtime.py`, `settlement_composition.py`, delivery
repositories/access route bindings and startup; bare metal
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/fulfillment_service.py`,
`settlement_stages.py`, `settlement_composition.py`, `sqlite_client.py`, `api.py` and
its access/result adapters. Reverify actual filenames against the dependency tree.

- [ ] 2.1 Replace VM's protected transitions with shared-path calls for hosted and
      Alkahest delivery, foreground and recovery. Remove both 3600-second defaults,
      remove `_parse_start_utc`'s missing-start-to-now fallback while retaining
      minute-format reads for persisted legacy timestamps. Preserve accepted
      selected-site routing and exact-request adoption. Delegate inside the domain
      fulfillment hook via composition closure, leaving StorefrontFulfillmentPorts
      unchanged and retaining core identity checks. Preserve D1's awaiting-delivery
      versus deferred-completion distinction and deployed retry owners; available
      maps to fulfilled, failure to failed only after durable lifecycle handoff. Verify:
      existing `test_fulfillment_resume_runtime.py`, `test_fulfillment_service.py`,
      `test_fulfillment_provisioning.py` and integration `test_payment_settlement.py`.
      Preserve foundation scenarios 'A buyer ends before provisioning', 'The end
      overlaps delivery start' and 'The storefront restarts between the end and
      provisioning' through the rebound admission seam.
- [ ] 2.2 Replace bare metal's commit-from-now and protected transitions with the
      same path, retaining domain preparation and public access models. Verify:
      existing `test_fulfillment_service.py` and integration
      `test_payment_settlement_client.py` with canonical clients; delayed settlement
      must preserve the original end in both domains. Preserve foundation's 'A buyer
      tears down bare metal' and the same early-end/admission restart scenarios.
- [ ] 2.3 Wire every capacity commit caller, including fresh/recovered holds and
      Alkahest, to reservation-only activation after readiness and before billing
      start/availability, no earlier than the accepted start. Validate the returned
      end as commit end or a verified end-service truncation; adopt it and the site's
      active instant, never extend it or supply a target deadline. Persist/retry calls. Verify: application integration/drive with the
      provisioning client, including truncation before activation, truncation after
      lost activation acknowledgement and expiry winning before any billing start.
      Implement verified null-phase legacy compatibility; missing route for a
      protected/unknown lease remains repair-required. Leave repository defaults off
      here. Section 4 qualifies callers before the default change; record public
      version/readiness evidence and rollback refusal, never hosted target identifiers.
- [ ] 2.4 Route buyer credential/result reads through the shared local admission
      check, live fetch and final revision/time check before response authorization.
      Do not alter provisioning's read-only result contract or fetch payment
      snapshots on these reads. Verify: both storefronts' access/result integration
      through canonical clients, with an end deliberately admitted during the fetch
      and a future end reached while physical teardown is delayed. VM settle/status
      remains its typed access surface: update settlement_composition, settle controller,
      hosted VM buyer and core buyer callers as needed, without a stored fallback.
      Coordinate with `buyers-use-the-storefront-client` if it lands first.
- [ ] 2.5 Preserve delivery priority by retrying persistence and adopting already
      running work while deferring unjournaled protected effects; remove VM credential
      persistence once active migrated records can fetch live. Verify: existing VM
      checkpoint-failure/recovery coverage follows the amended requirement, plus
      old-row recovery through its recorded fulfillment, not a replacement. In
      VM middleware/seller_auth.py and bare-metal response_auth.py, exclude credential-
      capable response bodies from retention, preserve request digest/signing and
      changed-request rejection, and re-enter live guards on exact retry. Purge old
      retained credentials only once adopted resources support live access. Verify
      exact retry after admitted end and inspect replay persistence for no secrets;
      coordinate the narrow policy with `redesign-authenticated-requests`.

Focused targets: `make test-storefront`, `make test-bare-metal` (limit to the named
files during iteration using the package's existing runner), plus affected family
integration. Do not add per-domain copies of the shared state-machine test. API-credit
application/issuance coverage remains unchanged and is exercised at section 4.

## 3. Undelivered handoff, with no second end or money engine

Files: family delivery orchestration and the same domain composition/recovery adapters.
`kit/deal-servicing` owns the final-request journal; consume its interface rather than
implement its internals in this change. No edits to the payment authority contract.

- [ ] 3.1 Wire D5's cause table into the foundation-owned single end-plus-optional-
      filing operation. Supply actor/cause/source, accepted start, fixed failure
      observation time, resource identities and evidence; retain signed site bytes.
      Supply verified refusal reasons/payment records, not event-kind classification:
      payer stop or mandate state is not automatically seller failure; missing
      pre-start funding is not exhaustion. Supply elapsed-window/payee-stop
      non-delivery and unserved setup evidence; the clock or seller stop cannot erase
      it. Consume foundation classification against the never-delivered start basis. For genuine never-delivered pre-start failure consume foundation's
      timing policy: journal now, defer the command to Agreement start when still ahead;
      otherwise use its fixed min(start,failure) basis. Do not clamp commands
      locally or recompute the instant on retry. Late settlement alone is not proof
      of buyer fault. No billing start may occur before activation.
      Verify: family-library integration with the real lifecycle journal and injected
      adapters for no dispatch, pre-start failure, lawful end before availability,
      late commitment, dispatched-but-pending and started-but-unavailable.
- [ ] 3.2 Use end service for proof-driven no-dispatch release or adoption/termination
      of dispatched work. Keep physical progress independent of authority availability.
      Verify: existing release/admission integration at
      `provisioning/compute/tests/integration/test_release.py`, plus application
      drive after the storefront restarts with a due site-end report.
- [ ] 3.3 Reuse the joint end/filing journal across a crash, retaining the same command
      key. Submit exceptional_end through the Agreement's dispute adapter; the seller
      sends no payment stop/reverse. Display pending/unsupported/repair-required honestly;
      an Alkahest deal without that dispute adapter retains accepted failure/reclaim.
      Verify: library integration uses shared kit-owned clock-injected fixtures; HTTP
      application/lane qualification waits for runnable payments/mediation doubles.
      Observe that delivery supplies an intent, not correction amounts, direct stop or
      alternate refund log. Filing retries belong to the lifecycle owner; mediation's
      only mechanical ruling is the payee-filed standard-or-stronger self-penalty.
      Confirm end_delivery has no at and yields signed receipt evidence, not a storefront
      billing stop. Buyer-side unreachable-authority retry keeps the same key and billing
      continues until it lands; optional buyer_end goes to human triage with the exact
      Agreement checked against the mandate's deal hash. Keep these lifecycle scenarios
      with their owning foundation/spot suites, consuming their outcomes here.

Acceptance property: recovery cannot lose an owed exceptional-end filing after recording the
local end; the lifecycle owner selects its fixed valid instant from cause/start/failure
evidence, never payment start or retry time. Lawful ends do not create seller penalties. Financial amounts and authority ruling policy
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
- [ ] 4.2 Explicitly enable activation_deadlines_enabled in owned lane setup only,
      leaving repository/operator defaults off. Drive a reserved deal in each domain through activation, then beyond the
      provisioning allowance but before Agreement end, observing the site's active
      instant and unchanged end. Drive settlement delayed within and beyond the
      absolute window. Record exact deal/lease evidence and outcomes, not just health.
- [ ] 4.3 Drive crash/restart at every adjacent delivery checkpoint and every
      external intent/acknowledgement gap with deterministic controls. Drive a crash
      before activation until the site's awaiting-activation expiry, recover and
      observe physical release plus the journaled exceptional-end dispute filing. Keep
      authority-application results distinct from local command evidence.
- [ ] 4.4 After converge task 3.1 composes the rate hook, consume convergence's
      single rate-servicing lane matrix execution at its task 4.1. The delivery
      activate/start/disclose race maps to row 4; post-activation start refusal and
      never-disclosed recovery map to row 8. Both rows there prove no start before
      activation and no duplicated start key across crashes in both domains against
      the in-lane doubles. Do not compose another hook or run duplicate rate drives
      here; unify retains only non-rate delivery qualification. Live authority
      qualification remains with activation.
- [ ] 4.5 After 4.2/4.3 qualify every commit/recovery caller, change the repository's
      compute-composition activation_deadlines_enabled default introduced by renewable
      in `provisioning/compute/service/src/compute_provisioning_service/container.py`
      and its configuration owner (reverify relocated paths). Document storefront-first,
      site-off rollout and hosted operators' independent caller-readiness gate in
      `docs/development/DEPLOYMENT_AND_CONFIG.md`. Record public artifact versions/
      readiness only, no hosted target identifiers. Off remains an explicit override
      for new commits and never clears existing deadlines.
- [ ] 4.6 Run the relevant complete-deal markers in the ready lanes:
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
      `docs/development/ROADMAP.md`; also amend only the capacity row's missing-start-at-commit clause:
      compute missing timing requires repair. Keep its separate start-on-activation
      gap open; this change does not implement it. Name both edits in promotion.
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
      `openspec/specs/fulfillment/architecture.md` (physical/delivery boundary),
      `openspec/specs/physical-provisioning/architecture.md` (verified bare-metal
      adoption, read-only legacy progress and retained evidence refusal), and
      `docs/development/ARCHITECTURE.md` (Family kits, authority boundaries,
      Fulfillment, Fulfillment status and results, Release), plus
      `docs/development/DEPLOYMENT_AND_CONFIG.md` for staged safeguard enablement,
      verified legacy compatibility and downgrade refusal. Archive promotes the
      VM, physical-provisioning, resource-pool-management and marketplace-identity deltas. Complete each row of the design-promotion record with its exact
      destination/heading; reference the owning lifecycle/site contracts without
      reintroducing their requirements.
- [ ] 5.10 **Documentation citations:** run
      `make check-doc-citations CHANGE=unify-compute-delivery-path`, then the pinned
      `bunx @fission-ai/openspec@1.14.0 validate unify-compute-delivery-path --strict`
      and `make check-change CHANGE=unify-compute-delivery-path`; resolve all failures.
- [ ] 5.11 **Archival:** archive after foundation and renewable, preserving their
      physical-provisioning event/watchdog clauses. Archive unify before
      redesign-authenticated-requests; its later identity MODIFIED block must retain
      this declaration. If order reverses, re-diff unify as a superset first. Re-diff
      every MODIFIED block against then-current permanent specs, retaining all clauses
      and scenarios that the other changes keep. Run
      `bunx @fission-ai/openspec@1.14.0 archive unify-compute-delivery-path -y`, merging
      deltas; point the index row at the archive. Closeout review reads the archived
      change and promoted current-state documentation.
