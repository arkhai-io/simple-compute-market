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

Notes compressed at closeout (9.4) to final behaviour, evidence, deferrals and
destinations; the refinements and rejected alternatives they recorded are in
`design.md` D16, and the full notes are in Git history.

## 1. Reserve replay keyed by the deal's placement

Delivers the site's placement-keyed reserve replay (D6; `site-capacity` "Reserve replay
is keyed by the deal's placement"). Files: `kit/site/src/market_site/ledger.py`
(`reserve`, `_find_reservation`), `kit/site/src/market_site/router.py` only if the
reserve body model needs the key named, `kit/site-client` only if its reserve call
filters `deal_ref`, and their tests.

- [x] 1.1 Accept `deal_ref.placement_key` in `CapacityLedgerService.reserve` as an
      idempotency key beside `escrow_uid`, looked up in the reserve's own transaction
      across every state (held, committed, released), not only
      `HELD_RESERVATION_STATES`. An exact replay returns the recorded reservation's
      payload and admits nothing; a replay under the key that changes the claim's
      dimensions or attributes, the pool, the site, the offering mode or the lease
      window raises the ledger's conflict error with nothing written. A reserve
      without the key behaves exactly as today (D6).
      Done: a unique `capacity_reservations.placement_key` column and the admitted
      request in `placement_request`, a replay judged against that record, not the
      row; a keyed escrow reserve adopts an unkeyed held row; a blank or non-string
      key is 422; the reserve route maps every `CapacityConflictError` to 409 (the
      escrow offering-mode mismatch had been a 500). `kit/site-client` unchanged.
      Refinements: D16 "Site".
- [x] 1.2 Add an index on the stored placement key if the lookup would otherwise scan
      `deal_ref` JSON, in both services hosting the ledger (compute provisioning and API
      credits), as an ordered migration each; leave expiry indexing and retention to
      `capacity-reservation-lifecycle-hardening` (D6).
      Done: `20261106_002_reservation_placement_key` (compute provisioning) and
      `20261106_008_reservation_placement_key` (API credits) add both columns and the
      unique index `ix_capacity_reservations_placement_key`; no backfill.
- [x] 1.3 Verify: library integration in `kit/site/tests/integration/test_ledger.py`
      for the three `site-capacity` scenarios — a lost acknowledgement replayed, a
      changed window refused with nothing written, a lapsed `:hold` beside a new
      `:settlement` placement — plus a replay of a released reservation returning it
      released, and the existing `escrow_uid` idempotency unchanged. Run
      `make -C kit test-site`, the compute provisioning and API-credit service suites
      for their migrations, and `make test`. End-to-end: none exercises the key until
      section 5 sends it; no scenario is owed here.
      Library integration (`test_ledger.py`): the three scenarios, each changed field
      refused with nothing written, a released replay, a truncated lease replayed
      exactly, key validation, escrow adoption and refusal; existing escrow tests
      unchanged. Application integration (`test_capacity_api.py`, typed
      `SiteCapacityClient`): replay, 409 on a changed window or offering mode, 422 on
      a bad key. Migration integration in both services: existing rows unkeyed,
      rerun idempotent, the index unique. `make -C kit test-site` 366 passed;
      `make test-provisioning` and the API-credit service suite passed; `make test`
      passed. End-to-end: none. Owed by validation: none.

## 2. Alkahest once-only delivery adapter

Delivers the Alkahest payment adapter composing `OnceDeliveryPolicy` (D10;
`deal-lifecycle` "Delivery phases use a shared evidence-gated protocol"). Files: a new
module in `kit/alkahest/src/market_alkahest/` beside `escrow_verification.py`,
`kit/alkahest/pyproject.toml` (declare `arkhai-kit-deal-lifecycle` and its contracts
kit, as `kit/arkhai-payments` does), its lock, and its tests.

- [x] 2.1 Implement the adapter to the `PaymentAdapter` protocol of
      `kit/deal-lifecycle/src/market_deal_lifecycle/adapters.py`: `authorize` and
      `start_billing` delegate to `OnceDeliveryPolicy` with an injected validator of the
      selected Alkahest stage's typed, versioned commitment evidence; `supported_commands`
      is empty, so `submit_payment` refuses every payment command; `read` reports the
      authority view as unsupported; billing start is a no-op only with activation
      evidence (D10).
      Done: `AlkahestOnceAdapter` in `market_alkahest.payment_adapter` (not
      re-exported), constructed with the negotiation, the stage's commitment and the
      composition's `CommitmentValidator`; evidence for another deal or commitment is
      refused before the validator runs; `read` is rejected naming `alkahest.v1`.
      Declared `arkhai-kit-deal-lifecycle` and its contracts; `make lock` added them
      wherever the Alkahest kit is installed and changed nothing else;
      `docs/development/RELEASING.md`'s row names them. No version bump (D16
      "Versions").
- [x] 2.2 Verify: unit tests in `kit/alkahest/tests/unit/` for allow on valid
      evidence, refuse on invalid evidence, a no-op start with activation evidence, a
      refused start without it, and every payment command refused by `submit_payment`;
      `make -C kit test-alkahest`; `make check-packaging` for the new declaration and
      lock; `make test`. End-to-end: none until section 5 composes it; no scenario is
      owed here.
      Unit (`test_payment_adapter.py`): every listed case, the binding check before
      the validator, and every command refused through a `PaymentAdapterTable` before
      the operation store. `make -C kit test-alkahest` 463 passed;
      `make check-packaging` passed; `make test` passed after the release-guide row
      fix. End-to-end: none. Owed by validation: none.

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

- [x] 3.1 Create the distribution `arkhai-compute-delivery` (source `compute_delivery`)
      at `domains/compute/delivery`, a compute specialization library depending on
      `arkhai-compute`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-servicing`,
      `arkhai-kit-capacity-publication`, `arkhai-kit-fulfillment` and the compute
      provisioning contracts, never on a storefront; wire its wheel and tests into
      `domains/Makefile` and the root `Makefile` so `make dist` and `make test` include
      it, per `docs/development/BUILD_AND_PACKAGING.md`. `make check-architecture`
      classifies it from its path with no override row (D1).
      Done, declaring what it imports rather than the list (D16 "Library"); dev group
      the Alkahest and payments kits its tests compose. Make targets wired; also
      `.github/workflows/tests.yml`'s matrix (`test-compute-delivery`) and the
      `compute` publish filter in `publish-pypi.yml` narrowed to that project's own
      files.
- [x] 3.2 Declare the two ports as `typing.Protocol`s — `DeliveryProgress` (load the
      recorded identities, step and activation instant; record reservation, dispatch,
      fulfillment and activation, each written once, in the caller's transaction) and
      `ComputeDeliveryDomain` (reserve claim, accepted hold if any, exact fulfillment
      request, ready evidence, continuation) — and `DeliveryOutcome` with its six
      outcomes, the closed `repair_required` reasons and the identities and evidence
      reference every `repair_required` and `ended` outcome carries (D1).
      Done in `ports.py` and `outcome.py`, adding `DeliveryProgress.release_claim`,
      `ComputeDeliveryDomain.accepted_deal` and the `SiteFulfillment` protocol
      (D1's "As built"). Promoted: `compute-delivery/architecture.md#ports-and-drive`.
- [x] 3.3 Implement `drive(negotiation_id)`'s fail-closed entry: no servicing record or
      no verified evidence is `repair_required(no_accepted_deal)` with nothing written;
      no progress row is a first drive creating it under admission for `reserve`; an
      unknown step, malformed or conflicting identity, wrong-kind port result or empty
      fulfillment result is `repair_required` with its reason and no further effect (D1).
      Done in `path.py` and `progress.py`, each failure mapped to a closed reason with
      an evidence reference naming what was read.
- [x] 3.4 Derive the window from `servicing_delivery`'s `start_at` and `term_end` only;
      missing or conflicting timing is `repair_required(timing_invalid)`. Before
      `start_at`, return `waiting(wake_at=start_at)` after the commit, releasing the
      convergence claim through the progress port, with nothing dispatched (D4).
      Done in `window.py`; a committed end earlier than the Agreement's is accepted,
      since only truncation moves a lease's end.
- [x] 3.5 Commit: adopt a supplied acceptance hold first, following D6's table — commit
      it; retry an unanswered or unsigned commit; reserve under
      `<negotiation_id>:settlement` only for a hold verified lapsed (its `:hold` replay
      returns it expired or released, or, keyless, its recorded expiry has passed);
      otherwise reserve under `:settlement`. Every reserve and commit goes through
      `CapacityEffects` after `authorize_delivery` for `commit`; a replayed reservation
      that comes back expired or released is repair-required or the end hand-off,
      never a fresh hold (D6).
      Done. A signed 404 or 409 is a refusal; anything else unanswered and repeated.
      A refused or mismatched `:hold` replay is `domain_result_invalid` with nothing
      released. A refused, empty or released `:settlement` placement is the end
      hand-off as `start_failure`. A reservation is recorded without admission, so
      the end releases it. Promoted: `compute-delivery/architecture.md#commit-and-hold-adoption`.
- [x] 3.6 A site refusal of the commit of a held reservation — a live hold or a
      settlement placement — calls `record_end` with the seller-failure classification
      and its `delivery_end` filing at the Agreement start, then releases the
      reservation through end service's no-dispatch path under one key (D11).
      Done (`_hand_off`, `_record_failure`): admission first, the refusal retained as
      a `seller_assertion` evidence item, the end recorded with its filing at the
      Agreement start (or, under an earlier lawful end, that end controlling with no
      filing), then `EndService.drive_physical` under the terminate intent's key,
      repeated by the next drive on failure. Deferred: classification chosen by the
      caller (D16 "Classification"), unowned work in `openspec/changes/README.md`.
- [x] 3.7 Dispatch: `authorize_delivery` for `dispatch`, the dispatch recorded through
      the progress port before `begin_fulfillment`, the fulfillment identity recorded
      on acknowledgement; recovery with a recorded fulfillment polls it and never
      schedules or begins another (D1, D4).
      Done: the dispatch record is the authorization's `apply` callback; a recorded
      dispatch without a fulfillment repeats the same request; authorization evidence
      holds only what is fixed before the phase (D16 "Library").
- [x] 3.8 Verify: library integration in `domains/compute/delivery/tests/` against
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
      Library integration (`test_drive_entry.py`, `test_drive_commit.py`,
      `test_drive_dispatch.py`, over the real servicing journal and end service on
      SQLite, the progress fake's row in the same database): every listed scenario
      and the fail-closed and malformed-answer cases. Unit: window, timestamps,
      committed-window check, progress reading, outcome invariants.
      `make -C domains test-compute-delivery` 81 passed; `make check-packaging`
      passed with no architecture warning; `make test` passed. End-to-end: none.
      Owed by validation: none.

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

- [x] 4.1 Activation after ready evidence, admission for `activate` and no earlier than
      the Agreement start, through `CapacityEffects.activate_lease`: on 200 record the
      site's `activated_at_utc` through the progress port and adopt the current end; on
      409 read `LeaseView` and enter the end hand-off for `releasing` or `released`,
      `repair_required(activation_unexplained)` otherwise; on 404, no answer or an
      unsigned answer, `repair_required(site_unanswered)`, never treated as activated
      (D7, D8).
      Done (`_activate`, `_activation_refused`); the instant in whole seconds, recorded
      once; an answer for another reservation or with no instant is `site_unanswered`;
      a 409 is explained only by a `LeaseView` naming the recorded reservation.
- [x] 4.2 Billing start: `authorize_delivery` for `start`, then `EndService.begin_billing`
      with a stable key and a `DeliveryEvidence` whose `ActivatedDeliveryRef` names the
      capacity reservation and the site's instant in integer seconds and whose
      `ReadyEvidenceRef` comes from the domain port; recovery repeats the same key and
      keeps no intent of its own (D9).
      Done (`_start_billing`), key `<negotiation_id>:billing-start`; a rejection is
      the end path when an end is due, else `no_accepted_deal`; guards for a site
      instant ahead of this clock and changed ready evidence (D16 "Library").
- [x] 4.3 Availability and convergence: `authorize_delivery` for `disclose`, then
      `EndSession.available` without any buyer read; `converged` once the domain's
      continuation is acknowledged or absent, retried without another fulfillment (D1).
      Done (`_disclose`, `_converge`): `available` written in the authorization's own
      transaction. Every drive of an available deal runs the continuation, then
      reconciles a due end (D11 "An end after availability", from round 1's triage,
      22 F2); a continuation answer of the wrong kind is `domain_result_invalid`.
- [x] 4.4 The end hand-off for refusals, provisioning failure, an elapsed window and a
      lapsed activation: `record_end` with actor, cause, source, the Agreement start, the
      fixed observation time, identities and verified evidence; consume end service's
      classification and timing; no amounts, stop or reverse; late settlement after the
      window dispatches nothing and supplies never-delivered evidence (D11).
      Done through `_hand_off`: `provisioning_failure`, `activation_lapse` and
      `non_delivery`, each under a source fixed by what failed; admission before every
      poll past dispatch; an unknown fulfillment state is `site_unanswered`; a buyer's
      lawful end ends the deal at the next admission with nothing recorded by the
      path. Promoted: `compute-delivery/architecture.md#the-end-hand-off`.
- [x] 4.5 The access check: `available` or `converged`, start reached, admission; a
      fetch through an injected result reader outside any transaction; a revision and
      due-end recheck before returning, discarding the fetched material when an end won;
      no payment snapshot (D5).
      Done: `ComputeDeliveryPath.read_access(negotiation_id, fetch)`, refusing with
      `AccessRefused` (`not_available`, `not_started`, `ended`); the recheck admits
      `disclose` at the pre-fetch and current revisions.
- [x] 4.6 Verify: library integration in `domains/compute/delivery/tests/` with the real
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
      Library integration (`test_drive_delivery.py`, `test_access.py`): every listed
      scenario, both once-only adapters (the payments kit's over its fake client),
      identity checks on status and lease answers, and an end after availability with
      and without a pending continuation. The in-process mediation fake is not used:
      the path journals the filing and never sends it, so the tests assert the
      journaled filing (D16 "Library"). `kit/deal-servicing`'s `test_end.py` gains
      the `begin_billing` refusal with nothing journaled.
      `make -C domains test-compute-delivery` 126 passed after round 1's triage
      fixes; `make -C kit test-deal-servicing` 64 passed; `make test`,
      `make check-packaging` and `make check-comment-hygiene` passed. End-to-end:
      none. Owed by validation: none.

      Round 1 triage fixes (review 22; validation 24 passed): 22 F1, identities checked
      on status and lease reads; 22 F2, an end after availability, the owner's option
      B, recorded in D11 and the delta's availability requirement. Tests as in 4.6.

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

- [x] 5.1 Implement `DeliveryProgress` over `vm_delivery_records` and
      `ComputeDeliveryDomain` from VM's fulfillment context, claim, accepted hold,
      result codec and Alkahest continuation; declare `arkhai-compute-delivery`; compose
      the Alkahest adapter in VM's payment-adapter table (D1, D10).
      Done: `VmDeliveryProgress` (`payment_repository.py`), `VmDeliveryDomain` and
      `VmSiteFulfillment` (new `delivery_ports.py`, the latter scheduling before it
      begins); the Alkahest entry in `VmDealLifecycle`'s table with validator
      `alkahest_commitment_valid`. `make lock` changed only the VM storefront and
      `e2e-tests` locks. Promoted: `vm-storefront-fulfillment/architecture.md#evidence-and-delivery-ownership`.
- [x] 5.2 Run `drive` inside `_fulfill_vm_context` and from the resume pass and the
      Alkahest servicing continuation, mapping outcomes to fulfilled, deferred or failed;
      remove the reservation, commit, dispatch and result steps the path now owns from
      `vm_fulfillment_service.py`, `fulfillment_service.py` and
      `fulfillment_resume_runtime.py` (D1, D4).
      Done: `drive_vm_delivery` records `ready`/`ended`, runs the failure policy once
      for the path's own end, emits the `provision` stage events once each, and keeps
      driving a dispatched deal up to `[provisioning].timeout`; `available` is deferred
      in both settle paths. `vm_fulfillment_service.py` is deleted. Outside the plan
      (D16 "VM composition"): `update_vm_delivery` no longer admits, `apply_end`
      writes no `ended` status, the release policy adopts the path's end, and no
      credential is written (section 6's storage removal). Permanent specs citing
      removed VM tests (`site-capacity`, `storefront-publication`,
      `settlement-servicing`) cite the surviving ones.
- [x] 5.3 Remove `_parse_start_utc`'s now-fallback and every `or 3600` duration default
      on the delivery path, keeping minute-format reads of persisted timestamps; remove
      the fresh-reserve fallback on a failed hold commit; `_place_capacity_hold` passes
      `<negotiation_id>:hold` (D4, D6).
      Done: the fallbacks went with the deleted module; `_place_capacity_hold`
      reserves under `:hold` and stores the exact request as the hold's `placement`.
      The negotiation's own `or 3600` (an Agreement term default) is untouched.
- [x] 5.4 Migration: add `vm_delivery_records.activated_at_utc` and rename stored
      `fulfillment_phase='activate'` to `'ready'`, in VM's ordered migration list (D1, D2).
      Done: `20261106_001_vm_delivery_activation`, idempotent. Promoted:
      `DEPLOYMENT_AND_CONFIG.md#migrations-at-startup`.
- [x] 5.5 Verify: application integration through the canonical typed clients in
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
      Application integration in a new `tests/integration/test_vm_delivery_path.py`
      (the named files' harness replaces VM's hook): every listed scenario through
      the real app, hook, path and end service, with the site and provisioning faked
      at the aggregate clients; the resume-pass suite moved to integration and
      rewritten over the real path. Amended and new unit tests for the result
      reading, migration, outcome projection and stage recovery; tests of deleted code
      removed. The foundation's admission scenarios pass unchanged.
      `make test-storefront` unit 1165, integration 541 passed; `make check-packaging`
      passed; `make test` passed after `manifests/published-distributions.json`
      gained `compute-delivery`. End-to-end: the three markers, the round's evidence
      with section 6. Owed by validation: none.
- [x] 5.6 Publish `arkhai-compute-delivery` with the first storefront that depends on
      it: a filter and a manifest row in `.github/workflows/publish-pypi.yml` (after
      `compute-provisioning-contracts`, which it depends on) and a row in
      `docs/development/RELEASING.md` naming its internal dependencies, or
      `scripts/tests/test_publish_matrix.py` fails once a published storefront
      declares it. A new PyPI project needs the owner's trusted-publisher setup and
      its GitHub environment, which no session can make: ask the owner before the
      section is committed. Added by section 3's implementation, which built the
      distribution.
      Done on the owner's answer A (2026-11-06): both workflow rows, the
      `RELEASING.md` rows and the manifest entry. Deferred to the owner: the PyPI
      trusted publisher and GitHub environment `pypi-arkhai-compute-delivery`
      before the next release; until then only that package's publish job fails.
      Release tooling passed (2433).

## 6. VM credentials read live and not replayed

Delivers VM's live credential reads, the end of credential storage, the declared
credential routes and the clearing migration (D2 for VM's clearing, D5;
`vm-storefront-fulfillment` "A VM deal records only how to reach its VM";
`marketplace-identity` "Body-bound authenticated request and response version").
Files under `domains/vms/storefront/src/market_storefront/`: `settlement_composition.py`
(`serialize_settlement_job`), `controllers/settle_controller.py`,
`middleware/seller_auth.py` and `middleware/buyer_auth.py`, `payment_settlement.py`,
`services/fulfillment_resume_runtime.py` and `services/vm_fulfillment_service.py`
(credential writes), `utils/migrations.py`. Amended by section 5's implementation:
`vm_fulfillment_service.py` is deleted and no credential is written any more (5.2's
notes); the live read goes through `delivery_ports.py`'s path.

- [x] 6.1 `settle` and `settle-status` obtain credentials through the library's access
      check over provisioning's fulfillment result, filling the existing typed response;
      stop writing `tenant_credentials` and core's `credentials` rows (D5).
      Done: `delivery_ports.read_vm_credentials` over `read_access`; the settle
      controller answers without credentials when access is refused or provisioning
      cannot serve the result. Provisioning clients are built on first use.
- [x] 6.2 Declare `settle` and `settle-status` credential-capable beside their operation
      names; record their outcomes without `tenant_credentials`; an exact retry of
      `settle-status` runs the access check again and is refused after an end with a
      signed answer; an exact retry of `settle` resumes the same operation and rebuilds
      only its access part; reservation, skew, changed-request rejection and signing are
      unchanged (D5).
      Done in `middleware/seller_auth.py` (`CREDENTIAL_CAPABLE_ROUTES`,
      `without_access_material`). An exact settle retry after an end resumes and
      answers without credentials rather than refusing, since its operation has
      already resumed. Core is unchanged.
- [x] 6.3 Migration: clear `tenant_credentials`, core `credentials` rows written for VM
      listings, and the `tenant_credentials` member of every recorded body in
      `auth_replay_reservations`, leaving each record's status and completion (D2).
      Done: `20261106_002_vm_credentials_cleared`, keeping the `credentials` rows of
      listings another offering mode binds; idempotent.
- [x] 6.4 Verify: application integration in
      `domains/vms/storefront/tests/integration/test_settle_controller.py` and
      `test_payment_settlement.py` for settle-status populated by a live read, an exact
      retry refused after an admitted end with no recorded body returned, the replay
      record holding no credential, and "A storefront upgrades with recorded credential
      responses" against a database seeded with a recorded body; unit coverage in
      `tests/unit/test_migrations.py`. Run `make test-storefront` and `make test`.
      End-to-end: `e2e_deal` and `e2e_deal_buyer_cli` read credentials through
      settle-status once deployed.
      Application integration in `test_vm_delivery_path.py`'s payment rig (the named
      files cover admin routes or replace VM's hook): every listed case, including the
      settle retry's rebuilt access part and the upgrade of a seeded database. Unit:
      the clearing and `serialize_settlement_job`. `make test-storefront` unit 1166,
      integration 545 passed; `make test` passed. End-to-end: `e2e_deal` and
      `e2e_deal_buyer_cli` (`compute_deal_driver.assert_delivery`). Owed by
      validation: none.

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

- [x] 7.1 Implement `DeliveryProgress` over `bare_metal_fulfillment_lifecycle` and
      `ComputeDeliveryDomain` from the whole-machine claim, the materialization and the
      access result; declare `arkhai-compute-delivery`; compose the Alkahest adapter
      (D1, D10).
      Done in `delivery_ports.py` (`BareMetalDeliveryProgress`,
      `BareMetalDeliveryDomain`, `BareMetalSiteFulfillment`); the row is created only
      while settlement is verified; the domain's refusals are
      `BareMetalDeliveryRefused` (409). The Alkahest entry in `BareMetalLifecycle`'s
      table has its own validator (D16 "Alkahest adapter"). `make lock` changed the
      bare-metal storefront, VM storefront and `e2e-tests` locks;
      `RELEASING.md`'s row names the library. Promoted:
      `physical-provisioning/architecture.md#bare-metal-storefront-pull-boundary`.
- [x] 7.2 Payment settle and the Alkahest continuation call `fulfill_domain` with the
      clients in `ports` and the lifecycle in `domain_input`; `fulfill_bare_metal`
      refuses without a lifecycle and runs `drive`; callers read state from the returned
      `StorefrontFulfillmentLifecycle`; `BareMetalLifecycle.cycle` drives waiting and
      pending deals; reserve passes `<negotiation_id>:settlement` beside `escrow_uid` and
      `_recover_reservation`'s full-list scan is removed (D3, D4, D6).
      Done: `BareMetalFulfillmentService.deliver` revalidates the settlement on every
      drive and calls `fulfill_domain`; `begin`, `_begin`, `_admit`,
      `_recover_reservation` and `lease_window.py` are gone. Settle refuses (409) a
      deal ended before dispatch; the Alkahest ready step publishes once available.
      Kept by permanent requirements: the status read refuses a site delivery
      conflicting with the recorded result, and drives an active, unavailable deal;
      the access read does not drive (D16 "Bare-metal composition"). `apply_end`
      releases rather than terminates a row with no dispatch and no fulfillment.
- [x] 7.3 Migration `bare-metal-storefront-0016`: add
      `bare_metal_fulfillment_lifecycle.activated_at_utc`, and clear `host`, `port` and
      `username` from every recorded body whose `method` is `ssh` in
      `auth_replay_reservations`, leaving status and completion (D2).
      Done: `bare-metal-storefront-0016-delivery-activation`, idempotent, leaving a
      database without core's replay table to core; it also marks a row with a saved
      materialization and no fulfillment as dispatched.
- [x] 7.4 Declare `access` and `status` credential-capable; `response_auth.py` records
      their outcomes without access material and resolves their exact retries by running
      the access check again (D5).
      Done: `response_auth.CREDENTIAL_CAPABLE_ROUTES` (`access` with `host`, `port`,
      `username`; `status` with none); `access` reads through `read_access`, 410 after
      an admitted end, 409 before availability or the start.
- [x] 7.5 Verify: application integration through the canonical typed clients in
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
      New `tests/integration/test_delivery_path.py` over the real storefront runtime:
      every listed scenario; the exact `access` retry goes through the buyer's typed
      transport with one request identity (round 2's triage, 39 F3).
      `test_site_reservation.py` against `kit/site`'s real router and ledger: the claim
      reserved, committed and replayed by key. `test_payment_settlement_client.py`,
      `test_http_settlement.py`, the lifecycle, Alkahest, restart and deal-control
      suites amended to typed site answers; unit migration tests for 0016.
      `test_fulfillment_service.py` (the deleted `begin`'s unit file) is removed, its
      cases moved; `storefront-publication`'s two citations of it moved too. The
      foundation's "A buyer tears down bare metal" passes. `make test-bare-metal`
      593 passed; `make check-packaging` passed; `make test` passed. End-to-end: the
      two markers. Owed by validation: none.

## 8. Cross-service qualification in the lanes

Delivers the lane evidence for both domains: activation observed at the site, delayed
settlement, the future-start wait, restart and acknowledgement gaps and a commit
refusal (D4, D6, D8, D11; the `compute-delivery` and `vm-storefront-fulfillment`
scenarios at system level). Files: `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`
and the VM and bare-metal deal scenario modules under
`e2e-tests/tests/e2e/roles/scenarios/`, using their existing typed clients, loop
controls and mock-provisioning rules.

- [x] 8.1 Extend the shared compute deal stages to read the lease through `LeaseView`
      after delivery and assert `activated_at_utc` is set and the end equals the
      Agreement end, in both domains' complete-deal scenarios.
      Done in the shared stages (`e2e_deal`, `e2e_bare_metal_mock_deal`; the
      real-provisioning modules declare them but are in no lane): 06b records the
      Agreement window, 09c holds the lease to it within `WINDOW_TOLERANCE` (1 s) and
      requires an activation after settlement inside the window.
- [x] 8.2 Add a stage settling a deal after its Agreement start, asserting the
      committed window is the Agreement's; and a forward deal asserting nothing is
      dispatched before its start and delivery follows it, using the lane's loop
      controls rather than sleeps.
      Late settlement is the canonical deal's 08b in both domains, waiting with
      `wait_until` until the start is `LATE_SETTLEMENT` (3 s) behind (unit-tested in
      `e2e-tests/tests/unit/test_compute_deal_stages.py`). The forward deal is VM's
      `vms/delivery_timing_deal.py` (13a–13c, 30 s ahead), waiting on the new
      `provision/reserved` event, then stepping the resume pass after the start. Bare
      metal has no forward deal (its Agreements start at acceptance); its wait is
      7.5's library integration. `docs/development/TESTING.md` amended (D15).
- [x] 8.3 Drive, with the existing loop and mock-rule controls, a restart at each
      adjacent step and each intent/acknowledgement gap (reserve, dispatch, activation,
      billing start) recovering the same reservation and fulfillment, and a commit
      refusal recorded as seller failure, released through the no-dispatch path, and
      recovered across a restart without a second reservation. Record the run evidence;
      the deadline-caused refusal is `renewable-compute-lease-deadlines`'.
      Restated by the owner, ratifying D15 (39 F1): the lanes show a restart as one
      recovery-loop step, and a seller failure before dispatch as a settlement
      placement that finds no capacity. The reserve, dispatch, activation and
      billing-start acknowledgement gaps, a refused commit of a live hold or
      reservation released without dispatch, and the replay under the placement key
      are qualified below the lanes: library integration in
      `domains/compute/delivery/tests/integration/` (`test_drive_commit.py`'s lost
      reserve and hold-commit answers and refused commits, `test_drive_dispatch.py`'s
      lost dispatch acknowledgement, `test_drive_delivery.py`'s lost billing-start
      acknowledgement and unanswered activation), the placement-key replay against
      `kit/site`'s real router and ledger (`test_site_reservation.py`), and both
      storefronts' application integration (5.5, 7.5). No lane control injects these
      faults, and none is added.
      Done to that boundary. Bare metal (`bare_metal/recovery_stages.py`): 09a1 steps
      `delivery-recovery` once the fulfillment is active and observes the re-drive
      activate the lease; 08b1 steps the cycle between dispatch and readiness (the
      same reservation and fulfillment, though nothing shows the drive ran). VM's
      recovery evidence is the forward deal, carried by the resume pass alone, since
      its settle call holds the claim. Commit refusal: VM's 13d and bare metal's 13a
      take the capacity after acceptance; the buyer's lifecycle read shows the
      seller's end, cause `capacity_unavailable`, source `delivery`, nothing
      dispatched, no reservation of the deal's own. Not in a lane: the acknowledgement
      gaps and a refused live commit (library and application integration), and
      filing dispatch (Alkahest unsupported; payment waits for
      `add-arkhai-payments-lane-double`).
      Defects the lanes found and fixed: VM's settle wait now takes `ended` as terminal
      (`test_a_settlement_wait_returns_once_delivery_has_ended`); bare metal's
      lifecycle watch reads a mandate only for an Arkhai payment
      (`test_an_alkahest_deals_lifecycle_read_shows_delivery_with_no_payment_account`).
      Bare metal's settle wait was fixed in round 2's triage (39 F2, below).
- [x] 8.4 Run the complete-deal markers in the ready lanes — `e2e_deal`,
      `e2e_deal_buyer_cli`, `e2e_vm_payment_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_payment_deal`, and `e2e_credits_payment_deal` as the API-credit
      regression — through `make -C e2e-tests test-e2e-vm`, `test-e2e-bare-metal` and
      `test-e2e-apicredits`. The mediation and filing lane runs wait for
      `add-arkhai-payments-lane-double`; until it lands they are recorded as blocked,
      never as passing. End-to-end: these markers are the section's evidence.
      Local `make -C e2e-tests test-e2e` over `eb488f40b`: VM 157 passed, 2 skipped;
      bare metal 73 passed; API credits 4 passed. The two skips are
      `e2e_vm_payment_deal`'s mediation case stages, blocked on
      `add-arkhai-payments-lane-double`, not passing. The fresh-context check's later
      stage fixes were not lane-run locally (Docker's credential helper failed
      through WSL); validation 41's pipeline is their lane evidence. `make test`,
      `make test-bare-metal`, `make check-packaging` and
      `make check-comment-hygiene` passed. Owed by validation: none.

Round 2's triage fixes (review 39, validation 41 passed at `312e67ccd`), outside the
plan's tasks:

- 39 F1: the owner ratified D15; 8.3 states the evidence boundary. No code.
- 39 F2: bare metal's admin settle wait answers a terminal `ended` once the deal's end
  has taken effect and it was never available (`deal_controls.py`,
  `BareMetalLifecycle.ended_before_delivery`), proven through the typed admin client
  (`test_deal_controls.py::test_wait_answers_a_deal_ended_before_delivery_at_once`;
  against the unfixed predicate it ran out its wait). `ROADMAP.md` Goal 8 records the
  owner's unowned gap on whether stage 09b should step delivery explicitly. Placed in
  the `compute-delivery` delta by the pre-closeout triage (53 F1).
- 39 F3: the exact-retry test goes through the buyer's typed transport:
  `core_buyer.signed_storefront_json` and `BareMetalFulfillmentTransport.status`/`.access`
  take an optional `request_id`.
- 31 R1 / 42 R1: `.agents/skills/change-validate/SKILL.md` gives the e2e log fetch the
  longest background timeout. Workflow guidance, outside the change's scope.

Checks: `make test-bare-metal`, `make test-core`, `make check-packaging`, `make test`
and `make check-comment-hygiene` passed.

## 9. Closeout

Documentation only; a code defect returns to implementation. Parts in the order of
`openspec/README.md#plan-closeout-requirements`.

- [x] 9.1 **Comment hygiene.** Run `make check-comment-hygiene`; any finding, or a
      comment this change added that describes the change rather than the invariant,
      returns the change to implementation.
      `make check-comment-hygiene` passed. A read of the comments and docstrings
      added since the merge base with `origin/dev` found none naming a review,
      triage or migration that introduced the code; the migration docstrings
      describe what each migration does to an earlier database, which is their
      subject. No fix round needed.
- [x] 9.2 **Import placement.** Check the imports sections 1–8 added are module-level
      unless a demonstrated cycle or recorded lazy-load reason keeps one local; a move
      returns the change to implementation.
      No indented (function-local, `TYPE_CHECKING` or guarded) import was added in
      any `.py` file since the merge base; the repository's local-imports check passed
      within `run pre-commit`. Nothing to move.
- [x] 9.3 **Documentation compliance.** Re-check D1–D14 against the placement table in
      `openspec/README.md#documentation-placement`; end service's and the site's rules
      are referenced, not restated.
      D1–D16 checked: normative behaviour in the six deltas; rationale and limits in
      the companions (the new `compute-delivery/architecture.md`, and the
      VM, physical-provisioning, site-capacity, deal-lifecycle and fulfillment
      companions); repository-wide shape in `ARCHITECTURE.md`; migrations in
      `DEPLOYMENT_AND_CONFIG.md`; lane method in `TESTING.md` (D15); D12–D14 and
      D16's versions item stay here. The `compute-delivery` delta and companion name
      end service's operations (`authorize_delivery`, admission, `begin_billing`,
      `record_end`) and the site's placement key and activation, linking their
      owning specifications rather than restating their rules. Promoted statements
      were written from the implementation notes and checked against the code where
      they name it: the path's entry and order (`path.py`), the migration IDs, both
      credential-route declarations, the stage events, `read_vm_credentials`,
      `ended_before_delivery` and `AlkahestOnceAdapter`.
- [x] 9.4 **Narrative compression.** Compress completed task notes to final behaviour,
      material evidence, deferred work and destinations; move any reasoning into
      `design.md` first.
      Done: sections 1–8 and the round-2 triage notes compressed. Moved to
      `design.md` first as D16: the site's replay refinements, the adapter's naming
      and per-storefront validators, the library's declarations, no lock and
      authorization-evidence rule, scheduling placement, the VM and bare-metal
      composition decisions with the declined test seams, versions, and
      classification. Dropped as duplication of Git history: fresh-context check
      narratives, debugging of transient test failures, and intra-change handoffs
      the later sections fulfilled.
- [x] 9.5 **Roadmap currency.** In `docs/development/ROADMAP.md` Goal 8: rewrite the
      `unify-compute-delivery-path` gap row as archived, and the current state's "No
      delivery path calls it yet" to say both domains activate every delivered lease
      through one path. Name the edits in the design promotion record.
      Done: the current state describes the one path, activation before billing and
      availability, placement-keyed recovery and live credential reads; "unified
      compute delivery" removed from what the once-only adapter does not claim; the
      gap row reads as archived and links the archive. Named in the record.
- [x] 9.6 **Campaign index currency.** In `openspec/changes/README.md`, point this
      change's row at its archive with its notes, and update Goal 8's graph; leave other
      rows' `Depends on` for archive cleanup; run `make check-change-index`.
      Done: the row's status is `in closeout`, its notes rewritten, its link pointed
      at the archive after archival. Goal 8's graph is unchanged: it draws no status
      but `archived`, which archive cleanup writes. Every other row's `Depends on`
      and status left for archive cleanup. `scripts/change-workflow check index`
      passed before and after the archive.
- [x] 9.7 **Packaging.** Run `make check-packaging` and
      `make check-architecture-change CHANGE=unify-compute-delivery-path`; resolve every
      failure, leaving no exception or override row owned by this change.
      `scripts/change-workflow run pre-archive unify-compute-delivery-path` at
      `885e2be4c`: `make check-packaging` passed (locks, wheels, Python selection,
      layer, scope, dependency and kind rules); "unify-compute-delivery-path owns no
      architecture row". The skills check passed within `run pre-commit`.
- [x] 9.8 **End-to-end pipeline.** Record the pipeline run and result and the outcome
      of each section 8 scenario; the mediation and filing lane runs are recorded as
      blocked on `add-arkhai-payments-lane-double` if it has not landed.
      Validation 54 at `885e2be4c` — the merge of `origin/dev` after the pre-closeout
      triage, the commit closeout builds on, with no code change since — passed:
      e2e.yml run 42367703989 succeeded (e2e-vm 157 passed, 2 skipped; e2e-bare-metal
      72 passed; e2e-apicredits 4 passed; native-ansible-gate 19 run, none failed);
      local `make test` and `make check-packaging` passed; the Helm release passed.
      Section 8's scenarios ran in those lanes with no failure: `e2e_deal`,
      `e2e_deal_buyer_cli` and `e2e_vm_payment_deal` (VM delivery, activation in 09c,
      late settlement in 08b, the forward deal 13a–13c, the capacity-taken failure
      13d, credentials through settle-status), and `e2e_bare_metal_mock_deal` and
      `e2e_bare_metal_payment_deal` (bare-metal delivery, 09c, 08b, the recovery
      steps 08b1 and 09a1, the capacity-taken failure 13a); `e2e_credits_payment_deal`
      as the API-credit regression. The record read the lanes' summaries, not each
      scenario's lines. The two VM skips are `e2e_vm_payment_deal`'s mediation case
      stages: blocked on `add-arkhai-payments-lane-double` (in design), not passing;
      no filing lane runs. No section owed a CI observation (`Owed by validation:
      none` throughout; validation 54's CI part not owed).
- [x] 9.9 **Promotion.** Write `openspec/specs/compute-delivery/architecture.md` (the
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
      (boundary only). The archive writes the six `spec.md` deltas, `compute-delivery`'s
      "A deal ended before delivery settles the wait as ended" among them, the settle
      wait's terminal `ended` that the 8.4 note flagged (53 F1). Complete the design
      promotion record with each exact heading.
      Done: every named document written, describing the current system; the
      `compute-delivery` row of `openspec/specs/README.md`'s capability table added
      after the archive, since the capability-index check refuses a link to a
      `spec.md` the archive has not yet written; its settlement-ownership row added
      before. `proposal.md`'s "Knowledge to promote" gained D16. The design promotion
      record names each heading. The six deltas merge through the archive (9.11):
      no permanent spec held their text beforehand.
- [x] 9.10 **Documentation citations.** Run
      `make check-doc-citations CHANGE=unify-compute-delivery-path`, then
      `make check-change CHANGE=unify-compute-delivery-path` (its strict OpenSpec
      validation included); resolve every failure.
      `scripts/change-workflow run pre-commit unify-compute-delivery-path --base
      origin/dev` (the repository's citations, specification index, decision
      destinations, history wording, version bumps, local imports and capability
      index checks, and `openspec validate --strict`): first run failed on D16's
      missing destination bullet and the index row linking the unwritten
      `compute-delivery/spec.md`; both resolved as above; the rerun passed.
- [x] 9.11 **Archival.** Archive with
      `bunx @fission-ai/openspec@1.14.0 archive unify-compute-delivery-path -y`, merging
      the six deltas; re-diff each MODIFIED block against the permanent requirement
      first. Archive before `redesign-authenticated-requests`, whose MODIFIED block of the
      same `marketplace-identity` requirement keeps this one's clauses.
      Each MODIFIED block (`deal-lifecycle`'s billing-start requirement,
      `marketplace-identity`'s body-bound requirement, six `vm-storefront-fulfillment`
      requirements) was compared with its permanent requirement at `885e2be4c`, after
      the merge of `origin/dev`: each keeps the permanent text and differs only by
      this change's intended clauses. `redesign-authenticated-requests` is still active, so this change
      archives first. Archived without `--skip-specs` through
      `scripts/change-workflow openspec archive`, which runs the pinned OpenSpec; the
      merged specs were then read back.
