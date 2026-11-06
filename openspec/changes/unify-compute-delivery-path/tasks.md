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

- [x] 1.1 Accept `deal_ref.placement_key` in `CapacityLedgerService.reserve` as an
      idempotency key beside `escrow_uid`, looked up in the reserve's own transaction
      across every state (held, committed, released), not only
      `HELD_RESERVATION_STATES`. An exact replay returns the recorded reservation's
      payload and admits nothing; a replay under the key that changes the claim's
      dimensions or attributes, the pool, the site, the offering mode or the lease
      window raises the ledger's conflict error with nothing written. A reserve
      without the key behaves exactly as today (D6).
      Done. The key is lifted from `deal_ref` into a unique
      `capacity_reservations.placement_key` column, and the request it was admitted
      for — resource type, claim attributes (the pool, when the claim names one),
      offering mode, dimensions and the window *as asked* (normalized start, duration)
      — into `placement_request` JSON. A replay is compared with that record, not with
      the row's own window, because commit and truncation move the row's window after
      admission: comparing against the row would refuse the exact replay of a
      truncated lease. The site is the ledger itself, so a replay at another site
      finds no key. The TTL is not compared: a replay returns the hold whose expiry
      was fixed at admission. The placement lookup runs first; with no recorded key
      the escrow lookup runs as before, and when it finds a held row placed without
      a key it adopts that row under the key (so a bare-metal deal reserved before
      the upgrade is found by its key once released), while a row held under another
      key refuses the reserve. A non-string or blank key is a `ValueError` (422).
      `resize_reservation` does not lift the key (it has no caller, and lifting would
      put two rows under one key). These refinements are recorded in `design.md` D6.
      Outside the plan: the reserve route mapped only
      `UndeclaredOfferingModeError` to 409, so the existing escrow
      offering-mode mismatch (`CapacityConflictError`) surfaced as a 500; the route
      now maps every `CapacityConflictError` to 409, which the placement refusal
      needs too (`kit/site/src/market_site/router.py`). `ReserveRequest.deal_ref`'s
      description names the key (`http_models.py`); `kit/site-client` passes
      `deal_ref` verbatim and needed no change.
- [x] 1.2 Add an index on the stored placement key if the lookup would otherwise scan
      `deal_ref` JSON, in both services hosting the ledger (compute provisioning and API
      credits), as an ordered migration each; leave expiry indexing and retention to
      `capacity-reservation-lifecycle-hardening` (D6).
      Done: `20261106_002_reservation_placement_key` (compute provisioning) and
      `20261106_008_reservation_placement_key` (API credits) add both columns and the
      unique index `ix_capacity_reservations_placement_key`, the name `create_all`
      gives a fresh database. No backfill: no reserve carried a key before.
- [x] 1.3 Verify: library integration in `kit/site/tests/integration/test_ledger.py`
      for the three `site-capacity` scenarios — a lost acknowledgement replayed, a
      changed window refused with nothing written, a lapsed `:hold` beside a new
      `:settlement` placement — plus a replay of a released reservation returning it
      released, and the existing `escrow_uid` idempotency unchanged. Run
      `make -C kit test-site`, the compute provisioning and API-credit service suites
      for their migrations, and `make test`. End-to-end: none exercises the key until
      section 5 sends it; no scenario is owed here.
      Library integration (`test_ledger.py`, real ledger on SQLite): the three
      scenarios; a changed start, duration, dimensions, pool attribute and offering
      mode each refused with no row, event or availability change; a released
      replay; a lease committed with a later start and then truncated, replayed by
      its exact request; a site-clock start replayed equal; a blank or non-string key
      refused; an unkeyed escrow reservation adopted under the key and found by it
      after release; an escrow held under another key refusing the reserve. The
      existing escrow tests pass unchanged. `make -C kit test-site`: 366 passed.
      Application integration (compute provisioning, typed `SiteCapacityClient`
      against the in-process app, `test_capacity_api.py`): a keyed replay returns
      the first reservation with the event version unchanged; a changed window
      answers 409 with one reservation listed and its recorded start unchanged; an
      escrow repeat naming another offering mode answers 409 (it was a 500); a
      non-string key answers 422. Library integration of the migrations
      (`provisioning/compute/service/tests/integration/test_database.py`,
      `domains/apicredits/service/tests/integration/test_migrations.py`): existing
      rows migrate with no key, a rerun changes nothing, the index is unique and
      refuses a second row under one key (`IntegrityError`). After the fresh-context
      review's fixes, `make test-provisioning` (unit 648, integration 589 passed)
      and the API-credit service suite (82 passed) pass. `make test` passed before
      those fixes, which touched only the keyed escrow path and tests; it is rerun
      with section 2. `make check-comment-hygiene` passes within `make check-change`.
      End-to-end: none, confirmed. Owed by validation: none.

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
      Done: `AlkahestOnceAdapter` in `kit/alkahest/src/market_alkahest/payment_adapter.py`,
      constructed with the deal's `negotiation_id`, the stage's `commitment_ref` and the
      composition's `validate_commitment` (`CommitmentValidator`, an async predicate
      over `DeliveryEvidence`). As `kit/arkhai-payments`' adapter does, evidence naming
      another negotiation or commitment is refused before the validator runs. `read`
      answers `AuthorityView(outcome=Rejected("alkahest.v1 has no lifecycle adapter"))`,
      the reason servicing already gives a deal with no adapter, so a read stays
      rejected naming the mechanism as `deal-lifecycle` "A read without an adapter
      still shows delivery" requires, whichever table a storefront composes it into;
      `validate` and `submit` refuse every command. The module is named for a payment
      adapter, not a lifecycle adapter: in the specs a lifecycle adapter is what makes
      an option carry lifecycle terms, and Alkahest still has none. Sections 5 and 7
      import `market_alkahest.payment_adapter`; it is not re-exported from the
      package. Declared
      `arkhai-kit-deal-lifecycle>=0.2.0` and `arkhai-kit-deal-lifecycle-contracts>=0.1.0`
      in `kit/alkahest/pyproject.toml` (both were already transitive through the
      settlement runtime); `make lock` added them to `kit/alkahest/uv.lock` and to the
      dependency list of the Alkahest kit in every lock that installs it (the three
      storefronts, `kit/storefront`, the buyers, the API-credit projects and
      `e2e-tests`), and changed nothing else. `docs/development/RELEASING.md`'s row
      for `arkhai-kit-alkahest` names the two new internal dependencies, as its
      publish-matrix test requires. No version bump: `kit/alkahest` (0.11.0) and
      `kit/site` (0.13.0) are already past their released versions on `dev`, and
      `RELEASING.md` bumps a package at most once before it is released.
      Handoff for sections 5 and 7: each storefront supplies the validator. It should
      compare the evidence with the deal's verified Alkahest settlement evidence (the
      stage's escrow reference and its schema version), not with a reference's mere
      presence; if both storefronts would write the same check, it belongs in
      `kit/alkahest` beside this adapter rather than twice in domain code.
- [x] 2.2 Verify: unit tests in `kit/alkahest/tests/unit/` for allow on valid
      evidence, refuse on invalid evidence, a no-op start with activation evidence, a
      refused start without it, and every payment command refused by `submit_payment`;
      `make -C kit test-alkahest`; `make check-packaging` for the new declaration and
      lock; `make test`. End-to-end: none until section 5 composes it; no scenario is
      owed here.
      Unit (`kit/alkahest/tests/unit/test_payment_adapter.py`, the adapter with a
      mocked validator): allow for each of the six phases on valid evidence; refuse
      when the validator refuses; refuse, with the validator not called, for another
      deal's or commitment's evidence; a no-op accepted billing start with activation
      evidence; a refused start without it (validator not called) and on invalid
      evidence; `start`, `stop` and `reverse` each refused by `submit_payment`
      through a `PaymentAdapterTable` that resolves this adapter, before the
      operation store is touched, and by the adapter's own `submit`; the authority
      view rejected naming `alkahest.v1`. Authorization and billing start are
      `OnceDeliveryPolicy`'s, already unit-tested in `kit/deal-lifecycle`; these
      tests hold the adapter's binding check and validator wiring to them.
      `make -C kit test-alkahest`: 463 passed (16 new). `make check-packaging`
      passes. `make test`'s first run with this section failed only the
      release-guide row test (`scripts/tests/test_publish_matrix.py`), fixed as
      above; `make test-release-tooling` then passed (2428), and a full `make test`
      over sections 1 and 2 together passes. `make check-change` reports only the
      citation of `openspec/specs/compute-delivery/architecture.md`, which closeout
      (9.9) creates. End-to-end: none, confirmed. Owed by validation: none.

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
      Done, with the declarations following the imports rather than the list: it
      declares `arkhai-core` (the result envelope), `arkhai-kit-deal-lifecycle` and
      its contracts, `arkhai-kit-deal-servicing`, `arkhai-kit-capacity-publication`,
      `arkhai-kit-site-client` (the site refusal and unsigned-answer errors it
      classifies), `arkhai-compute-provisioning-contracts`, `arkhai-kit-identity`
      (canonical evidence bodies) and `pydantic`. It imports nothing from
      `arkhai-compute` or `arkhai-kit-fulfillment` (the fulfillment surface it calls
      is the provisioning contracts' wire models), so neither is declared:
      `ARCHITECTURE.md` makes an undeclared import an error and a declaration without
      an import a defect. Dev group: `arkhai-kit-alkahest`, whose once-only adapter
      the tests compose; section 4 adds the payments kit with the tests that use it.
      `domains/Makefile` gains `dist-compute-delivery` (in `dist`) and
      `test-compute-delivery`; the root `Makefile` gains `test-compute-delivery` in
      `test`. The project's first lock was bootstrapped by writing a header-only
      `uv.lock` for `make lock PROJECTS=domains/compute/delivery` to rewrite, since
      `scripts/uv_project.py lock` reads an existing lock.
- [x] 3.2 Declare the two ports as `typing.Protocol`s — `DeliveryProgress` (load the
      recorded identities, step and activation instant; record reservation, dispatch,
      fulfillment and activation, each written once, in the caller's transaction) and
      `ComputeDeliveryDomain` (reserve claim, accepted hold if any, exact fulfillment
      request, ready evidence, continuation) — and `DeliveryOutcome` with its six
      outcomes, the closed `repair_required` reasons and the identities and evidence
      reference every `repair_required` and `ended` outcome carries (D1).
      Done in `ports.py` and `outcome.py`. Each `DeliveryProgress` method takes the
      `sqlite3.Connection` of the transaction the path opens on end service's
      database (both domains' rows live there), so a progress write commits with the
      admission that permits it. The port reports its row as `RecordedProgress`
      in the path's step vocabulary (`reserve`, `commit`, `dispatch`, `fulfillment`,
      `activated`); a value the path does not know is passed through for the path to
      refuse. Beyond the plan: `DeliveryProgress.release_claim` (3.4 releases the
      convergence claim through the progress port, which needs a method);
      `ComputeDeliveryDomain.accepted_deal`, returning `AcceptedDeal(commitment_ref,
      binding, payment)` or `None` — the verified-settlement check 3.3 needs, the
      listing's capacity binding that selects the site, and the payment adapter the
      storefront's table resolves (`None` never allows); and `SiteFulfillment`, the
      provisioning family's begin/status/result/lease reads routed by site, which
      each storefront adapts its client to (the two domains' clients route by
      different keyword arguments). `AcceptedHold` carries the hold's exact
      `HoldPlacement` when it was placed under `:hold`, else its recorded expiry.
      `ContinuationState` is `none`, `acknowledged` or `pending`.
      `DeliveryOutcome.hook_disposition` gives the hook's fulfilled/deferred/failed
      mapping. The outcome carries `evidence_ref` and a `detail` string.
- [x] 3.3 Implement `drive(negotiation_id)`'s fail-closed entry: no servicing record or
      no verified evidence is `repair_required(no_accepted_deal)` with nothing written;
      no progress row is a first drive creating it under admission for `reserve`; an
      unknown step, malformed or conflicting identity, wrong-kind port result or empty
      fulfillment result is `repair_required` with its reason and no further effect (D1).
      Done in `path.py` and `progress.py`. A settlement naming another commitment
      than the servicing record is `no_accepted_deal`, and so is a servicing record
      that does not parse in anything but its timing; a step that disagrees with the
      identities beside it is `progress_unreadable`; a wrong-kind domain answer, a
      fulfillment request for another reservation, an empty result envelope and a
      result showing no ready evidence are `domain_result_invalid`. A refused
      authorization that is not an end (no adapter, invalid commitment evidence) is
      `no_accepted_deal` with the authorization's intent as its evidence; a pending
      or unknown one is `pending`. A malformed site answer (another reservation, no
      reservation identity, a provisioning acknowledgement for another reservation)
      is `site_unanswered`. Evidence references name what was read
      (`servicing_delivery:<id>`, `delivery_progress:<id>`, `settlement:<id>`,
      `reservation:<id>`, `fulfillment:<id>`) or the end request's source.
- [x] 3.4 Derive the window from `servicing_delivery`'s `start_at` and `term_end` only;
      missing or conflicting timing is `repair_required(timing_invalid)`. Before
      `start_at`, return `waiting(wake_at=start_at)` after the commit, releasing the
      convergence claim through the progress port, with nothing dispatched (D4).
      Done in `window.py`. Missing timing is a servicing record that does not parse
      (its detail names the field); an empty term (`term_end <= start_at`) and a
      commit answer whose start differs from the Agreement's or whose end is later
      are conflicting timing. A committed end earlier than the Agreement's is
      accepted: only truncation moves a lease's end, always earlier.
- [x] 3.5 Commit: adopt a supplied acceptance hold first, following D6's table — commit
      it; retry an unanswered or unsigned commit; reserve under
      `<negotiation_id>:settlement` only for a hold verified lapsed (its `:hold` replay
      returns it expired or released, or, keyless, its recorded expiry has passed);
      otherwise reserve under `:settlement`. Every reserve and commit goes through
      `CapacityEffects` after `authorize_delivery` for `commit`; a replayed reservation
      that comes back expired or released is repair-required or the end hand-off,
      never a fresh hold (D6).
      Done. A signed 404 or 409 is a refusal; an unsigned answer, a transport
      failure or any other status is unanswered and the same effect is repeated. A
      keyed hold's `:hold` replay that the site refuses (409) or that finds another
      reservation is `domain_result_invalid` (the domain mis-describes its hold), its
      detail naming what the replay answered; nothing is released, since the site
      answers a found and a newly placed reservation alike and the found one may be
      the deal's live hold, while a placed one carries the hold's TTL. A keyless hold
      with no recorded expiry is never verified lapsed. A refused `:settlement` placement (404 or 409), one that finds
      no capacity (the site answers no reservation), and one that comes back
      released take the end hand-off as `start_failure`, as D6's table and D11 say; a
      released one is recorded first so the end releases it. A reservation is
      recorded without admission: the end operation releases what is recorded, so a
      reservation the site holds is recorded even when an end won meanwhile.
- [x] 3.6 A site refusal of the commit of a held reservation — a live hold or a
      settlement placement — calls `record_end` with the seller-failure classification
      and its `delivery_end` filing at the Agreement start, then releases the
      reservation through end service's no-dispatch path under one key (D11).
      Done (`_hand_off`, `_record_failure`): one transaction runs admission first (so
      a missed deadline is established), retains the observed refusal as a
      `seller_assertion` evidence item under a source fixed by the reservation
      (`delivery:commit-refused:<reservation>`), and records the end as
      `start_failure` with `failure_filing` (never-delivered basis, acting no earlier
      than the Agreement start); an earlier lawful end already due controls the
      classification instead, with no filing, as VM's failure action does. Then
      `EndService.drive_physical` ends the physical side through the domain's end
      port under the terminate intent's key; a failure there is logged and leaves the
      intent pending, and the next drive (admission now `ended`) repeats it under the
      same key. The classification query reads `servicing_final_requests` directly,
      as both domains already do; `EndSession` offers no read of it. Deferred, for
      the round's review to weigh: the fresh-context check read this, and the path's
      choice between its own failure kind and an earlier lawful end's, as end
      service's classification leaking into a third caller (`deal-lifecycle` "Cause
      classification is owned by end service"). Today `record_end` takes the
      caller's `Classification`, so VM's failure action, bare metal's lifecycle and
      this path each build it; moving that choice and the read behind an
      `EndSession` method is a `kit/deal-servicing` change outside this section's
      files, recorded as unowned work under "Settlement and deal servicing depth" in
      `openspec/changes/README.md`. Not separately tested: that admission runs first
      in `_record_failure`.
- [x] 3.7 Dispatch: `authorize_delivery` for `dispatch`, the dispatch recorded through
      the progress port before `begin_fulfillment`, the fulfillment identity recorded
      on acknowledgement; recovery with a recorded fulfillment polls it and never
      schedules or begins another (D1, D4).
      Done. The dispatch record is the authorization's `apply` callback, so it
      commits in the admission's transaction or not at all. A recorded dispatch with
      no fulfillment identity repeats the same request, which provisioning answers
      with the fulfillment it already accepted for the reservation. An exception from
      a fulfillment call propagates with the steps before it recorded. Authorization
      evidence holds only what is fixed before the phase (commit binds the
      commitment, dispatch adds the reservation): end service keys an authorization
      by phase and admission revision and refuses a same-revision retry whose
      evidence differs, which the first run of the late-settlement test hit. With a
      fulfillment recorded, `drive` polls its status and, once active, reads its
      result and the domain's ready evidence, and returns `pending`; activation and
      what follows are section 4's.
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
      Library integration (`tests/integration/`, `ComputeDeliveryPath.drive` over the
      real servicing journal and end service on SQLite, the Alkahest once-only
      adapter with a scripted validator, a fake site, provisioning service, domain
      port and end port; the progress fake keeps its row in the same SQLite database
      rather than in memory, so its writes share the path's transactions):
      `test_drive_entry.py` — a never-accepted deal, no verified settlement, another
      commitment, wrong-kind `accepted_deal`, `reserve_claim` and `accepted_hold`
      answers, missing timing with a recorded reservation kept, an empty term, a
      record unreadable beyond its timing, an unknown step, a self-contradicting row,
      a commitment the adapter refuses, and no adapter; `test_drive_commit.py` — late
      settlement (every commit, first and retried, sent the Agreement window), a
      forward reservation waiting and its claim released, an end recorded while it
      waits, a lost reserve acknowledgement, a released replay, a live hold committed,
      a hold commit's answer lost, a keyed and a keyless hold verified lapsed, a
      refused live hold (with and without a recorded expiry), a commit refused after
      reservation with its evidence item, filing at the Agreement start and a restart
      before the release acknowledgement retrying the same key, a placement finding
      no capacity, a refused placement (404, 409), an unsigned and a 500 commit
      answer each retried on the same reservation, malformed reserve and commit
      answers, a lease committed under other timing, a hold placement the site
      refuses, a hold replay answering another reservation (nothing released), a
      reservation recorded although an end won while it was placed,
      and an earlier lawful end controlling a commit refusal with no filing;
      `test_drive_dispatch.py` — an end recorded after the dispatch authorization
      was read (no dispatch, no dispatch record), an unknown authorization resolved
      under the same intent, dispatch recorded before `begin_fulfillment`, a lost
      dispatch acknowledgement repeating the same request, a worker polling the
      recorded fulfillment, a request for another reservation, a dispatch
      acknowledged for another reservation, an empty result and a result with no
      ready evidence. Unit (`tests/unit/`): window derivation, timestamp reading, the
      committed-window check, progress reading and outcome invariants.
      `make -C domains test-compute-delivery`: 81 passed.
      `make check-packaging` passes, its architecture rules with no warning for the
      new package. `make test`'s first run failed only
      `scripts/tests/test_tests_workflow.py::test_the_matrix_is_make_tests_targets`:
      `.github/workflows/tests.yml`'s matrix must list every `make test` target, so it
      gained `test-compute-delivery` (a file the plan did not name). A second run
      failed two API-credit wheel-install tests
      (`domains/apicredits/tests/test_distribution_install.py`) on an import from the
      installed `market_core`; they passed alone (41 passed) and in the next full
      run, which passed whole after the review's fixes. The `compute`
      publish filter in `.github/workflows/publish-pypi.yml` is narrowed to that
      project's own files, as `bare-metal`'s is, so the nested delivery project does
      not republish `arkhai-compute`. `make check-change` reports only the citation of
      `openspec/specs/compute-delivery/architecture.md`, which closeout (9.9)
      creates. End-to-end: none, confirmed; sections 5 and 7 compose the library.
      Owed by validation: none.
      Handoff for sections 5 and 7: the published storefronts will depend on
      `arkhai-compute-delivery`, so `publish-pypi.yml` needs its row (filter, after
      `compute-provisioning-contracts` in the manifest) and `RELEASING.md` its row,
      or `scripts/tests/test_publish_matrix.py` fails; a new PyPI project also needs
      the owner's trusted-publisher setup, which no session can do. Each storefront
      adapts its fulfillment client to `SiteFulfillment` (bare metal routes by
      `capacity_reservation_id`, VM by `site_id`), builds `AcceptedDeal` from its
      verified evidence, binding and payment-adapter table, and maps its progress
      row onto the step vocabulary. The path holds no lock: the caller serializes
      drives of one deal.

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
      Done (`_activate`, `_activation_refused`). Admission for `activate` runs in its
      own transaction just before the call; an end due there takes the end path. The
      site's instant is read in whole seconds and recorded once; an answer naming
      another reservation or carrying no instant is `site_unanswered`, as are a signed
      404, an unsigned answer and a transport failure. The lease's end is not touched,
      so an earlier truncation stands. "No earlier than the Agreement start" holds by
      order, with no separate check: activation follows dispatch, which follows the
      start. An exception from the `LeaseView` read after a 409 propagates, and the
      next drive asks again.
- [x] 4.2 Billing start: `authorize_delivery` for `start`, then `EndService.begin_billing`
      with a stable key and a `DeliveryEvidence` whose `ActivatedDeliveryRef` names the
      capacity reservation and the site's instant in integer seconds and whose
      `ReadyEvidenceRef` comes from the domain port; recovery repeats the same key and
      keeps no intent of its own (D9).
      Done (`_start_billing`), key `<negotiation_id>:billing-start`; the `start`
      authorization and `begin_billing` carry the same full bundle (reservation,
      fulfillment, activation, ready). An accepted outcome goes on; a rejected one
      takes the end path when an end is due and is otherwise `no_accepted_deal`
      (evidence: the journaled billing intent, or `billing:<negotiation_id>` when end
      service refused before journaling one); pending or unknown leaves the deal
      pending. Two guards before the call, each for a case a test triggers: while the
      site's activation instant is ahead of this clock the deal stays pending (end
      service refuses an activation in its own future, and the instant is the
      site's); and ready evidence that differs from what billing start already
      journaled is `domain_result_invalid`, since `begin_billing` refuses a retry
      whose evidence changed (the port's docstring requires stable evidence).
- [x] 4.3 Availability and convergence: `authorize_delivery` for `disclose`, then
      `EndSession.available` without any buyer read; `converged` once the domain's
      continuation is acknowledged or absent, retried without another fulfillment (D1).
      Done (`_disclose`, `_converge`). `available` is written in the `disclose`
      authorization's own transaction (its `apply`), stamped with the instant read
      just before the authorization: no later than the one the authorization admits
      at, so an end due at it would have refused the authorization too, and
      availability is always written when the authorization allows. End service
      already refuses `disclose` until the billing intent is accepted. Once `available_at` is recorded, later drives go straight to the
      continuation, reading no fulfillment status or result.
      `ContinuationState.pending` returns `available`; `none` and `acknowledged`
      return `converged`.
- [x] 4.4 The end hand-off for refusals, provisioning failure, an elapsed window and a
      lapsed activation: `record_end` with actor, cause, source, the Agreement start, the
      fixed observation time, identities and verified evidence; consume end service's
      classification and timing; no amounts, stop or reverse; late settlement after the
      window dispatches nothing and supplies never-delivered evidence (D11).
      Done through section 3's `_hand_off`: `provisioning_failure` for a fulfillment
      `failed`, `abandoned` or in a teardown state before availability (unless an end
      is already due, which takes the end path), `activation_lapse` for a refused
      activation of a releasing or released lease, and `non_delivery` for an elapsed
      window: admission `ended` with no end recorded and nothing available, which is
      also what settlement after the Agreement's end meets on its first drive, before
      any reservation. Each source is fixed by what failed
      (`delivery:fulfillment-failed:<fulfillment>`, `delivery:activation-lapsed:<reservation>`,
      `delivery:window-elapsed:<negotiation>`). Every drive past dispatch asks
      admission before polling, so a create that never settles cannot outlast a due
      end or the window. An unknown fulfillment state is `site_unanswered`. The path
      journals the filing and never dispatches it; the seller half's servicing does.
      "A lawful end wins before availability" is met this way: the buyer's end
      reaches end service through its own route, which records it with its lawful
      classification; the path's next admission ends the deal, and it records nothing
      of its own and files nothing. Where the path itself observes a failure after
      such an end is due, it records the failure with that end controlling and no
      filing (section 3's `_record_failure`, tested by the commit refusal under an
      earlier lawful end).
- [x] 4.5 The access check: `available` or `converged`, start reached, admission; a
      fetch through an injected result reader outside any transaction; a revision and
      due-end recheck before returning, discarding the fetched material when an end won;
      no payment snapshot (D5).
      Done: `ComputeDeliveryPath.read_access(negotiation_id, fetch)`, where `fetch`
      receives the fulfillment and reservation identities. It refuses with
      `AccessRefused` (`not_available`, `not_started` or `ended`). The recheck admits
      `disclose` again at the current instant, at the revision admitted before the
      fetch and at the current one if that changed: an end recorded earlier that
      falls due during the fetch refuses, as does one recorded during it, while a
      truncation still in the future discloses. It calls no payment adapter.
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
      Library integration (`ComputeDeliveryPath` over the real servicing journal and
      end service on SQLite, with section 3's fakes): `test_drive_delivery.py` — a
      buyer who never reads recorded available, the lease activated before billing
      started, and the billing intent's `ActivatedDeliveryRef` naming the reservation
      and the site's instant; an Alkahest no-op billing start (section 2's adapter);
      the hosted once-only payments adapter (`kit/arkhai-payments`' `PaymentAdapter`
      over its `FakePaymentsClient`, whose engine time the test sets) reaching
      `converged` with a no-op start, each phase read against its signed snapshot;
      pending evidence publication (`available`, then `converged`, with no second
      fulfillment, activation or fulfillment read); a truncation before activation
      kept; expiry claiming the lease first, `releasing` and `released` (no billing,
      `activation_lapse` with its filing); a refused activation of a running lease
      (`activation_unexplained`); a site that cannot activate (unsigned,
      unreachable, 404 — `site_unanswered`, retried to success) and activation
      answers naming another reservation or no instant; billing waiting for this
      clock to reach the site's instant; a lost billing-start acknowledgement
      recovered under the same key and intent (a once-only adapter makes no start,
      so there is none to duplicate); a refused, an end-refused and an unknown
      billing start; ready evidence changed after billing journaled it; a lawful end
      before availability (no filing, no billing, nothing recorded by the path);
      settlement after the window and a create that never settles before the
      window's end (nothing more dispatched, `non_delivery` with a never-delivered
      filing); a failed, abandoned, tearing-down and torn-down fulfillment handed to
      the end port, an end already due when provisioning fails, and an unknown
      fulfillment state. `test_access.py` — a live read making no payment adapter
      call, a future truncation recorded during the fetch still disclosing, an end
      recorded before the read falling due during the fetch discarding the material,
      refusals before availability and before the start, an end admitted during the
      fetch discarding the material, and a read repeated after an end refused
      without fetching while the earlier response stands (nothing in the path
      retracts it). `make -C domains test-compute-delivery`: 116 passed (section 3's
      late-settlement and forward-start tests now expect `converged`, which the path
      reaches). `make check-packaging` passes with the payments kit back in the dev
      group and the lock rewritten. `make test` passed whole on this section before
      the fresh-context check's last three fixes, which touched only the delivery
      library and its tests; that suite then passed (116). `make check-change`
      reports only the closeout citation. End-to-end: none, confirmed; sections 5
      and 7 compose the library. Owed by validation: none. `kit/deal-servicing/tests/integration/test_end.py`
      gains `begin_billing` refusing evidence with no `ActivatedDeliveryRef` before
      any adapter call, journaling no billing intent; `make -C kit test-deal-servicing`:
      64 passed. Differs from the plan: the in-process mediation fake is not used. The
      path journals the seller's `delivery_end` filing with the end and never sends
      it — the seller half's servicing dispatches filings — so a mediation fake would
      exercise servicing, not the path; the tests assert the journaled filing
      instead. The payments kit returns to the dev group for the hosted adapter test.

      Round 1 triage fixes (review 22; validation 24 passed with no failures; the
      owner's notes had none):
      - 22 F1, identities on authority reads: `_ready` acts on a fulfillment status
        only when it is a `FulfillmentStatusResponse` naming the recorded fulfillment
        and reservation, else `site_unanswered`; `_activation_refused` explains a 409
        from the lease only when it is a `LeaseView` naming the recorded reservation,
        else `activation_unexplained` with no hand-off. Both keep the recorded
        identities and end nothing.
      - 22 F2, an end after availability (the owner chose option B, recorded in D11
        and the delta's availability requirement): every drive of an available deal
        runs the continuation, then reconciles a due end — `pending` while the
        continuation is unacknowledged, `ended` through `_ended` once it is
        acknowledged or the domain has none; with no end due, `available` or
        `converged` as before. So 4.3's "later drives go straight to the continuation"
        now means they go to the continuation and then reconcile the end. A
        continuation answer that is not a `ContinuationState` is now
        `domain_result_invalid`: the earlier membership test read the string
        `"acknowledged"` as converged.
      - Tests (library integration, `test_drive_delivery.py`, with a `rewrite` hook on
        the fake fulfillment's status and lease reads): a status naming another
        fulfillment while `active`, and another reservation while `failed`; a status
        and a lease answer of the wrong kind; a lease view naming another reservation
        after a 409; an available Alkahest deal whose claim is pending when the
        buyer's end falls due (`pending`, then `ended` once acknowledged, with no
        delivery failure recorded); an available deal with no continuation ended by
        the buyer; one past its term (`ended`, no hand-off); an end recorded for later
        leaving the deal `converged`; and a continuation answer of the wrong kind.
      - Evidence: `make -C domains test-compute-delivery` 126 passed (library
        integration and unit); `make test` passed; `make check-packaging` passes;
        `make check-comment-hygiene` passes; `make check-change` fails only on the
        closeout citation of `openspec/specs/compute-delivery/architecture.md`, as
        before. The fresh-context check found nothing that must be fixed. Taken from
        it: a test for a lease answer of the wrong kind; the 2×2 status case reduced
        to two, per `TESTING.md`'s one representative case; and D11's residual
        widened to the `pending`-then-`ended` path a hook can see. Noted, no change:
        while the continuation is pending the path does not drive the physical end,
        because the route that records an end already does. End-to-end: none, as
        before; owed by validation: none.

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
      Done. `VmDeliveryProgress` (`payment_repository.py`) reads the step from what the
      row records — activation instant, then fulfillment identity, then a `dispatch`
      phase, then a reservation — so rows written before the path read the same way;
      a phase VM never writes is passed through as the step, so the path's
      `progress_unreadable` still fires for VM; each identity is written once in the
      path's transaction. The new module
      `delivery_ports.py` holds `VmDeliveryDomain`: `accepted_deal` reads the recorded
      verified evidence (commitment = its settlement reference, the servicing record's)
      and the listing's durable binding, and resolves the payment adapter from the deal
      lifecycle's table; `reserve_claim` is the evidence's claim with the binding's
      offering mode and `deal_ref` naming listing and negotiation (the path's commit
      sends only the claim's `deal_ref`, so the negotiation must be in it);
      `accepted_hold` reads `capacity_holds`, its `placement` when the hold was placed
      under its key, else its recorded expiry; `fulfillment_request` reuses a stored
      context once shown to match the evidence, else builds it from the evidence and
      stores it; `ready_evidence` is `vm.connection-details.v1` over the endpoint,
      readiness and resource identities (never a credential), checked against the
      recorded identities; `continuation` reads the result again, runs the selected
      stage's `continue_delivery` with the settlement composition, then records
      `fulfillment_uid`, `connection_details` and the listing's fulfilled resource —
      nothing VM-visible is written before availability. `VmSiteFulfillment` schedules
      before it begins, since provisioning accepts a fulfillment only for a scheduled
      reservation (the library calls only `begin_fulfillment`). The Alkahest entry is in
      `VmDealLifecycle`'s one payment-adapter table (`alkahest_adapter`, validator
      `alkahest_commitment_valid`: the recorded evidence's mechanism, status, escrow
      reference and schema), so `SellerServicing` resolves it too; its read stays
      rejected naming the mechanism. `arkhai-compute-delivery>=0.1.0` declared;
      `make lock` changed only the VM storefront and `e2e-tests` locks.
- [x] 5.2 Run `drive` inside `_fulfill_vm_context` and from the resume pass and the
      Alkahest servicing continuation, mapping outcomes to fulfilled, deferred or failed;
      remove the reservation, commit, dispatch and result steps the path now owns from
      `vm_fulfillment_service.py`, `fulfillment_service.py` and
      `fulfillment_resume_runtime.py` (D1, D4).
      Done. `_fulfill_vm_context` builds the path (`vm_delivery_path`, capacity and
      fulfillment from `ports` when given, else the runtime's) and runs
      `drive_vm_delivery`, which records `ready` on `converged` and `ended` on `ended`
      (`record_vm_delivery_outcome`, first terminal write wins), runs the seller's
      failure policy once when the end is the path's own failure record (evidence
      `delivery:*`), treats a drive stopped by an exception as deferred, and emits the
      `provision` stage events once each as the records first show them —
      `job_submitted` when a fulfillment identity is first recorded (the lanes wait on
      it), `fulfilled` on convergence, `failed` on the path's own failure end. As VM's
      settle task did, the hook keeps driving a dispatched deal while provisioning
      settles (`pending` with a fulfillment), polling at `[provisioning].poll_interval`
      up to `[provisioning].timeout`; past that the resume pass carries it. The hook
      maps `available`/`converged` to fulfilled, `ended` to failed, the rest deferred;
      payment `_provision` and Alkahest `fulfill_vm_settlement` treat an `available`
      outcome (continuation pending) as deferred, so the resume pass converges it. The
      resume pass revalidates through the stage, then drives. `vm_fulfillment_service.py`
      is deleted; `fulfillment_service.py` keeps the result reading
      (`fulfillment_result_connection`), the job-spec preview and `terminate_vm_lease`.
      `VmPaymentsCoordinator` takes optional `capacity`/`fulfillment`, the seam the tests
      inject through. Outside the plan, needed by the path: `update_vm_delivery` no
      longer admits (the path admits every protected step, and the Alkahest
      continuation's own writes must survive an end after availability, D11);
      `DeliveryEnded` and `admit_delivery`'s availability branch are gone;
      `VmPhysicalEnd.apply_end` no longer writes `status='ended'`, which would stop the
      resume pass driving an ended deal whose continuation is pending — the drive
      records it; `_end_failed_delivery` (failure policy's `release_capacity`) adopts an
      end the path recorded (`source == "delivery"`) instead of recording a second.
      Section 6 work done here because the modules that did it are deleted: nothing
      writes `tenant_credentials` (delivery record or escrow) or core's `credentials`
      rows any more (D5); settle and settle-status therefore carry no credentials until
      section 6's live read. Outside the plan, cross-references the deletions broke:
      `openspec/specs/site-capacity/spec.md`, `storefront-publication/spec.md` and
      `settlement-servicing/spec.md` cited removed or moved VM tests and now cite the
      surviving ones; `kit/site`'s ledger docstring and one of its tests named the
      deleted module.
- [x] 5.3 Remove `_parse_start_utc`'s now-fallback and every `or 3600` duration default
      on the delivery path, keeping minute-format reads of persisted timestamps; remove
      the fresh-reserve fallback on a failed hold commit; `_place_capacity_hold` passes
      `<negotiation_id>:hold` (D4, D6).
      Done: the fallbacks went with the deleted module and the rewritten resume pass;
      `reserve_vm_settlement_start` reads the evidence's start with no now-fallback.
      `_place_capacity_hold` reserves under `<negotiation_id>:hold` and stores the exact
      request (`claim`, `deal_ref`, `ttl_seconds`, start, duration) as the hold
      payload's `placement`, which `accepted_hold` replays. Tested: the key on the
      reserve a force-accept sends (`test_negotiate_controller.py`) and the read side
      (the live-hold delivery test seeds a recorded placement); the write of
      `placement` itself is not exercised end to end, since that fixture's site holds no
      matching capacity and saves no hold. The negotiation's own `or 3600` (an
      Agreement term default, not delivery) is untouched.
- [x] 5.4 Migration: add `vm_delivery_records.activated_at_utc` and rename stored
      `fulfillment_phase='activate'` to `'ready'`, in VM's ordered migration list (D1, D2).
      Done: `20261106_001_vm_delivery_activation` (`add_vm_delivery_activation` in
      `payment_repository.py`), appended to `VM_MIGRATIONS`; idempotent.
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
      Application integration through the canonical typed clients
      (`tests/integration/test_vm_delivery_path.py`, a new file rather than additions to
      the three the plan named, since their harness replaces VM's hook with a controlled
      one; real app, middleware, SQLite, VM hook, path, end service and deal lifecycle,
      the payments kit's fake behind `PaymentsClient`, and the site and provisioning
      service replaced at the aggregate clients by `tests/delivery_fakes.py`): a payment
      deal settled by `settle_agreement` is activated at the site, its billing intent's
      `ActivatedDeliveryRef` names the reservation and the recorded instant, it is
      available with no buyer read, `ready`, with connection details and no credential
      stored, one reservation (under the negotiation and its `:settlement` key, no
      settlement reference) and one schedule, and `job_submitted` then `fulfilled`
      reported once each; a lifecycle `commit` reaches `active`
      with no settle-status poll; late settlement commits the Agreement window on every
      commit; a forward deal is committed and leased at settlement, its claim released,
      nothing begun, and the resume pass still begins nothing before the start; a live
      `:hold` is committed and is the only reservation; a lost reserve acknowledgement
      leaves the deal open and the resume pass's replay under the placement key finds the
      same reservation and delivers it. Through core's `fulfill_domain` with the
      settlement already verified (the escrow check reads a chain): an Alkahest deal is
      activated, its billing start is the once-only no-op, its claim is published and
      bound and it converges `ready`, the published evidence carrying no credential; its
      publication failing once leaves it `available`/open and the next drive publishes
      it with no second fulfillment or reservation. The fulfillment request names no
      guest, is stored before it is sent and rebuilt identically, and a stored request
      for other evidence is refused. `tests/integration/test_fulfillment_resume_runtime.py`
      (moved from `unit/`, rewritten: the resume pass over the real path and SQLite): a
      recorded fulfillment resumes with no schedule or begin and converges; a failed
      fulfillment is handed to the end and the failure policy runs once across two
      passes; a result naming another fulfillment is never activated or made available;
      a phase VM never writes leaves the deal unactivated (`progress_unreadable`).
      Application integration with VM's hook replaced by the harness's controlled one:
      an available deal whose continuation is pending stays open through payment
      `_provision` (`test_payment_settlement.py`); the configured release adopts an end
      the path recorded, with one end and one filing (`test_lifecycle_failures.py`); the
      force-accept hold reserves under `<negotiation_id>:hold`
      (`test_negotiate_controller.py`). Unit: the result-to-connection reading, the
      no-relay source check and `terminate_vm_lease` (`test_fulfillment_service.py`,
      which absorbed `test_fulfillment_provisioning.py`), the migration's column, rename
      and rerun and a fresh database recording it (`test_migrations.py`), the outcome
      projection storing no credential and an available Alkahest outcome deferred, not
      fulfilled (`test_settlement_composition.py`), and the stage's ambiguous on-chain
      recovery never resubmitting (new `test_settlement_stages.py`). Removed with the
      code they tested: `test_two_phase_reserve.py`,
      `test_fulfill_vm_obligation_error_handling.py`, the `_do_provision`/poll/retry
      tests, `test_reservation_closes_oversized_dynamic_listings` (which drove the
      deleted `fulfill_compute_obligation`; the capacity-delta subscriber it observed is
      independent of delivery) and `test_committed_window`'s resume test (with the
      recovery commit gone it tested only the fake). Amended because the controlled hook
      no longer has `_provision` record availability: `test_lifecycle_failures.py`
      records it in setup; `_seed` gained a start and the listing's `sla`/`region` (the
      listing binding validates them); `vm_delivery_evidence`'s source names its chain,
      as recorded evidence does. The foundation's
      "A buyer ends before provisioning" and "The storefront restarts between the end and
      provisioning" (`test_lifecycle_admission.py`) pass unchanged, as does
      `test_servicing_composition.py` with the Alkahest adapter in the table.
      `make test-storefront`: unit 1165 passed, integration 541 passed.
      `make check-packaging` passes. `make test`'s first run failed only
      `scripts/tests/test_publish_matrix.py::test_a_manifest_package_depends_only_on_manifest_packages[vms-storefront]`:
      `manifests/published-distributions.json` also lists every published distribution
      in dependency order, so it gained `compute-delivery` after
      `compute-provisioning-contracts` (a file the plan did not name);
      `make test-release-tooling` then passed (2433) and `make test` passed whole.
      `make check-change` fails only on the closeout citation of
      `openspec/specs/compute-delivery/architecture.md` (9.9).
      End-to-end: `e2e_deal`, `e2e_deal_buyer_cli` and `e2e_vm_payment_deal` exercise VM
      delivery on the path once deployed, confirmed. They also read `tenant_credentials`
      from settle-status, which section 5 alone no longer stores; section 6's live read
      restores them in the same round, so the round's pipeline, not this commit's, is
      their evidence. Owed by validation: none.
      Fresh-context check: no layering, import-placement or packaging defect. Fixed from
      it: a progress row's unknown phase now reaches the path as unreadable; history
      and planned-behaviour wording in three docstrings and a comment; the specs' and
      `kit/site`'s stale citations; tests moved to their level (the stage-only test to
      unit, the result-reading tests into the module's own unit file), the
      fixture-testing commit test deleted, a vacuous assertion dropped, the delivery
      test module's docstring corrected; tests added for an `available` outcome
      deferred in both settle paths, the release policy adopting the path's end, and the
      hold's placement key; and the dead `[provisioning].poll_interval` it reported is
      live again in the hook's loop. Declined: replacing `lifecycle.end.physical` and
      `fake_site`'s module patch with new seams, as the existing harnesses do the same
      and the change is not about test seams.
      Handoff: the library calls only `begin_fulfillment`, and provisioning accepts a
      fulfillment only for a scheduled reservation, so VM's `VmSiteFulfillment`
      schedules first; section 7's bare-metal adapter needs the same, or the schedule
      step belongs in the library's `SiteFulfillment` contract. The Alkahest commitment
      validator is VM's (`VmDealLifecycle.alkahest_commitment_valid`); if bare metal's
      is the same check, hoist it into `kit/alkahest` as section 2's handoff says. A
      settle response's `tenant_credentials` is empty until section 6.
- [x] 5.6 Publish `arkhai-compute-delivery` with the first storefront that depends on
      it: a filter and a manifest row in `.github/workflows/publish-pypi.yml` (after
      `compute-provisioning-contracts`, which it depends on) and a row in
      `docs/development/RELEASING.md` naming its internal dependencies, or
      `scripts/tests/test_publish_matrix.py` fails once a published storefront
      declares it. A new PyPI project needs the owner's trusted-publisher setup and
      its GitHub environment, which no session can make: ask the owner before the
      section is committed. Added by section 3's implementation, which built the
      distribution.
      Done, on the owner's answer A (2026-11-06): the filter row and the manifest row
      after `compute-provisioning-contracts` in `publish-pypi.yml`, the row in
      `RELEASING.md` (and `arkhai-compute-delivery` in `arkhai-vms-storefront`'s row),
      and the entry in `manifests/published-distributions.json`. The owner creates the
      PyPI trusted publisher for `arkhai-compute-delivery` (environment
      `pypi-arkhai-compute-delivery`) and the matching GitHub environment before the
      next release; until then only that package's publish job fails. Release tooling
      passes (2433).

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
