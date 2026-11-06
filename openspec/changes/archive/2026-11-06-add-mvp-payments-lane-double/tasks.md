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

Round 1's order was 1 → 5 (the replanned order below runs 6 → 12, then the closeout,
13). Section 1 adds the kit's balance read and the
payments check function (D5, D12); section 2 builds the double on it (D1, D3, D4, D8);
section 3 adds the storefront CLIs' `check-payments` and the VM storefront's
unreachable-mediation proof (D2, D12); section 4 wires the three Compose lanes (D2, D6,
D7, D9); section 5 does Helm (D3, D11, D12). Each section needs only the sections before
it. No dependency gates implementation. `qualify-real-provisioning-by-scenario` waits on
this change's implementation. Permanent specifications, companions, `ARCHITECTURE.md`,
`TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, the operator handbook, `tools/README.md` and
the roadmap are written at closeout; a section writes only the package documentation its
code needs (the double's README, the kit's README entry).

**Replanned against the redesign** that round 1's triage returned the change for (31 O1)
and `reviews/50-design.triage.md` advanced. Sections 1–5 are round 1's, kept as
implemented; where the reviewed design changes what they built, the correction notes under
sections 4 and 5 name the later section that carries it. Sections 6–12 implement D13–D23
and the revisions of D2, D3, D6, D11, D12 and D19, in the order of D22's cadence:
section 6 makes the payments kit take a secret key and a configured CA (D19, D12);
section 7 gives dispute credentials a secret key and makes `MediationCredential` carry
the resolved token (D19, D2); section 8 gives the registry profile-shaped env files (D16);
section 9 moves the Compose stacks onto committed overlays, profiles and secret overlays
(D15, D16, D17, D19, D20, D23); section 10 moves the test runner onto committed lane
profiles and retires the Makefile's environment targets (D14, D18, D20, D21, D6);
section 11 gives the registry chart its env-file profile (D16); section 12 moves the
storefront charts onto a derived `ca_bundle_path` and the secret overlay (D3, D11, D12,
D19). Section 13, the closeout, replaces the unstarted section-6 closeout this plan
first ended with, replanned for D1–D23. Each section needs only the sections before it.
No dependency gates implementation.

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
  Unit, four cases in `test_client.py`: pass. `Balance` comes from
  `market_arkhai_payments.models`; an invalid account raises `ValidationError` before any
  request. The cases use a loopback origin so an ambient `HTTPS_PROXY` cannot mount ahead
  of the mock.
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

  Unit, eight engine cases in `test_balance_view.py` (injected clock): pass, beyond the
  list an after-stop hold under an open extension (`until: stop`) and a zero-gross part
  listing no hold. `releaseAt` shares `snapshot()`'s helper; the vector replay is
  unchanged.
- [x] 1.3 `FakePaymentsClient.get_balance(account)` delegates to `engine.balance` (D5),
  recorded in `calls` like its other methods and subject to `unavailable`. Unit: in the
  fake's tests, a served approval then a balance read returns the engine's view, and an
  unavailable fake raises the transport error.
  Unit, two cases in `test_balance_view.py` (the kit has no test module of the fake's
  own): pass.
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
  Unit, `test_access_check.py`: pass. As built (rationale in design.md): `config` also
  takes a mapping or `None`; a refusal is `step: "refused"` with a separate `code`; a
  protocol error is `transport`; a CR/LF key variable is `credential`; a malformed
  `account` raises `ValueError`; every `detail` is fixed text, the redaction cases putting
  the key in six places. A trust bundle that cannot be loaded at client construction is
  `transport` with fixed text (29 F1, `test_access_check_tls.py`). Exported from the
  package root.
- [x] 1.5 Version, README and relock (RELEASING.md, "Versioning policy"; `AGENTS.md`,
  "Package and dependency discipline"). Bump `arkhai-kit-arkhai-payments` once, minor,
  against its version on `dev` (confirm with `git show origin/dev:kit/arkhai-payments/pyproject.toml`;
  0.5.0 → 0.6.0 if unchanged). Add the balance read and the check function to the kit's
  README beside the client's other calls. Run `make check-uv-version`, then `make lock`,
  and commit every lock it rewrites. Dependents raise their lower bound on the kit in the
  section that first uses the new API (2.1, 3.1, 4.6).
  0.5.0 → 0.6.0; the bare-metal buyer's and storefront's exact pins moved to `==0.6.0`.
  README documents the balance read, the check, `PaymentsAuthority.balance` and
  `FakePaymentsClient.get_balance`. `make check-uv-version`, `make lock` and `make
  check-packaging` pass.
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

  Evidence: the kit suite (mypy, vector replay, generated models, unit tests), `make
  test`, `make check-packaging` and `make check-comment-hygiene` pass. No marker exercises
  section 1 directly. Owed observation confirmed: `test · test-kits`, with
  `test_balance_view.py`, `test_access_check.py` and the balance cases in `test_client.py`.

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

- [x] 2.1 The project (D1). A wheel-building project at `tools/payments-lane-double`,
  import package `payments_lane_double`, depending on `arkhai-kit-arkhai-payments>=0.6.0`,
  `arkhai-kit-identity`, FastAPI and uvicorn, and `cryptography` for the generator, each
  declared in its `pyproject.toml`; internal distributions resolved from the repository
  wheelhouse as `docs/development/BUILD_AND_PACKAGING.md` requires; its own committed
  `uv.lock`. A `Makefile` with `test` and `build`, following `tools/frp-grant-admission`.
  No package anywhere depends on it. The README states what the double is, what it mirrors,
  what it serves and claims (D8), its fixtures and their labels, the TLS generator and its
  check, and how lanes and the local release run it.
  Done; `make check-packaging` passes. `pydantic` and `starlette` are declared (imported
  directly); `arkhai-kit-deal-lifecycle` and `httpx` are dev dependencies; `cryptography`
  is a runtime dependency since 2.8. The Makefile also has `reinit`, `init`, `test-unit`,
  `check-tls` and `tls`.
- [x] 2.2 Fixtures (D4, D8). `fixtures/accounts.toml` holds the buyer, seller and dispute
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
  Unit, `test_fixtures.py` and `test_authentication.py` (a whitespace token refused at
  load): pass. Accounts b1 (buyer), b2 (seller), d1 (authority) in the
  `00000000-0000-4000-8000-0000000000xx` form; the buyer funded with 1000000000000 USD/6
  minor units; receipt seed `0d` × 32, with its `receipt_identity` stated beside it and
  the loader refusing a disagreement. The record key: a random Ed25519 key generated
  once, its private half discarded unrecorded, as the file says (no test can prove the
  absence). The authority file is a validated `DisputeEntry`, minimum dispute window 0.
- [x] 2.3 TLS (D3). `tls/generate.py` derives the CA and leaf Ed25519 keys from fixed
  seeds, writes the CA certificate (`lane-ca.pem`), the leaf certificate (`double.pem`,
  SANs `payments-double`, `localhost`, `127.0.0.1`) and the leaf key (`double.key.pem`),
  with fixed serials and validity ending 9999-12-31, and never writes the CA key. Commit
  its output. A `make check-tls` target (in the project's `Makefile`, run by its `test`)
  regenerates into a temporary directory and fails unless the bytes are identical.
  Unit: the leaf verifies under the CA, its SANs are exactly those three, and an
  `ssl.SSLContext` loaded with the CA accepts the leaf.
  Unit, `test_tls.py`: pass, "accepts" shown by a real handshake over `ssl.MemoryBIO` for
  each name under Python 3.13's strict X.509 flags. Seeds `CA` × 32 and `D0` × 32,
  serials 1 and 2, validity 2026-01-01 to 9999-12-31. Since 2.8 the key is generated at
  image build, not committed.
- [x] 2.4 The app (D8, D5). `app.py` serves, over the engine with wall-clock time injected
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
  Proven by 2.5's suite. As built (design.md, "The payments double"): a framework-free
  `PaymentsDouble`; its own mandate map, an unknown transaction 404
  `transaction_not_found`; inferred statuses (422 `unsupported_asset`/`fee_mismatch`,
  404 `account_not_found`), stated as inferred in `admission.py` and the README; the first
  non-matching attachment passed to the engine; malformed path or `Idempotency-Key` 400,
  unexpected errors 500, all as `ApiError`; case-insensitive `Bearer`; success 200.
  Settings from `PAYMENTS_LANE_DOUBLE_{FIXTURES,TLS,HOST,PORT}`.
- [x] 2.5 The suite (D8; the delta's scenarios "An approval is retried after its mandate
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
  Library integration, `tests/integration/test_double.py`, and unit,
  `tests/unit/test_admission.py`: pass. The real client reaches the app over a
  `MockTransport` forwarding to FastAPI's `TestClient`, at a loopback HTTPS origin; two
  suite-only accounts (a stranger and an authority-named watcher) join the fixture. Raw
  calls, each commented: the mandate route and three rejection paths the client cannot
  build. `deal_mismatch` is shown through `attach_agreement` and on an approval after
  the funds check.
- [x] 2.6 The image and the build graph (D1; `docs/development/BUILD_AND_PACKAGING.md`'s
  image rules). A `Dockerfile` installing the committed lock from the repository
  wheelhouse, copying `fixtures/` and `tls/` to the fixed path `settings.py` defaults to,
  running `python -m payments_lane_double`, with a healthcheck on `/health` over HTTPS
  trusting the lane CA. Root `Makefile`: `build-payments-lane-double` tagging
  `arkhai:payments-lane-double$(IMAGE_SUFFIX)`, added to `build-dev` (which the Helm
  validation runs) and to `build-e2e-vm`, `build-e2e-bare-metal` and `build-e2e-apicredits`;
  `test-payments-lane-double` running the project's `make test`, added to the root `test`
  target and to `.github/workflows/tests.yml`'s matrix. Verify the image builds and that
  `docker run` of it answers `/health` over HTTPS with the lane CA.
  The image builds; its healthcheck (`curl --cacert lane-ca.pem
  https://localhost:8443/health`) is what every lane waits on, so validation 82's lanes
  are its `/health` evidence. The image installs the project editable at
  `/repo/tools/payments-lane-double`, since its wheel is not in the wheelhouse;
  promotion records this two-level variant in `BUILD_AND_PACKAGING.md` (13.9).
  `payments-lane-double` is in `scripts/change_namespace.py`'s `BUILT_IMAGES` and the
  build-target tests; the image is never pushed.
- [x] 2.7 **Verification checkpoint.** Library integration and unit: the double's suite
  (`make test-payments-lane-double`, including `check-tls`). The image builds with
  `make build-payments-lane-double`. Run `make test`, `make check-packaging` (a new
  project, lock and image install) and `make check-comment-hygiene`.
  End-to-end: none — no lane runs the double until section 4. None is owed here.
  Owed by validation: `tests.yml`, job `test · test-payments-lane-double` — the job
  exists in the matrix and passes, `check-tls` included.

  Evidence: `make test-payments-lane-double` (`check-tls`, unit and library
  integration), `make build-payments-lane-double`, `make test`, `make
  test-release-tooling` (the matrix check and build-target tests), `make check-packaging`
  and `make check-change` pass. Owed observation confirmed as written.

- [x] 2.8 The leaf key is generated at image build, not committed (D3; the merge of the
  branch the change lands on, whose secret gate refuses a committed private key block and
  admits no fixture by path; the owner chose this over an allowlist entry).
  `tools/payments-lane-double/`: the Dockerfile's builder stage runs `tls/generate.py`
  and the runtime stage copies its `double.key.pem`; `Dockerfile.dockerignore` admits the
  generator and keeps out a locally written key; `cryptography` moves from the dev group
  to the runtime dependencies, since the image's `--no-dev` environment runs the
  generator; `check-tls` compares the two committed certificates; `tls/double.key.pem`
  is removed from Git and ignored, and `make tls` still writes it for running the double
  outside its image; the README and the generator's docstring say so. A unit test holds
  the generated key to the committed leaf certificate's public key.
  Verified: `make test-payments-lane-double`, `make check-packaging`, `make test`,
  `make check-change` and the secret gate's tree test; validation 82 built the image. The
  key stays in this branch's earlier commits, so the change lands from a landing branch
  (83 F1, the owner's choice): once this branch holds `dev`'s tip, the owner cuts a branch
  from `dev`'s tip whose one commit carries this branch's tree (`git commit-tree
  <tip>^{tree} -p origin/dev -m <message>`, then `git branch` on the commit it prints),
  the tree validation and closeout read, and opens the pull request from it. Archive
  cleanup's pull request description names that branch; its guarded push pushes only this
  one. Triage 83 also corrected the README's Fixtures sentence (83 F2) and the integration
  suite's docstring (83 F3).

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

- [x] 3.1 `check-payments --account <id>` on `market-storefront`, `bare-metal-storefront`
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
  Done. The three commands share the kit's `check_configured_payments_access`; a
  malformed account exits 2. Each command module has `payments_section()` and
  `payments_transport()` seams (design.md, "The payments kit"). Versions: VM storefront
  0.25.0 → 0.26.0 (its exact pin on the bare-metal storefront moved), bare-metal
  storefront 0.25.0 → 0.26.0, API-credit storefront 0.18.0 → 0.19.0. VM's dev group
  declares `arkhai-kit-deal-lifecycle-client`.
  Tests, all pass: VM `tests/unit/cli/test_check_payments.py` (unit, at that path rather
  than the plan's); API credits `tests/unit/test_cli_check_payments.py` (unit); each
  covering ok, no section, an unreadable configuration, an unset key, a certificate
  failure, a refusal (VM), redaction and a real section read. Bare metal
  `tests/test_check_payments_cli.py`, over real configuration files, its last case in a
  fresh interpreter against a closed loopback port showing the `transport` step with no
  database module imported. Kit: three cases for the new call, and
  `test_access_check_tls.py`, a real TLS listener whose certificate no store trusts,
  reaching `transport` with no request sent.
- [x] 3.2 The unreachable-authority proof (D2). Application integration in the VM
  storefront's suite: an Agreement pinned to the `.invalid` authority, the storefront
  configured with an identity-bound `[[DisputeCredential]]` for it whose variable resolves
  to a labelled development value, and servicing stepped: the deal's lifecycle view reads
  `state == "running"` with a non-`Accepted` dispute outcome, and the respondent poll
  neither raises nor marks the deal for repair. Use an injected mediation transport that
  raises the DNS failure an `.invalid` origin produces, so the test needs no network. If
  the view reads otherwise, stop: D2 and the test-compatibility delta are revised
  together before section 4 (design.md D2).
  `tests/integration/test_servicing_unreachable_authority.py`: pass; D2 and the delta
  stand. Over `test_payment_settlement`'s harness (routes, real SQLite, real
  `VmDealLifecycle`, the kit's fake at `PaymentsClient`), servicing stepped by
  `VmDealLifecycle.cycle()`: both the respondent poll and the watch reach
  `dispute.invalid` and fail, the cycle completes, the buyer's `LifecycleClient.read`
  shows `authority.state == "running"` with an `Unknown` outcome. Correction to the
  task's wording: the poll does raise, and the cycle logs it at ERROR as its only error
  and retries next cycle (design.md); nothing is marked for repair. New seam:
  `VmDealLifecycle(..., mediation_transport=None)`.
- [x] 3.3 **Verification checkpoint.** Unit: the three CLI suites. Application
  integration: `test_servicing_unreachable_authority.py`. Run `make test-storefront`,
  `make test-bare-metal`, `make test-apicredits`, then `make test`,
  `make check-packaging` (versions and locks) and `make check-comment-hygiene`.
  End-to-end: none yet — section 4's lane targets run `check-payments`, and
  `e2e_vm_payment_deal`'s stage 2 exercises 3.2's behaviour once the VM lane is wired.
  None is owed here.
  Owed by validation: `tests.yml`, jobs `test · test-storefront`, `test · test-bare-metal`
  and `test · test-apicredits` — each passes from the relocked environments.

  Evidence: `make test-storefront`, `make test-bare-metal`, `make test-apicredits`, `make
  -C kit test-arkhai-payments`, `make test`, `make check-packaging`, `make
  check-uv-version` and `make check-change` pass. Owed by validation, corrected to add
  `tests.yml`, job `test · test-kits`: the payments kit suite passes, with
  `test_access_check_tls.py` and the `check_configured_payments_access` cases. The lanes'
  `check-payments` at setup and `e2e_vm_payment_deal`'s stage 2 are this section's
  end-to-end evidence (13.8).

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

Correction, replanned against the redesign (D9, D14–D21, D23): this section's wiring
through generated environment files — 4.2's `api_key_env` and `SSL_CERT_FILE` in the
storefronts' environment, 4.3's `PAYMENTS_LANE_DISPUTE_AUTHORITIES`, 4.4's
`e2e-<lane>-payments-env` targets and `lane_env.py compose|runner`, 4.5's
`SSL_CERT_FILE` probe — is superseded. Section 9 moves the stacks onto committed
overlays, profiles and secret overlays, and section 10 the runner onto committed lane
profiles. The double, the scenarios, `LANE_OWNED`, the mediation prerequisite and
`check-payments` at setup stand.

- [x] 4.1 The double in each lane (D1, D3, D6). `compose.payments-double.yml` runs
  `payments-double` on the lane's network with no host port, its healthcheck on `/health`
  over HTTPS with the lane CA. Each lane's `-f` list in `e2e-tests/Makefile` (and the
  matching `e2e-*-down`/`-logs` invocations) includes it. Each payment storefront —
  Bob's VM storefront, the bare-metal storefront, the API-credit storefront —
  `depends_on` it with `service_healthy`, mounts the lane CA and sets `SSL_CERT_FILE`.
  Done; each lane's one compose list (`E2E_*_COMPOSE`) carries the file. Storefront
  wiring is in lane-only overlays: `compose.bare-metal-local.yml`,
  `compose.apicredits-lane.yml` and a new `compose.vms-lane.yml` (`compose.vms-local.yml`
  is shared with the full stack). The CA mount at `/run/payments-lane-double/lane-ca.pem`
  stands; `SSL_CERT_FILE` and the token variable were superseded by section 9. Unit
  (`test_domain_stack_configuration.py`) and Compose render (`test_lane_compose.py`,
  `test_bare_metal_compose.py`) cases, as reworked by section 9: pass.
- [x] 4.2 Storefront payments configuration (D9, D2, D11's "deployment values"). Each
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
  Done as full lane copies — `domains/vms/storefront/storefront.bob.lane.toml`,
  `domains/apicredits/storefront/storefront.credits.lane.toml` — and the bare-metal
  `storefront.dev.toml` in place (it is the lane's alone); copies because list merging
  would duplicate `priority` (design.md). The API-credit copy adds a `[pricing].settlements`
  publication clause, without which no payment option is published. A unit test holds
  each copy equal to its stack profile less the payments additions. Since section 9 the
  key and Bob's `[[DisputeCredential]]` are in the secret overlays and the sections state
  `ca_bundle_path`.
- [x] 4.3 Registry recommendations (D7). Each lane's registry — both VM registries, the
  bare-metal registry, the API-credit registry and the compute registry it routes through
  — sets `REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES` to the pinned authority
  rendered from `tools/payments-lane-double/fixtures/dispute-authority.toml`, through the
  lane's dev-env target. No storefront or buyer configuration gains a `[[Dispute]]` entry.
  Done, then moved by section 9 into `dev-env/registry/config-payments-lane.env`, which
  each lane's five registries layer. `tools/payments-lane-double/scripts/lane_env.py`
  (stdlib-only, outside the wheel) now keeps only `seller-account` and `seller-token`
  (10.5). Every lane's payment option, which needs an authority advertising
  `arkhai.payments.v1`, is the system evidence.
- [x] 4.4 Per-lane settings and the test runner (D9). Each lane target passes its
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
  Done, then superseded by section 10's runner profiles. What stands: `SELLER_ACCOUNT`
  reaches every lane (the VM listing reads it as its payee); the buyer's marketplace
  credential is unpadded base64url; the API-credit refund signs with the lane
  storefront's eip191 key and trusts that pinned principal (design.md, "Lanes and
  stacks"). `config-docker.yml` is unchanged.
- [x] 4.5 The helper (D6). In `helpers/payments.py`: `PAYMENTS.LANE_OWNED`, a strict
  boolean defaulting to false; with it true, an unready target fails naming its URL
  rather than skipping. `target_ready` builds an `ssl.SSLContext` from `SSL_CERT_FILE`
  when it is set and passes it as `verify`, keeping `trust_env=False`. `settings.toml`
  documents `lane_owned` in `[default.payments]`. Unit (`test_payments_helper.py`): an
  unready lane-owned target fails naming the URL; an unready external target still
  skips; the probe uses a context built from `SSL_CERT_FILE` and disables environment
  proxies, through an injected readiness seam rather than the network.
  Done; `LANE_OWNED` with no `SERVICE_URL` also fails, naming both. The probe trusts
  `PAYMENTS.CA_BUNDLE_PATH` since 10.2, not `SSL_CERT_FILE`. Unit,
  `test_payments_helper.py`: pass (the probe cases replace `get`; no handshake).
- [x] 4.6 The VM scenario's mediation prerequisite (D2). A `MEDIATION.SERVICE_URL`
  setting, blank by default in `settings.toml`, read by a helper beside the payments
  helper; `test_vm_payment_deal.py`'s stages 3 and 4
  (`test_operator_end_files_one_case_without_a_local_payment_remedy`,
  `test_seller_refund_is_financial_and_release_waits_for_the_callback`) report a blocked
  skip naming it when blank; stages 1 and 2 run unchanged. Update the
  `e2e_vm_payment_deal` marker's description in `e2e-tests/pyproject.toml`. Raise
  `e2e-tests`' bound on `arkhai-kit-arkhai-payments` only if it uses the new API, and
  relock if it does. Unit: the helper blocks on blank and returns the URL otherwise.
  Done: `helpers/mediation.py`'s `configured_mediation()` and a `mediation_target`
  fixture requested by stages 3–4 only; `[default.mediation]` in `settings.toml`; all
  three payment markers' descriptions updated. The setting is a gate only. No new kit
  API, so no relock. Unit, `test_mediation_helper.py`: pass. Validation 82's VM lane
  skipped exactly stages 3–4.
- [x] 4.7 `check-payments` at lane setup (D6, D12). After `up --wait`, each lane target
  runs `docker compose exec <storefront> <cli> check-payments --account <the lane's
  seller account>` for each payment storefront, and fails the target, before pytest, on a
  nonzero exit.
  Done: an `e2e_check_payments` macro in `e2e-tests/Makefile` (`exec -T`, the account
  from `lane_env.py seller-account`, an `::error::` line naming the service on failure).
  Validation 82: `"outcome": "ok"` in all three lanes.
- [x] 4.8 `e2e-tests/README.md`: correct the passages sections 1–4 make false — the shared
  payment configuration (a lane now configures its own target, `LANE_OWNED`), "Hosted VM
  servicing" (stages 1–2 run against the double, 3–4 need `MEDIATION.SERVICE_URL`), and
  "Bare-metal payment deal" (it runs in the lane; the re-drive repeats the canonical
  commit). The rest of the permanent documentation is closeout's.
  Done, with the lane setup check; also `tools/payments-lane-double/README.md` and
  `dev-env/identities/README.md` ("The payments lane double"). Rewritten again by 10.6.
- [x] 4.9 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
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

  Evidence: the unit, release-tooling and render suites, `make test`, `make
  check-packaging` and `make check-change` passed; only the bare-metal lane ran locally in
  round 1. Every lane ran in sections 9 and 10 and in validation 82 (13.8). The
  introduction cases that failed on `dev`'s removal of the option-level `mechanism` key
  pass since the merge of `dev`. Owed by validation, corrected to add `tests.yml`, jobs
  `test · test-payments-lane-double` and `test · test-deployment-packaging` (the Compose
  render cases and `make -C helm test-render`).
  Round 1's triage: 30 V2 gave the VM payment deal its own executor, pool and resource
  (`kvm-payment-deal`, `compute-e2e-payment-deal-pool`, `compute-e2e-payment-deal-001`),
  since a listing's binding outlives the listing; 29 F1 made `target_ready` report an
  unloadable bundle unready; 31 O1 returned the change to design for the Makefile-carried
  configuration (D9, D13–D21).

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

Correction, replanned against the redesign (D3, D11, D19): 5.2's CA option setting
`SSL_CERT_FILE` and 5.3's payments-key option are superseded. Section 12 makes the CA
option derive `[Settlement.arkhai_payments].ca_bundle_path` and removes the payments-key
option, the key travelling in the agent's runtime secret overlay. The subchart, the
payments-only render case, the `helm test` check and validation's run of it stand.

- [x] 5.1 The subchart (D3, D11). `payments-lane-double`, disabled in `helm/values.yaml`,
  enabled in `helm/local-values.yaml` and disabled again in
  `helm/bare-metal-release-values.yaml`, so the two-release topology runs one double. Its
  Service is named `payments-double` (not release-prefixed), port 8443. Its Deployment
  runs `arkhai:payments-lane-double` under the image overlay the other local images use;
  with `tls.existingSecret` set it mounts that Secret's certificate and key over the
  image's own files, and otherwise uses the image's. Render tests: default disabled; the
  local values render one Deployment and a Service named `payments-double`; the topology
  values render none; `tls.existingSecret` mounts the Secret.
  Chart render, `helm/charts/payments-lane-double/tests/test_render.py`: pass. The
  Deployment is release-scoped, one replica, `Recreate`; `tls.existingSecret` names a
  `kubernetes.io/tls` Secret mounted by `subPath` over the image's files (render-level
  only; a deployment with its own Secret is unrun). `helm/values.yaml` restates the
  image so the overlay suffixes it (`test_image_overlay.py`). The double is outside
  `TOPOLOGY_ROLLOUT_ORDER` (design.md, "Helm").
- [x] 5.2 The CA bundle option (D3; delta "A storefront chart trusts a
  deployment-supplied CA bundle"), on both storefront charts: a value naming a ConfigMap
  and key, or alternatively a Secret and key, mounted read-only and named by
  `SSL_CERT_FILE`; no default; nothing rendered when unset; refused when both sources are
  named. Render tests for each source and unset.
  Done as `caBundle: {configMapName, secretName, key}` (per agent in the storefront chart,
  top level in bare metal), mounted as `/etc/arkhai/ca/ca-bundle.pem`; both sources, or a
  source without its key, refused. `SSL_CERT_FILE` was replaced by the derived
  `ca_bundle_path` in 12.1.
- [x] 5.3 The payments-key option (D11; delta "A storefront chart injects the payments key
  from a deployment Secret"), on both storefront charts: a value naming a Secret and key,
  exposed with `secretKeyRef` under the variable the agent configuration's
  `Settlement.arkhai_payments.api_key_env` names, read case-insensitively as the chart
  reads every key it uses; refused at render when the configuration names no
  `api_key_env`; nothing rendered when unset. Render tests: set, unset, and refused.
  Done, then removed by 12.2 (D19): the key is in the runtime secret overlay.
- [x] 5.4 The payments-only render case (D11): a storefront agent with payments
  configured and Wallet, Chains and Alkahest set to `null` and RPC off renders with the
  payments configuration, the CA mount and the key variable and nothing for the removed
  settings, on both charts.
  Chart render, one case per chart: pass, each also running the storefront's own startup
  check over the rendered document (these print a skip in CI, where no job has both Helm
  and the storefront environments). No storefront template reads `global.rpc`, so "RPC
  off" changes nothing rendered.
- [x] 5.5 The `helm test` payments check (D12; the delta's Helm half). A
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
  Chart render, two cases per chart: pass. Shared helpers `storefront.agentEnv`,
  `.agentConfigMounts`, `.agentConfigVolumes` and `bare-metal-storefront.env`,
  `.configMounts`, `.configVolumes`, through which each Deployment now renders. The
  equality case compares the pod's `env`, mounts and volumes with the Deployment's less
  the data and tun volumes, with persistence on. As built: `tests.paymentsAccount` is per
  agent in the storefront chart (one pod per agent, `<agent fullname>-payments-check`);
  "payments configured" means a non-empty section in any spelling; the pod also mounts the
  Alkahest address book when named.
- [x] 5.6 The local rehearsal (D11, D3, D7). `helm/local-values.yaml` configures Bob's
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
  Chart render, `helm/tests/test_release_topology.py`: pass — one double in release 1 at
  both storefronts' URL; every payments value equal to the double's fixtures; no
  `development_auth`; the e2e-tests chart refusing credential keys; `payments-ca-bundle`
  the one ConfigMap the releases read and the script creates (`LOCAL_CONFIGMAPS`, checked
  by `check-local-secrets`, which `deploy-local` now runs first). Correction: the e2e-tests
  chart's closed `payments` value carries only the public keys; the marketplace
  credentials and the buyer token are not carried, since charts take no credential in
  values and the release serves no payment scenario. `seller-payments-key` was retired by
  12.2; Bob's `[[DisputeCredential]]` reached the release in 12.6.
- [x] 5.7 **Verification checkpoint.** Chart render: `make -C helm test-render`, with every
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

  Evidence: `make -C helm test-render`, `make test-deployment-packaging`, `make -C
  tools/payments-lane-double test`, `make test`, `make check-packaging` and `make
  check-change` pass; no cluster was reached locally. Correction to the plan: validation's
  Helm part ran only the scenario pod, so round 1's triage (29 F2) made
  `scripts/validate_slice.py` run every `-payments-check` pod from the release's hooks as
  its own step, a pass counting only with exit status 0, a release rendering none warned,
  each log kept as evidence (D12; `test_validate_slice.py`). Validation 82 ran Bob's,
  exit 0. Owed observation confirmed, with `tests.yml`, job `test ·
  test-payments-lane-double` added for the `seller-token` case.
  Round 1's triage also: 29 documentation, the MODIFIED delta of "A storefront's
  configuration reaches it through its configuration system", since revised by the
  redesign (D19); and the owner's fix of `SQLiteClient.listing_id_for_derivation_key`,
  which called an undefined `_connect()` (a real-SQLite case in
  `core/storefront/tests/integration/test_listing_closure.py`).
  Destinations this section named, carried into 13.9: `DEPLOYMENT_AND_CONFIG.md`'s
  "Release topology" (`topology-up` restarts neither dev-env nor the double;
  `check-local-secrets` checks `LOCAL_CONFIGMAPS`; `deploy-local` runs it), its
  "Kubernetes: ConfigMap and Secret mounting" pod rule and its storefront pass-through
  table of the pod environment; `TESTING.md`'s "Chart Render Tests" and its account of
  what the Helm part runs and keeps; `.agents/skills/change-validate/SKILL.md`'s account
  of the Helm part, which names only the scenario pod.

## 6. The payments kit's secret key and configured CA

Delivers `[Settlement.arkhai_payments].api_key` as a secret setting, one key resolution,
`ca_bundle_path` with `PaymentsClient`'s CA argument, and the payments check's
`configuration` step for an unloadable bundle (D19's payments-key, one-resolution and
CA-bundle bullets; D12; settlement-configuration MODIFIED "Payments configuration
separates accounts and credentials"; deployment-state "A storefront checks its payments
access from its own container", scenario "The storefront's CA bundle cannot be loaded").

Files: `kit/arkhai-payments/src/market_arkhai_payments/{settlement_config.py, client.py,
access_check.py, __init__.py}`; `kit/arkhai-payments/tests/{test_settlement_config.py,
test_client.py, test_access_check.py, test_access_check_tls.py}`;
`kit/arkhai-payments/README.md`; `kit/arkhai-payments/pyproject.toml` and every lock
`make lock` rewrites; the storefront charts' generated `values.schema.json` files that
`make helm-values-schema` rewrites (`helm/charts/storefront/`,
`helm/charts/bare-metal-storefront/`).

- [x] 6.1 `ArkhaiPaymentsConfig` gains `api_key: SecretStr | None`, marked
  `json_schema_extra={"secret": True}` as the storefront's other secret fields are, and
  `ca_bundle_path: str | None` (D19). Validation, as `validate_development_auth` refuses
  today's conflicts: `api_key` is refused when empty; `api_key` with `api_key_env`, and
  either with `development_auth`, are refused naming both (the delta's "Both key forms are
  set"). Unit cases in `test_settlement_config.py`: each refusal; a configuration loaded
  from TOML text with `api_key` validates under the model's strict mode; `api_key` never
  appears in the model's `repr` or a dumped public view.
  Done. Unit, `test_settlement_config.py`: pass. Differs from the plan (design.md, "The
  payments kit"): the key-form conflicts are refused whether or not the section is
  enabled; an empty, blank or multi-line `api_key` and an empty `ca_bundle_path` are
  refused; the model sets `hide_input_in_errors`, held by
  `test_a_validation_error_never_shows_a_stated_key`.
- [x] 6.2 One key resolution (D19): a public function in `settlement_config.py`, exported
  from `__init__.py`, returning the `SecretStr` from `api_key`, otherwise from the variable
  `api_key_env` names in the mapping it is given (the process environment by default),
  and raising `ArkhaiPaymentsConfigurationError` naming the form that is missing or
  unavailable. `payments_client_for_owner`, `arkhai_payments_preflight` and
  `check_payments_access` call it and no longer read `api_key_env` themselves; the
  preflight's blocker for a missing key names both forms. Unit cases: each source,
  precedence when only one is configured, the preflight blocker, and the check's
  `credential` step from an `api_key` configuration with no environment variable set (the
  delta's "A storefront's key is in its secret overlay").
  Done: `resolve_payments_api_key(config, *, environment=None) -> SecretStr`, refusing a
  blank or multi-line variable too. The preflight's no-key blocker is
  `arkhai_payments.api_key_missing`. The check reports neither form as `configuration`
  and an unusable variable as `credential`. Unit, `test_settlement_config.py` and
  `test_access_check.py`: pass.
- [x] 6.3 `PaymentsClient(..., ca_bundle: str | None = None)` (D19): when set, the client
  verifies the service with an SSL context loaded from that file alone and passes it as
  the connection's verification, so the process trust store and the client's proxy
  behaviour are otherwise unchanged; `payments_client_for_owner` passes
  `config.ca_bundle_path`. `check_payments_access` reports a bundle `ca_bundle_path` names
  that is missing, unreadable or malformed as step `configuration`, with a fixed detail
  naming `ca_bundle_path`, before any request (D12). Round 1's `transport` classification
  of a process-level `SSL_CERT_FILE` that cannot be loaded stays, since a process may
  still set one. Cases in `test_access_check_tls.py`, which already serves TLS from a
  private CA: a client given the CA's bundle verifies the server with no `SSL_CERT_FILE`
  set; a client without it refuses (`transport`); a missing and a malformed
  `ca_bundle_path` report `configuration`.
  Done: `ssl.create_default_context(cafile=ca_bundle)` passed as `verify`; an empty
  `ca_bundle` is a `ValueError`. Library integration, `test_access_check_tls.py` (a real
  TLS listener on loopback, now issuing a private CA and leaf with the extensions
  Python 3.13 requires): the configured CA verifies; another CA's bundle or none fails
  `transport` with no request; a missing or malformed bundle fails `configuration` with
  the fixed detail. Unit, `test_client.py`: construction refusals. The process store
  being untouched off loopback is not tested (design.md).
- [x] 6.4 Package and schema housekeeping (RELEASING.md, "Versioning policy"; `AGENTS.md`,
  "Tests and diagnostics"). Bump `kit/arkhai-payments`'s version, `make lock`, and
  document `api_key`, `ca_bundle_path` and the resolution in `kit/arkhai-payments/README.md`.
  Run `make helm-values-schema`, so both storefront charts' generated definitions carry
  `ca_bundle_path` and refuse `api_key` in `config`; the storefronts' stale-schema unit
  test holds it.
  Done, without a bump: section 1's 0.6.0 is the one bump this change makes, so `make
  lock` changed no lock. The README documents both key forms, the resolution,
  `ca_bundle_path` and the check's steps. `make helm-values-schema` added `api_key: false`
  and `ca_bundle_path` to both storefront charts' schemas and the umbrella's copy.
- [x] 6.5 **Verification checkpoint.** Unit and library integration: `make -C kit
  test-arkhai-payments`. Unit: the three storefront CLI suites still pass over the kit
  (`make test-storefront`, `make test-bare-metal`, `make test-apicredits`), the VM
  storefront's stale-schema test included. `make test`. `make check-packaging`, since the
  kit's version and locks change.
  End-to-end: none yet — the lanes take `api_key` and `ca_bundle_path` in section 9, and
  `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` and `e2e_vm_payment_deal`
  exercise them from then. None is owed here.
  Owed by validation: `tests.yml`, job `test · test-kits` — the payments kit suite passes
  from the relocked environment with the new cases; jobs `test · test-storefront`,
  `test · test-bare-metal` and `test · test-apicredits` — each passes from the relocked
  environments.
  Evidence: the kit suite, the three storefront suites, `make test-payments-lane-double`,
  `make -C helm test-render` and `make check-packaging` pass. `make test` failed only on a
  `test_change_workflow_assumptions` case failing on `HEAD` before this section, later
  fixed on the branch (9.7).

## 7. Dispute credentials carry secrets; the mediation credential carries the token

Delivers `DisputeCredential.api_key`, a `MediationCredential` that carries a validated
resolved token, a `MediationClient` that reads no environment, and every direct
constructor migrated (D19's dispute-credentials bullet and contract; D2's VM storefront
credential; settlement-configuration MODIFIED "Dispute credentials are bound by identity
and no template ships an authority", its scenarios "A storefront's dispute credential is
in its secret overlay" and "A mediation credential is built from an unusable token").

Files: `kit/deal-lifecycle/src/market_deal_lifecycle/configuration.py` and a new
`kit/deal-lifecycle/tests/unit/test_dispute_credential.py`;
`kit/arkhai-mediation/src/market_arkhai_mediation/client.py`,
`kit/arkhai-mediation/README.md`, `kit/arkhai-mediation/examples/first_use.py`,
`kit/arkhai-mediation/tests/integration/{test_adapter.py, test_ruling_traces.py}`;
`kit/deal-servicing/examples/{receipt_first_use.py, respondent_first_use.py,
seller_first_use.py, watch_first_use.py}`,
`kit/deal-servicing/tests/integration/{test_filing_owner_recovery.py, test_respondent.py,
test_review_fix_a.py}`; `domains/vms/storefront/src/market_storefront/deal_lifecycle.py`,
`domains/vms/storefront/tests/integration/{test_lifecycle_admin.py,
test_lifecycle_ends.py, test_servicing_unreachable_authority.py}`;
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`;
`domains/vms/buyer/src/arkhai_vms_buyer/lifecycle.py` and
`domains/vms/buyer/tests/test_lifecycle_adoption.py`;
`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/lifecycle.py` and
`domains/bare_metal/buyer/tests/test_lifecycle_adoption.py`; the touched kits'
`pyproject.toml` versions and every lock `make lock` rewrites. Scripts under
`docs/attachments/` keep their wording (D18, D19).

- [x] 7.1 `DisputeCredential` gains `api_key: SecretStr | None`, refused when empty at
  configuration validation as a malformed `api_key_env` is, and one of `api_key` and
  `api_key_env` is required, both refused as `ArkhaiPaymentsConfig` refuses both key
  forms (D19). `resolve()` returns `api_key` when set, otherwise
  the variable's value, and still raises `ValueError` for an unset or empty variable, which
  the storefronts' `credential_available` reads as no usable credential (D2's
  `repair_required`). Unit cases in `test_dispute_credential.py`: each form, both or
  neither refused, an empty `api_key` refused, `resolve()` from each form and its
  `ValueError`, and the token absent from `repr`.
  Done. Unit, `test_dispute_credential.py`: pass, with an `api_key` entry loaded from TOML
  through `dispute_config`. Differs from the plan: a padded or multi-line `api_key` is
  refused too, by `MediationCredential`'s rules; `DisputeCredential` and `DisputeConfig`
  set `hide_input_in_errors` (design.md).
- [x] 7.2 `MediationCredential(identity, *, token: SecretStr)` (D19's contract): the field
  is renamed and keyword-only; `__post_init__` raises `TypeError` for a token that is not a
  `SecretStr`, and `ValueError` for an empty token, one with surrounding whitespace, or one
  containing CR or LF — the checks `MediationClient.__init__` makes today, moved there.
  `MediationClient` loses `environ=` and reads no environment. Library integration cases
  in `kit/arkhai-mediation/tests/integration/test_adapter.py`: each refusal, including an
  unmigrated positional `MediationCredential(identity, "DEMO_PAYEE")` failing at
  construction; a client built from a valid credential authenticates with exactly that
  token.
  Done (`field(kw_only=True)`). Library integration, `test_adapter.py` against the kit's
  contract fake: pass — each refusal unquoted, a credential bound to another authority
  refused, a filing sending exactly `Bearer fixture-payee`. The refusal cases stay in the
  kit's only test directory, `tests/integration/`.
- [x] 7.3 Migrate every direct constructor (D19): the VM and bare-metal storefronts' and
  buyers' lifecycle composition obtain the token through `DisputeCredential.resolve()` and
  build `MediationCredential(identity, token=...)`; the `kit/arkhai-mediation` and
  `kit/deal-servicing` examples and the kit and domain tests named above pass
  `token=SecretStr(...)` instead of an `environ` mapping; `kit/arkhai-mediation/README.md`
  shows the new form. A repository search for `MediationCredential(` and `environ=` at
  mediation call sites finds no unmigrated use outside `docs/attachments/`.
  `test_servicing_unreachable_authority.py` gains a case whose `[[DisputeCredential]]`
  states `api_key` with no variable set, and still reads `state == "running"` with a
  non-`Accepted` dispute outcome, the poll's transport error reaching the cycle, which
  logs it and completes, and no repair mark (D2).
  Done; the search finds no unmigrated use. Application integration,
  `test_servicing_unreachable_authority.py`, parametrized over an `api_key` entry and a
  variable entry: pass, every mediation request carrying `Bearer <token>`. The secret
  overlay's merge is shown by the bare-metal unit case
  `test_payments_and_dispute_keys_are_read_from_the_secret_overlay`. Unit, both buyers'
  `test_lifecycle_adoption.py`: an unset variable is a `MediationTransportError` and no
  client. The bare-metal settings' `settlement` and `disputecredential` are `repr=False`.
  Deferred: the `kit/deal-servicing` examples (`make -C kit/deal-servicing first-use`)
  and the mediation demo were not run (the calls were denied in that session, and neither
  kit's test target runs them); the mediation example is type-checked by its suite, the
  four deal-servicing examples by nothing run here.
- [x] 7.4 Bump the versions of `kit/deal-lifecycle` and `kit/arkhai-mediation` and of any
  other package whose public surface changed, and `make lock` (RELEASING.md, "Versioning
  policy").
  `kit/deal-lifecycle` and `kit/arkhai-mediation` 0.1.0 → 0.2.0; both storefronts, both
  buyers and `kit/deal-servicing`'s dev group raise their lower bounds; the buyers take
  patch bumps (VM 0.10.0 → 0.10.1, bare metal 0.7.0 → 0.7.1). `make lock` rewrote every
  lock carrying the kits.
- [x] 7.5 **Verification checkpoint.** Unit and library integration: `make -C kit
  test-deal-lifecycle`, `make -C kit test-arkhai-mediation`, `make -C kit
  test-deal-servicing` (its examples run as tests where they are collected). Application
  integration: `make test-storefront` (the lifecycle and unreachable-authority cases),
  `make test-bare-metal`, `make test-vms-buyer`. `make test`. `make check-packaging`.
  End-to-end: `e2e_vm_payment_deal`'s stage 2 exercises the VM storefront's credential
  once section 9 puts it in Bob's secret overlay; none is owed here.
  Owed by validation: `tests.yml`, jobs `test · test-kits`, `test · test-storefront`,
  `test · test-bare-metal` and `test · test-vms-buyer` — each passes from the relocked
  environments with the migrated constructors.
  Evidence: the four kit suites (the deal-servicing examples are not collected, 7.3), the
  storefront, bare-metal and VM buyer suites, `make helm-values-schema` (no change) and
  `make check-packaging` pass; `make test` failed only on the pre-existing case 6.5
  records. The plan gap the fresh-context check found — the storefront values schemas did
  not refuse a dispute credential in `config` — was closed by 12.6 and 12.7.

## 8. The registry reads profile-shaped env files

Delivers the registry's `CONFIG_DIRECTORY`/`ACTIVE_PROFILES` loading of
`config-<profile>.env`, the `registry_filter_spec_path` setting the filter-specification
loader reads through an injected `Settings`, and the unread variables removed (D16's
registry half; deployment-state "The registry reads profile-shaped env files", its loader
obligation and scenarios "A lane registry layers a lane profile" and "A profile selects
the filter specification").

Files: `core/registry/src/core_registry/{config.py, api/filter_spec.py}` and the
filter-specification loader's callers; `core/registry/tests/unit/test_filter_spec.py`,
`core/registry/tests/integration/test_settled_envelope_across_specs.py`, a new
`core/registry/tests/unit/test_config_profiles.py`; `core/registry/Dockerfile`,
`core/registry/.env.docker-compose`; `core/registry/README.md`;
`core/registry/pyproject.toml` and its lock.

- [x] 8.1 Profile env files (D16). `Settings` loads, after its current dotenv defaults,
  `<CONFIG_DIRECTORY>/config-<profile>.env` for each entry of `ACTIVE_PROFILES` in order,
  a later file overriding an earlier one and the process environment overriding every
  file. Both resolver variables are read from the process environment by the composition
  that builds `Settings`, not as settings. The profile files extend the dotenv list the
  class already reads, so a profile file that does not exist is skipped as a missing
  default file is. The misleading comment on `.env.local`'s priority states the actual
  order. Unit cases in `test_config_profiles.py`, against files in a temporary directory:
  two profiles layering, the later winning; the process environment winning over both;
  no `ACTIVE_PROFILES` loading the defaults alone; a JSON list
  (`REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES`) parsed from a single-quoted line;
  a hex identifier read as a string.
  Done: `config.profile_env_files(environment)` and `config.load_settings(environment=None)`
  (`Settings(_env_file=(*DEFAULT_ENV_FILES, *profiles))`); `settings = load_settings()`
  reads the resolver variables from the process (`CONFIG_DIRECTORY` defaulting to the
  working directory). Profile names parse as `arkhai-kit-config`'s
  `parse_active_profiles` does, restated (promotion records it, 13.9). Unit,
  `test_config_profiles.py`, each in an empty working directory: pass, with the
  default-then-profile order and a missing profile skipped.
- [x] 8.2 The filter-specification path (D16). `registry_filter_spec_path` is a `Settings`
  field aliased to `REGISTRY_FILTER_SPEC_PATH`, unset meaning the packaged
  `filter-spec.yaml`. `api/filter_spec.py` resolves its default path from a `Settings` it
  is given, defaulting to the module's `settings`, and no longer reads `os.environ`. The
  cases in `test_filter_spec.py` and `test_settled_envelope_across_specs.py` that select
  a specification through `monkeypatch.setenv` pass a `Settings` instead (`AGENTS.md`,
  "Tests and diagnostics"). A new case loads a specification a profile file names, with no
  process variable set (the delta's "A profile selects the filter specification").
  Done: `resolve_spec_path(settings=None)`, `load_filter_spec(path=None, *,
  settings=None)` and `reset_cache(settings=None)`, the existing seam extended; routes
  still call `get_loaded_spec()`. Unit, `test_filter_spec.py`, and application
  integration, `test_settled_envelope_across_specs.py` (a profile env file naming the
  specification, no process variable): pass. The startup path is covered by 8.1's
  process-environment case and the lanes.
- [x] 8.3 The unread variables (D16). Remove `ENABLE_HEALTH_CHECKS`,
  `HEALTH_CHECK_INTERVAL`, `ENDPOINT_CHECK_TIMEOUT` and `HEARTBEAT_TTL_SECS` from
  `core/registry/Dockerfile` and `core/registry/.env.docker-compose`, after confirming by
  search that nothing reads them (the chart's copies and `CHAIN_ID` go in section 11).
  Document the profile loading and the setting in `core/registry/README.md`. Bump the
  registry's version and relock if its metadata changed.
  Done: no reader found; removed also from `core/registry/docker-compose.yml`,
  `core/registry/.env.sample` and the root `config.registry.env.example`.
  `core/registry/README.md` gains "Configuration files". Registry 0.4.1 → 0.5.0,
  relocked. Deferred: `domains/vms/provisioning/iac/README.md` still shows the four
  variables in an example command, to be corrected where that document is next
  maintained.
- [x] 8.4 **Verification checkpoint.** Unit and application integration: `make
  test-registry`. `make test`. `make check-packaging` when the version or lock changed.
  End-to-end: none yet — the lane registries take profiles in section 9 and the chart in
  section 11; every lane's publication and discovery scenarios exercise the registry from
  then. None is owed here.
  Owed by validation: `tests.yml`, job `test · test-registry` — passes with the new and
  reworked cases.
  Evidence: `make test-registry` and `make check-packaging` pass; `make test` failed
  only on the pre-existing case 6.5 records. Handoff to promotion: the registry restates
  `parse_active_profiles`, which `deployment-state`'s architecture companion
  ("Configuration bootstrap boundary") places in `arkhai-kit-config`.

## 9. Compose stacks on committed overlays, profiles and secret overlays

Delivers every lane's and the full local stack's configuration in committed files: base
and domain files without development binds or guards, literal binds in the root-level
overlays, the five lane registries on profile env files, the three provisioning services
on site profiles, storefront payments, dispute and wallet keys in secret overlays, the
payments CA as `ca_bundle_path`, and the provisioning mode interpolated last (D15, D16's
lane profiles, D17, D19, D20's overlay half, D23, D7, D2, D3; deployment-state "A stack's
configuration lives in committed files" and "A storefront's secrets reach it through its
secret overlay").

Files: `domains/vms/compose.yml`, `domains/apicredits/compose.yml`,
`domains/bare_metal/compose.yml`; `compose.bare-metal.yml`, `compose.vms-local.yml`,
`compose.apicredits-local.yml`, `compose.vms-lane.yml`, `compose.apicredits-lane.yml`,
`compose.bare-metal-local.yml`, and the header comments of `compose.vms.yml`,
`compose.apicredits.yml`, `compose.payments-double.yml`; new
`dev-env/registry/config-{registry-a, registry-b, api-credits-registry, compute-registry,
bare-metal-registry, payments-lane}.env`; new
`dev-env/provisioning/config-{vms-bob-site, vms-alice-site, bare-metal-site}.yml`;
`dev-env/identities/{bob.storefront.secrets.toml, bare-metal.storefront.secrets.toml}`,
new `dev-env/identities/{alice.storefront.secrets.toml,
api-credits.storefront.secrets.toml}`; deleted
`domains/vms/storefront/{.env.bob.docker, .env.alice.docker}` and
`dev-env/identities/api-credits.wallet.env`; the lane storefront configurations
`domains/vms/storefront/storefront.bob.lane.toml`,
`domains/apicredits/storefront/storefront.credits.lane.toml`,
`domains/bare_metal/storefront/storefront.dev.toml`; `scripts/tests/{test_lane_compose.py,
test_bare_metal_compose.py, test_multi_storefront_compose.py}`.

- [x] 9.1 Base files keep topology (D15). Every development bind and every `${VAR:?…}`
  guard for one leaves `domains/{vms,apicredits,bare_metal}/compose.yml` and
  `compose.bare-metal.yml`; values the topology fixes — service names, ports, data paths,
  the definition documents' container paths, `REDIS_URL`, callback URLs — stay. First
  confirm, by bringing each affected service up without its binds, that it refuses to
  start; a service that starts without one keeps that guard, recorded here with the
  service and what it started without.
  Done. Left in the base files: the domain files' defaulted operator knobs and the VM
  provisioning's `${HOME}/.ssh/id_ed25519` (an operator's real key). `compose.bare-metal.yml`
  keeps `DATABASE_URL` and its `extends`; its buyer service moved whole into
  `compose.bare-metal-local.yml`. The bring-up without binds was not run (the step could
  run `docker` only through the lane targets); the refusal rests on each service's startup
  code, and the bare-metal site, which starts without its SSH key, lost its guard too
  (design.md, "Lanes and stacks"). Compose render,
  `test_a_base_file_renders_alone_with_no_development_bind`: pass.
- [x] 9.2 Literal overlays (D15). The `-local` and `-lane` overlays bind every committed
  file the base files no longer name, stated relative to the repository root: credential
  and identity files, storefront configurations and secret overlays, the bare-metal host
  and pool documents and SSH placeholder, the lane CA, and the buyer runtime directories
  as `./.e2e-buyer/…` (D18). The VM lane's Bob configuration and the API-credit lane's
  storefront configuration replace the base mount by its target. No overlay reads a
  variable but `PROVISIONING_MODE` (9.4).
  Done, the overlays also binding the Alkahest address book; the buyer services' `image`
  and `user` are literal. Compose render, `test_every_overlay_bind_names_a_committed_file`
  and the mount cases, every stack rendered with no environment file: pass.
- [x] 9.3 Registry profiles (D16, D7). Each of the five lane registries sets
  `CONFIG_DIRECTORY=/etc/arkhai/registry` and its `ACTIVE_PROFILES`, binds
  `./dev-env/registry`, and keeps only its credential bind; its `REGISTRY_*` values move
  from `environment:` and from the bare-metal wrapper's variables into its
  `config-<registry>.env` — registry-b's admin and bootstrap keys and the API-credit
  registry's filter specification path included. `config-payments-lane.env` holds the
  recommended dispute authorities, one JSON line restating
  `tools/payments-lane-double/fixtures/dispute-authority.toml`; each lane overlay appends
  `payments-lane` to its registries' profiles (both VM registries, the API-credit and
  compute registries, the bare-metal registry). The full local stack's registries load
  their own profiles without `payments-lane`. Each file carries the public-development
  label.
  Done; registry-b's profile also carries its read and write gates; `compute-registry` no
  longer binds `./shared-env`. Compose render,
  `test_each_registry_profile_pins_the_credential_its_registry_mounts`,
  `test_the_lane_profile_recommends_the_double_pinned_authority` and the profile cases:
  pass. Every lane run since started its registries from these profiles.
- [x] 9.4 Provisioning site profiles and the mode (D17, D20). `provisioning`,
  `alice-provisioning` and `bare-metal-provisioning` set `CONFIG_DIRECTORY=/app/config`,
  bind the packaged `config.yml` and `config-docker.yml` from
  `provisioning/compute/service/src/compute_provisioning_service/config/` and their site
  profile as single files, and state `ACTIVE_PROFILES=docker,<site>,${PROVISIONING_MODE:-mock}`;
  their `PROVISIONING_*` identity, storefront-identity, site-id and admin-identity
  variables move into the site profiles as quoted YAML strings, and the `@str` comments go.
  The base files keep `ACTIVE_PROFILES=docker`.
  Done: `dev-env/provisioning/config-{vms-bob-site, vms-alice-site, bare-metal-site}.yml`;
  `config-mock.yml` is not bound (mock is selected by the profile name), so lanes run
  `docker,<site>,mock`. Callback URLs stay in the base files. Compose render cases for
  the VM and bare-metal provisioning profiles under each mode and the site profiles'
  pins: pass.
- [x] 9.5 Storefront secrets and trust (D19, D23, D2, D3). The lane storefronts' payments
  key is `[Settlement.arkhai_payments].api_key` in their secret overlay (Bob's, the
  bare-metal storefront's, the API-credit storefront's new one), restating the seller token
  in `tools/payments-lane-double/fixtures/accounts.toml`; their lane configurations drop
  `api_key_env` and state `ca_bundle_path = "/run/payments-lane-double/lane-ca.pem"`, the
  overlay binding the lane CA there. The VM lane's `[[DisputeCredential]]` moves whole into
  Bob's secret overlay with an `api_key`, retiring `VM_LANE_DISPUTE_API_KEY`. Bob's and
  Alice's `[Wallet] private_key` and the API-credit storefront's move from the
  `STOREFRONT_`/`APICREDITS_STOREFRONT_` override variables into their secret overlays,
  Alice's new; the wallet env files are deleted once a search confirms no other reader.
  No `SSL_CERT_FILE`, `ARKHAI_PAYMENTS_API_KEY` or wallet variable is left in any overlay.
  Done; the three wallet env files had no other reader and are deleted. The full local
  stack mounts the same secret overlays, inert there; `storefront.credits.toml` states no
  key form, since two forms are refused even in a disabled section. Unit,
  `test_domain_stack_configuration.py`'s lane cases,
  `test_no_storefront_reads_a_secret_from_its_environment` and
  `test_each_storefront_secret_overlay_fits_the_configuration_beside_it`: pass. System:
  each lane's `check-payments` read with the overlay's key and the configured CA, the
  API-credit storefront settled with its overlay's wallet key, and the VM deal's stage 2
  read `running` on Bob's overlay credential.
- [x] 9.6 Restated values held to their sources (D21, the stack half). In
  `scripts/tests/`, replacing the compose test modules' checks of variables: each
  registry profile's principal derives from its credential file; the provisioning site
  profiles' pins equal the runner's `config-docker.yml` pins; the secret overlays' tokens
  equal `accounts.toml`; `config-payments-lane.env` equals `dispute-authority.toml`; each
  lane configuration's `ca_bundle_path` is the target its overlay binds the lane CA to;
  every overlay bind's source exists; `docker compose config` renders every lane's and the
  full stack's file list with no environment file, and no rendered base file carries a
  development bind.
  Done: `scripts/tests/test_committed_stack_values.py` (new) and the three compose test
  modules rewritten to render with no environment file; also registry-b's bootstrap key
  held equal across its four copies. `make test-release-tooling` gains `--with pyyaml`.
  Limits: renders use the caller's environment less `PROVISIONING_MODE`; "exists" means
  present in the checkout; overlay `environment:` values are checked by reading the five
  overlays, not by a test. Unit, `make test-release-tooling`, none skipped: pass.
- [x] 9.7 **Verification checkpoint.** Unit: `make test-release-tooling` (the compose test
  modules and 9.6's cases). System, from this checkout: each lane's stack comes up from its
  Compose files alone (`docker compose -p <project> -f … up -d --wait`) and its storefront's
  `check-payments` prints `ok`; the full local stack comes up with its documented file list.
  `make test`.
  End-to-end: every marker of the three lanes runs on these stacks once section 10
  changes the lane targets; `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` and
  `e2e_vm_payment_deal` exercise the secret overlays, `ca_bundle_path` and the dispute
  credential.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — `make
  test-release-tooling`'s compose render cases pass.

  Evidence: `make test-release-tooling`, `make test-e2e-unit`, `make -C helm
  test-render` and `make test` pass. System, through the three lane targets (the stacks
  came up from their Compose files alone, under mock): each lane's `check-payments` ok,
  `e2e_credits_payment_deal` (first lane run of it), `e2e_bare_metal_payment_deal` and
  `e2e_vm_payment_deal` stages 1–2 passing with 3–4 skipped. The direct `docker compose`
  bring-up and the full local stack's are unrun. Owed by validation, extended:
  `test · test-deployment-packaging` (the compose render cases and
  `test_committed_stack_values.py`) and `test · test-e2e-unit` (the static stack cases).
  The fresh-context check's fixes include `docs/bare-metal-seller-quickstart.md`, which
  now gives an operator overlay, registry profile and site profile (closeout confirms it,
  13.3), and `tools/issue-discovery`'s two `compose_up` phases, which set
  `PROVISIONING_MODE`. Destination this section made false, carried into 13.9:
  `DEPLOYMENT_AND_CONFIG.md`'s "Bare-metal role configuration" ("The Compose wrapper
  mounts the operator's storefront.toml…").

## 10. The runner's lane profiles and the Make targets

Delivers the runner's shared payments profile and per-lane profiles, the helper's token
and CA handling, lane targets naming only their files and mode, and the environment
targets retired (D14, D18, D20's Make half, D21's runner half and `lane_env.py`, D6's
probe; test-compatibility "A lane's runner reads committed lane profiles"; deployment-state
"A stack's configuration lives in committed files", scenario "A lane stack is brought up").

Files: new `e2e-tests/config/config-payments-lane.yml` and
`e2e-tests/config/config-{vms,bare-metal,apicredits}-lane.yml`;
`e2e-tests/tests/e2e/roles/helpers/payments.py` and the shared buyer-configuration writer
it uses; `e2e-tests/settings.toml`; `e2e-tests/tests/unit/{test_payments_helper.py,
test_domain_stack_configuration.py}`; `e2e-tests/Makefile`; the root `Makefile`;
`tools/payments-lane-double/scripts/lane_env.py` and
`tools/payments-lane-double/tests/integration/test_lane_env.py`; `.gitignore`;
`docker-compose.yml`'s header; `dev-env/identities/README.md`;
`docs/development/VALIDATION_RUNBOOK.md` (§6's mock-profile note, §8's full stack);
`e2e-tests/README.md`; `tools/payments-lane-double/README.md`.

- [x] 10.1 Runner profiles (D14). `config-payments-lane.yml` holds the shared `payments`
  section — service URL and identity, fee, livemode, `lane_owned`, `ca_bundle_path`,
  `api_key_env`, `buyer_api_key`, the buyer and seller accounts and the buyer's marketplace
  seed — and each `config-<lane>-lane.yml` only its seller marketplace credential, the
  bare-metal one adding `compute_hourly_gross` and `dispute_window`. Each file carries the
  public-development label. `e2e-tests/settings.toml` documents `ca_bundle_path` and
  `buyer_api_key` with empty defaults.
  Done: `e2e-tests/config/config-{payments-lane, vms-lane, apicredits-lane,
  bare-metal-lane}.yml`, quoted strings so no `@str` is needed. Unit: 10.5's profile
  cases, and through the runner's own loader
  `test_a_lane_runner_loads_a_complete_payments_section` and
  `test_a_runner_without_the_lane_profiles_has_no_payments_target`: pass.
- [x] 10.2 The helper (D14, D6). The payments helper writes `PAYMENTS.BUYER_API_KEY` into
  the `market` subprocess's environment under the variable `PAYMENTS.API_KEY_ENV` names,
  as provisioning writes `ANSIBLE_CONFIG` from its settings; the readiness probe trusts
  `PAYMENTS.CA_BUNDLE_PATH` with proxies still disabled; the shared buyer-configuration
  writer passes `ca_bundle_path` into the buyer's `[Settlement.arkhai_payments]`. The probe
  no longer reads `SSL_CERT_FILE`. Unit cases in `test_payments_helper.py`: the token
  reaches the subprocess environment and no other; the probe trusts the configured bundle
  and fails on a missing one; the buyer configuration carries `ca_bundle_path`.
  Done, beyond the plan's wording: the scenarios' in-process payments clients need the
  key too, so `buyer_payments_environment(config)` hands it to the `market` process
  (`create_profiled_buyer_cli`'s `credential_environment`) and `buyer_payments_client`
  to in-process clients, writing it into no process environment (design.md). The VM,
  API-credit and bare-metal scenarios use them. `target_ready(url, ca_bundle=…)` lost its
  `environ` seam; `payment_config_toml` writes `ca_bundle_path`. Unit,
  `test_payments_helper.py`: pass (that `BuyerCli.run` merges `credential_env` is read
  from code, not tested).
- [x] 10.3 Lane targets (D18, D20, D14). In `e2e-tests/Makefile`: each `test-e2e-<lane>`,
  `e2e-<lane>-down` and `e2e-<lane>-logs` names its Compose files and project only, with
  `PROVISIONING_MODE` exported to Compose; `test-buyer-machine` takes `RUNNER_PROFILES`
  (each lane target sets `docker,payments-lane,<lane>-lane`; unset, `docker` alone) and one
  literal lane-CA mount, and passes no environment file; `e2e_env_if_missing`, the
  environment-file variables and the stale "deadlines" comment go. `check-payments` at
  setup keeps `lane_env.py seller-account`.
  Done; the `mock`/`real` check is `E2E_REQUIRE_PROVISIONING_MODE`, first in each
  `test-e2e-<lane>`, `PROVISIONING_MODE` defaulting to `mock`. Unit,
  `scripts/tests/test_lane_compose.py` (`make -n` with `MAKE=:`): an unknown mode fails;
  no `--env-file`; `RUNNER_PROFILES` and the CA mount reach the runner. The export is
  shown by the lane runs.
- [x] 10.4 Retire the environment targets (D18, D20). In the root `Makefile`: remove
  `e2e-vms-dev-env`, `e2e-apicredits-dev-env`, `e2e-bare-metal-dev-env`, both
  `e2e-*-stack-env` helpers, `e2e-dev-identities`, `e2e-dev-identities-env`, the three
  `e2e-<lane>-payments-env`, their variables, the buyer seed and the `sed` read, and their
  `.PHONY` entries; keep the `PROVISIONING_MODE` `mock`/`real` check for the targets that
  bring a stack up. `.gitignore` drops the generated environment files and keeps
  `.e2e-buyer/`. `.github/workflows/e2e.yml`'s `PROVISIONING_MODE` keeps working unchanged.
  Done; `e2e.yml`'s comment now says the lane targets hand the mode to Compose.
  Correction: `.gitignore` keeps `.e2e-*.env` (design.md). Remaining readers of the
  retired targets, carried into 13.9: `DEPLOYMENT_AND_CONFIG.md`'s "Per-domain stack
  composition" and `TESTING.md`'s lane paragraph on `PROVISIONING_MODE`; dated records
  under `docs/attachments/` keep their wording.
- [x] 10.5 `lane_env.py` (D21). It keeps only `seller-account` and `seller-token`; the
  `compose` and `runner` modes, `CA_MOUNT`, `BUYER_API_KEY_ENV` and `_setting` go.
  `test_lane_env.py` follows, and gains the runner half of D21: the runner profiles' tokens,
  accounts, receipt identity and fee equal `accounts.toml`, and each lane profile's seller
  key equals the `ARKHAI_IDENTITY_CREDENTIAL` of the identity file its storefront signs
  with (`bob.identity.env`, `api-credits.identity.env`).
  Done; `SERVICE_URL` stays for `helm/tests/test_release_topology.py`, which now compares
  the e2e-tests chart's profile with the fixtures and `config-payments-lane.yml`. The
  double's dev group gains `pyyaml>=6`, relocked. Library integration, `make
  test-payments-lane-double`, and chart render: pass.
- [x] 10.6 Documents the targets named (D18). `docker-compose.yml`'s header and
  `VALIDATION_RUNBOOK.md` §8 give the full stack's `docker compose -f docker-compose.yml -f
  compose.vms-local.yml -f compose.apicredits-local.yml up -d`, the runbook's buyer step
  creating `.e2e-buyer/…` first and §6's note naming `PROVISIONING_MODE`;
  `dev-env/identities/README.md`'s table lists each stack's overlays and profiles instead
  of a target, and its fixture statements cover the new secret overlays and profiles;
  `e2e-tests/README.md`'s "Shared payment-scenario configuration" and lane passages and
  `tools/payments-lane-double/README.md` describe the profiles and secret overlays. Dated
  records under `docs/attachments/` keep their wording.
  Done; the runbook has no step running a buyer by hand, so §8 notes the `.e2e-buyer/`
  directories. `e2e-tests/config/config-docker.yml`'s bare-metal comment corrected.
- [x] 10.7 **Verification checkpoint.** Unit: `make test-e2e-unit`,
  `make test-payments-lane-double`, `make test-release-tooling`. System:
  `make -C e2e-tests test-e2e-vm`, `test-e2e-bare-metal` and `test-e2e-apicredits` from
  this checkout, each lane's markers green as before; `make test`.
  End-to-end: `e2e_bare_metal_payment_deal` (bare-metal lane) and
  `e2e_credits_payment_deal` (API-credit lane) pass without skips, `e2e_vm_payment_deal`'s
  stages 1–2 pass and 3–4 report the mediation blocked skip (VM lane), and every other
  marker in the three lanes' module lists stays green.
  Owed by validation: `tests.yml`, jobs `test · test-e2e-unit`,
  `test · test-payments-lane-double` and `test · test-deployment-packaging` — each passes.

  Evidence: the three unit suites, `make -C helm test-render`, `make test`, `make
  check-packaging` and `make check-change` pass. System, through the rewritten lane
  targets, no environment file written or read: each lane's `check-payments` ok under
  `docker,payments-lane,<lane>-lane`; the bare-metal and API-credit payment deals pass
  with no skip; the VM deal's stages 1–2 pass and 3–4 skip; every other marker passed but
  the introduction cases failing on `dev` then (since fixed by the merge of `dev`). Owed
  observations confirmed as written. The local Helm release's e2e-tests profile carries
  no `ca_bundle_path` and no buyer key; it serves no payment scenario (D11).

## 11. The registry chart's env-file profile

Delivers the registry chart rendering its values as `config-production.env`, the
`secretProfile` option, the retired key Secrets refused, and a Deployment environment of
the two resolver variables (D16's chart half; deployment-state "The registry reads
profile-shaped env files", scenarios "The registry chart renders a release" and "A values
file uses a retired key Secret").

Files: `helm/charts/registry/templates/{deployment.yaml, _helpers.tpl}`, a new
`helm/charts/registry/templates/configmap.yaml`; `helm/charts/registry/values.yaml`;
`helm/values.yaml` and `helm/values.schema.json` where they state the registry aliases'
`auth`; `helm/scripts/test-render.sh`; `helm/tests/test_release_topology.py`.

- [x] 11.1 The rendered profile (D16). A ConfigMap key `config-production.env` renders the
  identity, descriptor, `config.*` the registry reads, `PORT` from `service.port`, the
  constant `REGISTRY_AUTHORITY_CREDENTIAL_FILE` and `REGISTRY_FILTER_SPEC_PATH` from
  `config.filterSpecPath`, each value quoted for a dotenv reader and the dispute
  authorities as one JSON line; it mounts under `/app/config` with
  `CONFIG_DIRECTORY=/app/config` and `ACTIVE_PROFILES=production`. The chart's posture
  `fail` checks stay. The five unread variables are no longer rendered; their values keys
  stay accepted, so an existing values file renders (D16).
  Done: `templates/configmap.yaml` (`<fullname>-config`), each line `NAME='value'` from a
  `registry.envLine` helper escaping `\\` and `\'`; an unset value renders no line; a
  `registry.credentialFile` helper shared by the profile and the Secret mount; the profile
  mounted by `subPath`; a `checksum/config` annotation. The helper refuses a value ending
  in a backslash or holding `${` (design.md, "The registry"). `core/registry/Dockerfile`
  lost `ENV PORT`; `config.py`'s `root_path` comment corrected. `CHAIN_ID` is gone.
- [x] 11.2 `secretProfile` (D16). `secretProfile: {secretName, profile}` mounts
  `config-<profile>.env` from that existing Secret under `/app/config` and appends the
  profile to `ACTIVE_PROFILES`; `auth.bootstrapKeySecret` and `auth.adminKeySecret` with a
  name set fail rendering naming `secretProfile`. The umbrella's registry aliases drop
  their empty `auth` blocks. The Deployment's `env` holds only `CONFIG_DIRECTORY` and
  `ACTIVE_PROFILES`.
  Done; also refused: a `secretName` without a `profile`, and the profile `production`. A
  retired key with an empty name still renders. The umbrella schema's `registryInstance`
  gains a closed `secretProfile`; `helm/fixtures/two-registries-values.yaml` names one
  (`credits-registry-keys`, `credits-keys`).
- [x] 11.3 Render cases (D16; the delta's scenarios) in `helm/scripts/test-render.sh` or
  `helm/tests/test_release_topology.py`, where registry rendering is asserted today: the
  rendered profile's lines for the default and the API-credit alias, each with its own
  filter specification path; the Deployment's environment holding exactly the two
  variables; a `secretProfile` mounted and appended; each retired key refused by name; the
  posture checks still failing as before.
  Chart render, `helm/tests/test_release_topology.py` and `test-render.sh`: pass — each
  registry's exact profile key set and exact two-variable environment; unread keys
  rendering nothing; `secretProfile` mounted and layered, with its refusals; each retired
  key refused; the unreadable values refused; the posture checks. Beyond the plan,
  `test_the_rendered_registry_profile_loads_with_the_registry_loader` loads a rendered
  profile with non-default values and a hostile display name through
  `core_registry.config.load_settings` under `REGISTRY_PYTHON` (it skips in CI, where no
  registry environment is built). The existing cases reading registry pod variables now
  read the profile.
- [x] 11.4 **Verification checkpoint.** Chart render: `make -C helm test-render`. Unit:
  `make test-release-tooling`. `make test`.
  End-to-end: no pipeline marker exercises the chart; validation's Helm part deploys the
  release, whose registry must start from the rendered profile for its scenario pod and
  payments check to pass.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — `make -C helm
  test-render` passes with the registry cases.
  Evidence: `make -C helm test-render` (the loader case run), `make
  test-release-tooling`, `make test`, `make test-registry`, `make check-packaging` and
  `make check-change` pass. Validation 82's Helm deploy started the registry from the
  rendered profile. Destinations carried into 13.9: `TESTING.md`'s "Chart Render Tests"
  gains `REGISTRY_PYTHON`; `DEPLOYMENT_AND_CONFIG.md`'s "Kubernetes: ConfigMap and Secret
  mounting" names the registry as the chart mapping each value to its variable by name,
  its profile a dotenv file. The registry image's `CMD` hard-codes port 8080, pre-existing.

## 12. Storefront charts: a derived `ca_bundle_path` and the secret overlay

Delivers both storefront charts' CA option deriving `ca_bundle_path`, the payments-key
option removed, the payments-check pod without payments variables, and the local release's
token in the runtime secret overlay (D3, D11, D12, D19's charts bullet; deployment-state "A
storefront chart trusts a deployment-supplied CA bundle", "A storefront's secrets reach it
through its secret overlay", "The local release rehearses a deployment's payments
interface", "A storefront checks its payments access from its own container" (Helm half),
and MODIFIED "A storefront's configuration reaches it through its configuration system").

Files: `helm/charts/storefront/{values.yaml, values.schema.json,
templates/deployment.yaml, templates/_helpers.tpl, templates/tests/payments-check-test.yaml,
tests/test_render.py}` and the same under `helm/charts/bare-metal-storefront/`;
`helm/values.schema.json`; `helm/local-values.yaml`, `helm/bare-metal-release-values.yaml`,
`helm/fixtures/payments-ed25519-values.yaml`; `helm/Makefile` (`LOCAL_SECRETS`);
`helm/scripts/topology-secrets.sh`; `helm/tests/test_release_topology.py`;
`tools/payments-lane-double/README.md`'s Helm passage.

- [x] 12.1 The CA option derives `ca_bundle_path` (D3). With the option set, each chart
  mounts the bundle as before and adds `[Settlement.arkhai_payments].ca_bundle_path`,
  naming the mounted file, to the rendered configuration where `config` states none, and
  fails rendering naming both paths where `config` states another; it sets no
  `SSL_CERT_FILE`. Unset, it adds neither mount nor setting.
  Done: `storefront.deriveCaBundlePath` and `bare-metal-storefront.deriveCaBundlePath`
  set `/etc/arkhai/ca/ca-bundle.pem` in the section as `config` spells it; an equal
  stated path is kept, another refused naming both. Differs from the plan, confirmed by
  triage 61 and recorded in D3 and the delta: a bundle with no or an empty payments
  section is refused, naming the section; a disabled section still receives the path.
- [x] 12.2 The key in the secret overlay (D19, D11). Remove both charts' `paymentsKey`
  option, its helpers, its `api_key_env` checks and its environment entry, from the
  Deployment and the payments-check pod alike; the values schemas no longer accept it.
  `helm/local-values.yaml` and `helm/bare-metal-release-values.yaml` drop `paymentsKey` and
  `api_key_env`; `topology-secrets.sh` writes the seller token as
  `[Settlement.arkhai_payments].api_key` into each storefront's runtime Secret's
  `storefront.secrets.toml` (`arkhai-bob-runtime` and the bare-metal release's) from
  `lane_env.py seller-token`, instead of creating `seller-payments-key`, which leaves
  `LOCAL_SECRETS`. `helm/fixtures/payments-ed25519-values.yaml` follows.
  Done. Both environment helpers render only `XDG_CONFIG_HOME` and
  `ARKHAI_IDENTITY_CREDENTIAL`. The bare-metal schema's closed top level refuses
  `paymentsKey`; the storefront chart's open agent entry and the umbrella's copy state
  `"paymentsKey": false`. `topology-secrets.sh` refuses a token a TOML basic string could
  not carry unescaped. Comments, the Makefile's `LOCAL_SECRETS` note and the double's
  README Helm passage updated.
- [x] 12.3 The payments-check pod (D12). It mounts the configuration, the secret overlay
  and the CA bundle, and carries the identity credential and no payments variable, from
  the helpers the Deployment uses.
  Done with no template change but its comment: the shared helpers changed both.
- [x] 12.4 Render cases (D3, D11, D12, D19; the deltas' scenarios), in both charts'
  `tests/test_render.py` and `helm/tests/test_release_topology.py`: the derived
  `ca_bundle_path` from a ConfigMap and from a Secret source; a stated different path
  refused naming both; neither mount nor setting when unset; no `SSL_CERT_FILE` and no
  payments variable in the Deployment or the check pod; a `config` stating `api_key`
  refused by the values schema; the bare-metal pod environment holding only the
  configuration directory and the signing credential, with and without the CA option
  (the MODIFIED requirement's scenario); the payments-only case and the check pod mounting
  no data volume, as before; the local topology's Secrets without `seller-payments-key`.
  Chart render, both charts' suites and `test_release_topology.py`: pass. `_ca_bundle`
  asserts the volume, mount and derived path together and the two-variable environment;
  every listed case is covered, including the empty-section refusal and the storefront
  chart's own `"paymentsKey": false` rendered alone. Release tooling,
  `test_topology_secrets_writes_the_payments_key_into_each_storefronts_overlay` (fake
  `kubectl` capturing `--from-file` files): each runtime overlay's `Settlement` is exactly
  the seller token, and no other Secret holds it.
- [x] 12.5 **Verification checkpoint.** Chart render: `make -C helm test-render`. Unit:
  `make test-release-tooling`, `make test-payments-lane-double`. `make test`.
  End-to-end: no pipeline marker exercises the charts; validation's Helm part deploys the
  release and runs every `-payments-check` pod (D12), which must pass with the key from the
  runtime secret overlay and trust from the derived `ca_bundle_path`. Serving payment
  scenarios on Helm is not owed (D11).
  Owed by validation: `tests.yml`, jobs `test · test-deployment-packaging` — `make -C helm
  test-render` and release tooling pass with the new cases — and
  `test · test-payments-lane-double` — passes.
  Evidence: `make -C helm test-render` (no skip), `make test-release-tooling`, `make
  test-payments-lane-double`, `make test`, `make check-change` and `make check-packaging`
  pass. Validation 82's Helm part ran Bob's `-payments-check` pod, exit 0; the bare-metal
  one runs under `topology-check`. Owed observations confirmed as written. Settled by
  triage 61–63: the CA bundle without a payments section stays refused (D3); the deploy
  guard checks only that the ConfigMap and runtime Secrets exist (D3, D11); the
  dispute-credential schema gap is fixed in 12.6. Destinations carried into 13.9:
  `DEPLOYMENT_AND_CONFIG.md`'s "Storefront agents: pass-through configuration" (the
  derived `ca_bundle_path` in its derived-settings table and its "except for the port"
  sentence; `arkhai-bob-runtime`'s overlay naming the payments `api_key`); `TESTING.md`'s
  "Chart Render Tests" (the release-tooling case reading the overlays).
- [x] 12.6 Triage fixes (61 F1, 63 O1).
  - **61 F1, the dispute credential's token refused in public `config`.** Both
    storefront schema generators type `[[DisputeCredential]]` as an array of
    `model_fragment(DisputeCredential)` from `market_deal_lifecycle.configuration`, a
    distribution both already declare. Its `api_key`, marked secret, is refused in any
    spelling and as null, and the entry is closed to its other fields. The three
    committed schemas (`helm/values.schema.json`, `helm/charts/storefront/` and
    `helm/charts/bare-metal-storefront/values.schema.json`) were written with the Edit
    tool, since the triage step may not run `make helm-values-schema`; both drift tests
    pass, so they equal the generators' output as parsed JSON. A later `make
    helm-values-schema` may reorder keys, nothing else. Tests: a unit case per
    storefront's `test_values_schema.py`, and a render refusal per chart's
    `tests/test_render.py`, the VM one through the umbrella and through the chart alone.
    The delta gains the scenario "The public configuration states a dispute credential's
    token".
  - **63 O1, Bob's dispute credential in the local release.** `topology-secrets.sh`
    copies Bob's `[[DisputeCredential]]` from the committed Compose overlay
    `dev-env/identities/bob.storefront.secrets.toml` (new input
    `BOB_COMPOSE_SECRETS_FILE`, set in `helm/Makefile`) into `arkhai-bob-runtime`'s
    overlay, rewriting each setting as a TOML basic string and refusing a non-string
    value or a rewrite that does not read back as the file's entries. The bare-metal
    release's overlay gets none, as D2 says of its lane. Release tooling:
    `test_topology_secrets_gives_bob_his_compose_dispute_credential` asserts Bob's
    entries equal the Compose overlay's, their authority binding equals
    `fixtures/dispute-authority.toml`'s, and the bare-metal overlay has none. D11 and
    the delta's local-release requirement and scenario name the credential. Comments
    updated: `helm/local-values.yaml`, `helm/Makefile`, the overlay's header and
    `dev-env/identities/README.md`.
  Evidence: `make test-storefront`, `make test-bare-metal` (drift tests included), `make
  -C helm test-render`, `make test-release-tooling`, `make check-packaging` and `make
  test` pass. The fresh-context check's fixes: D3's wording on the ConfigMap and the
  checked Secrets; the positive render cases for a public `api_key_env` entry removed (12.7
  then refused the entry whole); the script's read-back check. Destination carried into
  13.9: `DEPLOYMENT_AND_CONFIG.md`'s account of `arkhai-bob-runtime` names Bob's
  `[[DisputeCredential]]` beside the payments `api_key`.
- [x] 12.7 Pre-closeout triage fix (74 F1): the named-variable credential paths refused in
  public `config`. 12.6 refused a dispute credential's token but still accepted an entry
  naming `api_key_env`, and `[Settlement.arkhai_payments].api_key_env` was accepted too,
  though the delta's requirement forbids a variable named by configuration and the chart
  sets none that could hold a key.
  - Both storefront schema generators now refuse `[[DisputeCredential]]` whole
    (`False`, in any spelling and as null) and `api_key_env` in the payments fragment,
    beside the secret-marked `api_key`. The refusal is the generators', not a `roles`
    marker on `ArkhaiPaymentsConfig.api_key_env`, which the settlement runtime would
    also enforce when a seller's configuration loads (D19, "Values schemas"). The
    generators import `ARKHAI_PAYMENTS_CONFIG_KEY` from `market_arkhai_payments`, which
    both packages declare, and no longer import `DisputeCredential`.
  - The three committed schemas were regenerated with `make helm-values-schema`; the
    diff is the two refusals alone.
  - Tests. Unit, in each storefront's `test_values_schema.py`:
    `test_a_dispute_credential_is_refused_whole` (with its token, naming a variable,
    with neither, empty, and null, under three spellings of the section) and
    `test_a_payments_key_named_by_variable_is_refused` (three spellings, a value and
    null, the rest of the section accepted); they replace the 12.6 test that asserted
    `api_key_env` allowed. Bare metal's closed-document test now excludes
    `disputecredential` from the settings the definition accepts. Chart render, in each
    chart's `tests/test_render.py`: `test_a_payments_key_named_by_variable_is_refused`
    and `test_a_dispute_credential_is_refused_in_public_configuration` (token and
    variable), the VM ones through the umbrella and the chart alone.
  - The delta's requirement names the three refusals; the scenario "The public
    configuration names a payments key's variable" is added and "The public
    configuration states a dispute credential" replaces "…a dispute credential's token".
    D19 gains "Values schemas".
  Evidence: `make test-storefront`, `make test-bare-metal`, `make -C helm test-render`,
  `make check-packaging`, `make test`, `make check-comment-hygiene` and `make
  check-change` pass. Destinations carried into 13.3 and 13.9:
  - `DEPLOYMENT_AND_CONFIG.md`: its list of what the storefront definition refuses
    (around "Storefront agents: pass-through configuration") should name the payments
    `api_key_env` and every `[[DisputeCredential]]` entry, not only a dispute
    credential's `api_key`; its `[Settlement]` passage resolving "an `api_key_env`
    reference" and its `[[DisputeCredential]]` example using `api_key_env` need the
    storefront's secret-overlay form beside the buyer's.
  - Seller documents still configuring a storefront's key by variable:
    `docs/seller-quickstart.md` (its `[Settlement.arkhai_payments]` example and the
    sentence after it), `domains/vms/storefront/examples/README.md`, and the comment in
    `domains/apicredits/storefront/src/apicredits_storefront/settings.toml`.
  - `e2e-tests/README.md`: its external-deployment passage forwards a variable for the
    storefront's `[[DisputeCredential]]`, and its lane passage places Bob's credential
    in `storefront.bob.lane.toml`; it is in `dev-env/identities/bob.storefront.secrets.toml`.
  - `openspec/specs/deployment-state/spec.md`, "Marketplace deployment config contains
    consumer data only", and `architecture.md`'s matching passage still say a payments
    consumer configures an environment-variable name for its key. No delta modifies
    that requirement, so archive would leave it contradicting this change's; closeout
    adds a MODIFIED delta naming the secret-overlay `api_key` for a storefront and
    `api_key_env` for a buyer.

## 13. Closeout

Replanned against the redesign: replaces the unstarted section-6 closeout this plan first
ended with. Confirm and promote the verified design, then archive last (D1–D23 and every
delta requirement). The eleven parts follow `openspec/README.md#plan-closeout-requirements`
in order. Closeout changes no code: a part needing a code, lock, chart, or test change
returns the change to implementation.

- [x] 13.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every
  comment and docstring sections 1–12 added: the kit's `access_check.py`, key resolution
  and balance view; the mediation credential and dispute credential; the registry's
  loader; the double's modules, fixtures and generator; the storefront CLIs' subcommands;
  the Compose files, profiles and secret overlays and the lane targets; the helper; the
  charts' values and templates. Each states current behaviour and every fixture value's
  label is present. A needed correction returns to implementation.
  Closeout, first session (2026-11-06): `make check-comment-hygiene` passes (no change-ID,
  task-number or change-name reference). A scan of every comment and docstring the branch
  adds (`git diff -U0 origin/dev...HEAD`, outside `openspec/` and `docs/`) for review,
  triage, migration or history wording found none; the matches ("replaces", "legacy",
  "retired key Secret") describe current behaviour or name a delta scenario. One comment
  needs a code edit, so this part is open and the change returns to implementation:
  - `.github/workflows/e2e.yml`, the lane list (lines 22–28), which section 10 edited:
    each lane's entry names what its stack runs and none names the payments double every
    lane now runs (`compose.payments-double.yml`), as section 4's handoff recorded. Fix:
    add the double to each lane's entry, or say once that every lane runs it.
  Correction, closeout resumed (2026-11-06): the owner confirmed the return, and
  `10207a47c`, made by the orchestrating session on the owner's word with its review and
  validation waived (log seq 153), adds one sentence after the lane list naming the
  payments double every lane's stack runs. `make check-comment-hygiene` passes again at
  that commit. Part confirmed.
- [x] 13.2 **Import placement — confirm.** Every import sections 1–12 added is at module
  level unless a verified cycle or recorded lazy-load reason keeps it local. A needed move
  returns to implementation.
  Confirmed: the branch's diff adds two function-local imports, both of
  `settlement_config_mapping` in a storefront CLI's `payments_section`
  (`domains/vms/storefront/src/market_storefront/cli.py`,
  `domains/apicredits/storefront/src/apicredits_storefront/cli.py`), each with the reason
  beside it: the storefront's settings resolve when its config module is first imported,
  which must follow the root `--config` option. Every other added import is at module
  level.
- [x] 13.3 **Documentation compliance.** Check D1–D23 against `openspec/README.md`'s
  placement rules and the promotion record below, recording a disposition per decision,
  and check every promoted statement against the code.
  Closeout, first session: open. 12.7's handoff lists, among the seller documents still
  configuring a storefront's payments key by variable, a comment in package code, which
  closeout may not edit:
  - `domains/apicredits/storefront/src/apicredits_storefront/settings.toml:59`, under
    `[Settlement.arkhai_payments]`, offers `# api_key_env = "ARKHAI_PAYMENTS_API_KEY"`.
    D19 and the settlement-configuration delta put a storefront's payments key in its
    secret layer as `api_key`, keeping `api_key_env` for the buyer. Fix: the comment says
    the key is `api_key` in the storefront's secret layer, never in this file.
  The other items of 12.7's handoff (`docs/seller-quickstart.md`,
  `domains/vms/storefront/examples/README.md`, `e2e-tests/README.md`,
  `DEPLOYMENT_AND_CONFIG.md`, and the deployment-state MODIFIED delta) are documents
  and change files, closeout's when it resumes, as is every 13.4–13.11 part.
  Correction, closeout resumed: `10207a47c` (owner's word, log seq 153) makes the comment
  say the storefront's key is `api_key` in its secret overlay, never in that file.
  Dispositions, by `openspec/README.md#documentation-placement`:
  - Permanent, behaviour in a `spec.md` through the deltas: D2, D3, D4, D5, D6, D8, D9,
    D11, D12, D14, D15, D16, D19 (test-compatibility, deployment-state,
    market-composition, settlement-configuration).
  - Permanent, rationale and conventions in companions and `docs/`: D1, D2, D3, D4, D6, D7,
    D8, D9, D11, D12, D14–D20, D23, each at the location the promotion record names.
  - Change history only: D10 and D22 (implementation cadences), D13's scope decision (its
    gap is in `ROADMAP.md`), and D21 (the tests are their own record).
  - None superseded or rejected beyond what each decision's own "Rejected" list records.
  Each promoted statement was checked against the code, charts, Compose files and
  Makefiles it describes as it was written (13.9). Judged and kept: D11 and the
  deployment-state delta say the local deploy target enables the double's subchart; the
  setting is `payments-lane-double.enabled: true` in `helm/local-values.yaml`, which
  `deploy-local` layers and release values never do, so the statement holds.
  `docs/bare-metal-seller-quickstart.md` (section 9 rewrote it) and
  `VALIDATION_RUNBOOK.md`'s "Bring Up Local Stack" were confirmed current. Found false and
  outside closeout's edit permissions: `core/registry/README.md`'s "Quick start" says a
  bare `docker compose up -d` brings up the stack, which the base topology no longer
  starts without its two `-local` overlays (13.9).
- [x] 13.4 **Narrative compression.** Compress section notes to final behaviour,
  validation evidence, deferred work, and destinations, moving durable rationale into
  `design.md` first.
  Done: sections 1–12's notes compressed (`tasks.md` from 3145 to about 1650 lines), every
  task line, planned paragraph, `Owed by validation:` line, deferral and documentation
  destination kept. The as-built rationale, review findings fixed and declined with
  their reasons, and known gaps moved first to `design.md`'s new "Implementation record"
  (the kit; the double; storefronts and the VM servicing proof; lanes and stacks; the
  registry; Helm). D12 now says the refusal step is `refused` with a separate `code`
  field, and gives the exit codes 0, 1 and 2. The other design wording the notes flagged
  (the Facts' API-credit "Ed25519 seed", D9's e2e-tests chart values, D3's ConfigMap
  creation) was already current.
- [x] 13.5 **Roadmap currency.** In `docs/development/ROADMAP.md`:
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
    revisited when an external run fails in a way the charts shape (D11);
  - add an unowned gap: the registry is configured by profile env files rather than the
    Dynaconf loader the provisioning service uses, from the profiles and `secretProfile`
    this change gives it (D13, D16);
  - add an unowned gap: the signing credential `ARKHAI_IDENTITY_CREDENTIAL` is the one
    secret not delivered as a secret profile, revisited when a change decides identity
    credential delivery (D19, the design's Open Questions).
  Done, in `ROADMAP.md`: Goal 8's row now names what `add-arkhai-payments-lane-double`
  still owns — controls on the payments double, a mediation double, the VM case stages'
  skip and hostile cases — and Goal 8's current state says every pipeline run settles the
  once-only payment scenarios against the in-lane double; Goal 1's dispute-authority row
  says no lane runs a mediation double, the pinned `.invalid` authority is unanswerable,
  and no guard refuses fixture identities, that guard being
  `add-arkhai-payments-lane-double`'s decision; "Payment qualification boundaries" says
  what the lanes' double establishes and what it does not, and lists the local Helm
  release serving no payment scenario as unowned, with its trigger. The registry's
  Dynaconf move and the signing credential's delivery are two unowned rows of a new
  "Configuration delivery" section, since no goal owns configuration delivery.
- [x] 13.6 **Campaign index currency.** In `openspec/changes/README.md`, set this change's
  row to its archived state and link, and update the Reach hosts campaign's graph lines
  naming it. Note in `qualify-real-provisioning-by-scenario`'s row that its storefront
  chart CA option is delivered here as a chart-derived `ca_bundle_path`, the storefront's
  payments key being `api_key` in its secret overlay, and that its delta's same-named
  requirement must be dropped or reduced to a MODIFIED at its reverification; note in
  `add-arkhai-payments-lane-double`'s row its D1/D7 revision, the fixture-identity guard it
  owns, and the `MediationCredential` carrying a resolved token it inherits. Run
  `make check-change-index`. Archive cleanup, not closeout, releases the dependents.
  Done, with one correction to the task: the row's status stays `in closeout`, since
  archive cleanup writes `archived` once the closeout review's triage advances the change
  (`openspec/README.md#plan-closeout-requirements` part 6), and its link moves to the
  archive directory at 13.11. Its `Notes` now record the validation, the promotion and the
  landing branch. `qualify-real-provisioning-by-scenario`'s row records the CA option as
  a mounted `caBundle` deriving `ca_bundle_path`, the key as `api_key` in the secret
  overlay, and its delta's requirement to drop or reduce; `add-arkhai-payments-lane-double`'s
  row records its D1/D7 revision, the guard it owns and what it inherits. The Reach
  hosts graph's two lines naming this change still hold, and every `Depends on` is left
  for archive cleanup. `scripts/change-workflow check index` passes.
- [x] 13.7 **Packaging.** Run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=add-mvp-payments-lane-double`. No `.agents/`,
  `.claude/` or `.codex/` edit is planned; if one was made, run `make check-agent-skills`.
  Done at `10207a47c`: `make check-packaging` passes, all eight checks OK. `make
  check-architecture-change` reports the change owns no architecture row. The branch
  edits `.claude/change-steps.toml` (step permissions for `make helm-values-schema`,
  image builds and lane teardown), so `make check-agent-skills` ran too, and passes.
- [x] 13.8 **End-to-end pipeline.** Confirm the pipeline passes on the closeout candidate
  and record the run, its result, and the scenarios exercising this change:
  `e2e_bare_metal_payment_deal` and `e2e_credits_payment_deal` passing without skips,
  `e2e_vm_payment_deal`'s stages 1–2 passing and 3–4 reporting the mediation blocked
  skip, each lane's `check-payments` at setup, and every lane's other markers green on the
  stacks configured from committed files; and the Helm part's payments check with the
  registry started from its rendered profile. A pipeline that cannot run for an unrelated
  reason is recorded as a blocker naming its cause and owner, and what it gates is unrun.
  Evidence: validation `reviews/82-validation.md`, passed, at `c95be45e5`, the merge of
  `dev`. Commits after it: `6bf7d9153` (pre-closeout triage 83's fixes), whose validation
  the owner waived; `b1d93a4d6`, change documents only; and `10207a47c` (two comments),
  whose review and validation the owner waived (log seq 153). Closeout changes no code,
  so the runs below describe the code the closeout commit carries, up to those waived
  commits.
  - Pipeline run 42198177940, success. e2e-apicredits: 4 passed, `e2e_credits_payment_deal`
    included. e2e-bare-metal: 70 passed, `e2e_bare_metal_payment_deal` included. e2e-vm:
    153 passed, 2 skipped. From the run's log (`.snapshot/e2e-logs/42198177940/`):
    `e2e_vm_payment_deal`'s stages 1–2 passed, and the two skips are its stages 3–4,
    `test_operator_end_files_one_case_without_a_local_payment_remedy` and
    `test_seller_refund_is_financial_and_release_waits_for_the_callback`. The run prints
    no skip reasons, so the mediation-target wording is not shown in this run.
  - Each lane's setup ran `check-payments` in its storefront container and printed
    `"outcome": "ok"` against `https://payments-double:8443` for the seller account `…b2`.
    Every lane's other markers passed on the stacks configured from committed files.
  - Helm: the scenario pod exited 0, and so did Bob's payments check pod
    (`arkhai-node-operator-storefront-bob-payments-check`). The registry was ready,
    started from its rendered profile.
  - CI, `tests.yml` run 42198188484, success, as the validation record maps the owed
    observations: `test · test-kits` (§1, §6, §7), `test · test-payments-lane-double`
    (§2), `test · test-storefront` and `test · test-bare-metal` (§3, §7), `test ·
    test-e2e-unit` (§4, §10), `test · test-deployment-packaging` (§5, §9, §11, §12) and
    `test · test-registry` (§8) each passed. No job of the run failed, `test ·
    test-apicredits` (owed by §3) included, though the record does not list it; the `dev`
    baseline was run 42115735337 at `f46c83632`.
- [x] 13.9 **Promotion.** Write and record in the promotion record:
  - `openspec/specs/test-compatibility/architecture.md`, "Payment evidence ownership":
    the in-lane double, what it mirrors and serves, what its results establish and do
    not, and the VM scenario's mediation prerequisite; its "Lifecycle contract evidence"
    sentence on the kit's fake, made accurate;
  - `docs/development/TESTING.md`, "Private Service Dependencies": the lanes' payments
    target, the runner's shared and per-lane payments profiles, `LANE_OWNED`, the pinned
    unanswerable authority, and the principle that a double mirrors its producer's API
    unless there is a compelling reason to deviate; and its lane paragraph on
    `PROVISIONING_MODE`, made accurate for the overlays' interpolated profile;
  - `docs/development/ARCHITECTURE.md`, "Testing strategy": the double-mirroring
    principle as a repository-wide rule; "Deployment topology": the secret-profile rule
    (principle 3) and the committed-stack-configuration rule (principle 4);
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`:
    - "Profile-based configuration": the secret-profile rule — a service takes its
      secrets from a secret profile or overlay file, never from an environment variable
      its configuration names — and the signing credential as its one exception;
    - "Kubernetes: ConfigMap and Secret mounting": the storefront charts' CA option and
      its derived `ca_bundle_path`, and the payments key in the runtime secret overlay;
    - "Registry descriptor configuration": the registry's profile env files, the chart's
      rendered `config-production.env`, `secretProfile`, and the retired key Secrets;
    - "Per-domain stack composition": the committed-stack-configuration rule, each
      stack's overlays, registry and provisioning profiles and secret overlays, base files
      holding topology only with no committed fallback, `PROVISIONING_MODE` as the one
      value a run supplies, and the full stack's command, replacing the generated
      environment files;
    - "Settlement consumer configuration and cutover": the storefront payments check, its
      steps, and `api_key` and `ca_bundle_path`;
    - "Dispute authority preferences": a `[[DisputeCredential]]` states `api_key` (in a
      secret overlay) or `api_key_env`, exactly one, resolved only when the authority is
      used, and the mediation client receives the resolved token (added by section 7's
      implementation: the passage still describes credentials as variable references
      only);
    - "Release topology": that a local release configures a service through the same
      values a deployment uses, never development-only modes, with the payments double
      enabled once per namespace;
  - `docs/operator-handbook.md`: a new "Payments access" section — the CA ConfigMap a
    deployment supplies, the payments key in the storefront's runtime secret overlay,
    `check-payments`, and the Helm test; and a new "Registry secret profile" section —
    moving `auth.bootstrapKeySecret` and `auth.adminKeySecret` to a Secret holding
    `config-<profile>.env` named by `secretProfile`;
  - `tools/README.md`: the payments double as a lane collaborator, the third kind of
    tool, beside `issue-discovery` and `frp-grant-admission`;
  - the deltas into `openspec/specs/test-compatibility/spec.md`,
    `openspec/specs/deployment-state/spec.md`, `openspec/specs/market-composition/spec.md`
    and `openspec/specs/settlement-configuration/spec.md`, written by the archive (13.11);
  - `openspec/specs/README.md`: no new capability or companion, so no entry; confirm.
  Closeout, resumed session: written, each statement checked against the code it
  describes:
  - `test-compatibility/architecture.md`: "Payment evidence ownership" with a new "The
    in-lane payments double"; "Lifecycle contract evidence" (the fake, the fixtures and
    the double share one engine; only the double serves a subprocess or a container).
  - `TESTING.md`: "Private Service Dependencies" rewritten; the system-test lane list
    (the bare-metal lane settles against the double, every lane runs
    `compose.payments-double.yml`, `PROVISIONING_MODE` as the overlays interpolate it);
    the Helm part's payments-check pods; "Chart Render Tests" (the `caBundle` and
    secret-config refusals, the check pod, the double's subchart, the registry's profile
    and `secretProfile`, `REGISTRY_PYTHON`, the `topology-secrets` overlay cases).
  - `ARCHITECTURE.md`: "Local development", under "Deployment topology", states principles
    4 and 3; "Testing strategy" states the double-mirroring rule.
  - `DEPLOYMENT_AND_CONFIG.md`: every heading this task lists, and beyond it the handoffs'
    "Storefront agents: pass-through configuration" (derived `ca_bundle_path`, the
    `caBundle` option, the check pod, `arkhai-bob-runtime`'s contents, the schema
    refusals), "Bare-metal role configuration" and "Introduction delivery" (the lane
    copy `storefront.bob.lane.toml`).
  - `operator-handbook.md`: "Payments access" and "Registry secret profile".
  - Beyond the list, from the handoffs: `BUILD_AND_PACKAGING.md` ("Images") records the
    double's two-level editable image install; `deployment-state/architecture.md` ("Role-
    separated topology", "Configuration bootstrap boundary" — the registry parses its own
    profiles until a move onto Dynaconf — "Settlement configuration cutover", "Arkhai
    payment consumers"); `settlement-configuration/architecture.md` ("Precedence and
    secret boundaries"); `docs/seller-quickstart.md` (the storefront's key is `api_key`
    in its secret overlay).
  - The deployment-state delta gains two MODIFIED requirements: "Marketplace deployment
    config contains consumer data only" (a storefront's key is `api_key` in its secret
    overlay, a buyer's is named by `api_key_env`; 12.7's handoff), and "Payment
    credentials stay with their owning process", whose "no payment authority" in public
    renderings is scoped beside the lanes and local release running the double (section
    4's handoff): the double is a development fixture, enabled only by the local
    release's own values, and a scenario holds a render from release values to no double.
  - `openspec/specs/README.md`: confirmed, no entry needed.
  Open — four READMEs outside closeout's edit permissions, which allow `openspec/`,
  `docs/` and `AGENTS.md` only (Edit of `tools/README.md` and of `e2e-tests/README.md`
  refused). Each needs its edit before the archive:
  - `tools/README.md`, before "Adding More Tools", a section "Lane collaborators": a
    stand-in for a service outside this repository, run by the lanes and the local Helm
    release; unlike a standalone component it may import internal kits, wrapping their
    engines rather than restating them; unlike a developer tool it is not invoked through
    `scripts/`; nothing imports it, and it ships only as a development image. Under it,
    "`payments-lane-double/`": an HTTPS double of the Arkhai Payments service mirroring
    its API over the payments kit's engine, with committed public development fixtures
    and a lane CA, its README saying what it serves and what its results establish; its
    `make test` (unit, library integration, `check-tls`); the root
    `make test-payments-lane-double`, part of `make test` and the Tests workflow's
    matrix; `make build-payments-lane-double`, part of `make build-dev` and each lane's
    `build-e2e-*` target, building `arkhai:payments-lane-double`, never pushed.
  - `e2e-tests/README.md`, the VM payment scenario passage: "Bob's lane configuration
    (`domains/vms/storefront/storefront.bob.lane.toml`) holds an identity-bound
    `[[DisputeCredential]]` for it, whose variable `compose.vms-lane.yml` sets to a public
    development value" becomes "Bob's secret overlay
    (`dev-env/identities/bob.storefront.secrets.toml`) holds an identity-bound
    `[[DisputeCredential]]` for it, whose `api_key` is a public development value"; and
    in the external-deployment paragraph, "Its `api_key_env` names the seller bearer
    credential variable; forward that variable into the storefront" becomes "State it
    whole in the storefront's secret overlay, its `api_key` the seller's bearer
    credential".
  - `domains/vms/storefront/examples/README.md`: "For example, in each role's public
    TOML:" becomes "For example, in the buyer's public TOML; a storefront's is the same
    without `api_key_env`:"; and "Set the named environment variable to that role owner's
    WorkOS user-scoped API key" becomes "The buyer's `api_key_env` names the variable
    holding its owner's WorkOS user-scoped API key. A storefront's key is `api_key` under
    `[Settlement.arkhai_payments]` in its secret overlay, `storefront.secrets.toml`,
    which its values schema keeps out of public configuration".
  - `core/registry/README.md`, "Quick start": `docker compose up -d` becomes
    `docker compose -f docker-compose.yml -f compose.vms-local.yml -f
    compose.apicredits-local.yml up -d`, since the base topology starts only with its
    `-local` overlays (13.3).
  Correction: the owner granted closeout edit rights for these four paths for the
  resumed session, and each edit above is made as written.
- [x] 13.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=add-mvp-payments-lane-double` after promotion and
  resolve every match, then `openspec validate add-mvp-payments-lane-double --strict`.
  Run against the promotion so far: `make check-change CHANGE=add-mvp-payments-lane-double`
  passes every check, documentation citations and `openspec validate --strict` (pinned
  1.14.0) included. Rerun after 13.9's four README edits: passes again.
- [x] 13.11 **Archival.** `openspec archive add-mvp-payments-lane-double -y`, merging the
  four deltas into `openspec/specs/`; then point the index row at the archive directory.
  Done with the pinned validator (`npx @fission-ai/openspec@1.14.0`, since `bunx` is not
  installed here), deltas merged, since no added requirement was already in a permanent
  spec: deployment-state +6 ~3, market-composition +1, settlement-configuration ~2,
  test-compatibility +3 ~2. Each merged requirement reads once as its delta states, and
  nothing else in the four specs changed. The test-compatibility MODIFIED "External
  payment qualification names its target" drops the sentence pointing to "Lane
  qualification identifies readiness and evidence class", a requirement the spec does not
  hold, so no rule is lost. The index row links `archive/2026-11-06-add-mvp-payments-lane-double/`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 The double's project and its place among tools | `tools/README.md#lane-collaborators`; `tools/payments-lane-double/README.md`; `docs/development/BUILD_AND_PACKAGING.md#images` (its editable image install) |
| D2 Lanes running the double; the VM scenario's mediation prerequisite and dispute credential | `openspec/specs/test-compatibility/spec.md` (delta); `openspec/specs/test-compatibility/architecture.md#the-in-lane-payments-double`; `e2e-tests/README.md` (the VM payment scenario's dispute credential) |
| D3 Committed lane CA and leaf; the CA option deriving `ca_bundle_path` | `tools/payments-lane-double/README.md`; `openspec/specs/deployment-state/spec.md` (delta, "A storefront chart trusts a deployment-supplied CA bundle"); `docs/development/DEPLOYMENT_AND_CONFIG.md#kubernetes-configmap-and-secret-mounting` and `#storefront-agents-pass-through-configuration` |
| D4 No production guard; the unusable pinned authority | `openspec/specs/test-compatibility/spec.md` (delta); `openspec/specs/test-compatibility/architecture.md#the-in-lane-payments-double`; `docs/development/TESTING.md#private-service-dependencies`; `docs/development/ROADMAP.md` (Goal 1's dispute-authority row) |
| D5 The balance read | `openspec/specs/market-composition/spec.md` (delta); `kit/arkhai-payments/README.md` |
| D6 Lane-owned targets fail | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md#private-service-dependencies` |
| D7 The pinned authority through the registry | `docs/development/TESTING.md#private-service-dependencies`; `e2e-tests/README.md` |
| D8 The double mirrors the service | `openspec/specs/test-compatibility/spec.md` (delta); `openspec/specs/test-compatibility/architecture.md#the-in-lane-payments-double`; `docs/development/TESTING.md#private-service-dependencies`; `docs/development/ARCHITECTURE.md#testing-strategy` |
| D9 Lane configuration in committed files, never generated by Make (principle 4) | `openspec/specs/deployment-state/spec.md` (delta, "A stack's configuration lives in committed files"); `docs/development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition`; `docs/development/ARCHITECTURE.md#local-development`; `openspec/specs/deployment-state/architecture.md#role-separated-topology` |
| D10 Round 1's implementation cadence | change history only |
| D11 The local release's payments rehearsal | `openspec/specs/deployment-state/spec.md` (delta, "The local release rehearses a deployment's payments interface"); `docs/development/DEPLOYMENT_AND_CONFIG.md#release-topology`; `docs/operator-handbook.md#payments-access` (the roadmap's Helm-serving gap went with its "Payment qualification boundaries" section, which `dev` removed before landing) |
| D12 `check-payments` | `openspec/specs/deployment-state/spec.md` (delta, "A storefront checks its payments access from its own container"); `docs/development/DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover`; `docs/operator-handbook.md#payments-access`; `docs/development/TESTING.md` (the Helm part's payments-check pods) |
| D13 The cleanup in this change | change history only; `docs/development/ROADMAP.md#configuration-delivery` (the registry's Dynaconf gap) |
| D14 The runner's shared and per-lane payments profiles | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md#private-service-dependencies`; `e2e-tests/README.md`, "Shared payment-scenario configuration" |
| D15 Development binds in the overlays; base files keep topology | `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition` and `#bare-metal-role-configuration`; `dev-env/identities/README.md`; `core/registry/README.md` (its Quick start) |
| D16 The registry's profile env files and chart | `openspec/specs/deployment-state/spec.md` (delta, "The registry reads profile-shaped env files"); `docs/development/DEPLOYMENT_AND_CONFIG.md#registry-descriptor-configuration` and `#kubernetes-configmap-and-secret-mounting`; `openspec/specs/deployment-state/architecture.md#configuration-bootstrap-boundary`; `docs/operator-handbook.md#registry-secret-profile`; `docs/development/TESTING.md#chart-render-tests`; `core/registry/README.md` |
| D17 Provisioning site profiles | `docs/development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition`; `dev-env/identities/README.md` |
| D18 The environment targets retired | `docs/development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition`; `docs/development/VALIDATION_RUNBOOK.md`, "Bring Up Local Stack"; `docker-compose.yml`'s header; `e2e-tests/README.md` |
| D19 Secrets through secret overlays; trust through configuration (principle 3) | `openspec/specs/settlement-configuration/spec.md` (delta); `openspec/specs/deployment-state/spec.md` (delta: "A storefront's secrets reach it through its secret overlay", and the MODIFIED "A storefront's configuration reaches it through its configuration system" and "Marketplace deployment config contains consumer data only"); `docs/development/DEPLOYMENT_AND_CONFIG.md#profile-based-configuration`, `#kubernetes-configmap-and-secret-mounting`, `#storefront-agents-pass-through-configuration`, `#settlement-consumer-configuration-and-cutover` and `#dispute-authority-preferences`; `docs/development/ARCHITECTURE.md#local-development`; `openspec/specs/deployment-state/architecture.md#settlement-configuration-cutover` and `#arkhai-payment-consumers`; `openspec/specs/settlement-configuration/architecture.md#precedence-and-secret-boundaries`; `docs/seller-quickstart.md`; `kit/arkhai-payments/README.md`; `kit/arkhai-mediation/README.md`; `docs/development/ROADMAP.md#configuration-delivery` (the signing-credential gap); `domains/vms/storefront/examples/README.md`; `e2e-tests/README.md` |
| D20 The provisioning mode | `docs/development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition`; `docs/development/TESTING.md`'s system-test lane paragraph |
| D21 Tests holding restated values | change history only; the tests are their own record |
| D22 Implementation cadence | change history only |
| D23 Storefront wallet keys in the secret overlays | `docs/development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition`; `dev-env/identities/README.md` |
| Public renderings and the double (section 4's handoff) | `openspec/specs/deployment-state/spec.md` (MODIFIED delta, "Payment credentials stay with their owning process") |
| The landing branch (83 F1) | change history only; archive cleanup's pull request description names the branch |
| Roadmap currency (13.5) | `docs/development/ROADMAP.md`: Goal 1's dispute-authority row, Goal 8's current state and its `add-arkhai-payments-lane-double` row, `#configuration-delivery` (`dev` removed "Payment qualification boundaries" before landing) |
| Campaign index currency (13.6) | `openspec/changes/README.md`: this change's row, `qualify-real-provisioning-by-scenario`'s and `add-arkhai-payments-lane-double`'s |
