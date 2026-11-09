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
      Done. Root `dist-lane-double-controls` is in both `dist` and `dist-ci` (CI's
      matrix builds with `dist-ci`). `make test` runs reinit, `check-tls`, `mypy --strict`
      over `src`, then the suite. `requires-python = ">=3.12,<3.14"`, because the
      mediation kit requires 3.12. Runtime dependencies: the mediation kit, httpx,
      jsonschema, pydantic; `cryptography` (the generator) and `uvicorn` (loopback fault
      tests) are dev-only. The middleware is plain ASGI and needs no starlette.
      `scripts/uv_project.py lock` refuses a project with no `uv.lock`, so the first lock
      was a header-only seed (`version`, `revision`, `requires-python`) that
      `make lock PROJECTS=tools/lane-double-controls` then rewrote; section 4's new
      project needs the same. Scripts suite (`make test-release-tooling`, unit, which
      includes `test_tests_workflow.py`): 2686 passed.
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
      Done. The shapes chosen within D4 are recorded in `design.md`, D4, "Control
      shapes": the boolean `delivery_end` with `end_delivery` refused in `effects`, the
      basis and effects validated against the contract, the filing-answer forms, and
      each double's match properties and actions (`MATCH_KEYS`, `ACTIONS`;
      `Rule.check_supported(double)` refuses others `422 invalid_request` for the
      doubles to call). `award` validates as the contract allows; whether the double
      can apply it is section 4's. `ControlError(status, code, message)` is the one error on
      both sides. `Status.contracts` maps each contract resource name to its SHA-256.
      `CaseView` (`case_ref`, `transaction`, `agreement`, `state`, `filer`, `kind`,
      `cause`) is a first cut section 4 may extend. Unit (`tests/unit/test_models.py`):
      passed.
- [x] 1.3 Route declarations and a typed sync client (`routes.py`, `client.py`) over
      httpx, authenticated by the control bearer token and trusting a configured CA
      bundle, raising one typed error carrying the control code. Routes live under
      `/test/` on each double's API port. (D4, "Scope and access")
      Done. `routes.py` declares each route with the doubles serving it (`routes_for`);
      resume is mediation's only, since no payments rule waits. `authorize(header,
      token)` is the control-token check both doubles call. The client sets
      `trust_env=False` so no runner proxy sees a lane-private name, keeps httpx's own
      error for a transport failure, and raises `ControlError(…, "unexpected_response",
      …)` for an error status whose body is not a control error. Unit
      (`tests/unit/test_routes.py`): passed. Library integration
      (`tests/integration/test_client.py`): passed — a stand-in over `MockTransport`
      that answers only the declared methods and paths (404 otherwise) holds each of
      the twelve client methods to its literal method, path, query and body and to the
      control token, and checks every declared route has a method; each control code
      raised as `ControlError`; a loopback HTTPS server with the mediation leaf, trusted
      through `ca_bundle_path` and refused under default trust. The stand-in is not a
      double: the client against the doubles' real routes is sections 2 and 4.
- [x] 1.4 The transport-fault ASGI middleware (`middleware.py`): it applies only to the
      contract's API routes, never to `/test/` routes; *unavailable* starts and then
      abandons every API response; *drop after commit* lets the matching request
      complete in the application, then starts and abandons its response. A matched
      request is counted in the rule listing. (D4, "Transport faults live in the
      doubles", "How a response is abandoned", "Control routes are never faulted")
      Done. The middleware reads the body, hands a `FaultRequest` (method, path,
      lower-cased headers, body) to the double's classifier, and replays the body to the
      app. The classifier owns matching and the matched count, since only the double
      knows its accounts and rules: sections 2 and 4 count a match in the listing
      (2.5 and 4.8 now verify a fault rule's count). Beside the control routes,
      `/health` is never faulted or classified (`routes.is_contract_path`): under
      *unavailable* a Helm liveness probe would otherwise restart the double and drop
      every deal's state; recorded in D4, "Control shapes". An
      abandoned response is started with `content-length: 1` and never finished, so the
      closed connection cannot read as a complete empty answer whatever framing uvicorn
      picks. Library integration (`tests/integration/test_middleware.py`, the
      middleware under uvicorn on loopback): passed, each fault raising
      `httpx.RemoteProtocolError` and the drop's handler running once.
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
      Done. The files are `lane-ca.pem`, `payments-double.pem` and
      `mediation-double.pem` (keys `<service>.key.pem`, ignored by `.gitignore`); the CA
      is named `lane doubles CA (public development value)`, so its bytes and the
      payments leaf's changed, and every reader takes them from the files. The payments
      image still places the CA, leaf and key at `/opt/payments-lane-double/tls/`
      (`lane-ca.pem`, `double.pem`, `double.key.pem`), so `compose.payments-double.yml`'s
      healthcheck and the `payments-lane-double` chart needed no edit. Repointed beyond
      the list: `e2e-tests/tests/unit/test_payments_helper.py` and
      `test_domain_stack_configuration.py`, `helm/tests/test_release_topology.py`, the
      payments double's `tests/integration/test_lane_env.py` and `Dockerfile.dockerignore`,
      `.gitignore`, `dev-env/identities/README.md` (its prose and restated-value table),
      the lane CA's provenance in `docs/development/DEPLOYMENT_AND_CONFIG.md`'s
      `make helm-topology-secrets` bullet, `helm/scripts/topology-secrets.sh`,
      `helm/Makefile`, `helm/bare-metal-release-values.yaml` and comments in two tests,
      and the false `check-tls` statements in `tools/README.md` and the payments
      double's README; the
      payments double's `check-tls`/`tls` targets and `tests/unit/test_tls.py` moved into
      the controls project. Compose mount targets stay `/run/payments-lane-double/…`
      (section 5 decides any new path). The certificates were written with the Write tool
      from the generator's output, since this run's `make -C tools/lane-double-controls
      tls` was denied; `check-tls` confirms them byte for byte. `make
      build-payments-lane-double` built the image.
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
      Evidence: `make -C tools/lane-double-controls test` — `check-tls` passed, `mypy
      --strict` clean, 112 passed (unit: models, routes, TLS generator against the
      committed CA and both leaves; library integration: middleware under loopback
      uvicorn, typed client). `make -C tools/payments-lane-double test`: 43 passed
      against the moved certificate. `make test-e2e-unit` (unit): 786 passed, 1 skipped.
      `make -C helm test-render` (render and release-topology units): passed.
      `scripts/change-workflow run pre-commit`: `after-functional-change` and
      `pre-commit-functional` passed, `make check-packaging` included (locks, layout,
      architecture); `pre-commit`'s `check-repository` failed only on the citations
      check, for three paths the plan cites that sections 4 and 6 create
      (`tools/mediation-lane-double/README.md`,
      `e2e-tests/tests/e2e/roles/helpers/lane_doubles.py`,
      and section 6's then-planned single VM controls module, since replanned as
      six modules), cited since planning.
      End-to-end scenarios covering the section once deployed: none; the lanes first
      run the package in section 5.
      Handoff: a fault is observable only through a real server — httpx's
      `ASGITransport` asserts on a response the app never completes rather than
      raising a transport error — so section 2's drop-after-commit and *unavailable*
      cases must serve the payments double under uvicorn on loopback, as
      `tests/loopback.py` here does (each project keeps its own copy, as the
      storefronts do). Declaring `lane-double-controls` in the payments double raises
      its `requires-python` floor to 3.12. Running the payments double outside its
      image takes the leaf and key copied under the image's names (its README, "Running
      it"); 2.1 may let `Settings` read the generator's names instead. Left for the
      owner: `make dist` now builds the controls wheel, as 1.1 prescribes, and
      `dist-release` is `make dist`, so the release workflow's
      `marketplace-wheelhouse.tar.gz` carries this development-only wheel; keeping it
      out means a release aggregate without it, to settle before section 5 makes
      `e2e-tests` depend on the wheel. For 9.9: `tools/README.md`'s "Lane
      collaborators" says nothing imports a collaborator and it ships only as an image,
      which the controls package (imported, a wheel) does not fit; promotion amends that
      definition or adds a category rather than only an entry.

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
      Done. `PerceivedClock` (`src/payments_lane_double/clock.py`) wraps the injected
      wall clock; `create_app(directory, clock=…)` still takes the wall clock, so the
      existing suite's injected clock keeps working, and admission reads the
      perceived clock too. The middleware wraps the whole app
      (`app.add_middleware`); `routes.is_contract_path` keeps it off the control and
      health routes. `requires-python` is now `>=3.12`, the version 0.2.0, and the
      lock relocked (`make lock PROJECTS=tools/payments-lane-double`). The bearer
      parse moved to `accounts.bearer_token`, shared by authentication and the rule
      book.
- [x] 2.2 Control routes under `/test/`, authenticated by a fixture control token added
      to `fixtures/accounts.toml` and labelled a public development value: rules
      (install, list, delete) for refusals with a published `ApiError` status and code,
      drop after commit and *unavailable*; clock advance and reset; fund an account
      (`PaymentsAuthority.fund`, `404 account_not_found` for an account outside the
      directory); rotate the receipt signer to a second committed fixture seed; status
      reporting the perceived now and the installed contract hashes from
      `market_arkhai_payments.contracts`. Refusals follow D4's table. (D2, D3, D4)
      Done. `fixtures/accounts.toml` gains `control_token` and `rotation_seed` (both
      labelled public development values); the loader refuses a control token that
      is also an account's token and a rotation seed equal to the receipt seed. No
      lane pins the rotated identity, so the fixture states only its seed. Handlers
      are registered from `routes_for("payments")`, and app construction fails if one
      is missing. The rule book (`src/payments_lane_double/rules.py`) is read twice:
      the middleware's classifier acts on and counts a drop or *unavailable* match;
      each API handler, after authenticating the caller, acts on and counts a
      refusal. Both take the first matching rule, an *unavailable* rule first, so one
      call meets one rule and is counted once. A refusal's code must be a published
      `ApiErrorCode` (else 422). For an approval, `transaction` is the id its mandate
      will have, so a rule can be scoped to one deal from its first call. Rotation
      swaps the engine's signer; a snapshot after it embeds the receipt under its
      original signature, so a verifier trusts both keys. Status reports
      `schema/payments.schema.json` and `test-vectors/payments.json`.
- [x] 2.3 Suite coverage of the rate and hold surface through the payments kit's
      `PaymentsClient` over an ASGI transport, with clock advances: rate parts and
      payee-only `start`; `stop` with notice and the earliest pending stop taking effect
      when the perceived clock reaches it; per-part `end`; funding exhaustion at
      funded-through; `afterStop` holds releasing after the clock passes them; partial
      `reverse` before and after a stop; `extend` and `lift` with `hold_not_extendable`,
      `extension_not_found` and `extension_closed`. (D10)
      Done in `tests/integration/test_double.py`, under "the rate and hold surface",
      each case moving time through the clock control and reading state through the
      kit's `PaymentsClient` (snapshots and the balance), the app in process behind
      Starlette's test client: payee-only start and earning; the payer's PT2H-notice
      stop superseded by the payee's earlier PT1H one, which takes effect at T0+1h; a
      part's `end` stopping it (`cause: terms`, the stop event naming the part); a
      payer funded with exactly two periods through the funding control, stopped at
      its funded-through; an `afterStop` once hold still held one second before
      T0+1h and released, net of fee, at it; reverses of 500 before and after a
      stop, then `insufficient_held_funds`; extend, lift, `extension_closed`,
      `extension_not_found`, and `hold_not_extendable` on a released once part. The
      shared lane helpers moved to `tests/integration/support.py`.
- [x] 2.4 Update `tools/payments-lane-double/README.md`'s claim from the once-only
      surface to the rate and hold surface, and describe the controls and clock. (D10;
      the README is the double's own documentation, maintained with its code)
      Done: "What it is", a new "Controls" section, "What it claims", the fixtures
      list and the `make test` bullet.
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
      Correction: the `/health` case is proven where the exemption lives, in the
      controls package's middleware test (`/health` answering under *unavailable*,
      never classified); no typed client here reads `/health`, and a raw call would
      break `TESTING.md`'s "no raw calls" rule.
      End-to-end: none in this section; section 5's lanes run this double.
      Owed by validation: `tests.yml`, job `test · test-payments-lane-double` — the
      double's `make test` passes with the new suites.
      Evidence: `make -C tools/payments-lane-double test` — 90 passed. Unit
      (`tests/unit`): `test_clock.py` (forward-only advance, reset to wall time);
      `test_rules.py` (each route's properties, the approval's transaction, first
      match, *unavailable* first, each layer counting only its own action, published
      codes, 409/404); `test_fixtures.py` (control token and rotation seed load and
      are refused when they collide). Control-token admission is unit-tested in the
      controls package (`authorize`); here it is proven through the app, in
      `test_controls.py`, rather than at unit level. Library integration, the app in
      process behind Starlette's test client: `test_double.py` (2.3's surface) and
      `test_controls.py` (refusal answered with its code and counted, a rule scoped to
      one transaction, funding through `get_balance` and its 404, rotation — a
      snapshot signed with the second key and verifying under both, an earlier
      receipt under the first, a later receipt under the second alone — status hashes
      against `get_contract().metadata`, clock advance and reset, admission on the
      perceived clock, wrong, missing and account tokens refused, `rule_exists` and
      `rule_not_found`, and a rule without `match` or a scoped *unavailable* rule
      refused by hand as rejection paths reading the status only). Library
      integration, the app under uvicorn on loopback (`test_faults.py`): a dropped
      approval raising `PaymentsTransportError`, counted; with the rule removed, the
      buyer already debited and the snapshot present before any retry, and a retry a
      minute later returning that receipt, approved at T0, with no second debit;
      *unavailable* abandoning a balance read and an approval while `/test/status`
      answers, both matches counted, and its removal restoring the API. `make
      build-payments-lane-double` built the image from the new lock.
      `scripts/change-workflow run pre-commit`: `after-functional-change` and
      `pre-commit-functional` (packaging and every suite) passed; `check-repository`
      failed only on the citations check, for the three later-section paths 1.6
      names.
      End-to-end scenarios covering the section once deployed: none; section 5's lanes
      run this double, and section 6's module drives its controls.
      Handoff: the lane-double evidence of 5.5 can read status through
      `ControlClient.status()`; its `contracts` keys are the kit's resource paths. The
      permanent `test-compatibility` companion ("The in-lane payments double") and
      `ROADMAP.md`'s row still say the double claims only the once-only surface: 9.9
      should name the companion beside the README for D10, and 9.5 the roadmap row.
      The double serves rotation but no scenario resets it; a lane that rotates keeps
      the second key for the rest of its run.

## 3. Mediation trust through configuration

Delivers `[[DisputeCredential]].ca_bundle_path` and the mediation client's CA argument,
passed by all four lifecycle compositions (D8). Requirement: settlement-configuration
"Dispute credentials are bound by identity and no template ships an authority".

- [x] 3.1 `kit/deal-lifecycle`: `DisputeCredential` (`configuration.py`) gains an
      optional `ca_bundle_path`, refused when empty, as the payments section refuses an
      empty one; it appears in no option, Agreement or status. (D8)
      Done: a blank path is refused too (`ca_bundle_path must name a file`), as the
      payments section refuses one. The credential is only ever configuration, so no
      projection changed. Version 0.3.0 (new public field).
- [x] 3.2 `kit/arkhai-mediation`: `MediationClient` (`client.py`) takes an optional CA
      bundle and uses it as its verification context
      (`ssl.create_default_context(cafile=…)`); absent means default trust; no process
      state changes. Update `kit/arkhai-mediation/README.md`'s client section. (D8)
      Done: keyword `ca_bundle=`, the payments client's shape. The context is built
      before the httpx client whether or not a transport is injected, so a missing or
      malformed bundle raises `OSError` (`FileNotFoundError`, `ssl.SSLError`) at
      construction and an empty one `ValueError`. README "Composition" says so and its
      example passes `credential.ca_bundle_path`. Version 0.3.0.
- [x] 3.3 Pass the credential's `ca_bundle_path` in every construction:
      `domains/vms/storefront/src/market_storefront/deal_lifecycle.py`,
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`,
      `domains/vms/buyer/src/arkhai_vms_buyer/lifecycle.py`,
      `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/lifecycle.py`. The
      storefronts' generated values schemas keep refusing `[[DisputeCredential]]` whole
      in public chart configuration; regenerate them if the model change alters them.
      (D8)
      Done. The values schemas did not change: both definitions refuse the section as
      `false`, and both drift tests pass unregenerated. Beyond the plan, what a bundle
      the client cannot load (`OSError` at construction) does, by the rules already
      written for an unusable credential: each buyer's `_MediationPort` answers it as a
      `MediationTransportError`, as it answers an unresolvable credential, which by
      that port's existing rule leaves surrender usable (no test here runs a
      surrender); each storefront's `credential_available`
      now builds (and caches) the client, so a credential whose token does not resolve
      or whose bundle does not load is not usable and the deal reads `repair required`
      ("a storefront holding no usable credential for a deal's authority reports the
      deal `repair_required`", `DEPLOYMENT_AND_CONFIG.md`, "Dispute authority
      preferences"). Without it the VM storefront's `cycle()`, which builds the
      respondent poller's adapter outside its per-deal `try`, would fail the whole
      servicing cycle for every deal on the page. A duplicate credential binding is
      still refused at lookup, outside that `try`; an origin the client refuses (not
      HTTPS off loopback) now reads `repair required` too, where the VM cycle raised.
      The repair reason is `deal-servicing`'s fixed "Agreement authority credential is
      missing", which misnames a present credential with an unloadable bundle, and the
      `OSError` is not logged: left as it is, since rewording the kit's text is outside
      this section, and section 7's `check-mediation` names the failing step. Versions, minor because each role
      honours a new setting: VM storefront and bare-metal storefront 0.28.0 (the VM
      storefront's exact pin on the bare-metal storefront moved), VM buyer 0.11.0,
      bare-metal buyer 0.8.0; each raises its lower bounds on the two kits to 0.3.0.
      `make lock` relocked every project.
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
      Evidence: unit, `make -C kit/deal-lifecycle test` — 81 passed
      (`tests/unit/test_dispute_credential.py`: none unless stated, empty and blank
      refused, the credential `credential_for` resolves from TOML carrying the path).
      `make -C kit/arkhai-mediation test` — contract and generated-model checks,
      `mypy` clean, 83 passed: unit (`tests/unit/test_client_ca_bundle.py`, a missing
      bundle `FileNotFoundError`, a malformed one `ssl.SSLError`, an empty or blank one
      `ValueError`, all at construction); library integration
      (`tests/integration/test_client_tls.py`, the real client against a loopback TLS
      listener serving a leaf a throwaway CA issued: given that CA's bundle it reads a
      respondent page; given another CA's bundle, or none, `MediationTransportError`
      and the listener receives no request).
      Correction to the application integration line: what reaches each composition
      is shown by the client's construction failing on a bundle that does not exist,
      which only the client loads; that a bundle verifies a server, and that none
      leaves a private CA untrusted, is the kit's TLS test above, and no test here
      shows which trust store a client built without a bundle holds. VM storefront,
      application integration (`tests/integration/test_lifecycle_mediation_trust.py`,
      over `test_payment_settlement`'s harness: the storefront's settle and lifecycle
      routes in an in-process app, real SQLite, the lifecycle class built by the
      harness from a dispute document rather than by the storefront's composition
      root): after a settled, delivered payment deal, the lifecycle's cycle (the
      `settlement-servicing` step) and the buyer's read through `LifecycleClient` —
      with no bundle the authority is contacted and the outcome is `Unknown`; with a
      missing bundle nothing is sent and the outcome is `repair required`.
      Bare-metal storefront (`tests/integration/test_lifecycle_mediation_trust.py`,
      the harness's runtime behind its in-process app, its dispute configuration
      replaced as the harness replaces its composition): with a missing bundle the
      buyer's `LifecycleClient` read reports `repair required` and no client is kept;
      with none, the composition's dispute port called directly, through no app,
      builds the deal's client — kept as the contrast because a read with a usable
      credential would contact the harness's authority origin. Buyers, unit
      (`tests/test_lifecycle_adoption.py`, the composition's `_MediationPort` called
      directly): a missing bundle is a `MediationTransportError` caused by
      `FileNotFoundError`, no client kept; a buyer is a CLI with no app, so the
      planned application-integration level is not delivered for the buyers.
      Suite results: VM storefront 551 passed, bare-metal storefront 598, VM buyer
      216, bare-metal buyer 33 (both storefronts' values-schema drift tests among
      them). `scripts/change-workflow run pre-commit`: `after-functional-change` and
      `pre-commit-functional` passed, `make check-packaging` (locks, layout,
      architecture) and every suite included; `pre-commit`'s `check-repository`
      failed only on the citations check, for the three later-section paths 1.6
      names. The first pre-commit run also failed `domains/apicredits`'
      `tests/test_distribution_install.py` (two wheel-install cases whose throwaway
      environment imported a `market_core.schemas` lacking a name); it did not
      reproduce — `make -C domains/apicredits test-domain` then passed 41, and the
      second pre-commit run passed it; the cause was not found.
      End-to-end scenarios covering the section once deployed: none yet; section 5's
      VM case stages and bare-metal filing are the first (Bob's and the buyer's
      credentials carry `ca_bundle_path` from 5.3 and 5.4).
      Handoff: section 5 writes `ca_bundle_path` into Bob's secret overlay and the
      buyer's credential; the field is strict text, refused blank. Section 7's access
      check builds the client with `ca_bundle=credential.ca_bundle_path` and should
      read an `OSError` at construction as its `configuration` step, as the payments
      check reads its own.

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
      Done, the payments double's layout: `authority.py` (fixture), `protection.py`
      (not-held reason), `rules.py` (rule book), `service.py` (framework-free
      `MediationDouble`), `app.py` (routes and controls; service calls run in
      Starlette's thread pool, since a payments call waits on the network),
      `settings.py`, `__main__.py`, `Dockerfile.dockerignore`. `build-dev` builds the
      image, since `change_namespace.BUILT_IMAGES` is every image `build-dev` writes;
      `scripts/tests/test_change_build_and_helm_targets.py`'s root image targets gain
      it. The lane build targets are section 5's (5.1). Seed lock as in 1.1, then
      `make lock PROJECTS=…`. Beyond the plan: `PerceivedClock` moved from the
      payments double into `lane_double_controls.clock`, which both doubles import
      (its `test_clock.py` moved with it), rather than a second copy; the payments
      double needs no further bump (0.2.0 in this change), nor the controls package
      (0.1.0, new).
- [x] 4.2 Fixtures in `fixtures/`, every value labelled a public development value,
      never for a public network: the authority identity (origin
      `https://mediation-double:8443`, account `00000000-0000-4000-8000-0000000000d1`, a
      record key from a committed seed), bearer tokens mapping the buyer and seller
      payment accounts, the authority's payments token, and the control token. (D5, D7)
      Done: `fixtures/authority.toml`, record seed `0f…0f`, record key
      `ed25519:2b8hSHSKhcidparY7gsPwtEF_TnUGkx5ZTY1TwrikAw` (the loader refuses a key
      its seed does not yield), payments token
      `payments-lane-double-dispute-authority-public-development-token`, which 5.2
      gives `…00d1` in the payments double's accounts. It also holds `params` and
      `advertisement`, which 5.2's registry profile renders in place of the
      retired `dispute-authority.toml`. The payments URL and CA are settings, not
      fixture values (`https://payments-double:8443`, the image's lane CA).
- [x] 4.3 API mechanics against the vendored contract: `POST /cases`, `POST /append`,
      `GET /cases/{ref}`, `GET /record`, `GET /respondent`; bearer authentication;
      schema validation; idempotency and `idempotency_conflict`; either party appending
      evidence, only `mandate.to` concurring; the closed-case refusal; the signed
      per-agreement record with sequences and cursors, an empty signed page for a known
      agreement with no cases, the contract's refusal for an unknown agreement or
      reader. (D1, "Real mechanics")
      Done; the answers chosen are in `design.md`, D4, "Mediation shapes": 401
      `authentication_required`, 400 `invalid_request` for a malformed body, query
      or key, and one `404 invalid_request` for an unknown case, an unknown
      Agreement and a non-party reader (the kit's adapter already reads an initial
      404 `invalid_request` as "nothing filed yet"). An Agreement is known from its
      first filing whose transaction payments answers, so a filing left
      `protection_incomplete` makes it known with an empty page. Parties come from
      the transaction's signed receipt (`from`, `to`), read as the authority. The
      only filing refusal is `filer_not_party`; no digest or authority-listing check
      (D1). Correction (4.9, after design review 62): the filing also refuses an
      Agreement whose hash is not the receipt's `deal`, `agreement_hash_mismatch`;
      still no authority-listing check. Records are signed with the fixture key over `records.record_message`,
      which validates each entry against `RecordEntry`.
- [x] 4.4 Filing protection through the payments kit's client as the authority's
      account: `extend` per part; only `hold_not_extendable` reports `not_held`, its
      reason classified from the part's signed snapshot amounts — `paid_out`, else
      `reversed`, else `nothing_held`; every other refusal and every transport failure
      answers `error` with `protection_incomplete`, completed by a same-key retry; a case
      whose every part is `not_held` is dismissed with `nothing_held`. (D1, "Extension
      results", "A not-held part's reason")
      Done. Each extend's request id is `<case_ref>:<part>`, and an incomplete
      filing keeps its case reference under its key, bound to that filing (another
      filing under the key is `idempotency_conflict`), so a retry re-sends the same
      extends and payments answers each with its stored event; `extension_ref` is
      the stored event's sequence. The snapshot is read once, after every extend,
      for the not-held parts' reasons; a failed read is `protection_incomplete` too.
- [x] 4.5 Programmed decisions: rules matching `operation`, `filer`, `kind`, `cause` and
      `transaction`; filing-answer overrides; a ruling recorded in the signed record,
      its effects applied as payment events with stable effect keys and the case
      reference, then only that case's extensions lifted; `pause_before_effects` and
      resume; an incompletely applied ruling resumed without a duplicate effect; operator
      decide and close on an open case; no ruling without a rule; no signature, digest or
      guard verification. (D1, "Programmed")
      Done; shapes in `design.md`, D4, "Mediation shapes". Effect ids are
      `<case_ref>:<ruling>:<n>` (the delivery end `<case_ref>:<ruling>:end`, recorded
      applied unless the gate holds it), so a second ruling on an open case never
      reuses a first's, and case references carry a per-process prefix
      (`case-<hex>-<n>`), so a restarted double never meets the payments double's
      stored answers to an earlier process's keys; each effect's event, fixed when
      first sent, carries `{case_ref, effect_id}`
      under request id `mediation:<case_ref>:<ruling>:effect:<n>`, and a lift
      `mediation:<case_ref>:lift:<part>` with the part's `extension_ref` (an
      `extension_closed` lift counts as done), following the producer's traces. Only
      `reverse` effects are applied; `stop` and `penalty` are refused at install,
      since both act on rate parts no lane in this change runs, and `award`, which
      the contract makes unexecutable on payments v1 (README, "Deviation"; the
      delta states it, 40 F2); convergence's rate rows will need `stop` and
      `penalty` executed first (design, "Effects on other changes"). Rule
      matching on `filer` before the app runs needs the transaction's parties, so
      the classifier reads an unseen transaction's receipt itself, on the
      middleware's worker thread and outside the service's lock, and only while a
      rule matches on `filer` (commented in `service._properties`). A refusal rule acts on every operation,
      reads included, for a call past authentication, validation and the party and
      case checks; a rule whose action an operation cannot take is passed over for
      it; a rule that could never act, a match value no call has included, is
      refused at install. Left as it is: with payments unreadable at
      classification, the middleware sees no `filer` while the service later reads
      it, so the two layers can take different first rules for that one call. A ruling stopped
      part-way stays recorded as its ruled entry left it, effects `prepared`, with
      no further entry until it completes: that is the
      delta's "recorded as incompletely applied". Closing an applying case is
      refused, `409 case_applying`, lifting nothing. A case's `filed_at` is its signed
      filed entry's time, which the kit's adapter compares with the respondent
      listing's.
- [x] 4.6 Controls and clock: the shared middleware on the API routes; `/test/` routes
      for rules, decide, close, the case listing by transaction, the rule listing, clock
      advance and reset, and status reporting the perceived now and the installed
      mediation contract hashes; refusals per D4's table. Record times come from the
      perceived clock. (D2, D3, D4)
      Done. Status's `contracts` keys are `contract_data/<name>` for the schema,
      vectors and `publication.json`. A case listing without `transaction` is `422
      invalid_request`. Handlers are registered from `routes_for("mediation")`, and
      app construction fails if one is missing. `payments_unavailable` joined the
      controls package's `ControlCode` for the close that payments does not lift.
- [x] 4.7 `README.md`: what the double serves, its deviation from its producer (a case
      the authority would rule mechanically is ruled only by a rule), what its results
      establish and what they do not. (D1; the double's own documentation)
      Done: "What it serves", "What a rule decides", "Deviation from its producer",
      "What its results establish", "Controls and clock", "Fixtures", "Running it".
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
      Evidence: `make -C tools/mediation-lane-double test` — 67 passed. Unit
      (`tests/unit`): `test_protection.py`, the five cases; `test_rules.py`, matching
      (every stated property equal, a missing one never matching, install order,
      *unavailable* first), install refusals (`rule_exists`, a payments property, an
      unpublished code, an `award` effect), `rule_not_found` and `rule_not_waiting`,
      matched and waiting counts; `test_fixtures.py`, the committed fixture and its
      refusals. The fresh-context check's fixes added: a filing whose second extend
      fails once after the first committed (transport, and a `ledger_unavailable`
      refusal), completed by a retry whose extends, one per part, all carry the
      retried case's reference; a failed
      snapshot read after a nothing-held refusal completed on retry; another filing
      under an incomplete filing's key refused as a conflict; a ruling's second
      effect lost after payments took it, resumed with no second reverse; a second
      ruling on an open case applying its own effect ids; a close payments does not
      lift answered `502 payments_unavailable`; a refusal rule on a record read; the
      rules that could never act refused; and a control call with no `Authorization`
      at all (a rejection-path call, its status alone asserted). The second check's
      fixes added: a ruling's second effect refused (`ledger_unavailable`),
      unreachable, or lost after commit, each resumed with one reverse per effect; a
      case whose effect payments keeps refusing (since round 1's triage, 40 F1, its
      close refused `case_applying`, nothing lifted); the gate recording the delivery end `prepared`; the `error`
      and `rejected` filing answers; an append's exact retry and conflict. The third
      check's fixes added unit cases for the pass-over and for match values no call
      has. Payments
      failures are injected through `create_app`'s payments argument
      (`support.Failing`). Correction: the case refusals of D4's table (`case_not_found`,
      `case_closed`, an empty listing, the control token) are proven through the
      typed client in `test_controls.py`, not at unit level, since each needs a case
      the service filed. Library integration, the kit's real `MediationClient` over
      an ASGI transport to the app and the payments kit's `FakePaymentsClient` acting
      as the authority over its engine, the engine's clock the double's perceived
      clock: `test_mechanics.py` (two parts held, their `extension_ref`s the extend
      events' sequences; an unauthorized extend answered `protection_incomplete` with
      no part not held; the retries above; an exact retry and an
      `idempotency_conflict`; `filer_not_party`; a part refunded first dismissed
      `reversed`/`nothing_held`; an eight-day clock advance
      giving `paid_out` and a dismissal; evidence, payer concurrence refused and
      payee concurrence accepted, then `case_closed` after a close; record paging by
      cursor and the stranger refused; an unfiled Agreement refused and a known one
      reading an empty page; the respondent listing cleared by the respondent's
      append; a party's case read), `test_rulings.py` (a ruling recorded `prepared`,
      its reverse carrying `{case_ref, effect_id}`, both parts' extensions lifted and
      `applied` in the closed entry; a gated ruling applying only on resume; a
      payments failure on the second effect leaving the case `applying` and waiting,
      then resumed with one reverse each, 300 reversed; a ruling without `close`
      attested by a second ruled entry, nothing lifted), `test_controls.py`
      (through `ControlClient` over Starlette's test client: rule refusals, a
      refusal answered to the kit client and counted, a pending override followed by
      the same case once removed, an operator's partial reverse leaving the case
      open, close without ruling recorded `dismissed`/`operator`, the case listing,
      clock and status hashes against the kit's resources, records dated by the
      perceived clock, the control token required). Library integration under
      uvicorn on loopback (`test_faults.py`): *unavailable* abandoning a respondent
      read and a filing (`MediationTransportError`) while `/test/status` answers,
      both matches counted, and its removal restoring the API; a filing whose
      response a payee-scoped drop rule lost, counted, and adopted under the same key
      as the one case with one extend. `scripts/change-workflow run pre-commit`:
      `after-functional-change` and `pre-commit-functional` passed, `make
      check-packaging` (locks, layout, architecture) and every suite included,
      `make check-comment-hygiene` among `pre-commit`'s checks; `check-repository`
      failed only on the citations check, for the two section 6 paths 1.6 names
      (`tools/mediation-lane-double/README.md` now exists).
      `make build-mediation-lane-double` built the image; `make build-payments-lane-double` rebuilt the payments image after the
      clock move. `make -C tools/lane-double-controls test` 117 passed (the moved
      clock tests among them); `make -C tools/payments-lane-double test` 85.
      End-to-end scenarios covering the section once deployed: none; section 5
      first runs the double in the lanes, and section 6's module drives its
      controls. No test here crosses HTTP to the payments double; 5.6 is the first.
      Handoff: section 5 adds service `mediation-double` to the overlay and the
      lane build targets, gives `…00d1` the payments token the fixture states, and
      renders the registry recommendation from `fixtures/authority.toml` (identity,
      `params`, `advertisement`). The buyer's and seller's mediation tokens are the
      fixture's `accounts` tokens. A rule matching `filer` on a filing reads the
      transaction's parties from payments before the app runs, so it needs payments
      answering; with payments unavailable a filer-scoped drop rule does not match.
      Section 6's journey 5 (payments failing between two programmed effects) has
      no control sequence yet: a payments rule matches `route`, `account`, `event`
      and `transaction`, which two reverses of one ruling share, and a gated ruling
      resumed under payments *unavailable* fails its first effect, not its second.
      6.2 must settle how a lane stops a ruling after its first effect before
      writing that journey; it may need a payments match property, which is a
      design question, not a scenario detail.
      Round 1's triage fixes (reviews 40 and 41, against `1eb2cc4aa`):
      - 40 F1: closing a case applying a ruling is refused, `409 case_applying`
        (a new `ControlCode`), lifting nothing, since the contract's closed entry
        follows every effect's application and has no state for an abandoned
        effect; the delta gains "Closing a case still applying its ruling is
        refused", and design D4's table and "Mediation shapes", both READMEs and
        `test_rulings.py` follow.
      - 40 F2: the delta and proposal claim executing `reverse` effects and
        recording the delivery end; `stop` and `penalty`, which act on rate parts,
        and `award`, unexecutable on payments v1, are refused at install, now with
        that true reason in `rules.py`, the README and "Mediation shapes"; a unit
        case per refused kind. Convergence executes `stop` and `penalty` before its
        rate rows rule with them (design, "Effects on other changes"; 9.5).
      - 40 F3: the shared transport-fault middleware runs the classifier on a
        worker thread (`asyncio.to_thread`), so the control and health routes
        answer while the mediation classifier reads a transaction's parties.
      - 41 O1 (outside the plan, the owner's note): the lane doubles' image
        targets moved from the root `Makefile` into a new `tools/Makefile`, its
        `build` running both; the root's `build-tools` replaces them in
        `build-dev` and the three `build-e2e-*` targets; the READMEs, Dockerfile
        headers and subproject help texts name the new place, and
        `test_change_build_and_helm_targets.py` holds `build-tools` to both tags
        with and without `IMAGE_SUFFIX`.
      Evidence: `make test-lane-double-controls` (unit and library integration,
      `check-tls` and `mypy --strict` included) 120 passed, among them a loopback
      test that `/test/status` and `/health` answer while a classification is held;
      `make test-mediation-lane-double` (unit and library integration) 70 passed;
      `make test-payments-lane-double` 85 passed; `make test-release-tooling`
      2686 passed. `scripts/change-workflow run pre-commit`: "after-functional-change
      … passed, exit 0"; "pre-commit-functional … passed, exit 0" (`make
      check-packaging` and `make test`); "pre-commit … failed, exit 2" only on the
      documentation citations check, for the two section 6 files 1.6 names
      (`e2e-tests/tests/e2e/roles/helpers/lane_doubles.py` and the then-planned
      single VM controls module); the index, tasks, skills and strict
      OpenSpec checks passed. No image was built in this session: `make -n
      build-tools` is what the test reads, and the fix commit's Helm validation runs
      `build-dev`. The fresh-context check found two stale references (the app
      docstring's "event loop" exception; 4.5's "or the case is closed"), the
      controls README missing the classifier's threading contract, a spec scenario
      title reading as a successful close, and `tools/README.md`'s "built from the
      repository root": all fixed. Declined: renaming `build-tools` to name only the
      lane doubles, since the owner chose the name; `tools/README.md` says what it
      builds.
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
      Done. `_Parties` carries the receipt's `deal`, read with the parties and
      cached with them. The check runs after `filer_not_party` and before the
      readers, the rule book, the reservation and any extend, so a refused filing
      makes the Agreement known to no reader and no rule is consulted for it (the
      code's order; no test installs a rule for it); its answer is remembered
      under its key. The module docstring of `service.py` and the README's "What it
      serves" (`POST /cases`, and `GET /record`'s "first filing the double
      admits") and "Deviation from its producer" now say the binding is checked
      and only the concurrence signature and guard are not.
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
      Evidence: `make test-mediation-lane-double` — 73 passed. Application
      integration (the double's app in process through the kit's typed client;
      the plan, and section 4's earlier notes, call this suite library
      integration, which `TESTING.md` reserves for a component against its
      storage with no application),
      `test_mechanics.py::test_a_filing_whose_agreement_is_not_the_payments_is_rejected_before_any_effect`:
      correction to the planned seam — like the rest of the suite, the kit's real
      `MediationClient` reaches the app in process over an ASGI transport, and the
      payments peer is the payments kit's `FakePaymentsClient` over the shared
      `PaymentsAuthority` engine, not the payments double over HTTP (no suite here
      crosses HTTP to it; the lanes are the first). A filing whose Agreement's
      `price` differs is `rejected`, `agreement_hash_mismatch`; the engine's
      snapshot holds no `extend`; `ControlClient.cases` lists none; the buyer's
      record read of that Agreement is `404 invalid_request`; the same key returns
      the same refusal; an honest filing under another key is accepted, its part
      held, its case reference the process's first (the refusal reserved none),
      the one case listed. `support.filing` gained an `agreement` keyword.
      End-to-end scenarios covering the section once deployed: `e2e_vm_payment_deal`
      (the storefront's operator-end filing) and `e2e_bare_metal_payment_deal` (the
      buyer's teardown filing), each passing the check with an honest Agreement;
      section 6's markers join them once that section adds them. No scenario files
      a mismatched Agreement.
      `scripts/change-workflow run pre-commit`: `after-functional-change` and
      `pre-commit-functional` passed (`make check-packaging` and every suite);
      `pre-commit`'s index, tasks, skills and strict OpenSpec checks passed, and
      `check-repository` failed only on the citations check, for the two section 6
      paths not yet created (`e2e-tests/tests/e2e/roles/scenarios/vms/payment_deal.py`,
      `e2e-tests/tests/unit/test_lane_doubles_fixtures.py`). The fresh-context
      check's fixes (this note's level, 4.3's correction, the README's "first
      filing the double admits", the case-reference assertion) came after that run;
      the double's suite (73 passed) and `make check-comment-hygiene` were rerun.
      Handoff: the check sits where the double already reads the receipt, so a
      lane filing pays no extra payments read.

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
      Note: since round 1's triage (41 O1) the lane targets call `build-tools`,
      which builds both doubles' images through `tools/Makefile`, so the image half
      of this task is done.
      Done. The service starts once `payments-double` is healthy, since it extends
      there as the authority; Bob's storefront, the one lane storefront holding a
      dispute credential, waits for it too (`compose.vms-lane.yml`). Beyond the
      plan: the lane CA's mount target moved from `/run/payments-lane-double/` to
      `/run/lane-doubles/lane-ca.pem` (section 1 left the path to this section; D8's
      example names it), in the three lane overlays, the three lane storefront
      configurations, `e2e-tests/Makefile`'s runner mount, the runner profile and the
      tests naming it (`test_domain_stack_configuration.py`, the payments double's
      `test_lane_env.py`); `kit/arkhai-payments/tests/test_settlement_config.py`
      keeps the old string, an arbitrary path value there. `scripts/tests/
      test_bare_metal_compose.py`'s service set gains the double.
- [x] 5.2 The payments double's `fixtures/accounts.toml` gives `…00d1` a token, which the
      mediation double's fixture restates; retire the payments double's
      `fixtures/dispute-authority.toml` and its tests;
      `dev-env/registry/config-payments-lane.env` recommends the mediation double's
      identity. Update `core/registry/tests/unit/test_config_profiles.py` and the stack
      value tests that held the `.invalid` identity. (D5, D7, D9)
      Done. The fixture's removal reached beyond the plan's list: the payments
      double's Dockerfile `COPY`, its conftest helper, its README's fixtures list,
      its now-unused dev dependency on `arkhai-kit-deal-lifecycle` (relocked), and
      its suite's "cannot authenticate" case, now the authority's token
      authenticating as its account alone. The Helm release read the retired file
      too, so 8.2's recommendation half is done here: `helm/local-values.yaml`'s
      registry recommends the mediation double's identity, held by
      `helm/tests/test_release_topology.py` (two cases) to
      `tools/mediation-lane-double/fixtures/authority.toml`'s `interface`, `origin`,
      `account`, `record_key`, `params` and `advertisement`;
      `scripts/tests/test_change_build_and_helm_targets.py` holds Bob's copied
      credential's four identity keys to the same fixture. The topology test's runner
      profile parser now reads only the `payments` section, since the profile gained
      a `mediation` one with keys of the same names. The payments token's
      restatement is held in `scripts/tests/test_committed_stack_values.py`, which
      reads both doubles' fixtures, so neither double's suite reads the other's
      project. `dev-env/identities/README.md`'s restated-value tables follow (9.9's
      D7 entry for that table is so far done).
- [x] 5.3 `dev-env/identities/bob.storefront.secrets.toml`'s `[[DisputeCredential]]`
      carries the mediation double's seller token and `ca_bundle_path`, and the lane
      overlays mount the CA where that path names. (D8, D9)
      Done: bound to the double's identity, `api_key` its seller token,
      `ca_bundle_path = "/run/lane-doubles/lane-ca.pem"`, which `compose.vms-lane.yml`
      binds. The Helm release copies the credential with that Compose path until
      8.2 rewrites it; no payment deal runs in Helm meanwhile.
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
      Done. Beyond the listed keys: `mediation.account` and `mediation.record_key`,
      since a dispute credential is bound to the authority's whole identity, and
      `payments.control_token`, which 5.5's evidence and section 6 read. The helper
      offers `mediation_if_configured()` (None when the run names no target and
      claims none) and `configured_mediation()` (that, or the blocked skip);
      `API_KEY_ENV`, `ACCOUNT` and `RECORD_KEY` are required once a target is named,
      `CONTROL_TOKEN` once it is lane-owned. Readiness is the payments helper's
      `target_ready`, generalised to either target. Both purchase drivers
      (`vms/purchase_driver.py`, `bare_metal/purchase_driver.py`) write the
      credential and hand the token when the run names a target, so a qualification
      run naming none still buys. The restated values are held by the mediation
      double's new `tests/unit/test_lane_profile.py` (and its leaf covering the
      origin) and, for `payments.control_token`, the payments double's
      `test_lane_env.py`; `scripts/tests/test_lane_compose.py` holds both sections'
      CA path to the runner's mount. `e2e-tests` is not published, so no version
      bump; beyond the plan it now declares the deal-lifecycle, deal-lifecycle-buyer
      and deal-lifecycle-contracts kits it imports (the last was already imported
      undeclared). The helper is unit-tested (`test_mediation_helper.py`, the buyer's
      own `dispute_config` reading the written credential); the purchase drivers'
      use of it was not run end to end in this session. Like its sibling
      `test_payments_helper.py`, that test replaces the helper module's
      `settings`, which `TESTING.md`'s mocking convention discourages: a settings
      seam for both helpers is a refactor of its own, left as it is.
- [x] 5.5 Lane-double evidence: a payment scenario records the label *lane doubles* and
      both doubles' installed contract hashes, read from their status through the typed
      client. (D3)
      Done in `e2e-tests/tests/e2e/roles/helpers/lane_doubles.py` (created here;
      section 6 adds its rule and clock fixtures): a module fixture
      `lane_doubles_evidence`, re-exported by `tests/e2e/roles/conftest.py`, which
      reads both doubles' `status()` through `ControlClient` when both targets are
      lane-owned and logs the label and both hash maps, the run's record in the
      lane's log (no lane run writes a JUnit report, so a pytest property would
      reach nothing); otherwise it reads and logs nothing. The four payment
      scenarios (`e2e_vm_payment_deal`, `e2e_vm_payment_purchase`,
      `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal`) use it, so each
      also fails setup by name on an unready lane-owned mediation target. Unit
      (`tests/unit/test_lane_doubles_evidence.py`): the status read through the
      typed client over a mock transport, the logged record, and nothing read for
      each run whose targets are not both lane-owned. Not run end to end in this
      session.
- [x] 5.6 Scenarios: `e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_payment_deal.py`'s
      operator-end case and refund stages run against the mediation double — the
      seller's filing accepted and held per part with no rule, the refund reversing the
      held money; the bare-metal buyer's teardown filing
      (`e2e-tests/tests/e2e/roles/helpers/buyer_purchase_stages.py`) asserts a case
      filed and held per part, not a ruling. (D6)
      Done. The operator-end stage asserts the filing answer's parts each `held`
      with an extension reference, no `ruled` event, and the storefront's lifecycle
      read listing exactly one open extension per snapshot part, each bound to the
      case; the
      refund stage is unchanged. `Purchase10` parses the teardown's printed
      `EndDeliveryProgress` and asserts its case `accepted` with every part held,
      only where the run names a mediation target. The `e2e_vm_payment_deal`
      marker's text follows. Not run end to end in this session.
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
      Evidence: unit, `make test-e2e-unit` — 802 passed, 1 skipped:
      `test_mediation_helper.py` (blank target blocked, lane-owned without a URL
      failed, each missing setting failed by name, the control token required of a
      lane-owned target, unready lane-owned failed and external blocked by name, a
      non-boolean flag refused, the written credential read by the buyer's
      `dispute_config` as bound to the authority with the CA bundle, its token
      resolved from the handed environment), `test_lane_doubles_evidence.py`, and
      `test_domain_stack_configuration.py` at the moved CA path. Release tooling,
      `make test-release-tooling` (unit; renders the stacks with Docker Compose) —
      2690 passed: `test_lane_compose.py` (the mediation double in each lane, no
      host port, after the payments double, its probe trusting the lane CA; none in
      the full stack; both runner sections' CA path at the runner's mount),
      `test_committed_stack_values.py` (the lane registry profile against the
      mediation fixture, the authority's payments token against it, Bob's
      credential against its identity and seller token with its CA path where the
      VM lane binds the lane CA), `test_change_build_and_helm_targets.py`,
      `test_bare_metal_compose.py`. Doubles' suites (unit and library integration):
      `make test-payments-lane-double` 84 passed, `make test-mediation-lane-double`
      72 passed (`test_lane_profile.py` among them). `make -C helm test-render`
      (render and release-topology units): passed. `make -C core/registry
      test-unit`: 139 passed. The application integration line (the VM storefront's
      `test_servicing_unreachable_authority.py`, its own `.invalid` fixture) ran in
      the pre-commit run's every-suite hook, which passed. The end-to-end scenarios
      were not run in this session; validation's pipeline is their evidence.
      End-to-end scenarios covering the section once deployed: `e2e_vm_payment_deal`
      (case and refund stages against the mediation double, lane-double evidence),
      `e2e_vm_payment_purchase` (the buyer's credential written, evidence),
      `e2e_bare_metal_payment_deal` (the teardown filing held per part, evidence),
      `e2e_credits_payment_deal` (evidence) — confirmed.
      Handoff: section 6 extends `helpers/lane_doubles.py` (its control clients
      `payments_controls()` and `mediation_controls(target)` are there) and the
      runner's `payments.control_token`, `mediation.*` settings. `e2e-tests/README.md`
      ("Hosted VM servicing", "Shared payment-scenario configuration") and
      `TESTING.md`'s "The lanes' payments target" paragraphs still describe the
      unanswerable `.invalid` authority and the blocked case stages: 9.9's D6 and D9
      promotions rewrite them. Left for the owner, as section 1 recorded:
      `e2e-tests` now depends on the controls wheel, which `make dist` builds into
      the release wheelhouse as well; this section changes nothing there.
      Checked in the next session, on the evidence above: the section's suites
      passed again in that session's `pre-commit-functional` (every suite,
      `make test-e2e-unit` and `make test-release-tooling` among them) on 4.9's
      working tree, base `1407827ca`. Correction to a level above: the doubles'
      `tests/integration` suites run each double's app in process through a typed
      client, which is application integration, not library integration. Its
      end-to-end lines are validation's: no pipeline has yet run a commit carrying
      section 5 (validation 49 judged `4e6430991`, before it), so the four markers
      above, none skipping for want of a mediation target, await the round's
      validation, which must read their per-scenario results. The `Owed by
      validation:` line is confirmed: `test · test-e2e-unit`; the section's other
      suites run in `tests.yml` jobs other sections already owe
      (`test-deployment-packaging`, both doubles' jobs), except `core/registry`'s
      profile test, whose job validation reads with the rest of `tests.yml`. Section 9 (the release
      wheelhouse) now owns the wheelhouse note.

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
      Done. The objects are `LaneDoubleRules` (`install`, `view` for a rule's
      counts, `resume`, `delete`, which forgets a rule the module removed, and
      `remove_all`) and `LaneDoubleClock` (`advance`, `reset`); each fixture runs
      its cleanup through a context manager, `rules_removed_after` and
      `clocks_reset_after`, so the unit test drives the same cleanup after a body
      that raises. `remove_all` reads both listings before deleting, since a
      deleted rule leaves the listing, attempts every read and deletion through
      `run_cleanup` whichever fails, and fails only after; a `rule_not_found` on
      delete is cleanup's success. Both fixtures
      take `lane_double_controls()`, a blocked skip unless both targets are the
      lane's own (`PAYMENTS.LANE_OWNED`, `MEDIATION.LANE_OWNED`), since only those
      offer controls.
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
      Done as `file_as_buyer` (target, negotiation id, transaction, Agreement,
      store directory, optional `ended_at` and `transport`). It submits through
      the deal-lifecycle kit's `submit_dispute` — the path `BuyerLifecycle.submit`
      takes, without its courtesy hint to the storefront, which would be a
      second side effect — with the adapter in a `DisputeAdapterTable`; the
      operation key names the deal, since the harness files once per deal. The
      credential's identity is the target's, so `MediationClient` refuses an
      Agreement pinning another authority before sending. `e2e-tests` declares
      `arkhai-kit-arkhai-mediation>=0.3.0`; the kit was already in the lock
      transitively, so the relock adds only the declaration's two lines.
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
      Done, with these placements. `host_registry.py` gains each scenario's
      resource id beside its host and pool. `payment_deal.py` holds
      `commit_hosted_deal` (returning a `HostedDeal` with the accepted Agreement)
      and, beside it rather than in `dispute/stages.py`, the reads
      `lifecycle_read`, `commit` and `payment_snapshot`, moved out of
      `test_vm_payment_deal.py` so that module and the dispute modules share one
      definition (`dispute/stages.py` re-exports `lifecycle_read` and wraps the
      snapshot as `snapshot_part` and `snapshot_events`). The commit also writes
      the handoff the shared lease-expiry stages read: the listing, negotiation,
      fulfillment, `settlement_ref` (the negotiation, as a VM lease is keyed),
      the lease view and id, and the resource. `dispute/stages.py` holds
      `DisputeState`, `scenario_driver`, `servicing_step`, `cases`, the commit
      stage `DisputeStage01_HostedDealCommitted` and the closing
      `DisputeStageZ_NoFurtherCase`; `dispute/conftest.py` holds the modules'
      `payments_config`, `mediation_target`, `dispute` and `vm_lifecycle_buyer`
      fixtures. A module still delivering at its end subclasses
      `Stage09c2_ArmTeardownGate` (the purchase's ending arms the gate too)
      through `Stage11b_TeardownCompletion`, then the case-listing stage; since
      `Stage09c2` and `Stage10a` require `_provisioning_storefront_ok`, every
      module also subclasses the readiness stages `Stage00`, `00a`, `00b`, `00c`
      and `00h`. The storefront dispatches a journaled filing only at a
      servicing step or an operator end (`seller.py`, `dispatch_filings`), and
      a lease-ended site report can journal one, so
      `DisputeStageZ_NoFurtherCase` steps servicing once before reading the
      listing; without the step it could not see such a filing, and a later
      module's servicing would dispatch it. Where the buyer filed first, the
      adapter refuses a second delivery-end filing without sending it, so the
      listing alone would not show one; the stage also reads the lifecycle
      read's `filings`, the storefront's own, and requires none. The stages read
      their `DisputeState` prerequisites through `require_state`, so a stage
      after a failed one reports blocked, not failed. The commit stage runs
      `commit_hosted_deal`'s several side effects as one, the body the plan
      moves unchanged out of `test_vm_payment_deal.py`. Beyond the plan:
      `e2e-tests/tests/unit/test_scenario_cleanup_order.py` globbed each lane's
      directory without recursing, so it would have skipped `dispute/`; it now
      recurses. None of the six modules was run in this session: no lane ran,
      and each scenario's assertions about the storefront and the doubles rest
      on reading their code; two fresh-context checks read them against the
      storefront's servicing, the adapter, both doubles and the shared stages,
      and their corrections are in these notes.
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
      Done. The ruling's basis is `operator` (the contract's bases are
      `payee_filed`, `payee_signed` and `operator`, and the claim is the
      payer's); the reverse is a quarter of the part's gross. A stage of its own
      arms the mock teardown gate before the servicing step, which records the
      end and site reports into `lifecycle_purchase` for `Stage12c`. Not run
      (6.3's note).
- [x] 6.5 `dispute/test_operator_discount.py` (D6, D17): commit; the buyer files
      with no rule — each part held; a servicing step — the storefront's answer on
      the record (an `appended` entry by the seller, a contest, since no surrender
      matches); decide through `ControlClient.decide` a partial `reverse` with no
      delivery end and `close: true` — the snapshot reversing that amount, the
      extension lifted, the case `closed`; a servicing step — delivery `active`, no
      end recorded; the deal's ending (6.3).
      Done; the answer is asserted as one `appended` entry whose actor is
      `PAYMENTS.SELLER_ACCOUNT` — that it is a contest rather than a
      concurrence, the plan's wording, is not asserted — and the lift as the
      snapshot part's open `extensions` emptied. Not run (6.3's note).
- [x] 6.6 `dispute/test_lost_filing_answer.py` (D18): commit; install a mediation rule
      `{"operation": "file", "transaction": <the deal's>}` with
      `drop_response_after_commit`; the operator end (`admin_interrupt_deal`) — the
      filing's outcome unknown, the end recorded, delivery `tearing_down`, the rule's
      match counted; delete the rule; the operator end repeated — or, where the
      storefront's servicing retries the filing itself, a servicing step — the adapter
      adopting the one case, the outcome accepted with its case reference; a servicing
      step — the lifecycle read and the case listing each showing exactly one case;
      the teardown to the capacity's release.
      Done with the servicing step as the adopting stage: every servicing watch
      dispatches the deal's pending filings first (`seller.py`, `watch` and
      `dispatch_filings`), so the storefront retries the filing itself, the
      plan's second branch. The stage reads the adoption from the lifecycle
      read's `filings` (one, accepted, naming the double's one case) and the end
      as first recorded; the next servicing step shows one case at both. A
      stage of its own arms the mock teardown gate before the operator end. Not
      run (6.3's note).
- [x] 6.7 `dispute/test_mediation_unavailable.py` (D18): commit; the buyer files with
      no rule; a servicing step answering it; install mediation *unavailable* (`match:
      {}`); a servicing step — the lifecycle read's authority outcome not accepted, as
      the adapter reports an unreachable authority, delivery `active`; delete the rule;
      a servicing step — the authority read accepted again with the case; the deal's
      ending (6.3).
      Done; the unreachable authority is asserted as the lifecycle read's
      outcome `unknown`, which the adapter answers a transport failure with
      (the read polls the watch live), and which respondent discovery, whose
      failed listing the cycle catches, does not change. Not run (6.3's note).
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
      Done; the amounts are an eighth and a quarter of the part's gross, and
      the reverse events are read from the buyer's snapshot, their amounts in
      order and their `effect_id`s distinct. Deleting the drop rule and
      installing *unavailable* are two stages. Not run (6.3's note).
- [x] 6.9 `dispute/test_hold_passed.py` (D18; "A once part's hold is passed"): commit;
      the deal's ending (6.3), before any clock moves; advance both doubles through
      `lane_double_clock` past the part's release instant read from its signed
      snapshot — the snapshot showing the part paid out; the buyer files — the answer
      reporting part 0 `not_held` with reason `paid_out`, and the case listing it
      `closed`, dismissed with nothing held. No storefront step follows the advance;
      the fixture resets both clocks when the module ends.
      Done in two advances where the plan has one: the hosted part's hold is
      `afterStop`, and a once part stops only at its terms end (`end.at`, the
      Agreement start plus its hour), which the lease's ending does not move,
      so its snapshot states no `releaseAt` until then. The first stage
      advances both doubles past `end.at`, after which the snapshot states
      `releaseAt` with the money still held; the second advances past
      `releaseAt` and reads the payout. Each advance is the instant less the
      payments double's perceived now, plus a second. "Dismissed with nothing
      held" is read as every part `not_held` and the case `closed`. Not run
      (6.3's note).
- [x] 6.10 Markers, one per module as every VM scenario has its own:
      `e2e_vm_dispute_ruled_end`, `e2e_vm_dispute_discount`,
      `e2e_vm_dispute_lost_filing`, `e2e_vm_dispute_mediation_unavailable`,
      `e2e_vm_dispute_payments_hold`, `e2e_vm_dispute_hold_passed`, registered with
      their descriptions in `e2e-tests/pyproject.toml` and added to
      `e2e-tests/Makefile`'s `E2E_MODULE`. No order among them is needed (D21).
      Done; the Makefile's comment says why no order is needed: each module
      removes its rules and resets the clocks. Cases, records and transactions
      stay behind, each on that module's own deal; after the hold-passed module
      the payments engine still evaluates that one transaction at its own,
      later instant, which no other module reads.
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
      Evidence: unit, `make test-e2e-unit` — 833 passed, 1 skipped.
      `test_lane_doubles_fixtures.py` (seven cases, each double an in-memory
      control surface behind `ControlClient` on a mock transport, the cleanup
      driven through the context managers the fixtures run): every rule a
      failing body installed deleted on both doubles; a rule the module deleted
      itself not deleted again; a rule left holding a case named after every
      rule is deleted; an unreadable listing still leaving no rule installed;
      the clock advancing both doubles together; both clocks reset after a
      failing body; a double keeping an offset after its reset named.
      `test_mediation_helper.py` (two cases, the mediation kit's
      `MediationContractFake` as the authority behind a mock transport, the real
      client, adapter, `submit_dispute` and `FileEvidenceStore`): the buyer's
      filing posts the contract's `Filing` to `/cases` with the delivery-end
      claim, the buyer's bearer token, the Agreement and transaction, under the
      adapter's key, a 64-character lowercase hex SHA-256 (its derivation is
      the kit's, not asserted here), and is accepted with its case reference
      and parts;
      an unreachable authority leaves the outcome `unknown` with no case. The
      unit suite's existing source checks pass over the six modules:
      `test_scenario_holds.py` (no pause or resume outside the hold helpers),
      `test_scenario_lane_holds.py` (each module in the VM lane's marker
      expression holds every lane hold, which also collects them), and, now that
      it recurses, `test_scenario_cleanup_order.py` (holds released after the
      module's other cleanup; the lane's cleanup set up). No stage-set check
      covers these modules: `test_compute_deal_stages.py` holds named lanes'
      modules to the whole canonical stage order, which a dispute module runs
      only part of.
      `scripts/change-workflow run pre-commit`, run last over the finished
      section: `after-functional-change`, `pre-commit-functional` (`make
      check-packaging`, then every suite) and `pre-commit` (the index, tasks,
      skills and strict OpenSpec checks, then `check-repository`, its citations
      check now resolving every path the plan cites) all passed, exit 0.
      End-to-end: not run in this session; the six markers and
      `e2e_vm_payment_deal` (its commit now `commit_hosted_deal`) are
      validation's pipeline evidence, `make -C e2e-tests test-e2e-vm`.
      End-to-end scenarios covering the section once deployed:
      `e2e_vm_dispute_ruled_end`, `e2e_vm_dispute_discount`,
      `e2e_vm_dispute_lost_filing`, `e2e_vm_dispute_mediation_unavailable`,
      `e2e_vm_dispute_payments_hold`, `e2e_vm_dispute_hold_passed`, and
      `e2e_vm_payment_deal` for the moved commit — confirmed.
      Owed by validation: confirmed as written above.
      Handoff: these six modules have never run, and validation's pipeline is
      their first execution; expect its first failures here, read against the
      code each stage exercises rather than relaxed. The assertions most
      exposed: 6.4's and 6.6's site reports present right after the end (as the
      VM payment scenario's operator end finds them); 6.6's lifecycle read
      `filings` naming the adopted case; 6.8's ruled entry listing both
      reverses unapplied while payments holds it; 6.9's `releaseAt` appearing
      once the part's terms end has passed. A failure that shows the
      storefront files for a lease-expiry end is the stop 6.3 names: report it,
      since the design settled no such filing. The harness files as the buyer
      without the courtesy hint `BuyerLifecycle.submit` sends the storefront;
      the storefront learns of the case by respondent discovery at its next
      servicing step.

## 7. The storefront's mediation check

Delivers the mediation kit's access check and the VM storefront's
`market-storefront check-mediation --origin` (D11, "The storefront checks its mediation
configuration from its own container"). Requirement: deployment-state "A storefront
checks its mediation configuration from its own container".

- [ ] 7.1 `kit/arkhai-mediation`: a mediation access check beside the client
      (`src/market_arkhai_mediation/access_check.py`), modelled on
      `kit/arkhai-payments/src/market_arkhai_payments/access_check.py`: from a role's
      dispute credentials and an origin it selects the credential, resolves its token,
      builds the client with its `ca_bundle_path`, makes one authenticated `respondent`
      read, and returns `ok` with the origin or the failing step — `configuration` (no
      credential for the origin; an unreadable or malformed CA file, before any
      request), `credential` (an unresolvable token, before any request), `transport`,
      or `refused` with the authority's code — every detail fixed text plus public
      configuration. It asserts nothing about the read's answer. (D11)
- [ ] 7.2 `domains/vms/storefront/src/market_storefront/cli.py`:
      `check-mediation --origin <authority>` loads configuration as `serve` does, calls
      the kit check, prints one JSON line with no credential, and exits 0 on `ok`, 1 on a
      failed step, 2 on a malformed origin, as `check-payments` does. (D11)
- [ ] 7.3 Verification.
      Unit: `kit/arkhai-mediation/tests` — each failing step and `ok` against an
      injected transport, including an empty and a full respondent listing both `ok`.
      Application integration: `domains/vms/storefront/tests/unit/cli/test_check_mediation.py`
      beside `test_check_payments.py` — the command's output and exit codes through its
      configuration and transport seams.
      End-to-end: none in the Compose lanes (D9); section 8's Helm test runs it.
      Owed by validation: `tests.yml`, jobs `test · test-kits` and `test · test-domains`
      — both pass.

## 8. The local Helm release

Delivers the `mediation-lane-double` subchart, the release's recommendation and copied
credential, and the storefront chart's mediation-check test run by Helm validation
(D11). Requirements: deployment-state "Payment credentials stay with their owning
process", "The local release rehearses a deployment's payments interface", "A storefront
checks its mediation configuration from its own container".

- [ ] 8.1 Subchart `helm/charts/mediation-lane-double` modelled on
      `helm/charts/payments-lane-double`: Service `mediation-double`, TLS from a named
      Secret or the image's files, disabled by default; `helm/Chart.yaml`,
      `helm/values.yaml` and `helm/values.schema.json` declare it; `helm/local-values.yaml`
      enables it; `helm/bare-metal-release-values.yaml` disables it, as for the payments
      double. (D11)
- [ ] 8.2 The release's registry recommends the mediation double's identity
      (`helm/local-values.yaml`); `helm/scripts/topology-secrets.sh` rewrites the copied
      dispute credential's `ca_bundle_path` to the storefront chart's CA file, and a test
      holds it to `storefront.caBundleFile`. (D11)
- [ ] 8.3 Storefront chart test pod `helm/charts/storefront/templates/tests/mediation-check-test.yaml`,
      rendered from the Deployment's helpers for an agent with a dispute credential and
      `tests.mediationOrigin` (values and `values.schema.json`), running
      `market-storefront check-mediation --origin` directly with the Deployment's image,
      configuration and secrets mounts, identity credential and CA bundle mount, without
      the data volume, probes or ZeroTier capabilities and device; the local release
      sets Bob's `tests.mediationOrigin` to `https://mediation-double:8443`. (D11)
- [ ] 8.4 `scripts/validate_slice.py` runs every `-mediation-check` pod the release's
      hooks render as it runs the payments checks, counting each passed only on its
      pod's exit status of 0 and keeping its log. (D11)
- [ ] 8.5 Verification.
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

## 9. The release wheelhouse

Delivers a release wheel set without the distribution only tests depend on (D20).
Files: the root `Makefile`, `scripts/tests/`.

- [ ] 9.1 Root `Makefile`: a target building the release set, whose prerequisites are
      every current prerequisite of `dist` but `dist-lane-double-controls`; `dist`
      builds that target and `dist-lane-double-controls`, so the lanes, CI and
      validation, whose images install the controls wheel from `.dist`, build what
      they build today; `dist-release` builds the release set alone. `dist-ci` and
      `.github/workflows/release.yml` are unchanged: the workflow already runs
      `make dist-clean` before `make dist-release`. (D20)
- [ ] 9.2 Verification.
      Unit (`make test-release-tooling`): a case in
      `scripts/tests/test_change_build_and_helm_targets.py`, reading `make -n` as
      that file does, holds that `dist-release` builds no `lane-double-controls`
      wheel and builds every other wheel `dist` builds, and that `dist` and `dist-ci`
      still build it. Then `make check-packaging`.
      End-to-end: none; the lanes build `dist`, which is unchanged, and no validation
      part runs the release workflow.
      Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — the
      release-tooling suite passes with the new case.

## 10. Closeout

Closeout changes documentation only; a part needing a code edit returns the change to
implementation. In the order of `openspec/README.md#plan-closeout-requirements`:

- [ ] 10.1 Comment hygiene: run `make check-comment-hygiene`; any finding, or a comment
      this change added that still needs rewriting, returns the change to implementation.
- [ ] 10.2 Import placement: check the imports sections 1–9 added; one that should move
      to module level returns the change to implementation.
- [ ] 10.3 Documentation compliance: re-check D1–D21 against `openspec/README.md`'s
      placement rules — the doubles' behaviour in `test-compatibility`, configuration in
      `settlement-configuration` and `deployment-state`, tooling in `tools/`, the
      controls scenarios in `e2e-tests/README.md`, the release wheelhouse in
      `docs/development/RELEASING.md`, and no future state in permanent documents (the
      lane-wide clock, the buyer filing command and the meaning of a prepared delivery
      end belong to the roadmap).
- [ ] 10.4 Narrative compression: shorten completed task notes to final behaviour,
      validation evidence, deferred work and destinations; move any rationale not already
      in `design.md` there first.
- [ ] 10.5 Roadmap currency, `docs/development/ROADMAP.md` Goal 8: the current-state
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
- [ ] 10.6 Campaign index currency, `openspec/changes/README.md`: this row's status and
      notes; the Goal 8 dependency graph is unchanged. Record the dispositions and run
      `make check-change-index`.
- [ ] 10.7 Packaging: `make check-packaging`, then
      `make check-architecture-change CHANGE=add-arkhai-payments-lane-double`; resolve
      every failure; this change owns no architecture exception.
- [ ] 10.8 End-to-end pipeline: record the pipeline run, its result, and the scenarios
      exercising this change — `e2e_vm_payment_deal`, `e2e_vm_payment_purchase`,
      `e2e_vm_dispute_ruled_end`, `e2e_vm_dispute_discount`,
      `e2e_vm_dispute_lost_filing`, `e2e_vm_dispute_mediation_unavailable`,
      `e2e_vm_dispute_payments_hold`, `e2e_vm_dispute_hold_passed`,
      `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` — and Helm
      validation's `-mediation-check` pod; a run blocked for a reason outside this
      change is recorded as a blocker with its owner, its gated validations unrun.
- [ ] 10.9 Promotion, and the design-promotion record:
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
        where it describes `check-payments`.
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
        depend on, while `make dist` adds `lane-double-controls` for the lanes and CI.
      - D21: `e2e-tests/README.md`, "VM dispute controls" (one module per scenario,
        and why no order among them is needed).
      - The three deltas (`test-compatibility`, `settlement-configuration`,
        `deployment-state`) are written to `openspec/specs/` by the archive in 10.11;
        none of the three capabilities has an `index.md`, and `openspec/specs/README.md`
        needs no entry, since no capability or companion is added.
- [ ] 10.10 Documentation citations: `make check-doc-citations CHANGE=add-arkhai-payments-lane-double`,
      resolving every match, then
      `scripts/change-workflow openspec validate add-arkhai-payments-lane-double --strict`.
- [ ] 10.11 Archival: `scripts/change-workflow openspec archive add-arkhai-payments-lane-double -y`,
      merging the three deltas, and link the index row to the archived directory.

## Design promotion record

Filled in at closeout (10.9), naming each decision's permanent location.
