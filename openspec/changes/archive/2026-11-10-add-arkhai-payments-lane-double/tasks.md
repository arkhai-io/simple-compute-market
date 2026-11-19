# Tasks — in-lane mediation double and controls for both doubles

Replanned against the reviewed design (design reviews 15 and 26 and their triage). The
earlier draft predated the design's reverification and no task of it was checked; it
is replaced whole. Amended against design review 62 and its triage, after section 6
returned to design: task 4.9 adds the filing's Agreement-binding check (62 F1);
section 6 is replanned as six controls scenarios (D14–D19, D21); section 9, the
release wheelhouse (D20), is new; and closeout, formerly section 9, is section 10, so
a completed task's note naming 9.x means 10.x. Decisions are `design.md`'s D1–D21;
requirements are the deltas under `specs/`. New paths below are planned deliverables. The tools under `tools/`
are outside the package architecture check (`docs/development/ARCHITECTURE.toml`,
`skip`); the kit and domain edits of sections 3 and 7 are inside it.

Every section runs `scripts/change-workflow run pre-commit add-arkhai-payments-lane-double`
before its commit. A package whose code changes bumps its version once in this change,
moves the exact pins on it, and relocks (`make lock`), as
`docs/development/BUILD_AND_PACKAGING.md` states.

Closeout compressed the completed notes below to final behaviour, evidence, deferrals
and destinations; the implementation choices worth keeping moved to `design.md`,
"Settled during implementation". Every section's `scripts/change-workflow run
pre-commit` passed before its commit, except that until section 6 created its files
the citations check failed only on the paths later sections create, cited since
planning.

## 1. The control contract, its client, the transport-fault middleware and the lane CA

Delivers `tools/lane-double-controls`, the package both doubles and the e2e harness
import (D4), its clock models (D2), and the lane CA moved into it with a
`mediation-double` leaf (D7). Requirement: "Lane double controls are typed
deterministic steps".

- [x] 1.1 Create `tools/lane-double-controls` (import `lane_double_controls`):
      `pyproject.toml`, `uv.lock`, `Makefile` (`test`, `reinit`, `typecheck`, `check-tls`),
      `README.md`, `src/lane_double_controls/`, `tests/unit/`, `tests/integration/`, built
      into the wheelhouse by `make dist` like every internal distribution. Add root
      `make test-lane-double-controls`, put it in `make test`, and add it to
      `.github/workflows/tests.yml`'s matrix (`scripts/tests/test_tests_workflow.py`
      holds the matrix to `make test`). (D4, "Where the contract lives")
      Done. Root `dist-lane-double-controls` is in `dist` and `dist-ci`; `make test`
      runs reinit, `check-tls`, `mypy --strict`, then the suite. `requires-python
      >=3.12,<3.14` (the mediation kit's floor). A new project's first lock is a
      header-only seed that `make lock PROJECTS=…` rewrites, since
      `scripts/uv_project.py lock` refuses a project with no `uv.lock`.
- [x] 1.2 Models in `src/lane_double_controls/models.py`: a rule (`rule_id`, required
      `match`, and one of refusal `{status, code}`, `drop_response_after_commit`,
      `unavailable`, or, for mediation, filing-answer override or ruling
      `{basis, delivery_end, effects, close}` with optional `pause_before_effects`);
      operator decide and close; clock advance and reset; funding; signer rotation; the
      rule listing with matched and waiting counts; the case listing; the status
      (perceived now, installed contract hashes); and the one error body
      `{"code", "message"}`. An *unavailable* rule requires `match: {}` (26 F2). Ruling
      and effect shapes validate against the vendored mediation contract through
      `market_arkhai_mediation.contract`. (D2, D3, D4's table and "Control semantics")
      Done; the shapes are `design.md`, D4, "Control shapes". `ControlError(status,
      code, message)` is the one error on both sides; `Rule.check_supported(double)`
      refuses another double's properties and actions.
- [x] 1.3 Route declarations and a typed sync client (`routes.py`, `client.py`) over
      httpx, authenticated by the control bearer token and trusting a configured CA
      bundle, raising one typed error carrying the control code. Routes live under
      `/test/` on each double's API port. (D4, "Scope and access")
      Done. The client sets `trust_env=False`, keeps httpx's own error for a
      transport failure, and raises `unexpected_response` for an error body that is
      not a control error. `authorize(header, token)` is the doubles' token check.
- [x] 1.4 The transport-fault ASGI middleware (`middleware.py`): it applies only to the
      contract's API routes, never to `/test/` routes; *unavailable* starts and then
      abandons every API response; *drop after commit* lets the matching request
      complete in the application, then starts and abandons its response. A matched
      request is counted in the rule listing. (D4, "Transport faults live in the
      doubles", "How a response is abandoned", "Control routes are never faulted")
      Done. `/health` is exempt too (D4, "Control shapes"); the classifier, not the
      middleware, matches and counts (design, "Settled during implementation").
- [x] 1.5 Move the lane CA generator and certificates from
      `tools/payments-lane-double/tls/` to `tools/lane-double-controls/tls/`, issuing a
      second leaf for `mediation-double` (SANs `mediation-double`, `localhost`,
      `127.0.0.1`), deterministic as before, private keys still generated at image
      build and never committed. Repoint every reader of the old path:
      `tools/payments-lane-double/Dockerfile` and its tests, `compose.vms-lane.yml`,
      `compose.bare-metal-local.yml`, `compose.apicredits-lane.yml`,
      `compose.payments-double.yml`'s healthcheck path as the image places it,
      `e2e-tests/Makefile`, `helm/Makefile`'s `PAYMENTS_LANE_CA_FILE`, and the tests
      holding mounts to sources (`scripts/tests/test_lane_compose.py`,
      `scripts/tests/test_committed_stack_values.py`). `check-tls` regenerates both
      leaves and requires them unchanged. (D7)
      Done: `lane-ca.pem`, `payments-double.pem`, `mediation-double.pem`, keys
      ignored; the CA is renamed `lane doubles CA (public development value)`, so its
      bytes changed and every reader takes them from the files. The payments image
      keeps its in-image paths, so its chart and healthcheck needed no edit. Readers
      repointed beyond the list: two e2e unit tests, the release-topology test, the
      payments double's lane test and dockerignore, `.gitignore`,
      `dev-env/identities/README.md`, the `make helm-topology-secrets` bullet of
      `DEPLOYMENT_AND_CONFIG.md`, `helm/scripts/topology-secrets.sh`, `helm/Makefile`,
      `helm/bare-metal-release-values.yaml`, `tools/README.md` and the payments
      README. The certificates were written with the Write tool from the
      generator's output after a denied `make -C … tls`; `check-tls` confirms them
      byte for byte.
- [x] 1.6 Verification.
      Unit (`tools/lane-double-controls/tests/unit`): every refusal of D4's "Control
      semantics" table at the model level — a rule without `match`, an *unavailable*
      rule with a non-empty `match`, a malformed ruling or effect, an empty effect list
      accepted; the TLS generator reproduces the committed CA and both leaves.
      Library integration (`tests/integration`): a minimal ASGI app behind the
      middleware, driven through httpx — *unavailable* yields `httpx.RemoteProtocolError`
      on an API route while a `/test/` route answers; *drop after commit* runs the
      handler once and the caller sees a transport error; the typed client raises its
      typed error on each refusal code.
      Repository: `make check-packaging`.
      End-to-end: none yet; the lanes use the package from section 5.
      Owed by validation: `tests.yml`, job `test · test-lane-double-controls` — the
      package's `make test` passes, `check-tls` included; and job
      `test · test-payments-lane-double` — the payments double's suite passes against
      the moved certificates.
      Evidence: `make -C tools/lane-double-controls test` — `check-tls`, `mypy
      --strict`, 112 passed (unit; library integration under loopback uvicorn and the
      typed client against a `MockTransport` stand-in holding each method to its
      route). Payments double 43 passed; `make test-e2e-unit` 786 passed, 1 skipped;
      `make -C helm test-render` passed; `make check-packaging` passed in pre-commit.
      Destinations: `tools/README.md`'s "Lane collaborators" now defines the
      controls package as the one shared library (10.9, D4).

## 2. The payments double's controls, perceived clock and claimed surface

Delivers the payments double's control routes, perceived clock and status, the
middleware mounted, and its suite claiming the rate and hold surface (D2, D3, D4, D10).
Requirements: "The in-lane payments double mirrors the service and proves its engine's
surface", "Each lane double reads a perceived clock the scenario advances", "Lane double
controls are typed deterministic steps".

- [x] 2.1 `tools/payments-lane-double`: declare `lane-double-controls`; a perceived clock
      (wall time plus a forward-only offset, reset to zero) injected into
      `PaymentsAuthority` in place of `wall_clock` (`src/payments_lane_double/app.py`);
      mount the middleware on the API routes. (D2, D4)
      Done. `create_app(directory, clock=…)` still takes the wall clock, which the
      perceived clock wraps; admission reads the perceived clock. Version 0.2.0,
      `requires-python >=3.12`, relocked.
- [x] 2.2 Control routes under `/test/`, authenticated by a fixture control token added
      to `fixtures/accounts.toml` and labelled a public development value: rules
      (install, list, delete) for refusals with a published `ApiError` status and code,
      drop after commit and *unavailable*; clock advance and reset; fund an account
      (`PaymentsAuthority.fund`, `404 account_not_found` for an account outside the
      directory); rotate the receipt signer to a second committed fixture seed; status
      reporting the perceived now and the installed contract hashes from
      `market_arkhai_payments.contracts`. Refusals follow D4's table. (D2, D3, D4)
      Done. The fixture gains `control_token` and `rotation_seed`, each refused when
      it collides with an account token or the receipt seed. Handlers register from
      `routes_for("payments")`. A refusal's code must be a published `ApiErrorCode`.
      An approval's `transaction` is its mandate's future id, so a rule can scope one
      deal from its first call. After rotation a snapshot embeds the earlier receipt
      under its original signature. No scenario resets rotation; a lane that rotates
      keeps the second key for its run.
- [x] 2.3 Suite coverage of the rate and hold surface through the payments kit's
      `PaymentsClient` over an ASGI transport, with clock advances: rate parts and
      payee-only `start`; `stop` with notice and the earliest pending stop taking effect
      when the perceived clock reaches it; per-part `end`; funding exhaustion at
      funded-through; `afterStop` holds releasing after the clock passes them; partial
      `reverse` before and after a stop; `extend` and `lift` with `hold_not_extendable`,
      `extension_not_found` and `extension_closed`. (D10)
      Done in `tests/integration/test_double.py`, "the rate and hold surface", each
      case moving time through the clock control and reading state through the kit's
      client.
- [x] 2.4 Update `tools/payments-lane-double/README.md`'s claim from the once-only
      surface to the rate and hold surface, and describe the controls and clock. (D10;
      the README is the double's own documentation, maintained with its code)
      Done: "What it is", "Controls", "What it claims", fixtures, `make test`.
- [x] 2.5 Verification.
      Unit (`tests/unit`): the clock moves only forward, reset returns to wall time;
      control authentication refuses a missing or wrong token.
      Library integration (`tests/integration/test_double.py`, `test_controls.py`):
      2.3's surface; a refusal rule answered to the kit client with its status and code
      and counted in the listing; funding visible through `get_balance`; a drop after
      commit on an approval retried under the same key returns the original receipt with
      no second debit; *unavailable* refuses API routes while `/test/status` answers;
      signer rotation signs later snapshots with the second key; status hashes equal
      the kit's installed contract hashes; a drop-after-commit and an *unavailable*
      match each counted in the rule listing, the classifier counting it (section 1's
      middleware leaves matching and counting to the double); `/health` answering
      under *unavailable*.
      Correction: the `/health` case is proven in the controls package's middleware
      test, where the exemption lives; control-token admission is proven through the
      app in `test_controls.py`. The `tests/integration` suites run the app in process
      through typed clients, which is application integration.
      End-to-end: none in this section; section 5's lanes run this double.
      Owed by validation: `tests.yml`, job `test · test-payments-lane-double` — the
      double's `make test` passes with the new suites.
      Evidence: `make -C tools/payments-lane-double test` — 90 passed: unit
      (`test_clock.py`, `test_rules.py`, `test_fixtures.py`), application integration
      (`test_double.py`, `test_controls.py`), and `test_faults.py` under loopback
      uvicorn (a dropped approval counted, retried a minute later returning the
      receipt approved at T0 with no second debit; *unavailable* abandoning reads and
      approvals while `/test/status` answers). `make build-payments-lane-double`
      built the image.
      Destinations: the `test-compatibility` companion's "The in-lane payments
      double" and `ROADMAP.md` (10.9 D10, 10.5).

## 3. Mediation trust through configuration

Delivers `[[DisputeCredential]].ca_bundle_path` and the mediation client's CA argument,
passed by all four lifecycle compositions (D8). Requirement: settlement-configuration
"Dispute credentials are bound by identity and no template ships an authority".

- [x] 3.1 `kit/deal-lifecycle`: `DisputeCredential` (`configuration.py`) gains an
      optional `ca_bundle_path`, refused when empty, as the payments section refuses an
      empty one; it appears in no option, Agreement or status. (D8)
      Done; a blank path is refused too. Version 0.3.0.
- [x] 3.2 `kit/arkhai-mediation`: `MediationClient` (`client.py`) takes an optional CA
      bundle and uses it as its verification context
      (`ssl.create_default_context(cafile=…)`); absent means default trust; no process
      state changes. Update `kit/arkhai-mediation/README.md`'s client section. (D8)
      Done: keyword `ca_bundle=`; the context is built at construction, so a missing
      or malformed bundle raises `OSError` there and an empty one `ValueError`. README
      "Composition" updated. Version 0.3.0.
- [x] 3.3 Pass the credential's `ca_bundle_path` in every construction:
      `domains/vms/storefront/src/market_storefront/deal_lifecycle.py`,
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`,
      `domains/vms/buyer/src/arkhai_vms_buyer/lifecycle.py`,
      `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/lifecycle.py`. The
      storefronts' generated values schemas keep refusing `[[DisputeCredential]]` whole
      in public chart configuration; regenerate them if the model change alters them.
      (D8)
      Done; the values schemas did not change. An unusable credential's handling, and
      the warning both storefronts log for it (pre-closeout fix, 77 F3), are in
      `design.md`, "Settled during implementation". Versions: both storefronts
      0.28.0, VM buyer 0.11.0, bare-metal buyer 0.8.0, each on the two kits' 0.3.0;
      relocked.
- [x] 3.4 Verification.
      Unit: `kit/deal-lifecycle` configuration tests — the field parses, an empty value
      is refused, the resolved credential carries it.
      Library integration: `kit/arkhai-mediation/tests` — a client given a CA bundle
      verifies a TLS server whose certificate that bundle issues and refuses one it does
      not, as `kit/arkhai-payments`' TLS cases do; without one, default trust.
      Application integration: each storefront's and buyer's lifecycle composition
      tests show the credential's bundle reaching the client.
      End-to-end: section 5's lanes are the first deployed use.
      Owed by validation: `tests.yml`, jobs `test · test-kits` and `test · test-domains`
      — both pass.
      Evidence: `make -C kit/deal-lifecycle test` 81 passed; `make -C
      kit/arkhai-mediation test` 83 passed (`test_client_ca_bundle.py`;
      `test_client_tls.py` against a loopback TLS listener: the issuing CA's bundle
      reads, another's or none fails with no request received).
      Correction to the application integration line: each composition shows the
      bundle reaching the client by construction failing on a missing bundle — each
      storefront's `test_lifecycle_mediation_trust.py` (`repair required`, nothing
      sent, the warning logged; none logged without a bundle) and each buyer's
      `test_lifecycle_adoption.py` at unit level (a buyer is a CLI with no app).
      Suites: VM storefront 551 integration, bare-metal storefront 598, VM buyer 216,
      bare-metal buyer 33. One pre-commit run failed `domains/apicredits`'
      `test_distribution_install.py` once; it did not reproduce and its cause was not
      found.

## 4. The mediation double

Delivers `tools/mediation-lane-double`: the dispute authority's API mechanics,
programmed decisions, effect application, perceived clock and controls (D1, D2, D3,
D4, D7). Requirements: "Lanes run a mediation double that answers from programmed
rules", "Lane double controls are typed deterministic steps", "Each lane double reads a
perceived clock the scenario advances".

- [x] 4.1 Create `tools/mediation-lane-double` (import `mediation_lane_double`):
      `pyproject.toml` declaring the mediation and payments kits and
      `lane-double-controls`, `uv.lock`, `Makefile`, `Dockerfile` building image
      `arkhai:mediation-lane-double` from the wheelhouse and the committed lock with its
      leaf key generated from `tools/lane-double-controls/tls/`, `README.md`,
      `src/mediation_lane_double/` with a framework-free service and thin FastAPI
      routes, as the payments double is built. Root `make test-mediation-lane-double`
      in `make test` and `tests.yml`'s matrix; root `make build-mediation-lane-double`;
      add the image to `scripts/change_namespace.py`'s image list. (D7)
      Done in the payments double's layout (`service.py` framework-free, service calls
      in Starlette's thread pool). `PerceivedClock` moved into
      `lane_double_controls.clock`. Correction (41 O1): both doubles' image targets
      live in `tools/Makefile`, built by the root's `make build-tools`, which
      `build-dev` and the `build-e2e-*` targets run.
- [x] 4.2 Fixtures in `fixtures/`, every value labelled a public development value,
      never for a public network: the authority identity (origin
      `https://mediation-double:8443`, account `00000000-0000-4000-8000-0000000000d1`, a
      record key from a committed seed), bearer tokens mapping the buyer and seller
      payment accounts, the authority's payments token, and the control token. (D5, D7)
      Done: `fixtures/authority.toml`, whose loader refuses a record key its seed does
      not yield; it also holds the `params` and `advertisement` the lane registry
      profile renders.
- [x] 4.3 API mechanics against the vendored contract: `POST /cases`, `POST /append`,
      `GET /cases/{ref}`, `GET /record`, `GET /respondent`; bearer authentication;
      schema validation; idempotency and `idempotency_conflict`; either party appending
      evidence, only `mandate.to` concurring; the closed-case refusal; the signed
      per-agreement record with sequences and cursors, an empty signed page for a known
      agreement with no cases, the contract's refusal for an unknown agreement or
      reader. (D1, "Real mechanics")
      Done; answers in `design.md`, D4, "Mediation shapes". Parties come from the
      transaction's signed receipt. Correction (4.9): the filing also refuses
      `agreement_hash_mismatch`.
- [x] 4.4 Filing protection through the payments kit's client as the authority's
      account: `extend` per part; only `hold_not_extendable` reports `not_held`, its
      reason classified from the part's signed snapshot amounts — `paid_out`, else
      `reversed`, else `nothing_held`; every other refusal and every transport failure
      answers `error` with `protection_incomplete`, completed by a same-key retry; a case
      whose every part is `not_held` is dismissed with `nothing_held`. (D1, "Extension
      results", "A not-held part's reason")
      Done; extend request ids are `<case_ref>:<part>` and an incomplete filing keeps
      its case reference under its key, so a retry re-sends the same extends.
- [x] 4.5 Programmed decisions: rules matching `operation`, `filer`, `kind`, `cause` and
      `transaction`; filing-answer overrides; a ruling recorded in the signed record,
      its effects applied as payment events with stable effect keys and the case
      reference, then only that case's extensions lifted; `pause_before_effects` and
      resume; an incompletely applied ruling resumed without a duplicate effect; operator
      decide and close on an open case; no ruling without a rule; no signature, digest or
      guard verification. (D1, "Programmed")
      Done; shapes in `design.md`, D4, "Mediation shapes", and the two layers' rule
      choice in "Settled during implementation". Only `reverse` effects are applied;
      `stop`, `penalty` and `award` are refused at install (40 F2). Closing an
      applying case is refused, `409 case_applying` (40 F1).
- [x] 4.6 Controls and clock: the shared middleware on the API routes; `/test/` routes
      for rules, decide, close, the case listing by transaction, the rule listing, clock
      advance and reset, and status reporting the perceived now and the installed
      mediation contract hashes; refusals per D4's table. Record times come from the
      perceived clock. (D2, D3, D4)
      Done. `payments_unavailable` and `case_applying` joined `ControlCode`.
- [x] 4.7 `README.md`: what the double serves, its deviation from its producer (a case
      the authority would rule mechanically is ruled only by a rule), what its results
      establish and what they do not. (D1; the double's own documentation)
      Done.
- [x] 4.8 Verification.
      Unit (`tests/unit`): the not-held classification's five cases — released only,
      reversed only, released and reversed, refunded only, nothing moved; rule matching;
      control refusals per D4's table.
      Library integration (`tests/integration`), the kit's real `MediationClient` over
      an ASGI transport, with the payments kit's `FakePaymentsClient` over the shared
      `PaymentsAuthority` engine as the payments peer and one injected clock for both:
      no-rule filing held per part; a refusal other than nothing held answered
      `protection_incomplete` and completed on retry; dismissal when nothing is held; a
      programmed ruling's effects and lift; a payments failure between effects resumed
      without duplicates; appends, concurrence and the closed-case refusal; record
      cursors and the empty page; the respondent listing answered by an append; a lost
      filing response adopted under the same key; *unavailable* with control routes
      answering, and its match and the lost filing's counted in the rule listing; a
      clock advance past a once hold yielding `not_held` with `paid_out`.
      End-to-end: none in this section; the HTTP hop to the payments double is first
      exercised in section 5.
      Owed by validation: `tests.yml`, job `test · test-mediation-lane-double` — the
      double's `make test` passes.
      Correction: the case refusals of D4's table are proven through the typed client
      in `test_controls.py`, not at unit level, since each needs a filed case; the
      `tests/integration` suites run the app in process, which is application
      integration.
      Evidence: after round 1's triage (reviews 40 and 41: 40 F1 `case_applying`,
      40 F2 the refused effect kinds, 40 F3 the classifier on a worker thread, 41 O1
      `tools/Makefile`), `make test-mediation-lane-double` 70 passed — unit
      (`test_protection.py`, `test_rules.py`, `test_fixtures.py`), application
      integration (`test_mechanics.py`, `test_rulings.py`, `test_controls.py`, payments
      failures injected through `create_app`'s payments argument) and `test_faults.py`
      under loopback uvicorn; `make test-lane-double-controls` 120 (among them
      `/test/status` and `/health` answering while a classification is held);
      `make test-payments-lane-double` 85; `make test-release-tooling` 2686.

- [x] 4.9 The filing's Agreement-binding admission check (D1 "Real mechanics", D4
      "Mediation shapes"; 62 F1): in `tools/mediation-lane-double/src/mediation_lane_double/service.py`'s
      `file`, after the `filer_not_party` check and before the Agreement's readers are
      recorded, a case reference is reserved or any part is extended, refuse a filing
      whose Agreement's JCS SHA-256 (`canonical_json`, as the double already hashes it)
      differs from the `deal` of the transaction's signed payment receipt, answering
      the contract's `rejected` filing with reason `agreement_hash_mismatch`,
      remembered under its key as `filer_not_party` is. The receipt is the one
      `_parties_of` already reads; its cached parties gain the `deal`. Correct
      `tools/mediation-lane-double/README.md`, "Deviation from its producer", which
      lists "Agreement digest" among what the double does not verify: it verifies the
      Agreement's binding to its payment, and no concurrence signature or mechanical
      guard. Requirement: "Lanes run a mediation double that answers from programmed
      rules", scenario "A filing's Agreement is not the payment's".
      Done; the check runs before the readers, the rule book, the reservation and any
      extend. The README and `service.py`'s docstring follow.
- [x] 4.10 Verification of 4.9.
      Library integration (`tools/mediation-lane-double/tests/integration/test_mechanics.py`,
      through the mediation kit's real client over HTTP against the payments double's
      engine): a filing whose Agreement differs from the receipt's `deal` by one field
      is answered `rejected`, `agreement_hash_mismatch`; payments records no `extend`;
      the case listing for the transaction is empty; a reader of that Agreement's
      record is refused as unknown; a retry under the same key returns the same
      refusal; an honest filing for the same transaction is then accepted. Run
      `make test-mediation-lane-double`.
      End-to-end: every lane filing is honest, so the check passes in
      `e2e_vm_payment_deal`, `e2e_bare_metal_payment_deal` and section 6's scenarios,
      none of which a refusal would leave passing.
      Owed by validation: `tests.yml`, job `test · test-mediation-lane-double` — the
      double's suite passes with the new case.
      Correction: the case is application integration, and its payments peer is the
      kit's `FakePaymentsClient` over the shared engine in process, not the payments
      double over HTTP; no suite here crosses HTTP to it, the lanes being the first.
      Evidence: `make test-mediation-lane-double` 73 passed, among them
      `test_a_filing_whose_agreement_is_not_the_payments_is_rejected_before_any_effect`
      (no extend, no case listed, the record refused, the same refusal on retry, then
      an honest filing accepted as the process's first case reference).

## 5. Lane wiring and the existing payment scenarios

Delivers the mediation double in all three lanes, the registries recommending it, the
runner's lane-owned `MEDIATION` target, the buyer's credential, and the VM case stages
and bare-metal filing running against it (D3, D5, D6, D7, D9). Requirements: "Lanes run
a mediation double that answers from programmed rules", "A lane-owned mediation target
fails rather than skips", "The in-lane payments double mirrors the service and proves its
engine's surface", "A compute buyer purchase settled through Arkhai payments runs in
each compute lane against the lane doubles".

- [x] 5.1 `compose.payments-double.yml` adds service `mediation-double`
      (`arkhai:mediation-lane-double`, no host port, healthcheck trusting the lane CA
      alone); the root `Makefile`'s lane build targets build its image. (D9)
      Done. It starts once `payments-double` is healthy, and Bob's storefront waits
      for it. The lane CA's mount target is `/run/lane-doubles/lane-ca.pem` in every
      overlay, storefront configuration, runner mount and test naming it.
- [x] 5.2 The payments double's `fixtures/accounts.toml` gives `…00d1` a token, which the
      mediation double's fixture restates; retire the payments double's
      `fixtures/dispute-authority.toml` and its tests;
      `dev-env/registry/config-payments-lane.env` recommends the mediation double's
      identity. Update `core/registry/tests/unit/test_config_profiles.py` and the stack
      value tests that held the `.invalid` identity. (D5, D7, D9)
      Done, with the retired fixture's Dockerfile copy, conftest helper and unused
      deal-lifecycle dev dependency. `helm/local-values.yaml`'s registry recommends the
      mediation double (8.2's half), held by `helm/tests/test_release_topology.py` to
      the fixture; `scripts/tests/test_committed_stack_values.py` holds the payments
      token's restatement, so neither double's suite reads the other's project.
- [x] 5.3 `dev-env/identities/bob.storefront.secrets.toml`'s `[[DisputeCredential]]`
      carries the mediation double's seller token and `ca_bundle_path`, and the lane
      overlays mount the CA where that path names. (D8, D9)
      Done.
- [x] 5.4 Runner: `e2e-tests/config/config-payments-lane.yml` gains `mediation` —
      `service_url`, `lane_owned: true`, `ca_bundle_path`, `buyer_api_key`,
      `api_key_env`, `control_token`; `e2e-tests/tests/e2e/roles/helpers/mediation.py`
      fails setup by name on an unready lane-owned target and keeps the blocked skip for
      an external one; the buyer configuration writer emits the buyer's
      `[[DisputeCredential]]` with `api_key_env` and `ca_bundle_path`, and the harness
      hands the buyer's mediation token to each `market` process under that variable,
      writing it into no runner environment. Declare `lane-double-controls` in
      `e2e-tests/pyproject.toml` and relock. Tests hold every restated value to its
      fixture. (D9)
      Done, adding `mediation.account`, `mediation.record_key` and
      `payments.control_token`. Both purchase drivers write the credential only when
      the run names a target. `e2e-tests` also declares the deal-lifecycle kits it
      imports. Deferred, left as it is: `test_mediation_helper.py`, like
      `test_payments_helper.py`, replaces the helper module's `settings`, which
      `TESTING.md`'s mocking convention discourages; a settings seam for both helpers
      is a refactor of its own.
- [x] 5.5 Lane-double evidence: a payment scenario records the label *lane doubles* and
      both doubles' installed contract hashes, read from their status through the typed
      client. (D3)
      Done: the module fixture `lane_doubles_evidence`
      (`e2e-tests/tests/e2e/roles/helpers/lane_doubles.py`) logs the label and both
      hash maps when both targets are lane-owned (no lane run writes a JUnit report);
      the four payment scenarios use it.
- [x] 5.6 Scenarios: `e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_payment_deal.py`'s
      operator-end case and refund stages run against the mediation double — the
      seller's filing accepted and held per part with no rule, the refund reversing the
      held money; the bare-metal buyer's teardown filing
      (`e2e-tests/tests/e2e/roles/helpers/buyer_purchase_stages.py`) asserts a case
      filed and held per part, not a ruling. (D6)
      Done: the operator-end stage asserts each part `held`, no `ruled` event, and one
      open extension per part bound to the case; `Purchase10` asserts the teardown's
      case accepted with every part held where the run names a mediation target.
- [x] 5.7 Verification.
      Unit: `e2e-tests/tests/unit/test_mediation_helper.py` (lane-owned failure,
      external blocked skip, missing settings), the buyer configuration writer's
      credential, the value-to-fixture tests, `scripts/tests/test_lane_compose.py` for
      the overlay's new service.
      Application integration: `domains/vms/storefront/tests/integration/test_servicing_unreachable_authority.py`
      keeps its own unreachable-authority fixture and still passes.
      End-to-end: `e2e_vm_payment_deal` and `e2e_vm_payment_purchase` in
      `make -C e2e-tests test-e2e-vm`, `e2e_bare_metal_payment_deal` in
      `test-e2e-bare-metal`, `e2e_credits_payment_deal` in `test-e2e-apicredits`; none
      skips for want of a mediation target.
      Owed by validation: `tests.yml`, job `test · test-e2e-unit` — the harness unit
      suite passes.
      Evidence: `make test-e2e-unit` 802 passed, 1 skipped; `make
      test-release-tooling` 2690 (`test_lane_compose.py`,
      `test_committed_stack_values.py`, `test_change_build_and_helm_targets.py`,
      `test_bare_metal_compose.py`); payments double 84, mediation double 72
      (`test_lane_profile.py`); `make -C helm test-render` passed; `make -C
      core/registry test-unit` 139; the VM storefront's
      `test_servicing_unreachable_authority.py` in pre-commit's every-suite hook. The
      end-to-end markers are validation's: validation 83 passed them (10.8).
      Destinations: `e2e-tests/README.md` and `TESTING.md`, rewritten from the
      `.invalid` authority (10.9 D6, D9).

## 6. The VM controls scenarios

Replanned against the reviewed design (design review 62): the single module of six
ordered journeys this section first planned, of which nothing was implemented, is
replaced by six scenarios, each a module of its own on its own once-only deal. The
design-input notes the section carried when it returned to design are now D14–D21.

Delivers the lane-double rule and clock fixtures, the buyer's filing through the
mediation kit's dispute adapter, the shared stages of the six scenarios, and the six
modules (D2, D4, D6, D14–D19, D21). Requirements: "Controls scenarios prove the lane's
dispute wiring in the VM lane", "Each lane double reads a perceived clock the scenario
advances" (scenarios "A once part's hold is passed", "A module that advanced the
clocks ends"), "Lane double controls are typed deterministic steps".

Every stage advances one side effect and acts through the services' typed clients
(the storefront admin client, `LifecycleClient`, the payments kit's `PaymentsClient`),
the doubles' `ControlClient`, or the mediation kit's `MediationAdapter`, never a raw
HTTP call (D14). No stage steps the storefront's servicing while a ruling waits at its
gate (D15). Each module holds the loops it depends on through the fixtures
`test_vm_payment_deal.py` uses and records lane-double evidence (`lane_doubles_evidence`).

- [x] 6.1 Fixtures in `e2e-tests/tests/e2e/roles/helpers/lane_doubles.py`, re-exported
      by `tests/e2e/roles/conftest.py` as `lane_doubles_evidence` is (D2, D4, "Scope and
      access"):
      - `lane_double_rules`, module-scoped: installs a rule on either double through
        `ControlClient.install_rule` and remembers it; its finaliser, whatever the
        module's outcome, deletes every rule it installed on both doubles and then
        asserts from `rules()` that none of them still had a case waiting at its gate,
        naming any that did.
      - `lane_double_clock`, module-scoped: `advance(seconds)` advances both doubles
        together through `advance_clock` and returns both perceived nows; its
        finaliser, whatever the module's outcome, resets both through `reset_clock`
        and fails naming a double that does not then report a zero offset.
      Done as `LaneDoubleRules` and `LaneDoubleClock`, their cleanup in the context
      managers `rules_removed_after` and `clocks_reset_after`; cleanup attempts every
      read and deletion before failing, and a `rule_not_found` on delete is success.
      Both fixtures report a blocked skip unless both targets are lane-owned.
- [x] 6.2 The buyer's filing, in `e2e-tests/tests/e2e/roles/helpers/mediation.py` (D14):
      a helper filing a delivery-end claim (`{kind: delivery_end, ended_at,
      delivered: true, cause: payer}`) as the buyer on a deal it names by negotiation
      id, transaction and accepted Agreement. It builds a `MediationClient` for the
      Agreement's dispute authority with a `MediationCredential` bound to the target's
      identity and its `buyer_api_key`, and the target's `ca_bundle_path`; a
      `MediationAdapter` over the Agreement's dispute binding; and submits a `dispute`
      command with the adapter's `build_request`, under `OperationKeys` whose store is
      the buyer kit's `FileEvidenceStore` over a directory of the module's own, as the
      buyer's lifecycle supplies one. It returns the adapter's lifecycle outcome, whose
      filing answer carries the case reference and each part's hold. Declare
      `arkhai-kit-arkhai-mediation` in `e2e-tests/pyproject.toml` (the harness now
      imports it directly) and relock (`make lock PROJECTS=e2e-tests`).
      Done as `file_as_buyer`, through the deal-lifecycle kit's `submit_dispute`
      (`design.md`, "Settled during implementation"). `e2e-tests` declares
      `arkhai-kit-arkhai-mediation>=0.3.0`.
- [x] 6.3 Shared stages (D17, D21):
      - `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`: one executor host,
        pool and resource id for each of the six scenarios, as every VM scenario has
        its own.
      - The hosted once-only commit — listing in `arkhai.payments.v1`, negotiation,
        approval, commit, delivery to `active` and the snapshot's held part — moves
        out of `test_vm_payment_deal.py`'s first stage into
        `e2e-tests/tests/e2e/roles/scenarios/vms/payment_deal.py`, parameterized by
        the scenario's host, pool and resource, so its body is defined once
        (`docs/development/TESTING.md`, "Every stage the compute domains run
        identically comes from one definition"); `test_vm_payment_deal.py` calls it,
        its other stages unchanged. It records the negotiation id, transaction,
        accepted Agreement and fulfillment for later stages.
      - `e2e-tests/tests/e2e/roles/scenarios/vms/dispute/` (`__init__.py`,
        `stages.py`): a storefront servicing step (`advance_storefront(...,
        "settlement-servicing")`), the storefront's lifecycle read, the payments
        snapshot read, the case listing, and the ending of a deal still delivering
        when its scenario's own stages end: the lease-expiry stages `test_vm_payment_purchase.py`
        runs (`Stage10a_LeaseExpirySetup` through `Stage11b_TeardownCompletion`,
        `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`), followed by the
        case listing showing no case beyond the scenario's own (D17: a stage that
        files nothing). Should the storefront file a case for that end, the
        implementation stops and reports it, since the design settled none other.
      Done. `payment_deal.py` holds `commit_hosted_deal` and the shared reads;
      `dispute/stages.py` holds `DisputeState`, `servicing_step`, `cases`, the commit
      stage and `DisputeStageZ_NoFurtherCase`; `dispute/conftest.py` the modules'
      fixtures. A module still delivering at its end runs `Stage09c2_ArmTeardownGate`
      through `Stage11b_TeardownCompletion` and the readiness stages they require.
      `DisputeStageZ_NoFurtherCase`'s servicing step is in `design.md`, "Settled
      during implementation". `test_scenario_cleanup_order.py` now recurses into
      `dispute/`. Pre-closeout fix (77 F2): the module docstring states the
      invariant `DisputeStageZ_NoFurtherCase` checks instead of citing the design.
- [x] 6.4 `dispute/test_ruled_delivery_end.py` (D15): commit; install through
      `lane_double_rules` a mediation rule matching `{"operation": "file",
      "transaction": <the deal's>}` with a ruling (a `RulingBasis` for a payer-filed
      claim, `delivery_end: true`, one `reverse` on part 0 of a stated amount,
      `close: true`) and `pause_before_effects: true`; the buyer files (6.2) — the
      filing accepted with part 0 held and an extension reference, the case
      `applying`, the rule listing one waiting, nothing reversed in the snapshot;
      resume the rule — the snapshot reversing exactly the stated amount once, the
      case `closed`; a servicing step — the lifecycle read showing the ruled entry
      with its delivery end, the end recorded with cause `ruling` and delivery
      `tearing_down`; then the teardown to the capacity's release, as the VM payment
      scenario's `Stage12c_CapacityReleasedOnce` proves it. No servicing step runs
      between the filing and the resume.
      Done; basis `operator` (the contract's bases have no payer-filed one), the
      reverse a quarter of the part's gross. Fixed for validation 71's V1: stage
      `05b` runs a second servicing step to read the site's end report (`design.md`,
      "Settled during implementation"); `make test-e2e-unit` 833 passed, 1 skipped.
- [x] 6.5 `dispute/test_operator_discount.py` (D6, D17): commit; the buyer files
      with no rule — each part held; a servicing step — the storefront's answer on
      the record (an `appended` entry by the seller, a contest, since no surrender
      matches); decide through `ControlClient.decide` a partial `reverse` with no
      delivery end and `close: true` — the snapshot reversing that amount, the
      extension lifted, the case `closed`; a servicing step — delivery `active`, no
      end recorded; the deal's ending (6.3).
      Done; the answer is asserted as one `appended` entry by the seller's account,
      not as a contest specifically.
- [x] 6.6 `dispute/test_lost_filing_answer.py` (D18): commit; install a mediation rule
      `{"operation": "file", "transaction": <the deal's>}` with
      `drop_response_after_commit`; the operator end (`admin_interrupt_deal`) — the
      filing's outcome unknown, the end recorded, delivery `tearing_down`, the rule's
      match counted; delete the rule; the operator end repeated — or, where the
      storefront's servicing retries the filing itself, a servicing step — the adapter
      adopting the one case, the outcome accepted with its case reference; a servicing
      step — the lifecycle read and the case listing each showing exactly one case;
      the teardown to the capacity's release.
      Done with the servicing step as the adopting stage (`design.md`, "Settled
      during implementation").
- [x] 6.7 `dispute/test_mediation_unavailable.py` (D18): commit; the buyer files with
      no rule; a servicing step answering it; install mediation *unavailable* (`match:
      {}`); a servicing step — the lifecycle read's authority outcome not accepted, as
      the adapter reports an unreachable authority, delivery `active`; delete the rule;
      a servicing step — the authority read accepted again with the case; the deal's
      ending (6.3).
      Done; the unreachable authority reads as outcome `unknown`.
- [x] 6.8 `dispute/test_payments_hold_a_ruling.py` (D16): commit; the buyer files with
      no rule; a servicing step answering it; install a payments rule `{"route":
      "events", "account": <the authority's account>, "event": "reverse",
      "transaction": <the deal's>}` with `drop_response_after_commit`; decide two
      `reverse` effects on part 0 with `close: true` — the case `applying`, the
      snapshot reversing the first amount only; a servicing step — the lifecycle read
      showing the ruled entry with both effects unapplied and no closed entry; delete
      the rule; install payments *unavailable*; the decision repeated — the case still
      `applying`; a servicing step — delivery `active`, the case not closed; delete
      *unavailable*; the decision repeated — the case `closed`, the snapshot reversing
      both amounts, each exactly once (two `reverse` events, one per effect id); a
      servicing step — the case closed in the lifecycle read; the deal's ending (6.3).
      Done; amounts an eighth and a quarter of the part's gross, the two reverses read
      from the buyer's snapshot with distinct `effect_id`s.
- [x] 6.9 `dispute/test_hold_passed.py` (D18; "A once part's hold is passed"): commit;
      the deal's ending (6.3), before any clock moves; advance both doubles through
      `lane_double_clock` past the part's release instant read from its signed
      snapshot — the snapshot showing the part paid out; the buyer files — the answer
      reporting part 0 `not_held` with reason `paid_out`, and the case listing it
      `closed`, dismissed with nothing held. No storefront step follows the advance;
      the fixture resets both clocks when the module ends.
      Done in two advances, past the terms end and then past `releaseAt` (`design.md`,
      "Settled during implementation").
- [x] 6.10 Markers, one per module as every VM scenario has its own:
      `e2e_vm_dispute_ruled_end`, `e2e_vm_dispute_discount`,
      `e2e_vm_dispute_lost_filing`, `e2e_vm_dispute_mediation_unavailable`,
      `e2e_vm_dispute_payments_hold`, `e2e_vm_dispute_hold_passed`, registered with
      their descriptions in `e2e-tests/pyproject.toml` and added to
      `e2e-tests/Makefile`'s `E2E_MODULE`. No order among them is needed (D21).
      Done.
- [x] 6.11 Verification.
      Unit (`make test-e2e-unit`): `e2e-tests/tests/unit/test_lane_doubles_fixtures.py`
      — the rule fixture deletes every rule it installed on both doubles after a
      failing module and names one left waiting; the clock fixture advances both
      doubles together and resets both after a failing module, failing on a double
      that keeps an offset; each over `ControlClient` on a mock transport.
      `e2e-tests/tests/unit/test_mediation_helper.py` — the buyer's filing sends the
      contract's `Filing` with the delivery-end claim, the buyer's bearer token and
      the Agreement, under an idempotency key the adapter derives, and maps an
      accepted answer and a transport failure to the adapter's outcomes, over a mock
      transport. The stage-set and marker checks the harness unit suite already runs
      pass with the six modules.
      End-to-end: the six markers and `e2e_vm_payment_deal` (its commit now the shared
      stage) in `make -C e2e-tests test-e2e-vm`; after the hold-passed module, both
      doubles report a zero offset, and the lane's later modules pass.
      Owed by validation: `tests.yml`, job `test · test-e2e-unit` — the harness unit
      suite passes with the fixtures' and the buyer filing's cases.
      Evidence: `make test-e2e-unit` 833 passed, 1 skipped:
      `test_lane_doubles_fixtures.py` (seven cases), `test_mediation_helper.py` (the
      buyer's filing against `MediationContractFake`), and the source checks
      `test_scenario_holds.py`, `test_scenario_lane_holds.py`,
      `test_scenario_cleanup_order.py`. No stage-set check covers the dispute modules,
      which run only part of the canonical stage order. The six modules' first run
      was validation's pipeline; validation 83 passed them (10.8).

## 7. The storefront's mediation check

Delivers the mediation kit's access check and the VM storefront's
`market-storefront check-mediation --origin` (D11, "The storefront checks its mediation
configuration from its own container"). Requirement: deployment-state "A storefront
checks its mediation configuration from its own container".

- [x] 7.1 `kit/arkhai-mediation`: a mediation access check beside the client
      (`src/market_arkhai_mediation/access_check.py`), modelled on
      `kit/arkhai-payments/src/market_arkhai_payments/access_check.py`: from a role's
      dispute credentials and an origin it selects the credential, resolves its token,
      builds the client with its `ca_bundle_path`, makes one authenticated `respondent`
      read, and returns `ok` with the origin or the failing step — `configuration` (no
      credential for the origin; an unreadable or malformed CA file, before any
      request), `credential` (an unresolvable token, before any request), `transport`,
      or `refused` with the authority's code — every detail fixed text plus public
      configuration. It asserts nothing about the read's answer. (D11)
      Done: `check_mediation_access`, `check_configured_mediation_access` and
      `authority_origin`; outcome JSON `{"check": "mediation", "outcome", "origin"}`
      plus `step`, `code`, `detail` on failure. Its extra `configuration` cases are in
      `design.md`, "Settled during implementation". The kit's floor on
      `arkhai-kit-deal-lifecycle` rose to 0.3.0; its `tests/integration` became a
      package.
- [x] 7.2 `domains/vms/storefront/src/market_storefront/cli.py`:
      `check-mediation --origin <authority>` loads configuration as `serve` does, calls
      the kit check, prints one JSON line with no credential, and exits 0 on `ok`, 1 on a
      failed step, 2 on a malformed origin, as `check-payments` does. (D11)
      Done; seams `dispute_credentials()` and `mediation_transport()`.
- [x] 7.3 Verification.
      Unit: `kit/arkhai-mediation/tests` — each failing step and `ok` against an
      injected transport, including an empty and a full respondent listing both `ok`.
      Application integration: `domains/vms/storefront/tests/unit/cli/test_check_mediation.py`
      beside `test_check_payments.py` — the command's output and exit codes through its
      configuration and transport seams.
      End-to-end: none in the Compose lanes (D9); section 8's Helm test runs it.
      Owed by validation: `tests.yml`, jobs `test · test-kits` and `test · test-domains`
      — both pass.
      Evidence: `make -C kit/arkhai-mediation test` 114 passed: unit
      `test_access_check.py` (25, against `MediationContractFake`) and library
      integration `test_access_check_tls.py` (6, a real TLS listener; an
      unresolvable origin is not exercised, reaching the check as the same transport
      error a refused connection does).
      Correction to the application integration line: `test_check_mediation.py` is a
      unit test, as its sibling is — Typer's runner, the module's factories replaced,
      no application. `make -C domains/vms/storefront test`: unit 1174 passed,
      1 skipped; integration 551.

## 8. The local Helm release

Delivers the `mediation-lane-double` subchart, the release's recommendation and copied
credential, and the storefront chart's mediation-check test run by Helm validation
(D11). Requirements: deployment-state "Payment credentials stay with their owning
process", "The local release rehearses a deployment's payments interface", "A storefront
checks its mediation configuration from its own container".

- [x] 8.1 Subchart `helm/charts/mediation-lane-double` modelled on
      `helm/charts/payments-lane-double`: Service `mediation-double`, TLS from a named
      Secret or the image's files, disabled by default; `helm/Chart.yaml`,
      `helm/values.yaml` and `helm/values.schema.json` declare it; `helm/local-values.yaml`
      enables it; `helm/bare-metal-release-values.yaml` disables it, as for the payments
      double. (D11)
      Done in the payments subchart's shape, one replica under `Recreate`; no
      configuration in the cluster. `topology-up` restarts neither double, since a
      restart loses every case.
- [x] 8.2 The release's registry recommends the mediation double's identity
      (`helm/local-values.yaml`); `helm/scripts/topology-secrets.sh` rewrites the copied
      dispute credential's `ca_bundle_path` to the storefront chart's CA file, and a test
      holds it to `storefront.caBundleFile`. (D11)
      Done; input `STOREFRONT_CA_BUNDLE_FILE` (`helm/Makefile`); an entry stating no
      `ca_bundle_path` keeps none.
- [x] 8.3 Storefront chart test pod `helm/charts/storefront/templates/tests/mediation-check-test.yaml`,
      rendered from the Deployment's helpers for an agent with a dispute credential and
      `tests.mediationOrigin` (values and `values.schema.json`), running
      `market-storefront check-mediation --origin` directly with the Deployment's image,
      configuration and secrets mounts, identity credential and CA bundle mount, without
      the data volume, probes or ZeroTier capabilities and device; the local release
      sets Bob's `tests.mediationOrigin` to `https://mediation-double:8443`. (D11)
      Done; it renders on `tests.mediationOrigin` alone (`design.md`, "Settled during
      implementation").
- [x] 8.4 `scripts/validate_slice.py` runs every `-mediation-check` pod the release's
      hooks render as it runs the payments checks, counting each passed only on its
      pod's exit status of 0 and keeping its log. (D11)
      Done by generalising the payments checks (`CheckPods`, `CHECK_PODS`,
      `_run_check_pods`); evidence key `mediation_checks`; a release rendering none is
      warned.
- [x] 8.5 Verification.
      Unit: `helm/charts/mediation-lane-double/tests/test_render.py` (off by default, one
      Service `mediation-double` in the local release, none in the bare-metal release,
      a named TLS Secret over the image's files); `helm/charts/storefront/tests/test_render.py`
      (the mediation-check pod's mounts and absences, rendered only with a credential and
      an origin); `helm/tests/test_release_topology.py` (release values render no
      double; the rewritten `ca_bundle_path`); `scripts/tests/test_validate_slice.py`
      (mediation-check pods run and judged by exit status).
      End-to-end: Helm validation's `-mediation-check` pod for Bob passes against the
      release's mediation double; no payment scenario runs on the release.
      Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — the chart
      render and release-topology suites pass.
      Evidence: `make -C helm test-render` passed (the three render suites).
      Correction: the rewritten `ca_bundle_path` is held in release tooling, not the
      topology test: `make test-release-tooling` 2697 passed,
      `test_change_build_and_helm_targets.py` running `topology-secrets` for real
      against `storefront.caBundleFile` read from `_helpers.tpl`, and
      `test_validate_slice.py` the mediation-check step. Validation 83's Helm part ran
      the pod (10.8).

## 9. The release wheelhouse

Delivers a release wheel set without the distribution only tests depend on (D20).
Files: the root `Makefile`, `scripts/tests/`.

- [x] 9.1 Root `Makefile`: a target building the release set, whose prerequisites are
      every current prerequisite of `dist` but `dist-lane-double-controls`; `dist`
      builds that target and `dist-lane-double-controls`, so the lanes, CI and
      validation, whose images install the controls wheel from `.dist`, build what
      they build today; `dist-release` builds the release set alone. `dist-ci` and
      `.github/workflows/release.yml` are unchanged: the workflow already runs
      `make dist-clean` before `make dist-release`. (D20)
      Done: `dist-release-set`; `dist` is that plus the test-only wheels;
      `dist-release` is `$(MAKE) dist-release-set`. Pre-closeout fix (77 F1, the
      owner keeping D20's firm form): `arkhai-apicredits-sample-app` leaves the
      release set too — `domains/Makefile` gains a `dist-release` aggregate without
      it, the root `dist-domains` builds that, and root `dist` and `dist-ci` build
      `dist-apicredits-sample-app` beside the controls wheel.
- [x] 9.2 Verification.
      Unit (`make test-release-tooling`): a case in
      `scripts/tests/test_change_build_and_helm_targets.py`, reading `make -n` as
      that file does, holds that `dist-release` builds no `lane-double-controls`
      wheel and builds every other wheel `dist` builds, and that `dist` and `dist-ci`
      still build it. Then `make check-packaging`.
      End-to-end: none; the lanes build `dist`, which is unchanged, and no validation
      part runs the release workflow.
      Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — the
      release-tooling suite passes with the new case.
      Correction to the planned file: the case is
      `scripts/tests/test_init_targets.py::test_the_release_set_builds_every_wheel_dist_does_but_those_only_tests_depend_on`,
      whose module already resolves a `make -n -w` wheel target to project
      directories; it holds that `dist` builds exactly the two test-only wheels beyond
      the release set and that `dist` and `dist-ci` build both.
      Evidence, with 77's fixes: `make test-release-tooling` 2698 passed; both
      storefronts' suites (598; 1174 + 551) with the warning cases; `make
      check-packaging` in pre-commit. Observed, not changed:
      `manifests/published-distributions.json` lists the sample app for
      `push-wheels`' registry push, which builds `make dist`; only the PyPI path omits
      it.

## 10. Closeout

Closeout changes documentation only; a part needing a code edit returns the change to
implementation. In the order of `openspec/README.md#plan-closeout-requirements`:

- [x] 10.1 Comment hygiene: run `make check-comment-hygiene`; any finding, or a comment
      this change added that still needs rewriting, returns the change to implementation.
      Done: `make check-comment-hygiene` passed (no change-ID, task-number or change
      name). A scan of every line the change added outside `openspec/` (base
      `842797c03`) for review, triage, migration, plan, design or "moved" wording
      found none naming its provenance; 77 F2's docstring was fixed before closeout.
- [x] 10.2 Import placement: check the imports sections 1–9 added; one that should move
      to module level returns the change to implementation.
      Done: the change adds one function-local import,
      `market_storefront.utils.config.settings` in `cli.py`'s `dispute_credentials`,
      commented where it stands: the storefront's settings resolve when that module is
      first imported, which must follow the root `--config` option, as
      `check-payments` does. It stays.
- [x] 10.3 Documentation compliance: re-check D1–D21 against `openspec/README.md`'s
      placement rules — the doubles' behaviour in `test-compatibility`, configuration in
      `settlement-configuration` and `deployment-state`, tooling in `tools/`, the
      controls scenarios in `e2e-tests/README.md`, the release wheelhouse in
      `docs/development/RELEASING.md` (with one sentence in `BUILD_AND_PACKAGING.md`),
      and no future state in permanent documents (the
      lane-wide clock, the buyer filing command and the meaning of a prepared delivery
      end belong to the roadmap).
      Done: each decision's destination follows `openspec/README.md`'s placement
      table, as the promotion record below lists; the three unsettled questions are
      roadmap gaps, and no permanent document states them as planned behaviour.
      Checked against the code: both doubles' READMEs and `tools/README.md` called
      their in-process suites library integration, which `TESTING.md` reserves for a
      component against its storage, so they now say application integration; the
      local Helm release, `TESTING.md`'s "Chart Render Tests" and the identities
      table now state the copied credential's rewritten `ca_bundle_path`; the
      lane-wide statements of `TESTING.md`, `e2e-tests/README.md` and the
      `test-compatibility` companion that described the `.invalid` authority and
      skipped case stages are rewritten to the mediation double.
- [x] 10.4 Narrative compression: shorten completed task notes to final behaviour,
      validation evidence, deferred work and destinations; move any rationale not already
      in `design.md` there first.
      Done: sections 1–9's notes cut to final behaviour, evidence, corrections,
      deferrals and destinations; the implementation choices they carried moved first
      to `design.md`, "Settled during implementation" (the abandoned response's
      framing, matching and counting and the two layers' rule choice, the shared
      clock, an unusable credential and its warning, `check-mediation`'s extra cases,
      the pod's rendering, the buyer filing's path, the ruled end's two servicing
      steps, the deal's ending, the two clock advances, the lost filing's retry).
      Fresh-context-check and rerun narratives were dropped as duplication of the
      commits; the one kept deferral is 5.4's settings seam.
- [x] 10.5 Roadmap currency, `docs/development/ROADMAP.md` Goal 8: the current-state
      paragraph says the case stages and six controls scenarios run against the
      mediation double; this change's gap row closes; convergence's row drops
      revised-case netting and records that its rate rows add `stop` and `penalty`
      execution to the mediation double before ruling with them (40 F2), and that a
      row using the gate steps no storefront servicing while its ruling waits (D15);
      the hosted dispute-authority row records D5 (no guard, inert by construction);
      three new unowned entries: the lane-wide perceived clock for storefronts, sites
      and the buyer half, naming convergence rows 6 and 7; a buyer command filing a
      dispute case on a running deal, which the controls scenarios would then use
      (D14); and what a `prepared` delivery end means to SCM, whose watch records an
      end from one whatever its state (D15), beside the hosted dispute-authority row.
      Record them in the promotion record.
      Done in `ROADMAP.md`: Goal 8's current state names the mediation double, the
      case stages, the bare-metal filing, the six controls scenarios, both doubles'
      controls and lane-double evidence; this change's row is marked archived;
      convergence's row drops revised-case netting and records `stop` and `penalty`
      execution and the gate's servicing rule; three unowned rows join Goal 8's table
      — the lane-wide perceived clock (convergence rows 6 and 7), a buyer command
      filing on a running deal, and what a `prepared` delivery end means, the last
      citing Goal 1's hosted dispute-authority row — which now records D5 instead of
      the `.invalid` authority.
- [x] 10.6 Campaign index currency, `openspec/changes/README.md`: this row's status and
      notes; the Goal 8 dependency graph is unchanged. Record the dispositions and run
      `make check-change-index`.
      Done: the row is `in closeout`, its notes rewritten to the validation, the
      promotion destinations and the unowned gaps; its link moves to the archive in
      10.11. The Goal 8 graph is unchanged, and no other row's `Depends on` or status
      changed (archive cleanup releases `converge-ongoing-compute-leases` and
      `separate-lane-infrastructure-chart`). `scripts/change-workflow check index`
      passed.
- [x] 10.7 Packaging: `make check-packaging`, then
      `make check-architecture-change CHANGE=add-arkhai-payments-lane-double`; resolve
      every failure; this change owns no architecture exception.
      Done: `scripts/change-workflow run pre-archive add-arkhai-payments-lane-double`
      at `0a4b64399` passed, exit 0 — `make check-packaging` (locks, layout, Python
      selection, the layer, scope, dependency and kind rules) and "OK:
      add-arkhai-payments-lane-double owns no architecture row"; it changed no file.
      The skills check runs among pre-commit's defaults (10.10).
- [x] 10.8 End-to-end pipeline: record the pipeline run, its result, and the scenarios
      exercising this change — `e2e_vm_payment_deal`, `e2e_vm_payment_purchase`,
      `e2e_vm_dispute_ruled_end`, `e2e_vm_dispute_discount`,
      `e2e_vm_dispute_lost_filing`, `e2e_vm_dispute_mediation_unavailable`,
      `e2e_vm_dispute_payments_hold`, `e2e_vm_dispute_hold_passed`,
      `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` — and Helm
      validation's `-mediation-check` pod; a run blocked for a reason outside this
      change is recorded as a blocker with its owner, its gated validations unrun.
      Done: validation 83 (`reviews/83-validation.md`) passed at `0a4b64399`, the
      merged `HEAD` this closeout commit builds on; closeout changes no code, so its
      runs describe the code the closeout commit carries. Pipeline: e2e.yml run
      42796718343, success — e2e-vm 290 passed, e2e-bare-metal 98, e2e-apicredits 4,
      the native gate passed; the VM lane ran `e2e_vm_payment_deal`,
      `e2e_vm_payment_purchase` and the six `e2e_vm_dispute_*` modules against both
      doubles, their first run, and the other lanes `e2e_bare_metal_payment_deal` and
      `e2e_credits_payment_deal` (the record takes each scenario's basis from the task
      notes and lane counts, not each scenario's own line). Helm: the served
      scenarios passed, Bob's payments check and mediation check pods each passed on
      exit 0 against the release's doubles. CI: tests.yml run 42796725828, success,
      all 20 jobs; every owed observation held — `test-lane-double-controls`
      (`check-tls` included; §1), `test-payments-lane-double` (§1, §2), `test-kits`
      and `test-domains` (§3, §7), `test-mediation-lane-double` (§4), `test-e2e-unit`
      (§5, §6), `test-deployment-packaging` (§8, §9); baseline dev's run 42792032103
      at `842797c03`, success, so no failure to compare. Local: `dist-clean`,
      `check-packaging` and `make test` passed. No blocker.
- [x] 10.9 Promotion, and the design-promotion record:
      - D1: `openspec/specs/test-compatibility/architecture.md`, a new "The in-lane
        mediation double" section after "The in-lane payments double";
        `docs/development/ARCHITECTURE.md`, "Testing strategy", and
        `docs/development/TESTING.md`, "Private Service Dependencies" — the
        programmed-decision principle; `tools/mediation-lane-double/README.md` (written
        in section 4).
      - D2: `docs/development/TESTING.md`, "The discipline every scenario follows",
        replacing its statement that no control moves the clock with the perceived-clock
        rule as current state, and `docs/development/ARCHITECTURE.md`, "Testing
        strategy"; the roadmap gap of 10.5.
      - D3: `openspec/specs/test-compatibility/architecture.md`, "Payment evidence
        ownership".
      - D4: `tools/README.md`, "Lane collaborators" (the controls package the
        collaborators and the harness import, and the mediation double);
        `tools/lane-double-controls/README.md` (section 1); `docs/development/TESTING.md`,
        "Private Service Dependencies".
      - D5: `openspec/specs/test-compatibility/architecture.md`, "The in-lane mediation
        double"; the roadmap row of 10.5.
      - D6: `e2e-tests/README.md`, a new "VM dispute controls" section after "VM buyer
        purchase" (the six controls scenarios, each on its own deal, and their
        markers), and the lane's list under "End-to-end lanes".
      - D7: `tools/README.md`, "Lane collaborators"; `dev-env/identities/README.md`'s
        table (the mediation fixture tokens, the retired `.invalid` authority).
      - D8: `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Dispute authority
        preferences" (the credential's `ca_bundle_path`, and that one whose bundle
        cannot be loaded is no usable credential: a storefront reports the deal
        `repair_required`, a buyer's filing reads the authority unreachable);
        `openspec/specs/settlement-configuration/architecture.md`, where it says a
        private CA is the payments section's alone; `kit/arkhai-mediation/README.md`
        (section 3).
      - D9: `docs/development/TESTING.md`, "Private Service Dependencies", and the
        paragraph on the lanes' doubles under "4. System Integration Tests
        (End-to-End)"; `e2e-tests/README.md`, "Shared payment-scenario configuration".
      - D10: `tools/payments-lane-double/README.md` (section 2);
        `openspec/specs/test-compatibility/architecture.md`, "The in-lane payments
        double", whose once-only claim and its statement that a result establishes
        nothing about rate parts and holds at the HTTP boundary are restated to the
        claimed rate and hold surface.
      - D11: `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Release topology" (the local
        release paragraph and the `make helm-topology-secrets` bullet);
        `docs/development/TESTING.md`, the Helm validation paragraph under "4. System
        Integration Tests (End-to-End)" and "Chart Render Tests";
        `docs/operator-handbook.md`, "Payments access"; `docs/development/VALIDATION_RUNBOOK.md`,
        where it describes `check-payments`; `docs/development/DEPLOYMENT_AND_CONFIG.md`,
        "Settlement consumer configuration and cutover", the paragraph "The
        storefront payments check" (beside it, the storefront's `check-mediation`,
        its outcome and steps) and "Storefront agents: pass-through configuration"
        (the `-mediation-check` test pod beside `-payments-check`);
        `openspec/specs/deployment-state/architecture.md`, "Arkhai payment consumers",
        where it says why each storefront CLI's `check-payments` reads from the
        storefront's own process (the same reason for `check-mediation`);
        `docs/seller-quickstart.md`, beside its `check-payments` step (a VM seller
        with a dispute credential runs `check-mediation --origin`); and
        `kit/arkhai-mediation/README.md`, "Composition" (written in section 7).
      - D12, D13: no permanent destination.
      - D14: `e2e-tests/README.md`, "VM dispute controls" (the harness files as the
        buyer through the mediation kit's dispute adapter, and why no SCM command
        does); the roadmap entry of 10.5.
      - D15: `openspec/specs/test-compatibility/architecture.md`, "The in-lane
        mediation double" (the gate holds a delivery end only in the double's record,
        and no stage steps servicing while a ruling waits there);
        `tools/mediation-lane-double/README.md`, "What a rule decides", and
        `tools/lane-double-controls/README.md`, "The controls", beside the gate; the
        roadmap entry of 10.5.
      - D16, D18: `e2e-tests/README.md`, "VM dispute controls".
      - D17, D19: the `test-compatibility` delta, by the archive in 10.11.
      - D20: `docs/development/RELEASING.md`, its introduction, beside the packages
        that are not published: the release workflow's `marketplace-wheelhouse.tar.gz`
        is what `make dist-release` builds, which carries no distribution only tests
        depend on, while `make dist` adds `lane-double-controls` and
        `arkhai-apicredits-sample-app` for the lanes and CI;
        `docs/development/BUILD_AND_PACKAGING.md`, "The wheelhouse", one sentence:
        `make dist` builds the lanes' superset of the release set `make dist-release`
        builds (77 F1).
      - D21: `e2e-tests/README.md`, "VM dispute controls" (one module per scenario,
        and why no order among them is needed).
      - The three deltas (`test-compatibility`, `settlement-configuration`,
        `deployment-state`) are written to `openspec/specs/` by the archive in 10.11;
        none of the three capabilities has an `index.md`, and `openspec/specs/README.md`
        needs no entry, since no capability or companion is added.
      Done as listed; the record below names each location. Beyond the list: the
      `test-compatibility` companion gains "The doubles' controls and perceived
      clocks" (D2, D4) and its purchase-evidence paragraph now describes the
      bare-metal filing against the double; `TESTING.md` gains the controls (D4) and
      the lane-double evidence label (D3) under "Private Service Dependencies"; the
      `deployment-state` companion states the copied credential's rewrite and that
      release values enable no double (D11); `DEPLOYMENT_AND_CONFIG.md`'s
      `helm-topology-up` and `helm-topology-check` bullets name the mediation double
      and check; `tools/lane-double-controls/README.md` says the release wheelhouse
      omits it (D20). The tools' READMEs written in sections 1, 2, 4 and 7 were
      corrected only as 10.3 says. Every destination under `tools/`, `e2e-tests/`
      and `dev-env/` — D4, D6, D7, D9's e2e part, D14–D16, D18, D20's tools part,
      D21, and 10.3's corrections there — is written in
      `reviews/closeout-readme-promotion.patch` for the closeout triage to apply
      (10.10); the record below names those locations as they will be once it is.
- [x] 10.10 Documentation citations: `make check-doc-citations CHANGE=add-arkhai-payments-lane-double`,
      resolving every match, then
      `scripts/change-workflow openspec validate add-arkhai-payments-lane-double --strict`.
      The first `scripts/change-workflow run pre-commit` refused — "the closeout
      step may not run after-functional-change" — because six promotion
      destinations this plan names lie outside the repository's inert paths
      (`openspec/`, `docs/`): `tools/README.md`, the three tool READMEs,
      `e2e-tests/README.md` (which `e2e-tests/tests/unit/test_qualification_modules.py`
      reads) and `dev-env/identities/README.md`; only implementation, triage and
      the merge make such commits (change-workflow CW-e1sg). The owner chose to
      keep closeout to the inert paths: the six edits, written in full, are saved as
      `reviews/closeout-readme-promotion.patch` (the `git diff` of those files,
      written with the Write tool; `git apply --check` was denied here, so it is
      unchecked by machine, though the files were then restored to `HEAD` by
      reversing exactly its hunks), and the six files are back at `HEAD`. **For the
      closeout review's triage:** apply that patch as a correction outside the inert
      paths, with the hooks a triage commit runs; until then the six READMEs still
      describe the `.invalid` authority and the skipped case stages, and the
      `#vm-dispute-controls` anchor that `TESTING.md`, `ROADMAP.md` and the
      `test-compatibility` companion cite does not yet exist. The owner's word: if
      the only paths changed since the closeout review's commit are the existing
      inert paths and READMEs, validation before archive cleanup may be waived
      (intervention ledger, last line); the inert paths are to be revisited for
      READMEs once this change merges to `dev` (`openspec/changes/README.md`,
      "Unowned work with no campaign").
      Done then: `scripts/change-workflow run pre-commit` passed, exit 0 — the
      index, tasks and skills checks, `openspec validate … --strict` ("valid"), and
      `make check-repository` (comment hygiene, documentation citations, decision
      destinations, history wording, local imports and the rest).
      Closeout triage (86 F1, F2): the patch is applied, with the Edit tool hunk by
      hunk, since `git apply` was denied here. The per-file line counts match the
      patch's, and `e2e-tests/README.md#vm-dispute-controls` now resolves for the
      three permanent citations. Under 86 F2, the controls package's suites are
      labelled "integration" (it owns no storage, so `TESTING.md`'s library
      integration does not fit) in its README, the patch's `tools/README.md` bullet
      and its Makefile help strings. The doubles' Makefile help strings and the
      root `Makefile` comments on the three test targets now say "application
      integration" to match the doubles' READMEs. The fresh-context check of the
      diff found two sentences of the patch's `e2e-tests/README.md` text
      overstating the code, and they are corrected: only the hold-passed module
      takes `lane_double_clock`, and the purchase stage asserts the case accepted
      with every part held, not that no ruling exists. It also flagged
      `e2e-tests/pyproject.toml`'s `e2e_vm_dispute_lost_filing` marker
      description, which is recorded as unowned in `openspec/changes/README.md`
      and not fixed here, since the owner's waiver covers only READMEs and
      Makefile comments. Evidence: `make test-e2e-unit` (unit) 896 passed and 1
      skipped, including `test_qualification_modules.py`, which reads the e2e
      README; `make test-lane-double-controls` (unit and integration) 120 passed;
      `make test-payments-lane-double` (unit and application integration) 84
      passed; `make test-mediation-lane-double` 73 passed; `scripts/change-workflow
      run pre-commit`: "after-functional-change … passed, exit 0",
      "pre-commit-functional … passed, exit 0", "pre-commit … passed, exit 0",
      rebuilding no file. The owner waived
      validation before archive cleanup, since only READMEs and Makefile help
      comments change (intervention ledger, last two lines).
- [x] 10.11 Archival: `scripts/change-workflow openspec archive add-arkhai-payments-lane-double -y`,
      merging the three deltas, and link the index row to the archived directory.
      Done: archived as `openspec/changes/archive/2026-11-10-add-arkhai-payments-lane-double/`,
      the deltas merged (no `--skip-specs`: none of the three specs held their
      content). `deployment-state` gained 1 requirement and 2 modified;
      `settlement-configuration` 1 modified; `test-compatibility` 7 added and 3
      removed. The diff of each holds each requirement once, as its delta states,
      and nothing else changed. The index row, `ROADMAP.md`'s row and
      `docs/attachments/settlement-option-envelope/index.md` now link the archive.
      Not repointed: `spot-deals-through-arkhai-payments`' `design.md` links the
      old directory with an anchor (`#d6-lane-first-use-and-evidence-classes`)
      that had already gone; that is another change's file, for its design
      reverification.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 The mediation double answers from programmed rules | `openspec/specs/test-compatibility/spec.md#requirement-lanes-run-a-mediation-double-that-answers-from-programmed-rules` (archive); `openspec/specs/test-compatibility/architecture.md#the-in-lane-mediation-double`; `docs/development/ARCHITECTURE.md#testing-strategy`; `docs/development/TESTING.md#private-service-dependencies`; `tools/mediation-lane-double/README.md` |
| D2 Perceived clocks under scenario control | `openspec/specs/test-compatibility/spec.md#requirement-each-lane-double-reads-a-perceived-clock-the-scenario-advances` (archive); `openspec/specs/test-compatibility/architecture.md#the-doubles-controls-and-perceived-clocks`; `docs/development/TESTING.md#the-discipline-every-scenario-follows`; `docs/development/ARCHITECTURE.md#testing-strategy`; `docs/development/ROADMAP.md`, Goal 8's lane-wide perceived clock row |
| D3 One contract per double and two evidence classes | `openspec/specs/test-compatibility/spec.md#requirement-the-in-lane-payments-double-mirrors-the-service-and-proves-its-engines-surface` (archive); `openspec/specs/test-compatibility/architecture.md#payment-evidence-ownership`; `docs/development/TESTING.md#private-service-dependencies` |
| D4 Controls: one rule mechanism, shared middleware, a typed client | `openspec/specs/test-compatibility/spec.md#requirement-lane-double-controls-are-typed-deterministic-steps` (archive); `openspec/specs/test-compatibility/architecture.md#the-doubles-controls-and-perceived-clocks`; `tools/lane-double-controls/README.md`; `tools/README.md#lane-collaborators`; `docs/development/TESTING.md#private-service-dependencies` |
| D5 No production guard on fixture identities | `openspec/specs/test-compatibility/architecture.md#the-in-lane-mediation-double`; `docs/development/ROADMAP.md`, Goal 1's hosted dispute-authority row |
| D6 This change's scenarios | `openspec/specs/test-compatibility/spec.md` (archive: the payments double's VM scenario, the buyer purchase's filing, the controls scenarios); `e2e-tests/README.md#vm-dispute-controls`, "Hosted VM servicing", "Bare-metal payment deal" and "End-to-end lanes"; `docs/development/TESTING.md#4-system-integration-tests-end-to-end` |
| D7 Project, fixtures and TLS | `tools/README.md#lane-collaborators`; `tools/mediation-lane-double/README.md`; `tools/lane-double-controls/README.md#tls`; `dev-env/identities/README.md` |
| D8 Mediation trust through configuration | `openspec/specs/settlement-configuration/spec.md#requirement-dispute-credentials-are-bound-by-identity-and-no-template-ships-an-authority` (archive); `docs/development/DEPLOYMENT_AND_CONFIG.md#profile-based-configuration` and `#kubernetes-configmap-and-secret-mounting` (the private-CA conventions it instances); `openspec/specs/settlement-configuration/architecture.md#precedence-and-secret-boundaries`; `kit/arkhai-mediation/README.md` |
| D9 Lane wiring | `openspec/specs/test-compatibility/spec.md#requirement-a-lane-owned-mediation-target-fails-rather-than-skips` (archive); `docs/development/TESTING.md#private-service-dependencies` and "4. System Integration Tests (End-to-End)"; `e2e-tests/README.md#shared-payment-scenario-configuration` |
| D10 The payments double's claimed surface | `openspec/specs/test-compatibility/spec.md#requirement-the-in-lane-payments-double-mirrors-the-service-and-proves-its-engines-surface` (archive); `openspec/specs/test-compatibility/architecture.md#the-in-lane-payments-double`; `tools/payments-lane-double/README.md` |
| D11 The local Helm release and `check-mediation` | `openspec/specs/deployment-state/spec.md#requirement-a-storefront-checks-its-mediation-configuration-from-its-own-container` and its two modified requirements (archive); `openspec/specs/deployment-state/architecture.md#arkhai-payment-consumers`; `docs/development/DEPLOYMENT_AND_CONFIG.md#release-topology` and `#storefront-agents-pass-through-configuration`; `docs/development/TESTING.md#4-system-integration-tests-end-to-end` and `#chart-render-tests`; `docs/operator-handbook.md#payments-access`; `docs/development/VALIDATION_RUNBOOK.md`; `docs/seller-quickstart.md`; `kit/arkhai-mediation/README.md` |
| D12 Scope removed from the earlier design | No permanent destination: it removes scope |
| D13 Implementation cadence | No permanent destination: change history |
| D14 The buyer files through SCM's dispute adapter | `openspec/specs/test-compatibility/spec.md#requirement-controls-scenarios-prove-the-lanes-dispute-wiring-in-the-vm-lane` (archive); `e2e-tests/README.md#vm-dispute-controls`; `docs/development/ROADMAP.md`, Goal 8's buyer filing command row |
| D15 A programmed ruling is staged by its gate | `openspec/specs/test-compatibility/spec.md` (archive: the gate scenario and the servicing rule); `openspec/specs/test-compatibility/architecture.md#the-in-lane-mediation-double`; `tools/mediation-lane-double/README.md#what-a-rule-decides`; `tools/lane-double-controls/README.md#the-controls`; `docs/development/ROADMAP.md`, Goal 8's `prepared` delivery end row |
| D16 Payments holds a ruling twice | `openspec/specs/test-compatibility/spec.md` (archive: "Payments holds a ruling before it completes"); `e2e-tests/README.md#vm-dispute-controls` |
| D17 One deal per scenario | `openspec/specs/test-compatibility/spec.md` (archive); `e2e-tests/README.md#vm-dispute-controls` |
| D18 The lost-filing, mediation-unavailable and hold-passed scenarios | `openspec/specs/test-compatibility/spec.md` (archive); `e2e-tests/README.md#vm-dispute-controls` |
| D19 The delta states the six scenarios | `openspec/specs/test-compatibility/spec.md#requirement-controls-scenarios-prove-the-lanes-dispute-wiring-in-the-vm-lane` (archive) |
| D20 The release wheelhouse carries no distribution only tests depend on | `docs/development/RELEASING.md`, its introduction; `docs/development/BUILD_AND_PACKAGING.md#the-wheelhouse`; `tools/README.md#lane-collaborators` |
| D21 Each controls scenario is a module of its own | `e2e-tests/README.md#vm-dispute-controls`; `openspec/specs/test-compatibility/spec.md` (archive) |
| Effects on other changes | `docs/development/ROADMAP.md`, Goal 8's convergence row; the dependents' own designs, reverified at archive cleanup |
| Roadmap currency (10.5) | `docs/development/ROADMAP.md`: Goal 8's current state, this change's row, convergence's row, three unowned rows; Goal 1's hosted dispute-authority row |
| Campaign index currency (10.6) | `openspec/changes/README.md`: this change's row; the Goal 8 graph unchanged |
