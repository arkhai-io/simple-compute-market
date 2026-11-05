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

- [x] 2.1 The project (D1). A wheel-building project at `tools/payments-lane-double`,
  import package `payments_lane_double`, depending on `arkhai-kit-arkhai-payments>=0.6.0`,
  `arkhai-kit-identity`, FastAPI and uvicorn, and `cryptography` for the generator, each
  declared in its `pyproject.toml`; internal distributions resolved from the repository
  wheelhouse as `docs/development/BUILD_AND_PACKAGING.md` requires; its own committed
  `uv.lock`. A `Makefile` with `test` and `build`, following `tools/frp-grant-admission`.
  No package anywhere depends on it. The README states what the double is, what it mirrors,
  what it serves and claims (D8), its fixtures and their labels, the TLS generator and its
  check, and how lanes and the local release run it.
  Done; `make check-packaging` passes on it (all eight checks). As built, differing
  from the plan:
  - `cryptography` sits in the `dev` group: only the generator and the tests import it.
    The image still carries it, through the identity kit.
  - `pydantic` and `starlette` are declared, since `app.py` imports both directly.
  - `arkhai-kit-deal-lifecycle` and `httpx` are `dev` dependencies, for the tests.
  - The Makefile's `build` builds the wheel into the project's own `dist/`, as
    frp-grant-admission's does. Nothing consumes that wheel, because the image
    installs the project editable (2.6). The project also has `reinit`, `init`,
    `test-unit`, `check-tls` and `tls` targets.
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
  Unit, `tests/unit/test_fixtures.py` (four cases) and `tests/unit/test_authentication.py`
  (nine cases, among them a whitespace token refused at load): pass. As built:
  - Accounts are b1 (buyer), b2 (seller) and d1 (dispute authority), in the
    `00000000-0000-4000-8000-0000000000xx` form D12's example uses. The buyer's
    funding is `1000000000000` USD/6 minor units.
  - The receipt seed is `0d` × 32. The fixture also states the identity it yields,
    `receipt_identity`, so lanes can pin it without deriving it. The loader refuses a
    file whose two disagree. The identity was derived once with
    `uv run --project tools/payments-lane-double python -c` over `Ed25519Signer`, and
    the fixture test re-derives it.
  - The record key was made by generating a random Ed25519 key once, printing only
    its public identity, and discarding the private half unrecorded. The file's
    comment says so. No test can prove there is no private half; the test proves only
    that the key parses as Ed25519.
  - The authority file is a `DisputeEntry` (interface, origin, account, record_key,
    params, advertisement), which the test validates. Its minimum dispute window is
    0 seconds, so every lane's options meet it.
- [x] 2.3 TLS (D3). `tls/generate.py` derives the CA and leaf Ed25519 keys from fixed
  seeds, writes the CA certificate (`lane-ca.pem`), the leaf certificate (`double.pem`,
  SANs `payments-double`, `localhost`, `127.0.0.1`) and the leaf key (`double.key.pem`),
  with fixed serials and validity ending 9999-12-31, and never writes the CA key. Commit
  its output. A `make check-tls` target (in the project's `Makefile`, run by its `test`)
  regenerates into a temporary directory and fails unless the bytes are identical.
  Unit: the leaf verifies under the CA, its SANs are exactly those three, and an
  `ssl.SSLContext` loaded with the CA accepts the leaf.
  Unit, `tests/unit/test_tls.py` (six cases, run on `generate()`'s output): pass. The
  output was committed by `make -C tools/payments-lane-double tls`, and `check-tls`
  passes. "Accepts" is proven by a real TLS handshake over `ssl.MemoryBIO`, with no
  socket, once for each of the three names. The client is
  `ssl.create_default_context(cafile=lane-ca.pem)`, so Python 3.13's strict X.509
  flags apply. A context with no trust anchors refuses the leaf. The seeds are `CA` ×
  32 and `D0` × 32, the serials 1 and 2, and validity runs from 2026-01-01 to
  9999-12-31 23:59:59. The CA is `pathlen:0` with critical basic constraints and key
  usage; the leaf has server-auth EKU, SKI and AKI.
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
  Proven by 2.5's library integration suite and 2.2's authentication unit cases. As
  built, differing from or adding to the plan:
  - `PaymentsDouble` is a framework-free service over the engine, and `create_app`
    binds thin FastAPI routes to it.
  - The double keeps its own map of approved mandates by transaction. The engine
    keeps mandates private, and both the repeat check and read authorization need
    them. An unknown transaction is 404 `transaction_not_found`.
  - Statuses the repository does not record for the service: 422 for
    `unsupported_asset` and `fee_mismatch`, following the engine's 422
    `invalid_mandate`, and 404 for `account_not_found`, as the kit's seller tests
    use. `admission.py` and the README say so; nothing here proves the service
    agrees.
  - Several attachments on one approval: the engine takes one Agreement. The double
    passes it the first attachment that does not hash to the deal, if there is one,
    so `deal_mismatch` still comes after the funds check.
  - A malformed path or `Idempotency-Key` is 400 `invalid_request`. An unmatched
    route answers its own status with `invalid_request`, and an unexpected error is
    500 `internal_error`, each in the `ApiError` body.
  - The `Bearer` scheme name is matched case-insensitively (RFC 7235).
  - Success statuses are all 200, since the kit's client accepts any 2xx.
  - Settings come from `PAYMENTS_LANE_DOUBLE_{FIXTURES,TLS,HOST,PORT}`, defaulting to
    `/opt/payments-lane-double/{fixtures,tls}`, `0.0.0.0` and 8443.
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
  Library integration, `tests/integration/test_double.py` (19 cases), and unit,
  `tests/unit/test_admission.py` (six cases): pass. The integration cases drive the
  kit's real `PaymentsClient` against the app over an `httpx.MockTransport` that
  forwards to FastAPI's `TestClient`, at a loopback HTTPS origin so no ambient proxy
  is mounted. The directory is the committed fixture plus two suite-only accounts
  with tokens, a stranger and an authority-named watcher; the committed fixture
  holds no account that could play either role. The suite reads no snapshot of a
  rate part and submits no event but `reverse`. Exceptions to `TESTING.md`'s "no raw
  calls" rule, each commented:
  - the mandate route, which the kit's client has no call for, read for both the
    403 and the watcher's 200;
  - three rejection paths the client cannot build: no token, a malformed body, and
    an approval attaching another Agreement.
  The rejection paths read the error code through the published `ApiError` model as
  well as the status, because the code is what the double mirrors.
  `deal_mismatch` is proven twice: through the client's `attach_agreement`, and on an
  approval, where it is shown to follow the funds check.
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
  `make build-payments-lane-double` builds the image. The `docker run` check of
  `/health` is unrun: the implement step's rules allow `make build-*` but not
  `docker run`. It is left to validation, whose rules allow `docker`; section 4's
  lanes then start the container and wait on its healthcheck. As built, differing
  from the plan:
  - The image installs the project editable at `/repo/tools/payments-lane-double`,
    from its source, and the runtime stage copies `src/` to the same path. The
    project's wheel is not in the wheelhouse, so the documented `install-wheel` step
    cannot find it. `BUILD_AND_PACKAGING.md` documents a kept editable install only
    for a project one level deep (`e2e-tests`). Closeout's promotion should record
    this two-level variant there.
  - The healthcheck is `curl --cacert lane-ca.pem https://localhost:8443/health`.
  - Because `build-dev` now builds the image, `payments-lane-double` is in
    `scripts/change_namespace.py`'s `BUILT_IMAGES`, so validation teardown removes
    it. `build-payments-lane-double` has its row in
    `scripts/tests/test_change_build_and_helm_targets.py`'s root image targets. The
    image carries no commit tag and is never pushed.
- [x] 2.7 **Verification checkpoint.** Library integration and unit: the double's suite
  (`make test-payments-lane-double`, including `check-tls`). The image builds with
  `make build-payments-lane-double`. Run `make test`, `make check-packaging` (a new
  project, lock and image install) and `make check-comment-hygiene`.
  End-to-end: none — no lane runs the double until section 4. None is owed here.
  Owed by validation: `tests.yml`, job `test · test-payments-lane-double` — the job
  exists in the matrix and passes, `check-tls` included.

  Evidence, all local:
  - `make test-payments-lane-double`: `check-tls` passes, and 44 tests pass (25 unit,
    19 library integration).
  - `make build-payments-lane-double`: the image builds. `docker run` against
    `/health` is unrun (2.6).
  - `make test`: exit 0. It ran before the review fixes (a token check, a
    case-insensitive scheme, dependency declarations, comments and test labels).
    Those touch only the double's project, which the gate above re-ran after them,
    with its relock.
  - `make test-release-tooling`: 2177 passed. It includes the tests.yml-matrix check
    against `make test` and the build-target tests.
  - `make check-packaging`: all eight checks OK after the relock.
  - `make check-change`: everything passes, comment hygiene included. Section 1's
    three citations of this section's files now resolve.

  End-to-end confirmed: none. No `e2e-tests` marker runs the double until section 4
  wires the lanes. Owed by validation, confirmed: `tests.yml`, job
  `test · test-payments-lane-double`, which must exist in the matrix and pass with
  `check-tls`.

  Fresh-context check: the reviewer found no layering, documentation-placement or
  public-content defects. Fixed:
  - `pydantic` and `starlette` are now declared, and `cryptography` moved to `dev`;
  - the generator's and README's claim about who can issue under the lane CA is
    corrected (its seed is public, so anyone can);
  - test values are labelled, and an overstated test name is renamed;
  - the raw mandate read's comment no longer describes a plan;
  - whitespace tokens are refused at load, and the `Bearer` scheme is matched
    case-insensitively.

  Declined:
  - Moving the suite's helpers out of `tests/conftest.py`. `from conftest import`
    works under pytest's default import mode, as the kit's `payment_terms` import
    does.

  Recorded here rather than changed:
  - the raw-call exceptions and the code read on rejection paths (2.5);
  - the inferred statuses (2.4);
  - the editable image install (2.6).

  Handoff to sections 3–5:
  - Lane values: the receipt identity is `receipt_identity` in
    `fixtures/accounts.toml`. The seller's account and token are `accounts.seller`,
    the buyer's `accounts.buyer`, and the lane CA is `tls/lane-ca.pem`. The service
    is `https://payments-double:8443`. The registry recommendation is
    `fixtures/dispute-authority.toml` as a `DisputeEntry` document, to render as
    JSON into `REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES`.
  - Section 1's follow-up stays open: no test yet shows the kit's `transport` step
    from a real TLS handshake with an untrusted certificate. Section 2's handshake
    cases are at `ssl` level only. Section 3's CLI tests are the cheaper place, or
    section 4's lane setup shows it against the running double.
  - The kit's `PaymentsClient` has no call for `GET /transactions/{id}/mandate`. A
    `get_mandate` would remove the suite's one happy-path raw call. Left out
    deliberately: no consumer reads the route, and the kit is not this section's.
  - Running a generator or a Python one-liner needs owner permission in the
    implement step. This run was granted the generator and
    `uv run --project tools/payments-lane-double python -c *`. Sections 4 and 5
    should read the fixtures with tools the step allows, or ask for the same.

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
  Done. Every case below passes. As built, differing from the plan:
  - The three commands share one kit call, `check_configured_payments_access(read_section,
    account)`, added to `access_check.py`. It validates the account first, then calls the
    command's section reader. A `ValueError` from the reader, meaning a configuration
    the storefront cannot read, becomes a `configuration` outcome with fixed text. So a
    `ValueError` escaping the call is always a malformed `--account`, which each command
    turns into a usage error (exit 2).
  - Each command module defines two factories, its seams under TESTING.md's
    command-module convention. `payments_section()` reads the section from the
    configuration `serve` reads: VM and API credits through `settlement_config_mapping()`,
    which their settlement composition resolves, and bare metal through
    `load_storefront_settings().settlement`. `payments_transport()` returns `None` in
    production. VM and API credits import their config module inside the reader, because
    their settings resolve on first import and must come after the root `--config` option.
  - Versions: VM storefront 0.25.0 → 0.26.0, bare-metal storefront 0.25.0 → 0.26.0,
    API-credit storefront 0.18.0 → 0.19.0, each against `dev`. VM pins the bare-metal
    storefront exactly, so that pin moved to `==0.26.0`. VM and API credits raised the
    kit bound to `>=0.6.0`; bare metal already pins `==0.6.0` (1.5). `make lock` rewrote
    the three storefront locks and `e2e-tests`'.
  - VM's dev group now declares `arkhai-kit-deal-lifecycle-client`, which its lifecycle
    integration tests (3.2's among them) import.
  Tests (the HTTP boundary mocked in every storefront case):
  - VM, `tests/unit/cli/test_check_payments.py`, beside the other CLI unit tests rather
    than at the plan's `tests/unit/test_cli_check_payments.py` (8 cases, unit). Both
    factories are replaced: ok and exit 0 with the bearer request; no section; an
    unreadable configuration (the reader raising); an unset key; a `ConnectError` naming
    a certificate failure; a 403 refusal. Each failure exits 1 naming its step, and the
    key appears in no output even when the exception and refusal carry it. A malformed
    account exits 2 before any request. One case keeps the real `payments_section` and
    sets `Settlement` on the storefront's loaded settings (`replaced_setting`): the
    command reads the section from there and reaches the service.
  - API credits, `tests/unit/test_cli_check_payments.py` (6 cases, unit), the same shape,
    including the real section read, without the refusal and usage cases.
  - Bare metal, `tests/test_check_payments_cli.py` (6 cases): the command in process over
    real configuration files under a temporary `XDG_CONFIG_HOME`, with only
    `payments_transport` replaced. It covers ok, no section, unset key, transport, and
    a file the loader refuses. Its sixth case runs the command in a fresh interpreter
    against a loopback port nothing listens on and requires the `transport` step, so the
    client was built and connected: the storefront's `sqlite_client`, `runtime`, `server`
    and `migrations` modules are never imported, and no database file appears.
  - Kit, `tests/test_access_check.py`: three cases for the new call (an unreadable
    configuration, with the key in the reader's message, is `configuration` without it;
    the configured section is read and checked; a malformed account is refused before
    the reader runs). Unit.
  - Kit, `tests/test_access_check_tls.py` (1 case, a real-boundary test in the kit's flat
    `tests/`, as all its tests are). This settles sections 1–2's follow-up. The real check
    and client run against a real TLS listener on 127.0.0.1, which serves a certificate
    the test issues at run time and no trust store holds. The handshake fails, no request
    reaches the listener, and the outcome is `transport`. It shows that a real certificate
    verification failure maps to the transport step. It has no trusted control run, and
    it does not exercise `SSL_CERT_FILE`, which the client ignores for a loopback origin.
    `cryptography` joined the kit's dev group for it.
  What no test here exercises: the storefronts' configuration files as a container
  mounts them for VM and API credits, whose settings load once per process. The lanes'
  `check-payments` at setup (4.7) runs that in each real container. None of the
  storefront "untrusted origin" cases runs a TLS handshake; only the kit's does.
- [x] 3.2 The unreachable-authority proof (D2). Application integration in the VM
  storefront's suite: an Agreement pinned to the `.invalid` authority, the storefront
  configured with an identity-bound `[[DisputeCredential]]` for it whose variable resolves
  to a labelled development value, and servicing stepped: the deal's lifecycle view reads
  `state == "running"` with a non-`Accepted` dispute outcome, and the respondent poll
  neither raises nor marks the deal for repair. Use an injected mediation transport that
  raises the DNS failure an `.invalid` origin produces, so the test needs no network. If
  the view reads otherwise, stop: D2 and the test-compatibility delta are revised
  together before section 4 (design.md D2).
  `tests/integration/test_servicing_unreachable_authority.py` (1 case): pass. The view
  reads as D2 expects, so D2 and the delta stand. It runs over
  `test_payment_settlement`'s harness, which gained optional `authority`, `disputes` and
  `mediation_transport` arguments. The harness has the storefront's settle and lifecycle
  routes in an in-process app, real SQLite and the real `VmDealLifecycle`, with the
  payments service replaced at `PaymentsClient` by the kit's fake.
  - Settle and the final read go through the typed clients. The read is the buyer's
    `LifecycleClient.read`, the call `e2e_vm_payment_deal`'s stage 2 makes.
  - Servicing is stepped by calling `VmDealLifecycle.cycle()` directly, the step the
    `settlement-servicing` loop runs, not through the run-cycle route. So the test is
    the in-process app plus a direct call into its lifecycle composition.
  - It shows: both the respondent poll (`/respondent`) and the deal's watch (`/record`)
    reach `dispute.invalid` and fail. The cycle completes. The deal list reads
    `running`. The buyer's view reads `authority.state == "running"` with an `Unknown`
    outcome ("mediation transport result is unknown").
  - Correction to the task's wording: the respondent poll itself does raise.
    `RespondentPoller.poll` lets the `MediationTransportError` escape, since
    `MediationAdapter.respondent` does not catch it. `VmDealLifecycle.cycle` catches
    it and logs "VM respondent discovery awaits recovery" at ERROR, every cycle, and
    the next cycle retries. The test asserts that log line is the cycle's only error.
    Nothing is marked for repair, because the poll fails before it reads any case.
    What D2 relies on holds: servicing does not stop and the deal is not
    `repair_required`.
  - New production seam: `VmDealLifecycle(..., mediation_transport=None)` hands one
    transport to every mediation client it builds (`deal_lifecycle.py`). It is an
    alternative to writing into `lifecycle.clients` directly, which
    `test_lifecycle_admin.py` and `test_lifecycle_ends.py` still do.
  - The authority's values are the lane's pinned ones from
    `tools/payments-lane-double/fixtures/dispute-authority.toml`, copied into the test
    and labelled, since the storefront does not depend on the double.
- [x] 3.3 **Verification checkpoint.** Unit: the three CLI suites. Application
  integration: `test_servicing_unreachable_authority.py`. Run `make test-storefront`,
  `make test-bare-metal`, `make test-apicredits`, then `make test`,
  `make check-packaging` (versions and locks) and `make check-comment-hygiene`.
  End-to-end: none yet — section 4's lane targets run `check-payments`, and
  `e2e_vm_payment_deal`'s stage 2 exercises 3.2's behaviour once the VM lane is wired.
  None is owed here.
  Owed by validation: `tests.yml`, jobs `test · test-storefront`, `test · test-bare-metal`
  and `test · test-apicredits` — each passes from the relocked environments.

  Evidence, all local, after the fresh-context fixes:
  - `make test-storefront`: unit 1213 passed, 1 skipped; integration 525 passed. These
    include the 8 CLI cases and 3.2's case.
  - `make test-bare-metal`: storefront 582 passed, with the 6 CLI cases. The domain,
    IaC, buyer and adapter suites pass.
  - `make test-apicredits`: storefront 254 passed, with the 6 CLI cases. The other
    API-credit suites pass.
  - `make -C kit test-arkhai-payments`: 195 passed, with the TLS case and the three
    cases for the new call.
  - `make test`: no failing suite. It ran before the second check's test-only fixes
    (the real section-read cases, the subprocess's step assertion, docstrings), which
    the three storefront gates above re-ran.
  - `make check-packaging`: all eight checks OK after `make lock`.
  - `make check-uv-version`: OK.
  - `make check-change`: every check passes, comment hygiene included.

  End-to-end confirmed: no `e2e-tests` marker exercises this section's behaviour yet.
  Every VM lane already constructs `VmDealLifecycle`, now with `mediation_transport=None`,
  so it shows only that the default is inert. Section 4's lane setup runs
  `check-payments` in each payment storefront's container (4.7), and
  `e2e_vm_payment_deal`'s stage 2 (`test_commit_replay_and_servicing_keep_the_same_hosted_deal`)
  then exercises 3.2's behaviour against the lane's unanswerable authority.
  Owed by validation, corrected to add the kit job, since this section changed the
  kit's `access_check.py`, its tests and its lock:
  - `tests.yml`, jobs `test · test-storefront`, `test · test-bare-metal` and
    `test · test-apicredits`: each passes from the relocked environments.
  - `tests.yml`, job `test · test-kits`: the payments kit suite passes, with
    `test_access_check_tls.py` and the new `check_configured_payments_access` cases.

  Fresh-context check. It found no layering, comment-hygiene or fixture-labelling
  defect. Fixed:
  - 3.2 could not show what it claimed about the respondent poll. It now asserts the
    paths both reads reach and the one logged error. The poll does raise, as 3.2's
    correction records.
  - The command body was copied in three CLIs. It is now one kit call.
  - The bare-metal suite was labelled "Unit" although it reads real files and starts a
    subprocess; its docstring now says what it runs.
  - 3.2's docstring cited the whole lane scenario; it now cites only the servicing part.
  - VM's dev group was missing `arkhai-kit-deal-lifecycle-client`; it is declared now.
  Declined:
  - Moving the kit's TLS test into a `tests/integration/` directory. The kit's suite is
    flat, and its tests import the shared `payment_terms` module by sibling path.
  - Showing the bare-metal loader's refusal message in the outcome. Every `detail` is
    fixed text by the kit's invariant, and the VM and API-credit loaders' messages
    (TOML decode errors) may quote input. `serve` and `config` still report the reason.
  A second check found these, all fixed: VM's and API credits' real section read was
  untested (one case each now); the bare-metal subprocess case did not require the
  `transport` step; two docstrings cited the untrusted-origin scenario without saying no
  handshake runs; the TLS test's level label; and three overstatements in these notes.

  Handoff to section 4:
  - Run the check as `docker compose exec <storefront> <cli> check-payments --account
    <seller account>`. It exits 0 on ok, 1 on a failed step, and 2 on a malformed
    account. Its one line on stdout is the JSON outcome. The CLIs are
    `market-storefront`, `bare-metal-storefront` and `apicredits-storefront`.
  - The lane CA must reach the storefront through `SSL_CERT_FILE`. The client honours it
    only for a non-loopback origin such as `https://payments-double:8443`.
  - The VM lane's storefront logs "VM respondent discovery awaits recovery" at ERROR on
    every servicing cycle while it holds the `.invalid` authority's credential. That is
    expected, not a failure; `e2e-tests/README.md` (4.8) may say so.
  - `e2e_vm_payment_deal`'s stage 2 reads `view.authority.state`, the payment view's
    state. It reads `running` because the deal's dispute credential resolves (3.2). If
    the VM lane's `[[DisputeCredential]]` variable is unset or empty, the view reads
    `repair_required`.

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

- [x] 4.1 The double in each lane (D1, D3, D6). `compose.payments-double.yml` runs
  `payments-double` on the lane's network with no host port, its healthcheck on `/health`
  over HTTPS with the lane CA. Each lane's `-f` list in `e2e-tests/Makefile` (and the
  matching `e2e-*-down`/`-logs` invocations) includes it. Each payment storefront —
  Bob's VM storefront, the bare-metal storefront, the API-credit storefront —
  `depends_on` it with `service_healthy`, mounts the lane CA and sets `SSL_CERT_FILE`.
  Done. Each lane's compose variable (`E2E_*_COMPOSE`) is the one list its test, down
  and logs targets share, so all three carry the new files. Storefront wiring is per
  lane, in a lane-only overlay: the bare-metal lane's `compose.bare-metal-local.yml`
  and the API-credit lane's `compose.apicredits-lane.yml`, both already lane-only, and
  a new `compose.vms-lane.yml` for VM, since `compose.vms-local.yml` is shared with the
  full local stack. The CA reaches each container at `/run/payments-lane-double/lane-ca.pem`
  from `${PAYMENTS_LANE_CA_FILE}`, and the seller token as `ARKHAI_PAYMENTS_API_KEY`
  from `${PAYMENTS_LANE_SELLER_API_KEY}`, both guarded with `:?`.
  Evidence:
  - Unit, `e2e-tests/tests/unit/test_domain_stack_configuration.py` (static reads of
    the overlay files: `depends_on`, `SSL_CERT_FILE`, the token variable and the CA
    mount for each storefront; no host port on the double; `-f
    compose.payments-double.yml` three times in `e2e-tests/Makefile`, a substring
    count, not a check of each `E2E_*_COMPOSE`; no "payments" in
    `docker-compose.yml` and no `PAYMENTS_LANE` variable in `compose.vms-local.yml` or
    `compose.apicredits-local.yml`): pass.
  - Compose render, `scripts/tests/test_lane_compose.py` and
    `scripts/tests/test_bare_metal_compose.py` in `make test-release-tooling`, which
    run `docker compose config` over each lane's files, in the order
    `e2e-tests/Makefile` layers them (lists copied by hand, not read from the
    Makefile), with the env file the root target prints. A new
    case per lane checks the rendered double (image, no ports), the storefront's
    `depends_on`, `SSL_CERT_FILE`, the token equal to the fixture seller's, the CA and
    configuration mounts, and each registry's recommendation parsing as the fixture
    authority. A full-stack case checks the double is absent there and Bob and the
    credits storefront keep the stack profiles and no payments variables: 2181 passed.
    These suites first failed (6 cases) because the section had not layered the new
    files into them; the fresh-context check caught it.
  - System: the bare-metal lane came up with the double healthy and the storefront
    waiting on it (4.9). The API-credit lane's compose files interpolated (its `down`
    ran) before that run was stopped; it and the VM lane were not brought up here
    (4.9).
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
  Done, through `*_STOREFRONT_CONFIG`, as full lane copies:
  - VM: `domains/vms/storefront/storefront.bob.lane.toml`, `storefront.bob.toml` plus
    the payments section, `arkhai.payments.v1` in `priority`, and the
    `[[DisputeCredential]]` (variable `VM_LANE_DISPUTE_API_KEY`, set by
    `compose.vms-lane.yml` to a labelled public development value).
  - API credits: `domains/apicredits/storefront/storefront.credits.lane.toml`,
    `storefront.credits.toml` plus the payments section, `priority`, and a payment
    publication clause in `[pricing].settlements` (1000 USD/6 base units per token to
    the seller's payee account, P7D window, 15-day dispute window).
  - Bare metal: `storefront.dev.toml` edited in place; it is the lane's alone.
  Why copies rather than an overlay: the storefronts' Dynaconf loaders merge with
  `merge_enabled`, which concatenates lists, so an overlay restating `priority` would
  duplicate entries, and the settlement registry refuses duplicates. A unit test holds
  each copy equal to its stack profile once the payments additions are removed, so the
  two cannot drift silently.
  Correction to the plan's premise for the API-credit lane: enabling payments alone
  publishes no payment option. The credits storefront's option builder publishes one
  only from a publication clause, and the seeded listing passes none of its own. A
  `[pricing].settlements` clause supplies it; it is configuration only, and it reaches
  every listing created without clauses, which in the lane is the seed. By reading
  `listing_service.publish_from_quota`, the seed's Alkahest escrow is still offered
  beside it, so `e2e_credits_deal` keeps its option; nothing here ran either the
  option builder over the clause or that scenario (4.9).
  `make e2e-vms-dev-env` was split: its stack values moved to `e2e-vms-stack-env`, which
  the full local stack's `e2e-dev-identities-env` now calls, as the API-credit stack
  already had `e2e-apicredits-stack-env`; the lane target adds
  `VMS_BOB_STOREFRONT_CONFIG` and the double's values.
  Evidence: unit, `test_domain_stack_configuration.py` (each lane copy equals its
  profile minus the payments additions, the profile has payments off; each lane
  storefront's payments section equals the double's fixture receipt identity and fee,
  `service_url`, `livemode = false` and `api_key_env`, with no `[[Dispute]]`; Bob's
  credential matches the fixture authority and its variable is set; the API-credit
  clause pays the fixture seller account): pass. System: the bare-metal storefront
  configuration served the payment deal (4.9).
- [x] 4.3 Registry recommendations (D7). Each lane's registry — both VM registries, the
  bare-metal registry, the API-credit registry and the compute registry it routes through
  — sets `REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES` to the pinned authority
  rendered from `tools/payments-lane-double/fixtures/dispute-authority.toml`, through the
  lane's dev-env target. No storefront or buyer configuration gains a `[[Dispute]]` entry.
  Done. A new stdlib-only script, `tools/payments-lane-double/scripts/lane_env.py`,
  reads the double's fixtures and prints `VAR=value` lines; the root Makefile runs it
  with the host's `python3 -I` (3.11 or newer, for `tomllib`). It sits outside the
  double's package, so the wheel and image do not carry it, following
  `kit/arkhai-payments/scripts/check_vectors.py`. Its `compose` mode gives
  `PAYMENTS_LANE_DISPUTE_AUTHORITIES` (the authority document as a one-item JSON array,
  single-quoted for Compose), `PAYMENTS_LANE_CA_FILE` and `PAYMENTS_LANE_SELLER_API_KEY`;
  each lane's dev-env target appends them. The five registries read the first through
  `REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES` in the lane overlays.
  Evidence:
  - `tools/payments-lane-double/tests/integration/test_lane_env.py` (5 cases, in the
    double's `make test`): two read the script without running it (its imports are
    standard library only; the service URL's host is a name the leaf certificate
    covers, at the double's port); three run it in a separate isolated (`-I`) process
    of the project's own interpreter, not the host `python3` the Makefile uses, so
    the 3.11 floor is untested, and check its output equals its functions', the
    recommendation validates as the fixture's `DisputeEntry`, and the runner values.
    Pass.
  - Compose render, `test_lane_compose.py`'s per-lane case: the single-quoted value
    reaches each of the five registries as JSON equal to the fixture authority. Pass.
  - Static, the registry cases in `test_domain_stack_configuration.py` (only that each
    overlay names the guarded variable): pass.
  - System: in the bare-metal lane the storefront published a payment option and the
    buyer accepted it; the option builder publishes none without an authority
    advertising `arkhai.payments.v1`, so the recommendation reached the storefront
    (4.9).
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
  Done. `lane_env.py runner` prints the shared overrides (`SERVICE_URL`,
  `SERVICE_IDENTITY`, `FEE_BPS`, `LIVEMODE=false`, `LANE_OWNED=true`, `API_KEY_ENV`,
  `BUYER_ACCOUNT`, `SELLER_ACCOUNT`), the buyer's token under `PAYMENTS_BUYER_API_KEY`
  (no `ARKHAI_` prefix, so the runner's settings never load it), and
  `SSL_CERT_FILE=/run/payments-lane-double/lane-ca.pem`. Root targets
  `e2e-{vms,bare-metal,apicredits}-payments-env` add the buyer marketplace seed and
  the lane storefront's own key, read from its identity env file; bare metal adds
  `COMPUTE_HOURLY_GROSS=1000000` and `DISPUTE_WINDOW=P7D`. Each lane target writes
  `.e2e-<lane>-payments.env` (git-ignored) and passes it to `test-buyer-machine` as
  `PAYMENTS_ENV_FILE`, which adds `--env-file` and the CA mount. String values carry
  `@str`, since the runner's Dynaconf parses environment values as TOML.
  Differences from the plan:
  - `SELLER_ACCOUNT` goes to every lane, not only bare metal: the VM scenario's listing
    reads it as its payee account.
  - The buyer marketplace seed is a Makefile constant (`E2E_PAYMENTS_BUYER_SEED`, 32
    bytes of `0xb1` as unpadded base64url), not a fixture file. The first lane run used
    hex and failed at profile creation: an Ed25519 credential must be unpadded
    base64url. `settings.toml`'s old comment calling the credentials hex was wrong too.
  - The API-credit scenario's refund built an Ed25519 signer from a hex seed and
    trusted it as the storefront's publisher. The lane's credits storefront signs as an
    eip191 principal (Anvil 3), so the refund now signs with
    `create_signer(<the lane's storefront scheme>, SELLER_MARKETPLACE_CREDENTIAL)`,
    checks it is the pinned storefront principal, and trusts that principal, as the
    bare-metal scenario does. The design's "Facts" called that credential an Ed25519
    seed; the plan's "that lane's storefront key, in that lane's scheme" is what holds.
  `buyer_cli.py` builds the subprocess environment from `dict(os.environ)`, so the
  token variable and `SSL_CERT_FILE` reach `market` unchanged; no change needed.
  `config-docker.yml` is unchanged.
  Evidence: `test_lane_env.py`'s runner case (the script run in a separate process)
  covers `lane_env.py runner` only: pass. The root `e2e-<lane>-payments-env` targets
  (the buyer seed, the seller key read with `sed`, the bare-metal extras) have no test
  of their own. System: the bare-metal target's output served the bare-metal payment
  deal (4.9), its `market` subprocess approving at the double. The VM and API-credit
  targets, and the API-credit refund's new signer path, are unrun: those lanes did not
  run here (4.9).
- [x] 4.5 The helper (D6). In `helpers/payments.py`: `PAYMENTS.LANE_OWNED`, a strict
  boolean defaulting to false; with it true, an unready target fails naming its URL
  rather than skipping. `target_ready` builds an `ssl.SSLContext` from `SSL_CERT_FILE`
  when it is set and passes it as `verify`, keeping `trust_env=False`. `settings.toml`
  documents `lane_owned` in `[default.payments]`. Unit (`test_payments_helper.py`): an
  unready lane-owned target fails naming the URL; an unready external target still
  skips; the probe uses a context built from `SSL_CERT_FILE` and disables environment
  proxies, through an injected readiness seam rather than the network.
  Done. `target_ready(url, *, get=httpx.get, environ=os.environ)`: `get` and `environ`
  are the injected seams. Beyond the plan, `LANE_OWNED` set with no `SERVICE_URL` fails
  too, naming both: a lane that claims its own target and configures none is a broken
  lane, which the MODIFIED requirement fails by name.
  Unit, `test_payments_helper.py` (new: unready lane-owned fails naming the URL; ready
  lane-owned yields its policy; lane-owned without a target fails; unready with
  `LANE_OWNED=false` still blocks; the probe's `verify` is a context holding exactly the
  lane CA's certificates with `trust_env=False`; without `SSL_CERT_FILE` it keeps
  `verify=True`; four unhealthy or unreachable answers read unready; `LANE_OWNED` joins
  the strict-boolean case): pass. The probe cases replace `get`, so no TLS handshake
  runs in them. System: the bare-metal lane's scenario read the double ready over HTTPS
  under the lane CA (`GET https://payments-double:8443/health` 200 in its log).
- [x] 4.6 The VM scenario's mediation prerequisite (D2). A `MEDIATION.SERVICE_URL`
  setting, blank by default in `settings.toml`, read by a helper beside the payments
  helper; `test_vm_payment_deal.py`'s stages 3 and 4
  (`test_operator_end_files_one_case_without_a_local_payment_remedy`,
  `test_seller_refund_is_financial_and_release_waits_for_the_callback`) report a blocked
  skip naming it when blank; stages 1 and 2 run unchanged. Update the
  `e2e_vm_payment_deal` marker's description in `e2e-tests/pyproject.toml`. Raise
  `e2e-tests`' bound on `arkhai-kit-arkhai-payments` only if it uses the new API, and
  relock if it does. Unit: the helper blocks on blank and returns the URL otherwise.
  Done. `helpers/mediation.py`'s `configured_mediation()`; a module fixture
  `mediation_target` in `test_vm_payment_deal.py`, requested by stages 3 and 4 only, so
  pytest skips them by name before their bodies run. `[default.mediation]` in
  `settings.toml`. The module docstring now says what the lane runs. The marker
  descriptions of all three payment scenarios were updated, not only VM's: the other two
  said "blocked without a reachable payments target", which a lane-owned target makes
  false. `e2e-tests` uses no new kit API, so no bound change and no relock.
  The setting is a gate only: the stages file with the authority their Agreement pins,
  through the registries, and never contact the URL. The helper's docstring and the
  README say so.
  Unit, `tests/unit/test_mediation_helper.py` (blank, whitespace and null block naming
  the setting; a set URL is returned stripped and without its trailing slash): pass.
  Stages 3–4's skip in the VM lane is unrun here (4.9).
- [x] 4.7 `check-payments` at lane setup (D6, D12). After `up --wait`, each lane target
  runs `docker compose exec <storefront> <cli> check-payments --account <the lane's
  seller account>` for each payment storefront, and fails the target, before pytest, on a
  nonzero exit.
  Done: an `e2e_check_payments` macro in `e2e-tests/Makefile`, `exec -T` (no TTY in CI),
  the account from `lane_env.py seller-account`, and on failure an `::error::` line
  naming the service. System: in the bare-metal lane it printed
  `{"check": "payments", "outcome": "ok", "service_url": "https://payments-double:8443",
  "account": "00000000-0000-4000-8000-0000000000b2", "assets": [], "held": 0}` and the
  lane went on to pytest. The VM (`bob-storefront`, `market-storefront`) and API-credit
  (`credits-storefront`, `apicredits-storefront`) invocations are unrun here (4.9).
- [x] 4.8 `e2e-tests/README.md`: correct the passages sections 1–4 make false — the shared
  payment configuration (a lane now configures its own target, `LANE_OWNED`), "Hosted VM
  servicing" (stages 1–2 run against the double, 3–4 need `MEDIATION.SERVICE_URL`), and
  "Bare-metal payment deal" (it runs in the lane; the re-drive repeats the canonical
  commit). The rest of the permanent documentation is closeout's.
  Done: those three passages, plus the lane setup check. The bare-metal passage already
  described the re-drive as the canonical commit and keeps it. Package documentation the
  code needed also changed: `tools/payments-lane-double/README.md` (how lanes run the
  double, `lane_env.py`) and `dev-env/identities/README.md` (a "The payments lane
  double" section, cited by the new overlays, and the stack table's files).
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

  Evidence, local, after both fresh-context checks' fixes unless noted:
  - `make test-e2e-unit`: 537 passed, with `test_payments_helper.py`,
    `test_mediation_helper.py` and the new `test_domain_stack_configuration.py` cases.
  - `make -C tools/payments-lane-double test`: `check-tls` passes; 49 passed, with the
    five `test_lane_env.py` cases.
  - `make test-release-tooling`: 2181 passed, with the Compose render cases (4.1).
  - `make -C helm test-render`: passes, `test_the_development_configuration_passes_the_schema`
    included over the edited `storefront.dev.toml`.
  - `make test`: exit 0, after the render-suite fix. The first run failed six render
    cases (4.1). It ran before the second check's fixes, which touched comments, a
    `settings.toml` comment line, the README and these notes, and no code path.
  - `make check-packaging`: all eight checks OK. `make check-change`: every check passes.
  - System, bare-metal lane, `make -C e2e-tests test-e2e-bare-metal` (before the fresh
    checks; the later edits touch no code it ran). The stack came up with the double
    healthy, and `check-payments` printed `"outcome": "ok"` for the seller's account.
    pytest: 61 passed, 2 failed, 2 skipped, 3 errors. The three errors were
    `e2e_bare_metal_payment_deal` failing at setup on the hex buyer seed (4.4). After
    the seed fix, `test-buyer-machine BUYER_MODULE=e2e_bare_metal_payment_deal
    PAYMENTS_ENV_FILE=…` against the running stack passed all three stages with no
    skip: discovery of the payment option, approval at the double, receipt-gated mock
    delivery, re-drive from the run log, seller refund read back as reversed at the
    double, and physical teardown. The run's env file was regenerated by hand with
    the Edit tool for that rerun, because the root target that writes it is outside
    this step's allowed commands; the committed Makefile constant is the same value.
  - The two failures predate this change: `test_bare_metal_introduction.py::TestStage02_Reveal`
    and `test_bare_metal_unbacked_introduction.py::...test_03_the_unbacked_listing_offers_only_an_introduction`
    read the option-level `mechanism` key, which `dev`'s 38a5fec12 (#314) removed from
    published options. The two skips follow the first failure. VM's
    `e2e_vm_introduction` shares `introduction_stages.py` and will fail the same way.
    Not fixed here: outside the section, and owned by whoever repairs #314's fallout.
  - API-credit and VM lanes: not run. Every lane names its chain container `anvil` and
    publishes port 8545, the bare-metal stack stayed up after its run, and this step may
    run neither `docker` nor `make -C e2e-tests e2e-*-down`, so no second lane could
    come up. The API-credit run got as far as its `down` (its compose files
    interpolate) before it was stopped. Both are left to validation's pipeline. Unrun
    there: `check-payments` in `bob-storefront` and `credits-storefront`;
    `e2e_credits_payment_deal`, including its new refund signer and the seed's payment
    option; `e2e_vm_payment_deal` stages 1–2 reading `running` and stages 3–4's
    mediation skip; and every other VM and API-credit marker with the registries'
    new recommendation.

  End-to-end confirmed: `e2e_bare_metal_payment_deal` passes in the bare-metal lane.
  `e2e_credits_payment_deal` and `e2e_vm_payment_deal` are the API-credit and VM lanes'
  evidence, owed to validation's pipeline. Each lane target's `check-payments` step is
  part of the lane run. The bare-metal and VM lanes' introduction markers fail for the
  pre-existing reason above.
  Owed by validation, confirmed: `tests.yml`, job `test · test-e2e-unit` passes. Corrected
  to add the jobs this section's other suites run in, since it changed their tests and
  the files they render: `tests.yml`, job `test · test-payments-lane-double`, with
  `test_lane_env.py`; and `tests.yml`, job `test · test-deployment-packaging`, which runs
  `make test-release-tooling`'s Compose render cases and `make -C helm test-render`.

  Fresh-context checks, two:
  - Fixed after the first: the six render-suite failures (the blocking finding); the
    script moved from the package to `scripts/`, out of the wheel and image; its test
    moved to `tests/integration/`; a rendered check that the recommendation arrives as
    JSON; two helper comments; the double README's claim that nothing restates the
    fixtures; the mediation setting described as the gate it is; the Python 3.11 floor
    documented; overstated notes.
  - Fixed after the second: a history comment copied into the credits lane copy; a
    forward reference to the cluster service in `lane_env.py`; `seller_account`
    documented; the README's note that the VM readiness gate reads its own
    `PAYMENTS.MEDIATION_URL`; four overstated notes.
  - Declined: patching the helpers' module-level `settings` in their tests, which
    `test_payments_helper.py` already does and which has no other seam; the static
    overlay checks in `test_domain_stack_configuration.py` beside the render cases,
    because the render cases skip without Docker Compose and the static ones do not;
    regenerating an old `.e2e-<lane>.env` in `e2e-*-down`/`-logs` (a local file
    predating this change lacks `PAYMENTS_LANE_*`, so down refuses until the next lane
    run rewrites it; CI starts clean).

  Handoff to section 5 and closeout:
  - Section 5 can reuse `tools/payments-lane-double/scripts/lane_env.py` for
    `topology-secrets.sh` (the seller token) and the e2e-tests chart's `PAYMENTS` values
    (`runner` mode prints them). Its `SERVICE_URL` is the double's Compose name, which
    D3 makes the cluster Service name too.
  - Lane-only storefront copies: `storefront.bob.lane.toml` and
    `storefront.credits.lane.toml`; a change to `storefront.bob.toml` or
    `storefront.credits.toml` must be made to the copy, or
    `test_a_lane_storefront_configuration_is_its_stack_profile_plus_payments` fails.
  - Closeout items, passages this section makes false: `docs/development/TESTING.md`'s
    "Private Service Dependencies" ("a blank SERVICE_URL … is what the pipeline runs",
    an unready target always blocking) and the bare-metal lane's "Unconfigured payments
    remain a named blocked prerequisite"; `DEPLOYMENT_AND_CONFIG.md`'s "Per-domain stack
    composition" (the overlay list, and "passes only the signer credential through the
    environment" for the lane's bare-metal storefront) and its naming of
    `storefront.bob.toml` as the VM lane's configuration; `ROADMAP.md`'s "none
    configures a payments target"; `.github/workflows/e2e.yml`'s lane descriptions,
    incomplete. Also for closeout to judge: `openspec/specs/deployment-state/spec.md`'s
    requirement that public renderings contain no payment authority, beside lane
    Compose renders that now run the double.
  - The design's "Facts" call the API-credit seller credential an Ed25519 seed; it is
    the lane storefront's eip191 key (4.4). Narrative compression should correct it.
  - The session ran long; section 5 should start fresh.

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

- [x] 5.1 The subchart (D3, D11). `payments-lane-double`, disabled in `helm/values.yaml`,
  enabled in `helm/local-values.yaml` and disabled again in
  `helm/bare-metal-release-values.yaml`, so the two-release topology runs one double. Its
  Service is named `payments-double` (not release-prefixed), port 8443. Its Deployment
  runs `arkhai:payments-lane-double` under the image overlay the other local images use;
  with `tls.existingSecret` set it mounts that Secret's certificate and key over the
  image's own files, and otherwise uses the image's. Render tests: default disabled; the
  local values render one Deployment and a Service named `payments-double`; the topology
  values render none; `tls.existingSecret` mounts the Secret.
  Chart render, `helm/charts/payments-lane-double/tests/test_render.py` (5 cases, run by
  `test-render.sh`'s chart loop): pass. As built:
  - The Deployment is release-scoped (`<release>-payments-lane-double`), one replica,
    `Recreate`; only the Service name is fixed.
  - `tls.existingSecret` names a `kubernetes.io/tls` Secret; its `tls.crt` and `tls.key`
    mount by `subPath` over `/opt/payments-lane-double/tls/double.pem` and
    `double.key.pem`. The probes are `httpGet` with `scheme: HTTPS`, which the kubelet
    does not verify, so they hold whichever certificate is served; the image's
    healthcheck trusts only the committed lane CA and would not. This is shown at
    render level only. No test ties the mount targets to the file names the double
    reads (`settings.py`'s `double.pem` and `double.key.pem`), so renaming one side
    would fail nothing here; a deployment with its own Secret is unrun.
  - `helm/values.yaml` restates the subchart's image, so a change's image overlay
    suffixes it; `helm/tests/test_image_overlay.py` now covers it, since the local
    release enables it. The umbrella schema gains an open `payments-lane-double` entry
    beside `bare-metal-storefront`'s; the subchart's own schema is closed.
  - `TOPOLOGY_ROLLOUT_ORDER` leaves the double out, as it leaves dev-env out: a restart
    loses every payment it holds in memory. A rebuilt double image therefore does not
    roll on `topology-up`.
- [x] 5.2 The CA bundle option (D3; delta "A storefront chart trusts a
  deployment-supplied CA bundle"), on both storefront charts: a value naming a ConfigMap
  and key, or alternatively a Secret and key, mounted read-only and named by
  `SSL_CERT_FILE`; no default; nothing rendered when unset; refused when both sources are
  named. Render tests for each source and unset.
  Chart render, three cases in each chart's `tests/test_render.py`: pass. The value is
  `caBundle: {configMapName, secretName, key}` (per agent in the storefront chart, top
  level in the bare-metal chart). The chosen key mounts as `ca-bundle.pem` in a
  read-only directory volume at `/etc/arkhai/ca`, and `SSL_CERT_FILE` is
  `/etc/arkhai/ca/ca-bundle.pem`. Empty names render nothing. Naming both is refused at
  render, naming both. A source without its key is refused: by the storefront chart's
  template, which has no default key, and by the bare-metal chart's values schema, which
  refuses an empty key; its `values.yaml` states every value with its default, the key
  included. The test helper asserts the volume, mount and variable together, all present or
  all absent. The values comments say the bundle replaces the image's trust store, so it
  must hold every CA the storefront's HTTPS peers chain to.
- [x] 5.3 The payments-key option (D11; delta "A storefront chart injects the payments key
  from a deployment Secret"), on both storefront charts: a value naming a Secret and key,
  exposed with `secretKeyRef` under the variable the agent configuration's
  `Settlement.arkhai_payments.api_key_env` names, read case-insensitively as the chart
  reads every key it uses; refused at render when the configuration names no
  `api_key_env`; nothing rendered when unset. Render tests: set, unset, and refused.
  Chart render, three cases in each chart: pass. The value is
  `paymentsKey: {secretName, key}`. The variable is read through each chart's folded
  lookups at `Settlement`, `arkhai_payments` and `api_key_env`. The set case renders it
  in two spellings (`arkhai_payments.api_key_env`, `Arkhai_Payments.API_KEY_ENV`). The
  refusal names `Settlement.arkhai_payments.api_key_env`, with no payments section and
  with one lacking the key. Nothing renders with no `secretName` or an empty one.
  Beyond the plan, found by the fresh-context check: a variable the chart already sets
  (`XDG_CONFIG_HOME`, `ARKHAI_IDENTITY_CREDENTIAL`, `SSL_CERT_FILE`, in any case) is
  refused, since it would render twice. So is one beginning `STOREFRONT_`, which the
  loader would read as a setting. One more case per chart covers both refusals.
- [x] 5.4 The payments-only render case (D11): a storefront agent with payments
  configured and Wallet, Chains and Alkahest set to `null` and RPC off renders with the
  payments configuration, the CA mount and the key variable and nothing for the removed
  settings, on both charts.
  Chart render, one case per chart: pass. The storefront chart renders the local
  release, with Bob's `Wallet`, `Chains`, `Settlement.alkahest`, `Settlement.contact`,
  the Alkahest clause and the address book set to `null`, `priority` set to
  `[arkhai.payments.v1]`, and `global.rpc.enabled: false`. The bare-metal chart
  renders its example the same way; it has no RPC value. "RPC off" is shown only as
  far as rendering goes: no storefront template reads `global.rpc`, so setting it
  changes nothing the storefront chart renders. The case's check for RPC keys
  re-checks the `Chains` removal. Beyond the plan, each case also runs the
  storefront's own check over the rendered document: the VM startup refusal reports
  none, and the bare-metal loader's publication checks report no problem. Both ran in
  this session, since `make init` had built both storefront environments. The first
  run caught the test's own overlay, which had left `alkahest.v1` in `priority`;
  `contact` is removed for the same reason. In CI no job has both Helm and the
  storefront environments (TESTING.md), so there these two checks print a skip.
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
  Chart render, two cases per chart: pass. Shared helpers:
  - storefront chart: `storefront.agentEnv`, `storefront.agentConfigMounts` and
    `storefront.agentConfigVolumes`;
  - bare-metal chart: `bare-metal-storefront.env`, `.configMounts` and `.configVolumes`.
  Each Deployment now renders its environment, its configuration mounts and their
  volumes only through them. The equality case renders the local release (storefront
  chart) or the example with payments access (bare metal). It compares the pod's whole
  `env` block with the Deployment's, and its mounts and volumes item by item with the
  Deployment's less `tun-device` and `arkhai-data` (`data` in bare metal). It checks
  that persistence is on and the Deployment mounts its claim, which the pod does not.
  It also checks the pod has no probe, capability, `/dev/net/tun` or `entrypoint.sh`,
  has the test labels and no `app.kubernetes.io/name`, and has `enableServiceLinks:
  false`. Each payments-deciding piece is present, so the comparison is not between
  empty lists. As built, differing from the plan:
  - In the storefront chart, `tests.paymentsAccount` is per agent
    (`agents.<name>.tests.paymentsAccount`), and one pod renders per agent that sets it,
    named `<agent fullname>-payments-check`: each agent has its own credential, key and
    payee account. The bare-metal chart's is top-level `tests.paymentsAccount`.
  - "Payments is configured" is read as a non-empty `[Settlement.arkhai_payments]`
    section in any spelling. An account without one renders nothing, as the plan's
    "rendered only when" says, rather than refusing.
  - The pod mounts the Alkahest address book too, when the agent names one: it is a
    configuration file the loaded settings name, and the check loads them as `serve`
    does.
  - The env and mounts are now rendered through the helpers. The suites are not byte
    snapshots, so what is shown is that every existing assertion over them passes
    unchanged, the defaults, fixtures and second-agent cases among them. One visible
    difference: the bare-metal ConfigMap volume's name is now quoted.
  - `make -C helm test-module MODULE=storefront` still filters the smoke test by name;
    the payments check runs under `make -C helm test` and `topology-check`.
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
  Chart render, `helm/tests/test_release_topology.py` (four new cases, three updated):
  pass. As built:
  - Values: Bob's agent in `local-values.yaml` and the bare-metal storefront in
    `bare-metal-release-values.yaml` gain `[Settlement.arkhai_payments]` (the double's
    URL, receipt identity, 250 bps, `livemode: false`,
    `api_key_env: ARKHAI_PAYMENTS_API_KEY`), `arkhai.payments.v1` in `priority`,
    `caBundle` and `paymentsKey` on the two names D3 and D11 give, and
    `tests.paymentsAccount` set to the seller's fixture account. The registry's
    `descriptor.recommendedDisputeAuthorities` names the pinned authority. The registry
    chart already had the value, so it needed no change.
  - The new cases:
    - one double, in release 1, whose Service URL is `lane_env.SERVICE_URL` and both
      storefronts' `service_url`;
    - every payments value equal to the double's fixtures, read with `tomllib`: the
      identity, the fee, the account each payments check reads, the registry's JSON
      recommendation, and the e2e-tests profile. The profile's accounts, identity
      and fee are compared with the fixtures, its URL and token variable with
      `lane_env`'s constants, and only `livemode` and `lane_owned` with
      `lane_env.runner_lines`. Neither render contains `development_auth`;
    - the e2e-tests chart refusing credential keys;
    - every ConfigMap the releases read and no chart renders is `payments-ca-bundle`,
      which is `LOCAL_CONFIGMAPS` and what the script creates, from the committed
      lane CA under the key both storefronts mount.
  - The existing case "created == referenced == checked" covers `seller-payments-key`.
  - Updated: release 1's and release 2's expected test templates gain
    `payments-check-test.yaml`, and the rollout order case allows the double's
    Deployment.
  - The e2e-tests chart gains a closed `payments` value with only the public keys:
    `service_url`, `service_identity`, `fee_bps`, `livemode`, `lane_owned`,
    `api_key_env`, `buyer_account` and `seller_account`. The umbrella's test-config
    writes it into the `helm` profile when the chart is enabled and the value is
    non-empty; release 2 has none. Correction to the plan: D9's
    `BUYER_MARKETPLACE_CREDENTIAL` and `SELLER_MARKETPLACE_CREDENTIAL`, and the buyer's
    bearer token, are not carried. The profile is a ConfigMap, and charts accept no
    credential in values (`helm/Makefile`; DEPLOYMENT_AND_CONFIG.md). Their place
    would be the `e2e-secret` profile `topology-secrets` writes, plus an environment
    variable for the token. The release serves no payment scenario (D11), so nothing
    reads them. A payment marker run on Helm would fail by name on the missing
    credentials, which is what `LANE_OWNED` asks of a broken configuration.
  - `topology-secrets.sh` creates the `seller-payments-key` Secret (`api-key`) from
    `lane_env.py seller-token`, a new mode with its own case in the double's
    `test_lane_env.py`, and the `payments-ca-bundle` ConfigMap (`ca-bundle.pem`) from
    `tools/payments-lane-double/tls/lane-ca.pem`. It now also requires `python3`.
    `helm/Makefile` adds `seller-payments-key` to `LOCAL_SECRETS`, and a new
    `LOCAL_CONFIGMAPS` that `check-local-secrets` checks. Beyond the plan,
    `deploy-local` now runs `check-local-secrets` first, so the local deploy target
    checks for both before installing (D3). Validation deploys through
    `make -C helm deploy`, not `deploy-local`, after `topology-secrets`, so its path is
    unchanged. `scripts/tests/test_change_build_and_helm_targets.py`'s
    `topology-secrets` case now counts the ConfigMap's apply.
  - Bob gets no `[[DisputeCredential]]`. Only the VM lane's scenario needs one (D2);
    the release serves no payment deal, and the credential's variable would be another
    environment variable the chart has no option for.
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

  Evidence, all local:
  - `make -C helm test-render`: every umbrella assertion and every chart's and
    `helm/tests/`' render test passes, the new cases of 5.1–5.6 among them. No skip
    line was printed: both storefront environments exist here, so the startup refusal
    over the local release with payments, the payments-only checks (5.4) and release
    2's loader check all ran.
  - Templates broken once while writing the tests: with `SSL_CERT_FILE` dropped from
    the storefront chart's environment helper, the CA bundle, payments-only and
    payments-check cases failed. With a `data` mount added to the bare-metal payments
    check pod, its equality case failed. Both breaks were reverted.
  - `make test-deployment-packaging`: release tooling 2181 passed, with the updated
    `topology-secrets` case, and the render suite above.
  - `make -C tools/payments-lane-double test`: `check-tls` passes; 50 passed, with the
    `seller-token` case.
  - `make test`: exit 0, no failing suite.
  - `make check-packaging`: all eight checks OK. No dependency or lock changed.
  - `make check-change`: every check passes.
  - System: not run. The plan's `topology-secrets`, `deploy-local`, `make -C helm test`
    and `topology-check` would deploy to a cluster, which this step's commands do not
    reach. Left to validation's Helm part, with the gap below.

  End-to-end: none, as planned; no `e2e-tests` marker exercises the charts.
  Correction to the plan's claim that validation's Helm part runs the release's
  `helm test`, the payments check among them: `scripts/validate_slice.py`'s
  `_run_scenarios` runs only the scenario pod (`helm test --filter
  name=<release>-e2e-tests-e2e-scenarios`). Validation's deploy does start the release,
  the double, and Bob configured for payments, and waits for every rollout; so a
  storefront that refuses its payments configuration, or a pod naming a missing
  ConfigMap or Secret, fails it. Nothing automated runs the payments check pods. They
  run under `make -C helm test` (Bob) and `topology-check` (both storefronts).
  Closeout's 6.8 asks for "the Helm part's payments check", so the round's triage
  should decide one of two things:
  - validation also runs the payments check pods, a change to
    `scripts/validate_slice.py` outside this section's files;
  - or 6.8 records it as an owner-run `make -C helm test` against the validated
    namespace.
  Owed by validation, confirmed, with one job added:
  - `tests.yml`, job `test · test-deployment-packaging`: `make -C helm test-render`
    passes with the new render cases, and release tooling with the updated
    `topology-secrets` case.
  - `tests.yml`, job `test · test-payments-lane-double`: the suite passes with the
    `seller-token` case.

  Fresh-context check. It found no rendering, indentation, schema, layering,
  comment-hygiene, test-level, packaging or public-content defect. Fixed:
  - The environment helpers' comments justified only the credential and the key; they
    now say why `SSL_CERT_FILE`, process trust and not a setting, travels outside the
    configuration system.
  - The `api_key_env` collision and `STOREFRONT_` refusals (5.3).
  - Fixture labels lacking "never for a public network": two in
    `bare-metal-release-values.yaml`, one in `local-values.yaml`.
  - `scripts/validate_slice.py`'s `HELM_SCENARIOS` comment, which this section made
    incomplete.
  - The storefront chart's `tests` comment, which left out the account condition.
  - Four overstated notes: 5.1's TLS Secret, 5.4's "RPC off", 5.5's "renders keep
    their content", and 5.6's profile comparison.
  After the fixes, `make -C helm test-render` and `make test-deployment-packaging`
  (release tooling 2181 passed, render suite passed) were re-run and pass. `make test`
  and `make check-packaging` ran before them; the fixes touched only these chart
  templates and tests, values comments, a script comment and these notes.
  Declined:
  - Testing the bare-metal chart's `required` on a `null` `caBundle.key` or
    `paymentsKey.key`. The schema refuses an empty key, and the default supplies one;
    only an explicit `null` reaches the template.
  - Raising the render suite's Python floor. `test_release_topology.py` now imports
    `tomllib`, as the bare-metal chart's render test already did, so `test-render.sh`'s
    `python3` was already 3.11 or newer.
  Recorded for the round's triage and closeout, not changed here:
  - `openspec/specs/deployment-state/spec.md`, "A storefront's configuration reaches it
    through its configuration system". Its scenario says the bare-metal chart's pod
    environment carries "only the configuration directory and the signing credential".
    That holds for every render without `caBundle` or `paymentsKey`, and the existing
    test still asserts it over the example. With either set, the environment also
    carries `SSL_CERT_FILE` or the payments key. The change's delta only adds
    requirements, so the archived spec would state both. It needs a MODIFIED delta
    naming the two options, which is a spec edit for the triage to accept.
  - Two design statements this section's build narrows, which `design.md` should be
    brought in line with at narrative compression: D9, "the local release's e2e-tests
    chart values carry the same keys", holds for the public keys only (5.6); and D3's
    "the local deploy target creates that ConfigMap" is done by `topology-secrets`,
    which D3's later sentence names, with `deploy-local` checking for it.

  Handoff to closeout:
  - Promotion, beyond 6.9's list, of behaviour the section made true, or the passage
    goes stale:
    - DEPLOYMENT_AND_CONFIG.md's "Release topology". `topology-up` restarts neither
      dev-env nor the payments double. `check-local-secrets` now also checks
      `LOCAL_CONFIGMAPS`, and `deploy-local` runs it.
    - Its "Kubernetes: ConfigMap and Secret mounting" pod rule.
    - Its storefront pass-through table of the pod environment.
    - TESTING.md's "Chart Render Tests" list of what each chart's suite asserts.
  - The validation gap above (5.7, End-to-end) decides how 6.8 shows the Helm payments
    check.
  - The section is a session of its own. The next step is the round's validation and
    implementation review.

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
