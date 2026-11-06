# Tasks — unify compute delivery

Replanned against the reviewed design (design review 12 and its triage). The earlier
draft's sections prescribed a shared delivery record, a bridge release and null-phase
compatibility that the design rejects; none of its tasks was checked, so every section
below replaces it.

Implementation gates: none of another change. `add-arkhai-payments-lane-double` gates
only the lane runs of the filing and restart drives in task 8.4; everything else,
including library integration of filings against the kit-owned clock-injected payments
engine and the in-process mediation fake, proceeds without it. Tests follow
`docs/development/TESTING.md`: pure transformations at unit level, durable
interleavings in library integration, routes and composition in application
integration through the canonical typed clients, cross-service behaviour in the lanes.

## 1. Reserve replay keyed by the deal's placement

Delivers the site's placement-keyed reserve replay (D6; `site-capacity` "Reserve replay
is keyed by the deal's placement"). Files: `kit/site/src/market_site/ledger.py`
(`reserve`, `_find_reservation`), `kit/site/src/market_site/router.py` only if the
reserve body model needs the key named, `kit/site-client` only if its reserve call
filters `deal_ref`, and their tests.

- [ ] 1.1 Accept `deal_ref.placement_key` in `CapacityLedgerService.reserve` as an
      idempotency key beside `escrow_uid`, looked up in the reserve's own transaction
      across every state (held, committed, released), not only
      `HELD_RESERVATION_STATES`. An exact replay returns the recorded reservation's
      payload and admits nothing; a replay under the key that changes the claim's
      dimensions or attributes, the pool, the site, the offering mode or the lease
      window raises the ledger's conflict error with nothing written. A reserve
      without the key behaves exactly as today (D6).
- [ ] 1.2 Add an index on the stored placement key if the lookup would otherwise scan
      `deal_ref` JSON, in both services hosting the ledger (compute provisioning and API
      credits), as an ordered migration each; leave expiry indexing and retention to
      `capacity-reservation-lifecycle-hardening` (D6).
- [ ] 1.3 Verify: library integration in `kit/site/tests/integration/test_ledger.py`
      for the three `site-capacity` scenarios — a lost acknowledgement replayed, a
      changed window refused with nothing written, a lapsed `:hold` beside a new
      `:settlement` placement — plus a replay of a released reservation returning it
      released, and the existing `escrow_uid` idempotency unchanged. Run
      `make -C kit test-site`, the compute provisioning and API-credit service suites
      for their migrations, and `make test`. End-to-end: none exercises the key until
      section 5 sends it; no scenario is owed here.

## 2. Alkahest once-only delivery adapter

Delivers the Alkahest payment adapter composing `OnceDeliveryPolicy` (D10;
`deal-lifecycle` "Delivery phases use a shared evidence-gated protocol"). Files: a new
module in `kit/alkahest/src/market_alkahest/` beside `escrow_verification.py`,
`kit/alkahest/pyproject.toml` (declare `arkhai-kit-deal-lifecycle` and its contracts
kit, as `kit/arkhai-payments` does), its lock, and its tests.

- [ ] 2.1 Implement the adapter to the `PaymentAdapter` protocol of
      `kit/deal-lifecycle/src/market_deal_lifecycle/adapters.py`: `authorize` and
      `start_billing` delegate to `OnceDeliveryPolicy` with an injected validator of the
      selected Alkahest stage's typed, versioned commitment evidence; `supported_commands`
      is empty, so `submit_payment` refuses every payment command; `read` reports the
      authority view as unsupported; billing start is a no-op only with activation
      evidence (D10).
- [ ] 2.2 Verify: unit tests in `kit/alkahest/tests/unit/` for allow on valid
      evidence, refuse on invalid evidence, a no-op start with activation evidence, a
      refused start without it, and every payment command refused by `submit_payment`;
      `make -C kit test-alkahest`; `make check-packaging` for the new declaration and
      lock; `make test`. End-to-end: none until section 5 composes it; no scenario is
      owed here.

## 3. The family delivery library: ports, `drive` and the path through dispatch

Delivers `domains/compute/delivery` with its ports, `drive` and its fail-closed rules,
Agreement-window derivation, the future-start wait, hold adoption, commit and dispatch
with recovery (D1, D4, D6's use, D11's commit refusal; `compute-delivery` "Compute
storefronts deliver through one family path behind domain ports", "Delivery is driven
one deal at a time and reports where it stands", "Delivery commits the Agreement
window", "A deal that starts later waits for its start", "Protected steps are
authorized and admitted" for commit and dispatch, "Every step recovers the same
resource", "A live acceptance hold is adopted"). Files: new
`domains/compute/delivery/` (`pyproject.toml`, `Makefile`, `uv.lock`,
`src/compute_delivery/`, `tests/`), `domains/Makefile` (`dist-compute-delivery`,
`test-compute-delivery`), the root `Makefile`'s `dist-domains` and `test` aggregates.

- [ ] 3.1 Create the distribution `arkhai-compute-delivery` (source `compute_delivery`)
      at `domains/compute/delivery`, a compute specialization library depending on
      `arkhai-compute`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-servicing`,
      `arkhai-kit-capacity-publication`, `arkhai-kit-fulfillment` and the compute
      provisioning contracts, never on a storefront; wire its wheel and tests into
      `domains/Makefile` and the root `Makefile` so `make dist` and `make test` include
      it, per `docs/development/BUILD_AND_PACKAGING.md`. `make check-architecture`
      classifies it from its path with no override row (D1).
- [ ] 3.2 Declare the two ports as `typing.Protocol`s — `DeliveryProgress` (load the
      recorded identities, step and activation instant; record reservation, dispatch,
      fulfillment and activation, each written once, in the caller's transaction) and
      `ComputeDeliveryDomain` (reserve claim, accepted hold if any, exact fulfillment
      request, ready evidence, continuation) — and `DeliveryOutcome` with its six
      outcomes, the closed `repair_required` reasons and the identities and evidence
      reference every `repair_required` and `ended` outcome carries (D1).
- [ ] 3.3 Implement `drive(negotiation_id)`'s fail-closed entry: no servicing record or
      no verified evidence is `repair_required(no_accepted_deal)` with nothing written;
      no progress row is a first drive creating it under admission for `reserve`; an
      unknown step, malformed or conflicting identity, wrong-kind port result or empty
      fulfillment result is `repair_required` with its reason and no further effect (D1).
- [ ] 3.4 Derive the window from `servicing_delivery`'s `start_at` and `term_end` only;
      missing or conflicting timing is `repair_required(timing_invalid)`. Before
      `start_at`, return `waiting(wake_at=start_at)` after the commit, releasing the
      convergence claim through the progress port, with nothing dispatched (D4).
- [ ] 3.5 Commit: adopt a supplied acceptance hold first, following D6's table — commit
      it; retry an unanswered or unsigned commit; reserve under
      `<negotiation_id>:settlement` only for a hold verified lapsed (its `:hold` replay
      returns it expired or released, or, keyless, its recorded expiry has passed);
      otherwise reserve under `:settlement`. Every reserve and commit goes through
      `CapacityEffects` after `authorize_delivery` for `commit`; a replayed reservation
      that comes back expired or released is repair-required or the end hand-off,
      never a fresh hold (D6).
- [ ] 3.6 A site refusal of the commit of a held reservation — a live hold or a
      settlement placement — calls `record_end` with the seller-failure classification
      and its `delivery_end` filing at the Agreement start, then releases the
      reservation through end service's no-dispatch path under one key (D11).
- [ ] 3.7 Dispatch: `authorize_delivery` for `dispatch`, the dispatch recorded through
      the progress port before `begin_fulfillment`, the fulfillment identity recorded
      on acknowledgement; recovery with a recorded fulfillment polls it and never
      schedules or begins another (D1, D4).
- [ ] 3.8 Verify: library integration in `domains/compute/delivery/tests/` against
      in-memory port fakes, a fake capacity client and fulfillment client, and the real
      `kit/deal-servicing` journal on SQLite, for every `drive` scenario of the
      `compute-delivery` delta named above — late settlement, missing timing, a forward
      reservation waiting and an end recorded while it waits, the end winning before
      dispatch, an unknown authorization outcome, a lost reserve acknowledgement, a
      released replay, a live hold committed, a hold commit's answer lost, a commit
      refused after reservation with a restart before the release acknowledgement, a
      never-accepted deal, an unknown step and an empty result — plus unit tests of the
      window derivation. Run `make -C domains test-compute-delivery`,
      `make check-packaging` (new distribution and lock) and `make test`. End-to-end:
      none until sections 5 and 7 compose the library.

## 4. The family delivery library: activation through availability, the end hand-off and access

Delivers activation, billing start, availability and convergence, the classified end
hand-off and the live access check (D5's check, D7, D8, D9, D11; `compute-delivery`
"Activation precedes billing start and availability", "Billing start uses end
service's one intent", "Availability and convergence have explicit meanings", "An
undelivered deal is handed to the end operation with classified evidence",
"Credentials are disclosed only through a live, admitted read", "Protected steps are
authorized and admitted" for start and disclose; `deal-lifecycle` "Billing-start
intent and evidence have one owner"). Files: `domains/compute/delivery/src/compute_delivery/`
and its tests; `kit/deal-servicing/tests/integration/` only for the billing-start
refusal scenario.

- [ ] 4.1 Activation after ready evidence, admission for `activate` and no earlier than
      the Agreement start, through `CapacityEffects.activate_lease`: on 200 record the
      site's `activated_at_utc` through the progress port and adopt the current end; on
      409 read `LeaseView` and enter the end hand-off for `releasing` or `released`,
      `repair_required(activation_unexplained)` otherwise; on 404, no answer or an
      unsigned answer, `repair_required(site_unanswered)`, never treated as activated
      (D7, D8).
- [ ] 4.2 Billing start: `authorize_delivery` for `start`, then `EndService.begin_billing`
      with a stable key and a `DeliveryEvidence` whose `ActivatedDeliveryRef` names the
      capacity reservation and the site's instant in integer seconds and whose
      `ReadyEvidenceRef` comes from the domain port; recovery repeats the same key and
      keeps no intent of its own (D9).
- [ ] 4.3 Availability and convergence: `authorize_delivery` for `disclose`, then
      `EndSession.available` without any buyer read; `converged` once the domain's
      continuation is acknowledged or absent, retried without another fulfillment (D1).
- [ ] 4.4 The end hand-off for refusals, provisioning failure, an elapsed window and a
      lapsed activation: `record_end` with actor, cause, source, the Agreement start, the
      fixed observation time, identities and verified evidence; consume end service's
      classification and timing; no amounts, stop or reverse; late settlement after the
      window dispatches nothing and supplies never-delivered evidence (D11).
- [ ] 4.5 The access check: `available` or `converged`, start reached, admission; a
      fetch through an injected result reader outside any transaction; a revision and
      due-end recheck before returning, discarding the fetched material when an end won;
      no payment snapshot (D5).
- [ ] 4.6 Verify: library integration in `domains/compute/delivery/tests/` with the real
      journal, port fakes, the once-only adapters (`kit/arkhai-payments`' and section 2's)
      and the clock-injected payments engine and in-process mediation fake from kit
      fixtures, for a truncation before activation, expiry claiming the lease first, a
      site that cannot activate, a lost billing-start acknowledgement, a once-only no-op
      start, a buyer who never reads, pending evidence publication, a lawful end before
      availability, settlement after the window, an end winning during the fetch and a
      response already in flight; and a `kit/deal-servicing` integration case, if none
      exists, for `begin_billing` refusing evidence without an `ActivatedDeliveryRef`
      and journaling nothing. Run `make -C domains test-compute-delivery`,
      `make -C kit test-deal-servicing` and `make test`. End-to-end: none until sections
      5 and 7.

## 5. VM on the family path

Delivers VM's port implementations, its hook and recovery running `drive`, the window
fallbacks removed, its hold and settlement placements keyed, the Alkahest adapter
composed, and its additive migration (D1, D2 for VM's column and phase rename, D4, D6,
D10; `vm-storefront-fulfillment` "A VM deal's lease begins at its reservation commit",
"VM settlement stages own their mechanism's steps", "Full settlement convergence
ownership", "Physical fulfillment resumption", "A step after physical fulfillment
defers a VM deal, never fails it"). Files under `domains/vms/storefront/src/market_storefront/`:
`payment_repository.py` (progress port), a new delivery-port module for
`ComputeDeliveryDomain`, `domain_runtime.py` (`_fulfill_vm_context`),
`payment_settlement.py`, `settlement_composition.py`, `services/fulfillment_service.py`,
`services/vm_fulfillment_service.py`, `services/fulfillment_resume_runtime.py`,
`negotiation_runtime.py` (`_place_capacity_hold`), `delivery_records.py`,
`utils/migrations.py`; `domains/vms/storefront/pyproject.toml` and its lock.

- [ ] 5.1 Implement `DeliveryProgress` over `vm_delivery_records` and
      `ComputeDeliveryDomain` from VM's fulfillment context, claim, accepted hold,
      result codec and Alkahest continuation; declare `arkhai-compute-delivery`; compose
      the Alkahest adapter in VM's payment-adapter table (D1, D10).
- [ ] 5.2 Run `drive` inside `_fulfill_vm_context` and from the resume pass and the
      Alkahest servicing continuation, mapping outcomes to fulfilled, deferred or failed;
      remove the reservation, commit, dispatch and result steps the path now owns from
      `vm_fulfillment_service.py`, `fulfillment_service.py` and
      `fulfillment_resume_runtime.py` (D1, D4).
- [ ] 5.3 Remove `_parse_start_utc`'s now-fallback and every `or 3600` duration default
      on the delivery path, keeping minute-format reads of persisted timestamps; remove
      the fresh-reserve fallback on a failed hold commit; `_place_capacity_hold` passes
      `<negotiation_id>:hold` (D4, D6).
- [ ] 5.4 Migration: add `vm_delivery_records.activated_at_utc` and rename stored
      `fulfillment_phase='activate'` to `'ready'`, in VM's ordered migration list (D1, D2).
- [ ] 5.5 Verify: application integration through the canonical typed clients in
      `domains/vms/storefront/tests/integration/test_payment_settlement.py`,
      `test_lifecycle_admission.py` and `test_servicing_composition.py` for a payment
      deal and an Alkahest deal each delivered through `drive` with activation and a
      no-op billing start, late settlement keeping the Agreement end, a forward deal
      waiting until its start, a live hold committed and a lost reserve acknowledgement
      replayed; amend `tests/unit/test_fulfillment_resume_runtime.py`,
      `test_fulfillment_service.py`, `test_fulfillment_provisioning.py` and
      `test_migrations.py` to the path; keep the foundation's admission scenarios ("A
      buyer ends before provisioning", "The storefront restarts between the end and
      provisioning") passing. Run `make test-storefront`, `make check-packaging` and
      `make test`. End-to-end: `e2e_deal`, `e2e_deal_buyer_cli` and
      `e2e_vm_payment_deal` exercise VM delivery on the path once deployed.

## 6. VM credentials read live and not replayed

Delivers VM's live credential reads, the end of credential storage, the declared
credential routes and the clearing migration (D2 for VM's clearing, D5;
`vm-storefront-fulfillment` "A VM deal records only how to reach its VM";
`marketplace-identity` "Body-bound authenticated request and response version").
Files under `domains/vms/storefront/src/market_storefront/`: `settlement_composition.py`
(`serialize_settlement_job`), `controllers/settle_controller.py`,
`middleware/seller_auth.py` and `middleware/buyer_auth.py`, `payment_settlement.py`,
`services/fulfillment_resume_runtime.py` and `services/vm_fulfillment_service.py`
(credential writes), `utils/migrations.py`.

- [ ] 6.1 `settle` and `settle-status` obtain credentials through the library's access
      check over provisioning's fulfillment result, filling the existing typed response;
      stop writing `tenant_credentials` and core's `credentials` rows (D5).
- [ ] 6.2 Declare `settle` and `settle-status` credential-capable beside their operation
      names; record their outcomes without `tenant_credentials`; an exact retry of
      `settle-status` runs the access check again and is refused after an end with a
      signed answer; an exact retry of `settle` resumes the same operation and rebuilds
      only its access part; reservation, skew, changed-request rejection and signing are
      unchanged (D5).
- [ ] 6.3 Migration: clear `tenant_credentials`, core `credentials` rows written for VM
      listings, and the `tenant_credentials` member of every recorded body in
      `auth_replay_reservations`, leaving each record's status and completion (D2).
- [ ] 6.4 Verify: application integration in
      `domains/vms/storefront/tests/integration/test_settle_controller.py` and
      `test_payment_settlement.py` for settle-status populated by a live read, an exact
      retry refused after an admitted end with no recorded body returned, the replay
      record holding no credential, and "A storefront upgrades with recorded credential
      responses" against a database seeded with a recorded body; unit coverage in
      `tests/unit/test_migrations.py`. Run `make test-storefront` and `make test`.
      End-to-end: `e2e_deal` and `e2e_deal_buyer_cli` read credentials through
      settle-status once deployed.

## 7. Bare metal on the family path, through core's hook

Delivers bare metal's port implementations, its entry through `fulfill_domain`, its
migration, the Alkahest adapter composed, its declared credential routes and clearing,
and the removal of its full-list reservation scan (D1, D2 for bare metal, D3, D5, D6,
D10; `physical-provisioning` "Bare-metal delivery enters through the core fulfillment
hook"; `marketplace-identity` for its routes). Files under
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`:
`fulfillment_service.py` (`fulfill_bare_metal`, `_begin`, `_recover_reservation`,
`status`, `access`), `sqlite_client.py` (progress port), a new delivery-port module,
`runtime.py`, `settlement_stages.py`, `alkahest_lifecycle.py`, `lifecycle.py`,
`response_auth.py`, `api.py` route declarations, `migrations.py`;
`domains/bare_metal/storefront/pyproject.toml` and its lock.

- [ ] 7.1 Implement `DeliveryProgress` over `bare_metal_fulfillment_lifecycle` and
      `ComputeDeliveryDomain` from the whole-machine claim, the materialization and the
      access result; declare `arkhai-compute-delivery`; compose the Alkahest adapter
      (D1, D10).
- [ ] 7.2 Payment settle and the Alkahest continuation call `fulfill_domain` with the
      clients in `ports` and the lifecycle in `domain_input`; `fulfill_bare_metal`
      refuses without a lifecycle and runs `drive`; callers read state from the returned
      `StorefrontFulfillmentLifecycle`; `BareMetalLifecycle.cycle` drives waiting and
      pending deals; reserve passes `<negotiation_id>:settlement` beside `escrow_uid` and
      `_recover_reservation`'s full-list scan is removed (D3, D4, D6).
- [ ] 7.3 Migration `bare-metal-storefront-0016`: add
      `bare_metal_fulfillment_lifecycle.activated_at_utc`, and clear `host`, `port` and
      `username` from every recorded body whose `method` is `ssh` in
      `auth_replay_reservations`, leaving status and completion (D2).
- [ ] 7.4 Declare `access` and `status` credential-capable; `response_auth.py` records
      their outcomes without access material and resolves their exact retries by running
      the access check again (D5).
- [ ] 7.5 Verify: application integration through the canonical typed clients in
      `domains/bare_metal/storefront/tests/integration/test_payment_settlement_client.py`,
      `test_servicing_composition.py` and `test_site_reservation.py` for a payment deal
      and an Alkahest deal entering through `fulfill_domain` with activation, late
      settlement keeping the Agreement end, a forward deal waiting, a lost reserve
      acknowledgement replayed by key, the hook refusing without a lifecycle, an exact
      `access` retry refused after an end, and "A bare-metal storefront upgrades with
      recorded access responses"; amend `tests/test_fulfillment_service.py`,
      `test_restart_recovery.py` and `test_migrations.py`; keep the foundation's "A
      buyer tears down bare metal" passing. Run `make test-bare-metal`,
      `make check-packaging` and `make test`. End-to-end: `e2e_bare_metal_mock_deal` and
      `e2e_bare_metal_payment_deal` exercise bare-metal delivery on the path once
      deployed.

## 8. Cross-service qualification in the lanes

Delivers the lane evidence for both domains: activation observed at the site, delayed
settlement, the future-start wait, restart and acknowledgement gaps and a commit
refusal (D4, D6, D8, D11; the `compute-delivery` and `vm-storefront-fulfillment`
scenarios at system level). Files: `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`
and the VM and bare-metal deal scenario modules under
`e2e-tests/tests/e2e/roles/scenarios/`, using their existing typed clients, loop
controls and mock-provisioning rules.

- [ ] 8.1 Extend the shared compute deal stages to read the lease through `LeaseView`
      after delivery and assert `activated_at_utc` is set and the end equals the
      Agreement end, in both domains' complete-deal scenarios.
- [ ] 8.2 Add a stage settling a deal after its Agreement start, asserting the
      committed window is the Agreement's; and a forward deal asserting nothing is
      dispatched before its start and delivery follows it, using the lane's loop
      controls rather than sleeps.
- [ ] 8.3 Drive, with the existing loop and mock-rule controls, a restart at each
      adjacent step and each intent/acknowledgement gap (reserve, dispatch, activation,
      billing start) recovering the same reservation and fulfillment, and a commit
      refusal recorded as seller failure, released through the no-dispatch path, and
      recovered across a restart without a second reservation. Record the run evidence;
      the deadline-caused refusal is `renewable-compute-lease-deadlines`'.
- [ ] 8.4 Run the complete-deal markers in the ready lanes — `e2e_deal`,
      `e2e_deal_buyer_cli`, `e2e_vm_payment_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_payment_deal`, and `e2e_credits_payment_deal` as the API-credit
      regression — through `make -C e2e-tests test-e2e-vm`, `test-e2e-bare-metal` and
      `test-e2e-apicredits`. The mediation and filing lane runs wait for
      `add-arkhai-payments-lane-double`; until it lands they are recorded as blocked,
      never as passing. End-to-end: these markers are the section's evidence.

## 9. Closeout

Documentation only; a code defect returns to implementation. Parts in the order of
`openspec/README.md#plan-closeout-requirements`.

- [ ] 9.1 **Comment hygiene.** Run `make check-comment-hygiene`; any finding, or a
      comment this change added that describes the change rather than the invariant,
      returns the change to implementation.
- [ ] 9.2 **Import placement.** Check the imports sections 1–8 added are module-level
      unless a demonstrated cycle or recorded lazy-load reason keeps one local; a move
      returns the change to implementation.
- [ ] 9.3 **Documentation compliance.** Re-check D1–D14 against the placement table in
      `openspec/README.md#documentation-placement`; end service's and the site's rules
      are referenced, not restated.
- [ ] 9.4 **Narrative compression.** Compress completed task notes to final behaviour,
      material evidence, deferred work and destinations; move any reasoning into
      `design.md` first.
- [ ] 9.5 **Roadmap currency.** In `docs/development/ROADMAP.md` Goal 8: rewrite the
      `unify-compute-delivery-path` gap row as archived, and the current state's "No
      delivery path calls it yet" to say both domains activate every delivered lease
      through one path. Name the edits in the design promotion record.
- [ ] 9.6 **Campaign index currency.** In `openspec/changes/README.md`, point this
      change's row at its archive with its notes, and update Goal 8's graph; leave other
      rows' `Depends on` for archive cleanup; run `make check-change-index`.
- [ ] 9.7 **Packaging.** Run `make check-packaging` and
      `make check-architecture-change CHANGE=unify-compute-delivery-path`; resolve every
      failure, leaving no exception or override row owned by this change.
- [ ] 9.8 **End-to-end pipeline.** Record the pipeline run and result and the outcome
      of each section 8 scenario; the mediation and filing lane runs are recorded as
      blocked on `add-arkhai-payments-lane-double` if it has not landed.
- [ ] 9.9 **Promotion.** Write `openspec/specs/compute-delivery/architecture.md` (the
      family path, its ports and `drive`, the future-start wait, the hold adoption table,
      activation and billing order, the access check); add `compute-delivery` to both
      tables of `openspec/specs/README.md`; amend `docs/development/ARCHITECTURE.md`
      "Family kits" (the delivery library beside `provisioning/compute`), "Capacity
      reservation" (the placement key; activation now called by delivery), "Fulfillment"
      (the delivery order), "Fulfillment status and results" (live credential reads)
      and "Marketplace identity" (credential-capable routes);
      `docs/development/DEPLOYMENT_AND_CONFIG.md` "Migrations at startup" (the additive
      migrations and shape clearing); `openspec/specs/vm-storefront-fulfillment/architecture.md`
      "Evidence and delivery ownership"; `openspec/specs/physical-provisioning/architecture.md`
      "Bare-metal storefront pull boundary" (entry through core's hook);
      `openspec/specs/site-capacity/architecture.md` "Reservation lifecycle";
      `openspec/specs/deal-lifecycle/architecture.md` "Package and counterpart
      boundaries" (the Alkahest once-only adapter);
      `openspec/specs/fulfillment/architecture.md` "Storefront pull composition"
      (boundary only). The archive writes the six `spec.md` deltas. Complete the design
      promotion record with each exact heading.
- [ ] 9.10 **Documentation citations.** Run
      `make check-doc-citations CHANGE=unify-compute-delivery-path`, then
      `make check-change CHANGE=unify-compute-delivery-path` (its strict OpenSpec
      validation included); resolve every failure.
- [ ] 9.11 **Archival.** Archive with
      `bunx @fission-ai/openspec@1.14.0 archive unify-compute-delivery-path -y`, merging
      the six deltas; re-diff each MODIFIED block against the permanent requirement
      first. Archive before `redesign-authenticated-requests`, whose MODIFIED block of the
      same `marketplace-identity` requirement keeps this one's clauses.
