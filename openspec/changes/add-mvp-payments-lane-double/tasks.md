# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/12-design.triage.md`. Every implementation task answers to a decision D1–D12, a
delta requirement under `specs/`, or a repository obligation cited at the task:
`openspec/README.md#plan-closeout-requirements`, the task rules in
`openspec/config.yaml`, `docs/development/TESTING.md`'s level definitions,
`docs/development/BUILD_AND_PACKAGING.md`, and `AGENTS.md`.

Test levels follow `docs/development/TESTING.md`: unit; library integration (a kit or
tool against its real collaborators in process, such as the real `PaymentsClient`
against the double's app through an in-process transport); application integration (an
in-process app through its typed clients); chart render tests; and system (the
`e2e-tests` markers, and the local release's `helm test`).

Order: 1 → 5, then the closeout, 6. Section 1 adds the kit's balance read and the
payments check function (D5, D12); section 2 builds the double on it (D1, D3, D4, D8);
section 3 adds the storefront CLIs' `check-payments` and the VM storefront's
unreachable-mediation proof (D2, D12); section 4 wires the three Compose lanes (D2, D6,
D7, D9); section 5 does Helm (D3, D11, D12). Each section needs only the sections before
it. No dependency gates implementation. `qualify-real-provisioning-by-scenario` waits on
this change's implementation. Permanent specifications, companions, `ARCHITECTURE.md`,
`TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, the operator handbook, `tools/README.md` and
the roadmap are written at closeout; a section writes only the package documentation its
code needs (the double's README, the kit's README entry).

Fixture discipline for every section (`AGENTS.md`, "Test fixtures and local development
configuration"; D4): every account, token, key, seed and certificate added is a
well-known deterministic development value, labelled in a comment where it is defined as
public and never for a public network; the pinned dispute authority's record key is the
one exception to "deterministic from a seed" (D4) and has no usable private half.

## 1. The kit's balance read and payments check

Delivers `PaymentsClient.get_balance`, the engine's balance view and the fake's parity
(D5; market-composition delta "The payments kit reads an account's own balance"), and
the payments check function the storefront CLIs call (D12; deployment-state delta "A
storefront checks its payments access from its own container", its kit half).

Files: `kit/arkhai-payments/src/market_arkhai_payments/{client.py, fixtures/authority.py,
fixtures/payments_client.py, __init__.py}`, a new
`kit/arkhai-payments/src/market_arkhai_payments/access_check.py`;
`kit/arkhai-payments/tests/{test_client.py, test_balance_view.py (new),
test_access_check.py (new)}`, and the fake's existing tests; `kit/arkhai-payments/README.md`;
`kit/arkhai-payments/pyproject.toml`; every lock `make lock` rewrites.

- [x] 1.1 `PaymentsClient.get_balance(account) -> Balance` (D5): validate `account` as
  `AccountId`, call `GET /balances/{account}`, return the generated `Balance` model
  through `_validated`, and raise `PaymentsAPIError` with the service's code on a
  refusal. Export nothing new from `__init__` beyond what callers need (`Balance` is
  already a generated model). Unit (`tests/test_client.py`, with an `httpx.MockTransport`):
  the path and bearer header, a valid body parsed, a 403 `caller_not_authorized` raised
  with that code, a malformed body refused as a protocol error, and an invalid account
  refused before any request.
  Unit, `tests/test_client.py` (four new cases, the real client over
  `httpx.MockTransport`): pass. `Balance` is not exported from `__init__`; callers take it
  from `market_arkhai_payments.models`. An invalid account raises pydantic's
  `ValidationError`, a `ValueError`, before any request. The bearer-key cases use a
  loopback host (`https://127.0.0.1`) because the client sets `trust_env` from the host
  alone: a non-loopback test origin would let an ambient `HTTPS_PROXY` mount a proxy
  transport ahead of the mock. These cases prove parsing and refusal handling over a
  mocked boundary; the client against a serving app is 2.5's library integration.
- [x] 1.2 `PaymentsAuthority.balance(account)` (D5). First advance every transaction
  whose mandate names the account as `from` or `to`, with `advance(transaction,
  refill=False)`, as `snapshot()` does. Then return `available` from the engine's balances
  for the account (`{}` for an unknown account) and `held` for parts where the account is
  the payee: one timed entry per part and distinct maturity among its held lots (`address`
  `hold:<transaction>:<part>:<releaseAt in Unix seconds>`, `balance` the sum of those lots,
  `releaseAt` that maturity as the snapshot formats it), and one
  `hold:<transaction>:<part>:until` entry for lots with no maturity yet, `until` `lift`
  when extensions are open unless an until-stop hold awaits its stop, otherwise `stop`.
  `from`, `to`, `asset`, `fee` and `transaction`/`part` come from the mandate. Return the
  generated `Balance`. Unit (`tests/test_balance_view.py`):
  - a payer after approval: `available` reduced by the gross, `held` empty;
  - a payee with one once part held for `P7D`: one timed entry with its `releaseAt`;
  - the before-and-after-maturity case the delta names: a read one second before a once
    hold matures lists it held; a read one second after, with no other operation between,
    lists nothing held for it and the payee's earnings net of fee in `available`;
  - a rate part with two earned periods under `hold.for`: two timed entries with
    distinct maturities;
  - an after-stop hold before its stop: one `until: stop` entry; an open extension with no
    end: `until: lift`;
  - an account the engine has never seen: `{"available": {}, "held": []}`.

  Unit, `tests/test_balance_view.py` (eight engine cases, the real `PaymentsAuthority`
  with an injected clock, approvals through its own `approve` so the payer is debited):
  pass. Beyond the plan's list it covers an after-stop hold awaiting its stop under an
  open extension, which reads `until: stop`, and a part seeded with a zero-gross receipt,
  which lists no empty hold. `releaseAt` uses one `_release_at` helper that
  `snapshot()` now shares, so the two cannot format a maturity differently; the
  snapshot's bytes are unchanged, as 1.6's vector replay shows. The rate case starts the
  part, which also refills a third period, and reads at two periods plus a second: two
  timed entries, the unearned third period outside `held`.
- [x] 1.3 `FakePaymentsClient.get_balance(account)` delegates to `engine.balance` (D5),
  recorded in `calls` like its other methods and subject to `unavailable`. Unit: in the
  fake's tests, a served approval then a balance read returns the engine's view, and an
  unavailable fake raises the transport error.
  Unit, `tests/test_balance_view.py` (two cases): pass. The kit has no test module of
  the fake's own (its cases live with the stages that use it), so its two cases sit
  beside the view they delegate to. The approval is the fake's convenience `approve`,
  which seeds the engine through `load` without a debit.
- [x] 1.4 The payments check function (D12), in `access_check.py`:
  `check_payments_access(config: ArkhaiPaymentsConfig, account: str, *, environment=None,
  transport=None) -> PaymentsAccessOutcome`. It builds the client through
  `payments_client_for_owner(config, account, …)`, calls `get_balance(account)`, and
  returns a frozen outcome with `outcome` (`ok` or `failed`), `service_url`, `account`, and
  on success the account's asset names and held-entry count; on failure the `step` —
  `configuration` (no `service_url`, a disabled or invalid section), `credential` (the
  `api_key_env` variable unset or empty), `transport` (`PaymentsTransportError`, which a
  TLS verification failure raises), or `refused` with the service's code — and a detail
  that never contains a credential. A method renders the outcome as the one JSON line D12
  shows. Unit (`tests/test_access_check.py`, with `MockTransport` and an injected
  environment): each outcome and step, and that no rendered outcome contains the API key
  even when the key appears in an exception's text.
  Unit, `tests/test_access_check.py` (the real check, client and
  `payments_client_for_owner` over `httpx.MockTransport` with an injected environment):
  pass. As built, differing from the plan's wording:
  - `config` is `ArkhaiPaymentsConfig | Mapping | None`: `None` (no section) and a raw
    section that fails validation are `configuration` outcomes, so each CLI passes
    whatever its settlement root holds under `arkhai_payments` and needs no handling of
    its own. An invalid section's detail lists each error's location and pydantic type
    code only, never a message or input, since a key pasted under the wrong name would
    otherwise be echoed.
  - The refusal is `step: "refused"` with a separate `code` field, not one `refused
    <code>` string; the JSON line carries `code` beside `step`.
  - A `PaymentsProtocolError` (an answer outside the published contract, such as a
    non-payments server at the URL) is a `transport` step with its own detail: the kit's
    `PaymentsTransportError` already means "could not be reached or its response could
    not be read", and the four steps D12 names have no fifth.
  - A key variable holding a CR or LF is a `credential` failure, checked before the
    client is built, since `PaymentsClient` would refuse it as a header value.
  - A malformed `account` raises `ValueError` rather than producing an outcome: it is
    the caller's argument, not the role's payments access.
  - Every `detail` is fixed text plus public configuration; no exception message ever
    reaches one. The redaction cases put the key in a transport exception, a refusal
    body, a protocol body, an extra section key, `api_key_env` (as a value that is not a
    variable name, so the section is invalid) and the URL's userinfo. A `credential`
    detail names the `api_key_env` variable, which is public configuration: a key
    written as that name is already published in the role's configuration, and the
    check does not try to recognise one.
  - The untrusted-certificate case raises a `ConnectError` naming an SSL failure through
    the mock transport; it relies on httpx raising `ConnectError` for a failed
    certificate verification, and no real TLS handshake runs in this suite.
  `check_payments_access` and `PaymentsAccessOutcome` are exported from the package
  root for the storefront CLIs.
- [x] 1.5 Version, README and relock (RELEASING.md, "Versioning policy"; `AGENTS.md`,
  "Package and dependency discipline"). Bump `arkhai-kit-arkhai-payments` once, minor,
  against its version on `dev` (confirm with `git show origin/dev:kit/arkhai-payments/pyproject.toml`;
  0.5.0 → 0.6.0 if unchanged). Add the balance read and the check function to the kit's
  README beside the client's other calls. Run `make check-uv-version`, then `make lock`,
  and commit every lock it rewrites. Dependents raise their lower bound on the kit in the
  section that first uses the new API (2.1, 3.1, 4.6).
  `dev` held 0.5.0; bumped to 0.6.0. README: the balance read and the check beside
  `payments_client_for_owner`, and `PaymentsAuthority.balance` and
  `FakePaymentsClient.get_balance` in the authority-fixture passage. `make
  check-uv-version` OK; `make lock` rewrote the kit's lock and every dependent's.
  Correction to the plan: `domains/bare_metal/buyer` and `domains/bare_metal/storefront`
  pin the kit exactly (`==0.5.0`), so the bump moved both pins to `==0.6.0`, as
  RELEASING.md requires of exact pins and as the 0.4.0 → 0.5.0 bump did, with no version
  bump of either package (3.1 bumps the storefront). The first `make lock` left those two
  locks, and the VM storefront's and `e2e-tests`' through them, on 0.5.0, because a stale
  0.5.0 wheel was still in the local `.dist`; CI's fresh wheelhouse would have failed to
  resolve them. After the pin move every lock resolves 0.6.0, and `make
  check-packaging` passes.
- [x] 1.6 **Verification checkpoint.** Unit: the kit suite (`make -C kit test-arkhai-payments`),
  with `test_client.py`, `test_balance_view.py`, `test_access_check.py` and the fake's
  tests, and the existing vector replay (`kit/arkhai-payments/scripts/check_vectors.py`) still passing. Run
  `make test`, `make check-packaging` (1.5 changes a version and locks) and
  `make check-comment-hygiene`.
  End-to-end: none — no deployed surface calls the balance read or the check until
  sections 3 and 4; `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` and
  `e2e_vm_payment_deal` exercise them once wired. None is owed here.
  Owed by validation: `tests.yml`, job `test · test-kits` — the kit suite passes from
  the relocked environment.

  Evidence, all local:
  - `make -C kit test-arkhai-payments`: mypy clean; the vector replay passes (published
    mandates, receipt, attachments, approvals, 4 snapshots and 9 scenario steps;
    historical raw framing); generated models current; 191 unit tests pass.
  - `make test`: exit 0, no failing suite. It ran before the last test-only edits
    (fixture labels, the zero-gross case), which the kit gate above then covered.
  - `make check-packaging`: passes after the bare-metal pin move.
  - `make check-change`: comment hygiene, agent skills, task list, change index, spec
    index and OpenSpec validation pass. Documentation citations fail on three citations
    of files section 2 creates (`tools/payments-lane-double/README.md`, twice, and
    `tools/payments-lane-double/fixtures/dispute-authority.toml`). They resolve once
    section 2 lands.

  End-to-end confirmed: no `e2e-tests` marker exercises section 1, and none was added.
  The three payment-deal markers reach this code only through sections 3 and 4.
  Owed by validation, confirmed: `tests.yml`, job `test · test-kits`, which must show
  the payments kit suite passing from the relocked environment. Its new cases are
  `test_balance_view.py`, `test_access_check.py` and the balance cases in
  `test_client.py`.

  Handoff to sections 2 and 3:
  - The double's `GET /balances/{account}` route is `PaymentsAuthority.balance(account)`.
    Its 403 for another account is the double's to enforce (D5, D8). The engine answers
    for any account it is asked about.
  - The storefront CLIs (3.1) call
    `check_payments_access(settlement.mechanisms.get("arkhai_payments"), account)` and
    print `outcome.json_line()`, exiting 0 on `outcome.ok`. They need no handling of a
    missing or invalid section, which are `configuration` outcomes. They must turn the
    `ValueError` a malformed `--account` raises into a usage error.
  - A disabled section fails with `configuration`, as planned, although
    `payments_client_for_owner` still serves accepted deals while payments is disabled
    for new ones. A storefront still servicing old payment deals with payments disabled
    reports the check failed.
  - Follow-up left deliberately: no test runs a real TLS handshake with an untrusted
    certificate. Section 2's committed lane CA and leaf make one cheap. For example, the
    real client against the double over HTTPS with a context that does not trust the
    lane CA would show the `transport` step end to end. Section 2 or 3 should add it, or
    record why not.
  - D12's text in `design.md` says `refused <code>`. The build has `step: "refused"`
    plus a `code` field (1.4's note). Closeout's narrative compression should bring the
    design in line.

## 2. The payments double

Delivers `tools/payments-lane-double`: the HTTP app mirroring the payments service over
the kit's engine, its fixtures, the deterministic TLS material and its generator, its
image, and its suite (D1, D3, D4, D5's route, D8; test-compatibility delta "Lanes run
payment scenarios against an in-lane payments double").

Files: `tools/payments-lane-double/{pyproject.toml, uv.lock, Makefile, Dockerfile,
Dockerfile.dockerignore, README.md}`; `src/payments_lane_double/{__init__.py,
__main__.py, app.py, accounts.py, admission.py, settings.py}`;
`fixtures/{accounts.toml, dispute-authority.toml}`; `tls/{generate.py, lane-ca.pem,
double.pem, double.key.pem}`; `tests/`; the root `Makefile` (`test-payments-lane-double`
in `test`, `build-payments-lane-double`, and its place in `build-dev` and the three
`build-e2e-*` targets); `.github/workflows/tests.yml`'s matrix.

- [ ] 2.1 The project (D1). A wheel-building project at `tools/payments-lane-double`,
  import package `payments_lane_double`, depending on `arkhai-kit-arkhai-payments>=0.6.0`,
  `arkhai-kit-identity`, FastAPI and uvicorn, and `cryptography` for the generator, each
  declared in its `pyproject.toml`; internal distributions resolved from the repository
  wheelhouse as `docs/development/BUILD_AND_PACKAGING.md` requires; its own committed
  `uv.lock`. A `Makefile` with `test` and `build`, following `tools/frp-grant-admission`.
  No package anywhere depends on it. The README states what the double is, what it mirrors,
  what it serves and claims (D8), its fixtures and their labels, the TLS generator and its
  check, and how lanes and the local release run it.
- [ ] 2.2 Fixtures (D4, D8). `fixtures/accounts.toml` holds the buyer, seller and dispute
  authority accounts (UUIDs in the `AccountId` pattern), the buyer's and seller's bearer
  tokens, the buyer's seed balance in `USD/6`, the fee policy (250 bps), and the
  receipt-signing seed, distinct from `FakePaymentsClient`'s, each labelled. The dispute
  authority's account has no token. `fixtures/dispute-authority.toml` holds the pinned
  authority — `interface = "arkhai.mediation.v1"`, `origin = "https://dispute.invalid"`,
  its account, its `record_key` (a public key with no usable private half, produced once
  by a nothing-up-my-sleeve derivation or by generating and discarding a key, with a
  comment saying which), and an advertisement whose `mechanisms` include
  `arkhai.payments.v1` and whose minimum dispute window the lanes' options meet — the
  one document lanes and the local release render into registry recommendations
  (sections 4, 5). Unit: the fixtures load, the authority's record key parses as an
  Ed25519 identity, and the authority account has no token.
- [ ] 2.3 TLS (D3). `tls/generate.py` derives the CA and leaf Ed25519 keys from fixed
  seeds, writes the CA certificate (`lane-ca.pem`), the leaf certificate (`double.pem`,
  SANs `payments-double`, `localhost`, `127.0.0.1`) and the leaf key (`double.key.pem`),
  with fixed serials and validity ending 9999-12-31, and never writes the CA key. Commit
  its output. A `make check-tls` target (in the project's `Makefile`, run by its `test`)
  regenerates into a temporary directory and fails unless the bytes are identical.
  Unit: the leaf verifies under the CA, its SANs are exactly those three, and an
  `ssl.SSLContext` loaded with the CA accepts the leaf.
- [ ] 2.4 The app (D8, D5). `app.py` serves, over the engine with wall-clock time injected
  and one lock serialising requests:
  - `GET /health` → `{"status": "ok"}`;
  - bearer authentication through the account file: missing or unknown token → 401
    `authentication_required`; a malformed body → 400 `invalid_request`;
  - `POST /transactions` in D8's order: authentication; caller is `mandate.from`, else
    403 `caller_not_authorized`; an exact repeat of an approved mandate returns its
    original receipt whatever the clock or balance; for a new approval only,
    `admission.py` refuses `mandate_expired`, `unsupported_asset` (not `USD/6`),
    `fee_mismatch` (against 250 bps), `account_not_found` (`from` or `to` outside the
    directory), then the engine's `insufficient_funds` and `deal_mismatch`; attachments in
    the approval body stored through the engine;
  - `GET /transactions/{id}` and `GET /transactions/{id}/mandate` for the parties and any
    account in any part's authorities, else 403;
  - `POST /transactions/{id}/attachments` through the engine;
  - `POST /transactions/{id}/events`, `Idempotency-Key` as `requestId`, the authenticated
    account as `account`, every event kind the engine serves;
  - `GET /balances/{account}` for the caller's own account only, else 403, from
    `PaymentsAuthority.balance`.

  Every error body is the published `ApiError` with the service's status for its code.
  The engine signs with the fixture seed and `livemode=False`; the buyer is funded once at
  startup from the fixture file. `__main__.py` serves HTTPS with uvicorn from the TLS and
  fixture paths `settings.py` reads, defaulting to the files built into the image (D3), on
  port 8443.
- [ ] 2.5 The suite (D8; the delta's scenarios "An approval is retried after its mandate
  expires" and "The double mirrors a refusal"). Library integration: the real
  `PaymentsClient` against the app through an in-process transport, with an injected
  clock:
  - approve, receipt verified with the kit's verifier against the fixture identity and
    `livemode=False`, Agreement attached, snapshot read by both parties, seller reverse
    and its idempotent repeat, buyer balance before and after;
  - a retry after the mandate's `expires` returns the original receipt; a retry after the
    buyer's balance no longer covers the gross returns the original receipt;
  - each refusal with its status and code: 401 without and with a wrong token, 403 for a
    non-payer approval, a stranger's snapshot and mandate read and another account's
    balance, 409 `mandate_expired` for a new expired mandate, `unsupported_asset`,
    `fee_mismatch`, `account_not_found`, `insufficient_funds`, `deal_mismatch`, 400
    `invalid_request`;
  - an account named only in a part's authorities may read the snapshot;
  - the dispute authority's account cannot authenticate.
  Unit: `admission.py`'s order. The suite claims nothing about rate parts or holds (D8).
- [ ] 2.6 The image and the build graph (D1; `docs/development/BUILD_AND_PACKAGING.md`'s
  image rules). A `Dockerfile` installing the committed lock from the repository
  wheelhouse, copying `fixtures/` and `tls/` to the fixed path `settings.py` defaults to,
  running `python -m payments_lane_double`, with a healthcheck on `/health` over HTTPS
  trusting the lane CA. Root `Makefile`: `build-payments-lane-double` tagging
  `arkhai:payments-lane-double$(IMAGE_SUFFIX)`, added to `build-dev` (which the Helm
  validation runs) and to `build-e2e-vm`, `build-e2e-bare-metal` and `build-e2e-apicredits`;
  `test-payments-lane-double` running the project's `make test`, added to the root `test`
  target and to `.github/workflows/tests.yml`'s matrix. Verify the image builds and that
  `docker run` of it answers `/health` over HTTPS with the lane CA.
- [ ] 2.7 **Verification checkpoint.** Library integration and unit: the double's suite
  (`make test-payments-lane-double`, including `check-tls`). The image builds with
  `make build-payments-lane-double`. Run `make test`, `make check-packaging` (a new
  project, lock and image install) and `make check-comment-hygiene`.
  End-to-end: none — no lane runs the double until section 4. None is owed here.
  Owed by validation: `tests.yml`, job `test · test-payments-lane-double` — the job
  exists in the matrix and passes, `check-tls` included.

## 3. Storefront `check-payments` and the VM storefront's unreachable authority

Delivers the `check-payments` subcommand on the three storefront CLIs (D12;
deployment-state delta "A storefront checks its payments access from its own container",
its CLI half) and the focused proof that a VM seller holding a dispute credential reports
a deal `running` while its pinned authority cannot be reached (D2; test-compatibility
delta "The VM payment scenario's case stages need a mediation target").

Files: `domains/vms/storefront/src/market_storefront/cli.py`,
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py`,
`domains/apicredits/storefront/src/apicredits_storefront/cli.py`, and their tests
(`domains/vms/storefront/tests/unit/test_cli_check_payments.py` and the bare-metal and
API-credit equivalents, new); `domains/vms/storefront/tests/integration/` (a new
`test_servicing_unreachable_authority.py`, beside `test_servicing_composition.py`); the
three storefronts' `pyproject.toml`; every lock `make lock` rewrites.

- [ ] 3.1 `check-payments --account <id>` on `market-storefront`, `bare-metal-storefront`
  and `apicredits-storefront` (D12). Each loads the storefront's configuration exactly as
  its `serve` command does — the same files, chart-rendered layer, overlay and
  environment — takes its `[Settlement.arkhai_payments]` section, calls
  `check_payments_access`, prints the outcome's JSON line, and exits 0 on `ok` and 1
  otherwise. It starts no server, opens no database and contacts nothing but the
  payments service. Bump each storefront once, minor, against `dev`, raising its bound on
  `arkhai-kit-arkhai-payments` to `>=0.6.0`; `make lock`. Unit, per CLI, with the CLI
  runner and an injected transport or a stubbed kit call: `ok` prints the outcome and
  exits 0; a configuration without the section, an unset key variable, and a transport
  failure each print their step and exit 1; no output contains the key.
- [ ] 3.2 The unreachable-authority proof (D2). Application integration in the VM
  storefront's suite: an Agreement pinned to the `.invalid` authority, the storefront
  configured with an identity-bound `[[DisputeCredential]]` for it whose variable resolves
  to a labelled development value, and servicing stepped: the deal's lifecycle view reads
  `state == "running"` with a non-`Accepted` dispute outcome, and the respondent poll
  neither raises nor marks the deal for repair. Use an injected mediation transport that
  raises the DNS failure an `.invalid` origin produces, so the test needs no network. If
  the view reads otherwise, stop: D2 and the test-compatibility delta are revised
  together before section 4 (design.md D2).
- [ ] 3.3 **Verification checkpoint.** Unit: the three CLI suites. Application
  integration: `test_servicing_unreachable_authority.py`. Run `make test-storefront`,
  `make test-bare-metal`, `make test-apicredits`, then `make test`,
  `make check-packaging` (versions and locks) and `make check-comment-hygiene`.
  End-to-end: none yet — section 4's lane targets run `check-payments`, and
  `e2e_vm_payment_deal`'s stage 2 exercises 3.2's behaviour once the VM lane is wired.
  None is owed here.
  Owed by validation: `tests.yml`, jobs `test · test-storefront`, `test · test-bare-metal`
  and `test · test-apicredits` — each passes from the relocked environments.

## 4. Compose lane wiring

Delivers the double in the VM, bare-metal and API-credit lanes with their storefronts,
registries and settings, a lane-owned target failing rather than skipping, the VM
scenario's mediation prerequisite, and `check-payments` at lane setup (D2, D6, D7, D9,
D12; test-compatibility deltas "Lanes run payment scenarios against an in-lane payments
double", "The VM payment scenario's case stages need a mediation target", and MODIFIED
"External payment qualification names its target" and "A configured bare-metal payment
purchase is qualified end to end").

Files: a new `compose.payments-double.yml` defining the `payments-double` service from
`arkhai:payments-lane-double`; `compose.vms-local.yml`, `compose.bare-metal-local.yml`,
`compose.apicredits-lane.yml` (or each lane's own overlay) for storefront environment,
CA trust, `depends_on`, and registry recommendations; the lane storefront configuration
each lane mounts (below); `dev-env/identities/` for any new labelled lane value; the root
`Makefile`'s `e2e-vms-dev-env`, `e2e-bare-metal-dev-env` and `e2e-apicredits-dev-env`;
`e2e-tests/Makefile` (the three lane compose lists, `check-payments` after `up`, and
`test-buyer-machine`'s per-lane environment and CA mount);
`e2e-tests/tests/e2e/roles/helpers/payments.py`, a mediation prerequisite helper beside
it, `e2e-tests/tests/unit/test_payments_helper.py`;
`e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_payment_deal.py`;
`e2e-tests/settings.toml`; `e2e-tests/pyproject.toml` (the VM marker's description);
`e2e-tests/README.md`'s payment passages that the code makes false.

- [ ] 4.1 The double in each lane (D1, D3, D6). `compose.payments-double.yml` runs
  `payments-double` on the lane's network with no host port, its healthcheck on `/health`
  over HTTPS with the lane CA. Each lane's `-f` list in `e2e-tests/Makefile` (and the
  matching `e2e-*-down`/`-logs` invocations) includes it. Each payment storefront —
  Bob's VM storefront, the bare-metal storefront, the API-credit storefront —
  `depends_on` it with `service_healthy`, mounts the lane CA and sets `SSL_CERT_FILE`.
- [ ] 4.2 Storefront payments configuration (D9, D2, D11's "deployment values"). Each
  payment storefront's lane configuration gains `[Settlement.arkhai_payments]`:
  `enabled = true`, `service_url = "https://payments-double:8443"`, the double's receipt
  identity, `fee_bps = 250`, `livemode = false`, and `api_key_env` naming a variable the
  lane's environment sets to the seller's fixture token; never `development_auth`. The
  settlement `priority` keeps the lane's existing mechanisms and adds
  `arkhai.payments.v1`. Bob's VM storefront also gains an identity-bound
  `[[DisputeCredential]]` for the pinned authority and its variable (D2). The
  configuration reaches only the lanes: select each lane's file through the existing
  `*_STOREFRONT_CONFIG` or secrets-overlay variables the dev-env targets print, and leave
  the root development stack's configuration unchanged.
- [ ] 4.3 Registry recommendations (D7). Each lane's registry — both VM registries, the
  bare-metal registry, the API-credit registry and the compute registry it routes through
  — sets `REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES` to the pinned authority
  rendered from `tools/payments-lane-double/fixtures/dispute-authority.toml`, through the
  lane's dev-env target. No storefront or buyer configuration gains a `[[Dispute]]` entry.
- [ ] 4.4 Per-lane settings and the test runner (D9). Each lane target passes its
  `ARKHAI_PAYMENTS__*` overrides to `test-buyer-machine` — `SERVICE_URL`,
  `SERVICE_IDENTITY`, `BUYER_ACCOUNT`, `BUYER_MARKETPLACE_CREDENTIAL`,
  `SELLER_MARKETPLACE_CREDENTIAL` (that lane's storefront key, in that lane's scheme),
  `API_KEY_ENV`, `LANE_OWNED=true`, and in the bare-metal lane `SELLER_ACCOUNT`,
  `COMPUTE_HOURLY_GROSS=1000000` and `DISPUTE_WINDOW=P7D` — plus the buyer token variable
  `API_KEY_ENV` names, `SSL_CERT_FILE`, and the lane CA mount. The values come from the
  committed fixtures through the lane's dev-env target. `config-docker.yml` is unchanged.
  Confirm the `market` subprocess the scenarios run inherits the token variable and
  `SSL_CERT_FILE` (`e2e-tests/tests/e2e/roles/buyer_cli.py`), passing them through
  where its environment is built explicitly.
- [ ] 4.5 The helper (D6). In `helpers/payments.py`: `PAYMENTS.LANE_OWNED`, a strict
  boolean defaulting to false; with it true, an unready target fails naming its URL
  rather than skipping. `target_ready` builds an `ssl.SSLContext` from `SSL_CERT_FILE`
  when it is set and passes it as `verify`, keeping `trust_env=False`. `settings.toml`
  documents `lane_owned` in `[default.payments]`. Unit (`test_payments_helper.py`): an
  unready lane-owned target fails naming the URL; an unready external target still
  skips; the probe uses a context built from `SSL_CERT_FILE` and disables environment
  proxies, through an injected readiness seam rather than the network.
- [ ] 4.6 The VM scenario's mediation prerequisite (D2). A `MEDIATION.SERVICE_URL`
  setting, blank by default in `settings.toml`, read by a helper beside the payments
  helper; `test_vm_payment_deal.py`'s stages 3 and 4
  (`test_operator_end_files_one_case_without_a_local_payment_remedy`,
  `test_seller_refund_is_financial_and_release_waits_for_the_callback`) report a blocked
  skip naming it when blank; stages 1 and 2 run unchanged. Update the
  `e2e_vm_payment_deal` marker's description in `e2e-tests/pyproject.toml`. Raise
  `e2e-tests`' bound on `arkhai-kit-arkhai-payments` only if it uses the new API, and
  relock if it does. Unit: the helper blocks on blank and returns the URL otherwise.
- [ ] 4.7 `check-payments` at lane setup (D6, D12). After `up --wait`, each lane target
  runs `docker compose exec <storefront> <cli> check-payments --account <the lane's
  seller account>` for each payment storefront, and fails the target, before pytest, on a
  nonzero exit.
- [ ] 4.8 `e2e-tests/README.md`: correct the passages sections 1–4 make false — the shared
  payment configuration (a lane now configures its own target, `LANE_OWNED`), "Hosted VM
  servicing" (stages 1–2 run against the double, 3–4 need `MEDIATION.SERVICE_URL`), and
  "Bare-metal payment deal" (it runs in the lane; the re-drive repeats the canonical
  commit). The rest of the permanent documentation is closeout's.
- [ ] 4.9 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
  `test_payments_helper.py` and the mediation helper's cases. System: run each lane —
  `make -C e2e-tests test-e2e-bare-metal`, `test-e2e-apicredits` and `test-e2e-vm` — and
  confirm each lane's `check-payments` passes at setup and its payment scenario runs: the
  bare-metal and API-credit payment deals pass without skipping; the VM payment deal's
  stages 1–2 pass with `state == "running"` and stages 3–4 report the mediation blocked
  skip; every other scenario in each lane passes as before. Then `make test`,
  `make check-packaging` and `make check-comment-hygiene`. A lane that cannot run here is
  disclosed and left to the validation's pipeline.
  End-to-end: `e2e_bare_metal_payment_deal` (bare-metal lane), `e2e_credits_payment_deal`
  (API-credit lane) and `e2e_vm_payment_deal` (VM lane) exercise this section; every other
  marker in the three lanes' module lists must stay green.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes.

## 5. Helm: the subchart, the storefront chart options, and the local rehearsal

Delivers the double in the local release, both storefront charts' CA bundle and
payments-key options, the local release's payments configuration through deployment
values, the `helm test` payments check, and the render cases (D3, D11, D12;
deployment-state deltas "A storefront chart trusts a deployment-supplied CA bundle", "A
storefront chart injects the payments key from a deployment Secret", "The local release
rehearses a deployment's payments interface", and the Helm half of "A storefront checks
its payments access from its own container").

Files: a new `helm/charts/payments-lane-double/` (`Chart.yaml`, `values.yaml`,
`values.schema.json`, `templates/{deployment.yaml, service.yaml}`, `tests/test_render.py`);
`helm/Chart.yaml`, `helm/values.yaml`, `helm/values.schema.json`; `helm/local-values.yaml`,
`helm/bare-metal-release-values.yaml`; `helm/Makefile` (`LOCAL_SECRETS`) and
`helm/scripts/topology-secrets.sh`; `helm/charts/storefront/{values.yaml,
values.schema.json, templates/deployment.yaml, templates/_helpers.tpl,
templates/tests/payments-check-test.yaml (new), tests/test_render.py}` and the same files
under `helm/charts/bare-metal-storefront/`; `helm/charts/registry/` values only where
the recommendation needs them; `helm/charts/e2e-tests/` values for `PAYMENTS`;
`helm/tests/{test_release_topology.py, test_image_overlay.py}`.

- [ ] 5.1 The subchart (D3, D11). `payments-lane-double`, disabled in `helm/values.yaml`,
  enabled in `helm/local-values.yaml` and disabled again in
  `helm/bare-metal-release-values.yaml`, so the two-release topology runs one double. Its
  Service is named `payments-double` (not release-prefixed), port 8443. Its Deployment
  runs `arkhai:payments-lane-double` under the image overlay the other local images use;
  with `tls.existingSecret` set it mounts that Secret's certificate and key over the
  image's own files, and otherwise uses the image's. Render tests: default disabled; the
  local values render one Deployment and a Service named `payments-double`; the topology
  values render none; `tls.existingSecret` mounts the Secret.
- [ ] 5.2 The CA bundle option (D3; delta "A storefront chart trusts a
  deployment-supplied CA bundle"), on both storefront charts: a value naming a ConfigMap
  and key, or alternatively a Secret and key, mounted read-only and named by
  `SSL_CERT_FILE`; no default; nothing rendered when unset; refused when both sources are
  named. Render tests for each source and unset.
- [ ] 5.3 The payments-key option (D11; delta "A storefront chart injects the payments key
  from a deployment Secret"), on both storefront charts: a value naming a Secret and key,
  exposed with `secretKeyRef` under the variable the agent configuration's
  `Settlement.arkhai_payments.api_key_env` names, read case-insensitively as the chart
  reads every key it uses; refused at render when the configuration names no
  `api_key_env`; nothing rendered when unset. Render tests: set, unset, and refused.
- [ ] 5.4 The payments-only render case (D11): a storefront agent with payments
  configured and Wallet, Chains and Alkahest set to `null` and RPC off renders with the
  payments configuration, the CA mount and the key variable and nothing for the removed
  settings, on both charts.
- [ ] 5.5 The `helm test` payments check (D12; the delta's Helm half). A
  `payments-check-test.yaml` in each storefront chart, rendered only when payments is
  configured and a `tests.paymentsAccount` value names the account, runs the storefront
  CLI's `check-payments --account <account>` directly, not through the entrypoint, with
  the Deployment's image, configuration and secrets mounts, identity credential variable,
  CA mount with `SSL_CERT_FILE`, and payments-key variable, rendered from helpers the
  Deployment also uses (move the shared pieces into `_helpers.tpl`), and without the data
  volume, the probes, or the ZeroTier capabilities and device. It carries no workload
  selector labels (deployment-state "Helm test pods carry no workload selector labels").
  Render tests: the pod's mounts and variables equal the Deployment's payments-deciding
  ones; it mounts no data volume with persistence enabled; it has no probes and no
  ZeroTier additions.
- [ ] 5.6 The local rehearsal (D11, D3, D7). `helm/local-values.yaml` configures Bob's
  storefront agent and `helm/bare-metal-release-values.yaml` the bare-metal storefront
  agent for payments through the agent configuration and the two options (ConfigMap
  `payments-ca-bundle` / `ca-bundle.pem`, Secret `seller-payments-key` / `api-key`), with
  `tests.paymentsAccount` the seller's fixture account; never `development_auth`. The
  registry's recommended dispute authorities name the pinned authority. The e2e-tests
  chart's values carry the `PAYMENTS` keys D9 lists, with `LANE_OWNED=true`.
  `helm/scripts/topology-secrets.sh` creates the `payments-ca-bundle` ConfigMap from
  `tools/payments-lane-double/tls/lane-ca.pem` and the `seller-payments-key` Secret from
  the fixture token, idempotently; `helm/Makefile`'s `LOCAL_SECRETS` names both so
  `check-local-secrets` refuses a deploy without them. A render test in
  `helm/tests/test_release_topology.py` holds the two releases to one double and both
  storefronts to `https://payments-double:8443`.
- [ ] 5.7 **Verification checkpoint.** Chart render: `make -C helm test-render`, with every
  render case of 5.1–5.6. Unit: `helm/tests` (`make test-deployment-packaging`). System:
  where a local cluster is available, `make -C helm topology-secrets`, `deploy-local`,
  then `make -C helm test`, whose payments check passes for Bob's storefront, and
  `topology-check` for the bare-metal storefront's; otherwise disclose it as left to the
  validation's Helm part. Run `make test`, `make check-packaging` and
  `make check-comment-hygiene`.
  End-to-end: no pipeline marker exercises the charts; the validation's Helm part
  deploys the release and runs its `helm test`, the storefront payments check among
  them. Serving payment scenarios on Helm is not owed (D11).
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
  `make -C helm test-render` passes with the new render cases.

## 6. Closeout

Confirm and promote the verified design, then archive last (D1–D12 and every delta
requirement). The eleven parts follow `openspec/README.md#plan-closeout-requirements` in
order. Closeout changes no code: a part needing a code, lock, chart, or test change
returns the change to implementation.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every
  comment and docstring sections 1–5 added: the kit's `access_check.py` and balance view,
  the double's modules, fixtures and generator, the storefront CLIs' subcommands, the
  compose overlay and lane targets, the helper, the charts' values and templates. Each
  states current behaviour and every fixture value's label is present. A needed
  correction returns to implementation.
- [ ] 6.2 **Import placement — confirm.** Every import sections 1–5 added is at module
  level unless a verified cycle or recorded lazy-load reason keeps it local. A needed move
  returns to implementation.
- [ ] 6.3 **Documentation compliance.** Check D1–D12 against `openspec/README.md`'s
  placement rules and the promotion record below, recording a disposition per decision,
  and check every promoted statement against the code.
- [ ] 6.4 **Narrative compression.** Compress section notes to final behaviour,
  validation evidence, deferred work, and destinations, moving durable rationale into
  `design.md` first.
- [ ] 6.5 **Roadmap currency.** In `docs/development/ROADMAP.md`:
  - Goal 8's open-gap row "Payment scenarios skip without a target, and hostile payment
    and dispute-authority cases cannot be driven deterministically": narrow it to the
    dispute-authority double, controls and evidence classes `add-arkhai-payments-lane-double`
    still owns, since the once-only payment scenarios now run against the lane double;
  - Goal 1's row "A hosted deployment has no controllable dispute authority…": correct its
    claim that production configuration refuses the lane double's fixture identities —
    no guard exists, the pinned lane authority is unusable by construction, and the guard
    is `add-arkhai-payments-lane-double`'s decision;
  - "Payment qualification boundaries": replace "none configures a payments target" with
    the lanes' double and what it does not establish;
  - add an unowned gap: payment scenarios are not served on the local Helm release,
    revisited when an external run fails in a way the charts shape (D11).
- [ ] 6.6 **Campaign index currency.** In `openspec/changes/README.md`, set this change's
  row to its archived state and link, and update the Reach hosts campaign's graph lines
  naming it. Note in `qualify-real-provisioning-by-scenario`'s row that its storefront
  chart CA option is delivered here and its delta's same-named requirement must be dropped
  or reduced to a MODIFIED at its reverification; note in
  `add-arkhai-payments-lane-double`'s row its D1/D7 revision and the fixture-identity
  guard it owns. Run `make check-change-index`. Archive cleanup, not closeout, releases
  the dependents.
- [ ] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=add-mvp-payments-lane-double`. No `.agents/`,
  `.claude/` or `.codex/` edit is planned; if one was made, run `make check-agent-skills`.
- [ ] 6.8 **End-to-end pipeline.** Confirm the pipeline passes on the closeout candidate
  and record the run, its result, and the scenarios exercising this change:
  `e2e_bare_metal_payment_deal` and `e2e_credits_payment_deal` passing without skips,
  `e2e_vm_payment_deal`'s stages 1–2 passing and 3–4 reporting the mediation blocked
  skip, and each lane's `check-payments` at setup; and the Helm part's payments check. A
  pipeline that cannot run for an unrelated reason is recorded as a blocker naming its
  cause and owner, and what it gates is unrun.
- [ ] 6.9 **Promotion.** Write and record in the promotion record:
  - `openspec/specs/test-compatibility/architecture.md`, "Payment evidence ownership":
    the in-lane double, what it mirrors and serves, what its results establish and do
    not, and the VM scenario's mediation prerequisite; its "Lifecycle contract evidence"
    sentence on the kit's fake, made accurate;
  - `docs/development/TESTING.md`, "Private Service Dependencies": the lanes' payments
    target, the per-lane settings, `LANE_OWNED`, the pinned unanswerable authority, and
    the principle that a double mirrors its producer's API unless there is a compelling
    reason to deviate;
  - `docs/development/ARCHITECTURE.md`, "Testing strategy": that principle as a
    repository-wide rule;
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`: under "Kubernetes: ConfigMap and Secret
    mounting", the storefront charts' CA bundle and payments-key options; under
    "Settlement consumer configuration and cutover", the storefront payments check; and
    under "Release topology", that a local release configures a service through the same
    values a deployment uses, never development-only modes, with the payments double
    enabled once per namespace;
  - `docs/operator-handbook.md`: a new "Payments access" section — the CA ConfigMap and
    key Secret a deployment supplies, `check-payments`, and the Helm test;
  - `tools/README.md`: the payments double as a lane collaborator, the third kind of
    tool, beside `issue-discovery` and `frp-grant-admission`;
  - the deltas into `openspec/specs/test-compatibility/spec.md`,
    `openspec/specs/deployment-state/spec.md` and `openspec/specs/market-composition/spec.md`,
    written by the archive (6.11);
  - `openspec/specs/README.md`: no new capability or companion, so no entry; confirm.
- [ ] 6.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=add-mvp-payments-lane-double` after promotion and
  resolve every match, then `openspec validate add-mvp-payments-lane-double --strict`.
- [ ] 6.11 **Archival.** `openspec archive add-mvp-payments-lane-double -y`, merging the
  three deltas into `openspec/specs/`; then point the index row at the archive directory.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 The double's project and its place among tools | `tools/README.md`; `tools/payments-lane-double/README.md` |
| D2 Lanes running the double; the VM scenario's mediation prerequisite and dispute credential | `openspec/specs/test-compatibility/spec.md` (delta); `openspec/specs/test-compatibility/architecture.md`, "Payment evidence ownership"; `e2e-tests/README.md` |
| D3 Committed lane CA and leaf; injection in Helm | `tools/payments-lane-double/README.md`; `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Kubernetes: ConfigMap and Secret mounting" |
| D4 No production guard; the unusable pinned authority | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`, "Private Service Dependencies"; `docs/development/ROADMAP.md` |
| D5 The balance read | `openspec/specs/market-composition/spec.md` (delta); `kit/arkhai-payments/README.md` |
| D6 Lane-owned targets fail | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`, "Private Service Dependencies" |
| D7 The pinned authority through the registry | `docs/development/TESTING.md`, "Private Service Dependencies"; `e2e-tests/README.md` |
| D8 The double mirrors the service | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`; `docs/development/ARCHITECTURE.md`, "Testing strategy" |
| D9 Per-lane settings | `e2e-tests/README.md`, "Shared payment-scenario configuration"; `docs/development/TESTING.md` |
| D10 Implementation cadence | change history only |
| D11 The local release's payments rehearsal and the chart options | `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Release topology"; `docs/operator-handbook.md`, "Payments access"; `docs/development/ROADMAP.md` (the Helm-serving gap) |
| D12 `check-payments` | `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover"; `docs/operator-handbook.md`, "Payments access" |
