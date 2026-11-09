# Tasks — in-lane mediation double and controls for both doubles

Replanned against the reviewed design (design reviews 15 and 26 and their triage). The
earlier draft predated the design's reverification and no task of it was checked; it
is replaced whole. Decisions are `design.md`'s D1–D13; requirements are the deltas
under `specs/`. New paths below are planned deliverables. The tools under `tools/`
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

- [ ] 1.1 Create `tools/lane-double-controls` (import `lane_double_controls`):
      `pyproject.toml`, `uv.lock`, `Makefile` (`test`, `reinit`, `typecheck`, `check-tls`),
      `README.md`, `src/lane_double_controls/`, `tests/unit/`, `tests/integration/`, built
      into the wheelhouse by `make dist` like every internal distribution. Add root
      `make test-lane-double-controls`, put it in `make test`, and add it to
      `.github/workflows/tests.yml`'s matrix (`scripts/tests/test_tests_workflow.py`
      holds the matrix to `make test`). (D4, "Where the contract lives")
- [ ] 1.2 Models in `src/lane_double_controls/models.py`: a rule (`rule_id`, required
      `match`, and one of refusal `{status, code}`, `drop_response_after_commit`,
      `unavailable`, or, for mediation, filing-answer override or ruling
      `{basis, delivery_end, effects, close}` with optional `pause_before_effects`);
      operator decide and close; clock advance and reset; funding; signer rotation; the
      rule listing with matched and waiting counts; the case listing; the status
      (perceived now, installed contract hashes); and the one error body
      `{"code", "message"}`. An *unavailable* rule requires `match: {}` (26 F2). Ruling
      and effect shapes validate against the vendored mediation contract through
      `market_arkhai_mediation.contract`. (D2, D3, D4's table and "Control semantics")
- [ ] 1.3 Route declarations and a typed sync client (`routes.py`, `client.py`) over
      httpx, authenticated by the control bearer token and trusting a configured CA
      bundle, raising one typed error carrying the control code. Routes live under
      `/test/` on each double's API port. (D4, "Scope and access")
- [ ] 1.4 The transport-fault ASGI middleware (`middleware.py`): it applies only to the
      contract's API routes, never to `/test/` routes; *unavailable* starts and then
      abandons every API response; *drop after commit* lets the matching request
      complete in the application, then starts and abandons its response. A matched
      request is counted in the rule listing. (D4, "Transport faults live in the
      doubles", "How a response is abandoned", "Control routes are never faulted")
- [ ] 1.5 Move the lane CA generator and certificates from
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
- [ ] 1.6 Verification.
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

## 2. The payments double's controls, perceived clock and claimed surface

Delivers the payments double's control routes, perceived clock and status, the
middleware mounted, and its suite claiming the rate and hold surface (D2, D3, D4, D10).
Requirements: "The in-lane payments double mirrors the service and proves its engine's
surface", "Each lane double reads a perceived clock the scenario advances", "Lane double
controls are typed deterministic steps".

- [ ] 2.1 `tools/payments-lane-double`: declare `lane-double-controls`; a perceived clock
      (wall time plus a forward-only offset, reset to zero) injected into
      `PaymentsAuthority` in place of `wall_clock` (`src/payments_lane_double/app.py`);
      mount the middleware on the API routes. (D2, D4)
- [ ] 2.2 Control routes under `/test/`, authenticated by a fixture control token added
      to `fixtures/accounts.toml` and labelled a public development value: rules
      (install, list, delete) for refusals with a published `ApiError` status and code,
      drop after commit and *unavailable*; clock advance and reset; fund an account
      (`PaymentsAuthority.fund`, `404 account_not_found` for an account outside the
      directory); rotate the receipt signer to a second committed fixture seed; status
      reporting the perceived now and the installed contract hashes from
      `market_arkhai_payments.contracts`. Refusals follow D4's table. (D2, D3, D4)
- [ ] 2.3 Suite coverage of the rate and hold surface through the payments kit's
      `PaymentsClient` over an ASGI transport, with clock advances: rate parts and
      payee-only `start`; `stop` with notice and the earliest pending stop taking effect
      when the perceived clock reaches it; per-part `end`; funding exhaustion at
      funded-through; `afterStop` holds releasing after the clock passes them; partial
      `reverse` before and after a stop; `extend` and `lift` with `hold_not_extendable`,
      `extension_not_found` and `extension_closed`. (D10)
- [ ] 2.4 Update `tools/payments-lane-double/README.md`'s claim from the once-only
      surface to the rate and hold surface, and describe the controls and clock. (D10;
      the README is the double's own documentation, maintained with its code)
- [ ] 2.5 Verification.
      Unit (`tests/unit`): the clock moves only forward, reset returns to wall time;
      control authentication refuses a missing or wrong token.
      Library integration (`tests/integration/test_double.py`, `test_controls.py`):
      2.3's surface; a refusal rule answered to the kit client with its status and code
      and counted in the listing; funding visible through `get_balance`; a drop after
      commit on an approval retried under the same key returns the original receipt with
      no second debit; *unavailable* refuses API routes while `/test/status` answers;
      signer rotation signs later snapshots with the second key; status hashes equal
      the kit's installed contract hashes.
      End-to-end: none in this section; section 5's lanes run this double.
      Owed by validation: `tests.yml`, job `test · test-payments-lane-double` — the
      double's `make test` passes with the new suites.

## 3. Mediation trust through configuration

Delivers `[[DisputeCredential]].ca_bundle_path` and the mediation client's CA argument,
passed by all four lifecycle compositions (D8). Requirement: settlement-configuration
"Dispute credentials are bound by identity and no template ships an authority".

- [ ] 3.1 `kit/deal-lifecycle`: `DisputeCredential` (`configuration.py`) gains an
      optional `ca_bundle_path`, refused when empty, as the payments section refuses an
      empty one; it appears in no option, Agreement or status. (D8)
- [ ] 3.2 `kit/arkhai-mediation`: `MediationClient` (`client.py`) takes an optional CA
      bundle and uses it as its verification context
      (`ssl.create_default_context(cafile=…)`); absent means default trust; no process
      state changes. Update `kit/arkhai-mediation/README.md`'s client section. (D8)
- [ ] 3.3 Pass the credential's `ca_bundle_path` in every construction:
      `domains/vms/storefront/src/market_storefront/deal_lifecycle.py`,
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`,
      `domains/vms/buyer/src/arkhai_vms_buyer/lifecycle.py`,
      `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/lifecycle.py`. The
      storefronts' generated values schemas keep refusing `[[DisputeCredential]]` whole
      in public chart configuration; regenerate them if the model change alters them.
      (D8)
- [ ] 3.4 Verification.
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

## 4. The mediation double

Delivers `tools/mediation-lane-double`: the dispute authority's API mechanics,
programmed decisions, effect application, perceived clock and controls (D1, D2, D3,
D4, D7). Requirements: "Lanes run a mediation double that answers from programmed
rules", "Lane double controls are typed deterministic steps", "Each lane double reads a
perceived clock the scenario advances".

- [ ] 4.1 Create `tools/mediation-lane-double` (import `mediation_lane_double`):
      `pyproject.toml` declaring the mediation and payments kits and
      `lane-double-controls`, `uv.lock`, `Makefile`, `Dockerfile` building image
      `arkhai:mediation-lane-double` from the wheelhouse and the committed lock with its
      leaf key generated from `tools/lane-double-controls/tls/`, `README.md`,
      `src/mediation_lane_double/` with a framework-free service and thin FastAPI
      routes, as the payments double is built. Root `make test-mediation-lane-double`
      in `make test` and `tests.yml`'s matrix; root `make build-mediation-lane-double`;
      add the image to `scripts/change_namespace.py`'s image list. (D7)
- [ ] 4.2 Fixtures in `fixtures/`, every value labelled a public development value,
      never for a public network: the authority identity (origin
      `https://mediation-double:8443`, account `00000000-0000-4000-8000-0000000000d1`, a
      record key from a committed seed), bearer tokens mapping the buyer and seller
      payment accounts, the authority's payments token, and the control token. (D5, D7)
- [ ] 4.3 API mechanics against the vendored contract: `POST /cases`, `POST /append`,
      `GET /cases/{ref}`, `GET /record`, `GET /respondent`; bearer authentication;
      schema validation; idempotency and `idempotency_conflict`; either party appending
      evidence, only `mandate.to` concurring; the closed-case refusal; the signed
      per-agreement record with sequences and cursors, an empty signed page for a known
      agreement with no cases, the contract's refusal for an unknown agreement or
      reader. (D1, "Real mechanics")
- [ ] 4.4 Filing protection through the payments kit's client as the authority's
      account: `extend` per part; only `hold_not_extendable` reports `not_held`, its
      reason classified from the part's signed snapshot amounts — `paid_out`, else
      `reversed`, else `nothing_held`; every other refusal and every transport failure
      answers `error` with `protection_incomplete`, completed by a same-key retry; a case
      whose every part is `not_held` is dismissed with `nothing_held`. (D1, "Extension
      results", "A not-held part's reason")
- [ ] 4.5 Programmed decisions: rules matching `operation`, `filer`, `kind`, `cause` and
      `transaction`; filing-answer overrides; a ruling recorded in the signed record,
      its effects applied as payment events with stable effect keys and the case
      reference, then only that case's extensions lifted; `pause_before_effects` and
      resume; an incompletely applied ruling resumed without a duplicate effect; operator
      decide and close on an open case; no ruling without a rule; no signature, digest or
      guard verification. (D1, "Programmed")
- [ ] 4.6 Controls and clock: the shared middleware on the API routes; `/test/` routes
      for rules, decide, close, the case listing by transaction, the rule listing, clock
      advance and reset, and status reporting the perceived now and the installed
      mediation contract hashes; refusals per D4's table. Record times come from the
      perceived clock. (D2, D3, D4)
- [ ] 4.7 `README.md`: what the double serves, its deviation from its producer (a case
      the authority would rule mechanically is ruled only by a rule), what its results
      establish and what they do not. (D1; the double's own documentation)
- [ ] 4.8 Verification.
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
      answering; a clock advance past a once hold yielding `not_held` with `paid_out`.
      End-to-end: none in this section; the HTTP hop to the payments double is first
      exercised in section 5.
      Owed by validation: `tests.yml`, job `test · test-mediation-lane-double` — the
      double's `make test` passes.

## 5. Lane wiring and the existing payment scenarios

Delivers the mediation double in all three lanes, the registries recommending it, the
runner's lane-owned `MEDIATION` target, the buyer's credential, and the VM case stages
and bare-metal filing running against it (D3, D5, D6, D7, D9). Requirements: "Lanes run
a mediation double that answers from programmed rules", "A lane-owned mediation target
fails rather than skips", "The in-lane payments double mirrors the service and proves its
engine's surface", "A compute buyer purchase settled through Arkhai payments runs in
each compute lane against the lane doubles".

- [ ] 5.1 `compose.payments-double.yml` adds service `mediation-double`
      (`arkhai:mediation-lane-double`, no host port, healthcheck trusting the lane CA
      alone); the root `Makefile`'s lane build targets build its image. (D9)
- [ ] 5.2 The payments double's `fixtures/accounts.toml` gives `…00d1` a token, which the
      mediation double's fixture restates; retire
      `tools/payments-lane-double/fixtures/dispute-authority.toml` and its tests;
      `dev-env/registry/config-payments-lane.env` recommends the mediation double's
      identity. Update `core/registry/tests/unit/test_config_profiles.py` and the stack
      value tests that held the `.invalid` identity. (D5, D7, D9)
- [ ] 5.3 `dev-env/identities/bob.storefront.secrets.toml`'s `[[DisputeCredential]]`
      carries the mediation double's seller token and `ca_bundle_path`, and the lane
      overlays mount the CA where that path names. (D8, D9)
- [ ] 5.4 Runner: `e2e-tests/config/config-payments-lane.yml` gains `mediation` —
      `service_url`, `lane_owned: true`, `ca_bundle_path`, `buyer_api_key`,
      `api_key_env`, `control_token`; `e2e-tests/tests/e2e/roles/helpers/mediation.py`
      fails setup by name on an unready lane-owned target and keeps the blocked skip for
      an external one; the buyer configuration writer emits the buyer's
      `[[DisputeCredential]]` with `api_key_env` and `ca_bundle_path`, and the harness
      hands the buyer's mediation token to each `market` process under that variable,
      writing it into no runner environment. Declare `lane-double-controls` in
      `e2e-tests/pyproject.toml` and relock. Tests hold every restated value to its
      fixture. (D9)
- [ ] 5.5 Lane-double evidence: a payment scenario records the label *lane doubles* and
      both doubles' installed contract hashes, read from their status through the typed
      client. (D3)
- [ ] 5.6 Scenarios: `e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_payment_deal.py`'s
      operator-end case and refund stages run against the mediation double — the
      seller's filing accepted and held per part with no rule, the refund reversing the
      held money; the bare-metal buyer's teardown filing
      (`e2e-tests/tests/e2e/roles/helpers/buyer_purchase_stages.py`) asserts a case
      filed and held per part, not a ruling. (D6)
- [ ] 5.7 Verification.
      Unit: `e2e-tests/tests/unit/test_mediation_helper.py` (lane-owned failure,
      external blocked skip, missing settings), the buyer configuration writer's
      credential, the value-to-fixture tests, `scripts/tests/test_lane_compose.py` for
      the overlay's new service.
      Application integration: `domains/vms/storefront/tests/integration/test_servicing_unreachable_authority.py`
      keeps its own unreachable-authority fixture and still passes.
      End-to-end: `e2e_vm_payment_deal` and `e2e_vm_payment_purchase` in
      `make -C e2e-tests test-e2e-vms`, `e2e_bare_metal_payment_deal` in
      `test-e2e-bare-metal`, `e2e_credits_payment_deal` in `test-e2e-apicredits`; none
      skips for want of a mediation target.
      Owed by validation: `tests.yml`, job `test · test-e2e-unit` — the harness unit
      suite passes.

## 6. The VM controls module

Delivers one VM-lane module of once-only deals proving the lane's dispute wiring through
D6's six journeys, with the clock fixture resetting both doubles (D2, D6). Requirements:
"A controls scenario proves the lane's dispute wiring in the VM lane", "Each lane double
reads a perceived clock the scenario advances", "Lane double controls are typed
deterministic steps".

- [ ] 6.1 Harness helpers in `e2e-tests/tests/e2e/roles/helpers/lane_doubles.py`: a rule
      fixture whose finaliser deletes its rules and asserts none waits, and a clock
      fixture advancing both doubles together whose finaliser resets both whatever the
      module's outcome. (D2, D4)
- [ ] 6.2 Module `e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_dispute_controls.py`,
      marker `e2e_vm_dispute_controls` registered in `e2e-tests/pyproject.toml` and added
      to `e2e-tests/Makefile`'s `E2E_MODULE`, holding the storefront's loops and
      advancing each transition, in this order: (1) a programmed ruling with a delivery
      end and a reverse, the reverse visible at the payments double and the storefront
      ending delivery after observing it; (2) an operator decision with a partial reverse
      and no delivery end, the deal running; (3) a lost filing response, the dispute
      adapter adopting the one case; (4) mediation unavailable, servicing reporting the
      authority unreachable while the deal runs; (5) payments unavailable between two
      programmed effects, the ruling incompletely applied and then completed with no
      duplicate effect; (6) a clock advance past a once part's hold, the payout visible
      and a later case reported `not_held` with `paid_out` and dismissed. (D6)
- [ ] 6.3 Verification.
      Unit: `e2e-tests/tests/unit` cases for the fixtures' finalisers (rules deleted,
      clock reset after a failure).
      End-to-end: `e2e_vm_dispute_controls` in `make -C e2e-tests test-e2e-vms`; after
      it, both doubles report wall time, and the lane's later modules pass.
      Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes.

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

## 9. Closeout

Closeout changes documentation only; a part needing a code edit returns the change to
implementation. In the order of `openspec/README.md#plan-closeout-requirements`:

- [ ] 9.1 Comment hygiene: run `make check-comment-hygiene`; any finding, or a comment
      this change added that still needs rewriting, returns the change to implementation.
- [ ] 9.2 Import placement: check the imports sections 1–8 added; one that should move
      to module level returns the change to implementation.
- [ ] 9.3 Documentation compliance: re-check D1–D13 against `openspec/README.md`'s
      placement rules — the doubles' behaviour in `test-compatibility`, configuration in
      `settlement-configuration` and `deployment-state`, tooling in `tools/`, and no
      future state in permanent documents (the lane-wide clock belongs to the roadmap).
- [ ] 9.4 Narrative compression: shorten completed task notes to final behaviour,
      validation evidence, deferred work and destinations; move any rationale not already
      in `design.md` there first.
- [ ] 9.5 Roadmap currency, `docs/development/ROADMAP.md` Goal 8: the current-state
      paragraph says the case stages run against the mediation double; this change's gap
      row closes; convergence's row drops revised-case netting; the hosted
      dispute-authority row records D5 (no guard, inert by construction); a new unowned
      gap records the lane-wide perceived clock for storefronts, sites and the buyer half,
      naming convergence rows 6 and 7. Record it in the promotion record.
- [ ] 9.6 Campaign index currency, `openspec/changes/README.md`: this row's status and
      notes; the Goal 8 dependency graph is unchanged. Record the dispositions and run
      `make check-change-index`.
- [ ] 9.7 Packaging: `make check-packaging`, then
      `make check-architecture-change CHANGE=add-arkhai-payments-lane-double`; resolve
      every failure; this change owns no architecture exception.
- [ ] 9.8 End-to-end pipeline: record the pipeline run, its result, and the scenarios
      exercising this change — `e2e_vm_payment_deal`, `e2e_vm_payment_purchase`,
      `e2e_vm_dispute_controls`, `e2e_bare_metal_payment_deal`,
      `e2e_credits_payment_deal` — and Helm validation's `-mediation-check` pod; a run
      blocked for a reason outside this change is recorded as a blocker with its owner,
      its gated validations unrun.
- [ ] 9.9 Promotion, and the design-promotion record:
      - D1: `openspec/specs/test-compatibility/architecture.md`, a new "The in-lane
        mediation double" section after "The in-lane payments double";
        `docs/development/ARCHITECTURE.md`, "Testing strategy", and
        `docs/development/TESTING.md`, "Private Service Dependencies" — the
        programmed-decision principle; `tools/mediation-lane-double/README.md` (written
        in section 4).
      - D2: `docs/development/TESTING.md`, "The discipline every scenario follows",
        replacing its statement that no control moves the clock with the perceived-clock
        rule as current state, and `docs/development/ARCHITECTURE.md`, "Testing
        strategy"; the roadmap gap of 9.5.
      - D3: `openspec/specs/test-compatibility/architecture.md`, "Payment evidence
        ownership".
      - D4: `tools/README.md`, "Lane collaborators" (the controls package the
        collaborators and the harness import, and the mediation double);
        `tools/lane-double-controls/README.md` (section 1); `docs/development/TESTING.md`,
        "Private Service Dependencies".
      - D5: `openspec/specs/test-compatibility/architecture.md`, "The in-lane mediation
        double"; the roadmap row of 9.5.
      - D6: `e2e-tests/README.md`, "End-to-end lanes" (the controls module and its
        marker).
      - D7: `tools/README.md`, "Lane collaborators"; `dev-env/identities/README.md`'s
        table (the mediation fixture tokens, the retired `.invalid` authority).
      - D8: `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Dispute authority
        preferences"; `kit/arkhai-mediation/README.md` (section 3).
      - D9: `docs/development/TESTING.md`, "Private Service Dependencies", and the
        paragraph on the lanes' doubles under "4. System Integration Tests
        (End-to-End)"; `e2e-tests/README.md`, "Shared payment-scenario configuration".
      - D10: `tools/payments-lane-double/README.md` (section 2).
      - D11: `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Release topology" (the local
        release paragraph and the `make helm-topology-secrets` bullet);
        `docs/development/TESTING.md`, the Helm validation paragraph under "4. System
        Integration Tests (End-to-End)" and "Chart Render Tests";
        `docs/operator-handbook.md`, "Payments access"; `docs/development/VALIDATION_RUNBOOK.md`,
        where it describes `check-payments`.
      - D12, D13: no permanent destination.
      - The three deltas (`test-compatibility`, `settlement-configuration`,
        `deployment-state`) are written to `openspec/specs/` by the archive in 9.11;
        none of the three capabilities has an `index.md`, and `openspec/specs/README.md`
        needs no entry, since no capability or companion is added.
- [ ] 9.10 Documentation citations: `make check-doc-citations CHANGE=add-arkhai-payments-lane-double`,
      resolving every match, then
      `scripts/change-workflow openspec validate add-arkhai-payments-lane-double --strict`.
- [ ] 9.11 Archival: `scripts/change-workflow openspec archive add-arkhai-payments-lane-double -y`,
      merging the three deltas, and link the index row to the archived directory.

## Design promotion record

Filled in at closeout (9.9), naming each decision's permanent location.
