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

  Implementation round 1's triage (reviews 29–31), fixes to this section:
  - 29 F1. A trust bundle the client could not load escaped the check's JSON outcome.
    `PaymentsClient` loads the bundle `SSL_CERT_FILE` names when it is built, off
    loopback, so a missing, unreadable or malformed file raised `FileNotFoundError` or
    `ssl.SSLError` before any request, and the CLIs printed a traceback. `access_check.py`
    now builds the client in its own `try` and reports an `OSError` there as the
    `transport` step, detail "the trust bundle SSL_CERT_FILE names could not be loaded",
    composed from fixed text. Building is now separate from the read, so only a failure
    to build gets that detail. `test_access_check_tls.py` adds the missing and malformed
    cases against a non-loopback origin at `.invalid`.

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

  Implementation round 1's triage (reviews 29–31), fixes to this section:
  - 30 V2. Validation 30's VM lane had `e2e_vm_payment_deal`'s stage 1 refused with a 409
    "publication source is already bound". The scenario listed `test_full_deal`'s
    resource, `compute-e2e-deal-001`, which the canonical deal binds earlier on the same
    stack, and a listing's binding outlives the listing. The VM deal driver
    (`compute_deal_driver.py`) now takes its executor, pool and resource as fields,
    defaulting to the canonical deal's. `test_vm_payment_deal.py` overrides `deal_driver`
    with its own: `kvm-payment-deal`, `compute-e2e-payment-deal-pool` and
    `compute-e2e-payment-deal-001`, the first two in `host_registry.py`. It offers the
    canonical shape under that resource. Stage 2's failure followed from stage 1's. No
    lane has yet run the stages after the listing.
  - 29 F1, the e2e half. `helpers/payments.py`'s `target_ready` built its SSL context
    outside its `try`, so a missing or malformed `SSL_CERT_FILE` bundle raised, instead
    of reporting the target not ready, which fails a lane-owned target by name. It now
    builds the context inside the `try` and catches `OSError`, of which `ssl.SSLError` is
    one. `test_payments_helper.py` adds the missing and malformed cases.
  - Returned to design, 31 O1. The owner's notes on this round found the lane settings
    carried by the Makefile against `DEPLOYMENT_AND_CONFIG.md`'s "Profile-based
    configuration": the `e2e-<lane>-payments-env` targets print `ARKHAI_PAYMENTS__`
    variables, with a hard-coded buyer seed and a seller key read with `sed`, and
    `lane_env.py compose` prints the Compose values. The owner chose alternative B: move
    this section's settings into per-lane runner profiles and literal overlays, and move
    the pre-existing `e2e-*-dev-env` targets, with their services' `REGISTRY_*` and
    `PROVISIONING_*` values, into profile files too. That reverses D9 and widens the
    scope, so the change returns to design (`design.md` D9 and Open Questions). This
    section's lane wiring is reworked by whatever the design and plan make of it.

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

  Implementation round 1's triage (reviews 29–31), fixes to this section and outside
  any section:
  - 29 F2. Validation now runs the payments check pods, as decided in `design.md` under
    D12. `scripts/validate_slice.py` reads the release's hooks (`helm get hooks`) and
    runs each `-payments-check` pod as its own step after the scenario pod. A pass counts
    only with the pod's exit status 0, and a pod with no status is stopped. The validator
    keeps each pod's log under `evidence["payments_checks"]` and in the rendered summary.
    A release rendering no check pod is warned, never passed. In
    `scripts/tests/test_validate_slice.py`, the full-sequence case now includes Bob's
    check. Eight cases are new: two pods, a nonzero exit, no exit status, a commit during
    the check, no pod rendered, unreadable hooks, the hook parser, and the suffix both
    charts render. 6.8 reads the check from the validation record.
  - 29 documentation. The permanent requirement "A storefront's configuration reaches it
    through its configuration system" allowed only two kinds of value outside the
    configuration system, and its scenario said the pod environment holds only the
    configuration directory and the signing credential. Both are false with 5.2's
    `caBundle` and 5.3's `paymentsKey`. The `deployment-state` delta now MODIFIES it
    with a third kind: a value something other than the loader reads from the process
    environment, such as `SSL_CERT_FILE`. The credential kind now includes the variable
    `api_key_env` names. One scenario covers each case. The owner's disposition: code
    follows the guidance, and where a spec disagrees, one of them changes. The
    fresh-context check found that the guidance does not yet say this either.
    `DEPLOYMENT_AND_CONFIG.md`'s "Profile-based configuration" lets a pod spec set only
    the profile resolver variables and a variable an external subprocess reads. Its
    example, `ANSIBLE_CONFIG`, is written into `os.environ` from resolved settings, not
    set on the pod, and it names no credential variable. Whether that guidance gains the
    in-process reader and the named-credential kinds, or `SSL_CERT_FILE` travels another
    way, is recorded in `design.md`'s Open Questions for the design session this change
    returns to.
  - Also from the fresh-context check. Two fixes: the payments check pod is stopped
    when the commit moves during its step, with a case for it in
    `test_validate_slice.py`, and the `deployment-state` delta gains the scenario "The
    storefront's CA bundle cannot be loaded" for 29 F1. Promotion destinations for 29 F2,
    beyond 6.9's list: `docs/development/TESTING.md`'s account of what the Helm part
    runs and keeps, and `.agents/skills/change-validate/SKILL.md`'s, both of which name
    only the scenario pod. For 6.8, a `payments check` warning, meaning no check pod was
    rendered, is not evidence.
  - Evidence for these fixes, all local, against base `5e2f0fd86`:
    - Unit and integration (`TESTING.md`'s levels):
      - `make -C core/storefront test`: 226 passed, the new real-SQLite case included.
      - `make -C kit/arkhai-payments test`: 197 passed, with mypy, vectors and
        generated models checked.
      - `make test-e2e-unit`: 539 passed. `test_vm_payment_deal.py` collects its 4
        tests, by `make -C e2e-tests test-unit PYTEST_ARGS=--collect-only …`.
      - `make test-release-tooling`: 2189 passed, re-run after the fresh-context
        fixes.
    - `make test`: exit 0, run before the fresh-context fixes. Those touched only
      `validate_slice.py` and its tests, which were re-run above, a test comment, and
      change documents.
    - `make check-packaging`: all eight checks OK. No dependency or lock changed.
    - `make check-comment-hygiene` and `make check-change`: pass.
    - Not run: any end-to-end lane or Helm deployment. The VM payment deal past its
      listing, and Bob's payments check pod in a cluster, are owed to the validation of
      the round the design and plan make of this return.
    - Fresh-context check, against `5e2f0fd86`: no code bug. Fixed, as above: the stop on
      a commit change, the spec scenario, the test comment, and the overstated note on
      the guidance. Left as recorded:
      - an `OSError` from `SSL_CERT_DIR` or certifi shares the trust-bundle detail, a
        negligible edge;
      - the index row stays `in implementation` until the return is confirmed and the
        design step takes it.
  - Owner's addition to 30 V2. `core_storefront`'s
    `SQLiteClient.listing_id_for_derivation_key` called an undefined `self._connect()`,
    so every source-conflict 409 logged an `AttributeError` and could not name the
    listing holding the source, as validation 30's VM log showed. It now opens
    `sqlite3.connect(self.db_path)` like its neighbours. A real-SQLite case in
    `core/storefront/tests/integration/test_listing_closure.py` covers it: the method
    names the bound listing, still names it once closed, and returns `None` for an
    unknown key. The fix removes the unowned-work row for this in
    `openspec/changes/README.md`.

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
  Done. Unit (`test_settlement_config.py`, in `make -C kit test-arkhai-payments`, pass):
  the three conflicts refused naming both forms and never the key, also on a disabled
  section; an empty, blank or multi-line `api_key` refused without echoing it; an empty or
  blank `ca_bundle_path` refused; TOML text with `api_key` and `ca_bundle_path` validated
  strictly (pydantic's strict `SecretStr` accepts a TOML string), the key absent from
  `repr`, `model_dump_json()` and the JSON dump. Differs from the plan: the key-form
  conflicts are refused whether or not the section is enabled, since a disabled section
  still builds clients for accepted deals and one resolution must find one form; only
  `development_auth`'s loopback rule stays gated on `enabled`. A multi-line key is refused
  as well as an empty one, since it travels as a header value. `ca_bundle_path` refuses an
  empty value, because `ssl.create_default_context(cafile="")` reads it as none given and
  loads the default store (found by the fresh-context check).
  Correction (section 7): the "never echoing the key" claim held only because pydantic
  shortened a long input in the message; a three-character key was shown whole. The
  model now sets `hide_input_in_errors`, and
  `test_a_validation_error_never_shows_a_stated_key` holds it.
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
  Done: `resolve_payments_api_key(config, *, environment=None) -> SecretStr`, which also
  refuses a variable whose value is blank or multi-line. Unit (`test_settlement_config.py`,
  `test_access_check.py`, pass): each source, a stated `api_key` winning over a set
  variable, the process environment as default, each failure naming its form; the
  preflight passing on a stated key with no variable and naming both forms when neither is
  stated; the check authenticating with `Bearer <api_key>` and `environment={}`. The
  preflight's blocker code for no key is now `arkhai_payments.api_key_missing` (was
  `api_key_env_missing`; nothing outside the kit read it). The check reports neither form as
  `configuration` and an unusable variable as `credential`.
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
  Done: the client builds `ssl.create_default_context(cafile=ca_bundle)` and passes it as
  `verify`, refusing an empty `ca_bundle` with `ValueError`. Library integration
  (`test_access_check_tls.py`, the real check and client against a real TLS listener on
  loopback, pass): a leaf issued by a private CA verifies with that CA as
  `ca_bundle_path`; another CA's bundle, or none, fails `transport` with no request sent; a
  missing and a malformed `ca_bundle_path` fail `configuration` with the fixed detail
  naming `ca_bundle_path` and not the path; the process `SSL_CERT_FILE` cases still fail
  `transport`. Unit (`test_client.py`, pass): a missing or malformed bundle raises at
  construction, an empty one `ValueError`. Differs from the plan: the file served a
  self-signed leaf, not a private CA, so it now issues a CA and a leaf, carrying the
  extensions Python 3.13's default strict X.509 verification requires (key usage, key
  identifiers, EKU); without them the configured bundle failed verification. The
  "verifies with no `SSL_CERT_FILE`" case proves nothing about `SSL_CERT_FILE` on loopback,
  where the client sets `trust_env=False`; no test can show the process store untouched
  off loopback without a resolvable non-loopback origin, so that rests on the client
  setting no process state and on httpx consulting `SSL_CERT_FILE` only for
  `verify=True`.
- [x] 6.4 Package and schema housekeeping (RELEASING.md, "Versioning policy"; `AGENTS.md`,
  "Tests and diagnostics"). Bump `kit/arkhai-payments`'s version, `make lock`, and
  document `api_key`, `ca_bundle_path` and the resolution in `kit/arkhai-payments/README.md`.
  Run `make helm-values-schema`, so both storefront charts' generated definitions carry
  `ca_bundle_path` and refuse `api_key` in `config`; the storefronts' stale-schema unit
  test holds it.
  Done, with one correction: the kit's version is **not** bumped. Section 1 already bumped
  it 0.5.0 → 0.6.0 on this branch, and RELEASING.md's "Versioning policy" bumps a package
  at most once per change against the branch it merges into (a second bump of an
  unreleased version only moves the exact pins on it), so `make lock` changed no lock.
  The README documents both key forms, `resolve_payments_api_key`, `ca_bundle_path` and
  the check's steps. `make helm-values-schema` (after `make init-storefront` and `make
  init-bare-metal-storefront`, since it runs `--no-sync` in each storefront's environment)
  added to `helm/charts/storefront/values.schema.json`,
  `helm/charts/bare-metal-storefront/values.schema.json` and `helm/values.schema.json`
  (the umbrella's copy of the storefront subchart's definition) `api_key: false` and
  `ca_bundle_path` as a nullable string under `[Settlement.arkhai_payments]`.
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
  Results: `make -C kit test-arkhai-payments` (unit and library integration, with mypy,
  the vector check and the generated-model check) 219 passed. `make test-storefront`
  1213 passed, 1 skipped (unit, the stale-schema test included) and 525 passed
  (application integration); `make test-bare-metal` 126, 224, 582, 31 and 137 passed;
  `make test-apicredits` every suite passed. `make test`: every suite passed but
  `scripts/tests/test_change_workflow_assumptions.py::test_every_target_and_path_the_workflow_names_is_provided_here`,
  which fails on `HEAD` before this section: `.claude/change-steps.toml` names `make
  build-*` (commit 4a9c8e2f6) and the workflow's provisions list does not, outside this
  change's code. That failure stops `make test` inside `test-deployment-packaging`, so the
  targets after it were run alone and passed: `make -C helm test-render`, `make
  test-frp-grant-admission` (203 passed, 15 skipped), `make test-payments-lane-double`
  (50 passed). `make check-packaging` passed. `make check-change` passed but for its
  citations check, which reports `e2e-tests/config/config-payments-lane.yml` and
  `config-bare-metal-lane.yml`, cited by `design.md` and `tasks.md` and created by
  section 10. End-to-end scenarios confirmed as planned: none exercises this section yet;
  the three payment markers do from section 9.

  Handoff: the fresh-context check found the version bump (reverted, see 6.4), the empty
  `ca_bundle_path` falling back to the default store (refused at config and in the
  client), and tests short of the plan's TLS claims (a client unit case and the
  "another CA's bundle" transport case added). Declined: moving the TLS test to an
  `integration/` directory (the kit's tests are flat and the task names the path), and
  removing the check's second key resolution (it resolves once to classify the failure
  and `payments_client_for_owner` resolves again, both through the one function).
  Clearing a stale wheel: `make lock` resolves lower-bound consumers to the highest wheel in
  `.dist`, so reverting a bump needs `make dist-clean` before `make lock`. Section 9's lane
  configurations state `api_key` in the secret overlays and `ca_bundle_path`; the
  bare-metal storefront needs no code change for either, since it parses the section
  through `ArkhaiPaymentsConfig`.

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
  Done. Unit (`kit/deal-lifecycle/tests/unit/test_dispute_credential.py`, in `make -C kit
  test-deal-lifecycle`, pass): each form resolving, a stated key winning over a set
  variable, an unset or empty variable's `ValueError` naming it, both and neither refused,
  an empty, padded or multi-line `api_key` refused without showing it, a malformed
  variable name still refused, the token absent from `repr` and the JSON dump, an
  `api_key` entry loaded from TOML text through `dispute_config`, and a configuration error
  never showing a stated token. Differs from the plan: a padded or multi-line `api_key` is
  refused too, by the rules `MediationCredential` applies, so a stated key that passes
  validation and resolves is one a client can send; without it, `credential_available`
  would report the credential usable and client construction would raise instead of the
  deal reporting `repair_required` (found by the fresh-context check). `DisputeCredential`
  and `DisputeConfig` set `hide_input_in_errors`, since pydantic prints a short enough
  input, the token included, in a validation error's message.
- [x] 7.2 `MediationCredential(identity, *, token: SecretStr)` (D19's contract): the field
  is renamed and keyword-only; `__post_init__` raises `TypeError` for a token that is not a
  `SecretStr`, and `ValueError` for an empty token, one with surrounding whitespace, or one
  containing CR or LF — the checks `MediationClient.__init__` makes today, moved there.
  `MediationClient` loses `environ=` and reads no environment. Library integration cases
  in `kit/arkhai-mediation/tests/integration/test_adapter.py`: each refusal, including an
  unmigrated positional `MediationCredential(identity, "DEMO_PAYEE")` failing at
  construction; a client built from a valid credential authenticates with exactly that
  token.
  Done: `token` is a keyword-only dataclass field (`field(kw_only=True)`), so a second
  positional argument raises `TypeError`. Library integration (`test_adapter.py`, against
  the kit's contract fake, in `make -C kit test-arkhai-mediation` with its mypy over `src`
  and `examples`, pass): the positional call failing with `TypeError`; a `str` or `bytes`
  token refused with `TypeError`; an empty, padded, CR/LF or LF token refused with
  `ValueError` without quoting it; a credential bound to another authority refused; a
  filing sending `Bearer fixture-payee` and nothing else, read at a recording transport.
  The refusal cases are single-object edge cases that `TESTING.md` would put in unit
  tests; the kit has only `tests/integration/` and the task places them there, so they
  stay.
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
  Done: the four compositions build `MediationCredential(identity,
  token=credential.resolve())`; the buyers' ports resolve inside the existing `try`, so an
  unresolvable credential is still a `MediationTransportError` at I/O. A search for
  `MediationCredential(` and `environ=` finds no unmigrated use outside
  `docs/attachments/` (whose two scripts keep their wording). Application integration
  (`test_servicing_unreachable_authority.py`, the VM storefront's routes and real lifecycle
  composition in process, pass): parametrized over an `api_key` entry with no variable set
  and a variable entry; both read `running`, a non-`Accepted` (`Unknown`) outcome, the
  poll's error logged once and the cycle completing, no repair, and every mediation request
  carrying `Bearer <token>`. The harness passes the merged dispute document to
  `RegistryDisputePolicy.from_document`, not the storefront's files, so this case does not
  show the secret overlay's merge; the bare-metal unit case
  `test_payments_and_dispute_keys_are_read_from_the_secret_overlay` (`test_config_loader.py`)
  does, for both keys: the overlay's `[Settlement.arkhai_payments].api_key` and
  `[[DisputeCredential]]` `api_key` are read through `load_storefront_settings`, resolve
  with no variable, and stay out of the settings' `repr`. Unit (both buyers'
  `test_lifecycle_adoption.py`, pass): the port given a credential whose variable is unset
  raises `MediationTransportError` naming the credential unavailable and builds no client.
  Also changed: the bare-metal settings' `settlement` and `disputecredential` fields are
  `repr=False`, since both now hold secrets when the overlay states them.
  Not run: the `kit/deal-servicing` examples (`make -C kit/deal-servicing first-use`) and
  the mediation demo (`make -C kit/arkhai-mediation demo`): both calls were denied in this
  session, and neither kit's test target runs its examples. The mediation example is
  type-checked by its suite's mypy; the four deal-servicing examples are not checked by
  any target run here.
- [x] 7.4 Bump the versions of `kit/deal-lifecycle` and `kit/arkhai-mediation` and of any
  other package whose public surface changed, and `make lock` (RELEASING.md, "Versioning
  policy").
  Done: `kit/deal-lifecycle` 0.1.0 → 0.2.0 (new public API) and `kit/arkhai-mediation`
  0.1.0 → 0.2.0 (incompatible, pre-1.0 minor); neither was bumped on this branch before.
  Consumers that use the new forms raise their lower bounds: both storefronts
  (`arkhai-kit-arkhai-mediation>=0.2.0`, `arkhai-kit-deal-lifecycle>=0.2.0`), both buyers
  and `kit/deal-servicing`'s dev group (`arkhai-kit-arkhai-mediation>=0.2.0`). The buyers,
  whose source changed and which were at their `dev` versions, take patch bumps (VM
  0.10.0 → 0.10.1, bare metal 0.7.0 → 0.7.1); the storefronts were already bumped on this
  branch. `make lock` rewrote every lock carrying the kits.
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
  Results: `make -C kit test-deal-lifecycle` 76 passed; `make -C kit test-arkhai-mediation`
  55 passed with mypy clean; `make -C kit test-deal-servicing` 63 passed (its examples are
  not collected; see 7.3); `make -C kit test-arkhai-payments` 220 passed. `make
  test-storefront` 1213 passed, 1 skipped and 526 passed; `make test-bare-metal` 126, 224,
  583, 32 and 137 passed; `make test-vms-buyer` 215 passed. `make test`: everything passed
  but the same pre-existing `test_change_workflow_assumptions` failure section 6 records,
  and the targets after it (`make -C helm test-render`, `make test-payments-lane-double`)
  passed run alone. `make helm-values-schema` changed nothing. `make check-packaging`
  passed. `make check-change` failed only on section 10's two runner profiles, as in
  section 6. End-to-end confirmed as planned: none yet; `e2e_vm_payment_deal`'s stage 2
  exercises the VM storefront's credential once section 9 states it in Bob's secret
  overlay.

  Handoff: the fresh-context check also found, and this section fixed, comments claiming a
  values schema refuses `DisputeCredential.api_key`, the mediation README's change-history
  wording and a snippet calling `credential_for` on the `dispute_config` function, unsorted
  imports, and test names that claimed a secret overlay the harness never reads.
  `ArkhaiPaymentsConfig` now also sets `hide_input_in_errors`: a three-character key was
  shown whole in its validation error (`test_a_validation_error_never_shows_a_stated_key`
  failed before the setting and passes after). Left for later sections:
  - **A plan gap.** The deployment-state delta requires the storefront charts' values
    schemas to refuse a secret dispute credential setting in `config`, and no task
    delivers it: the VM schema has no `[[DisputeCredential]]` definition and the
    bare-metal settings type it `list[dict[str, Any]]`, so `api_key` there passes the
    schema. It belongs with section 12's chart and schema work, which should add a typed
    `DisputeCredential` to both storefronts' generated definitions (the field is already
    marked secret); the triage or a plan amendment should place it.
  - The closeout's `DEPLOYMENT_AND_CONFIG.md` list now names "Dispute authority
    preferences", whose credential passage describes variable references only.
  - Declined: moving the `MediationCredential` refusal cases to a unit directory (see
    7.2). Not rerun: a second fresh-context check after these fixes, which were local to
    the files it named.

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
  Done: `config.profile_env_files(environment)` and `config.load_settings(environment=None)`,
  which builds `Settings(_env_file=(*DEFAULT_ENV_FILES, *profiles))`; the module's
  `settings = load_settings()` is the composition reading `CONFIG_DIRECTORY` (the working
  directory when unset) and `ACTIVE_PROFILES` from the process environment. Profile names
  parse as `arkhai-kit-config`'s `parse_active_profiles` does (comma-separated, stripped,
  empties dropped), restated here since the registry does not depend on that kit. The
  `.env.local` comment now states the real order (a later file overrides an earlier one, so
  `.env.local` is the lowest). Unit (`core/registry/tests/unit/test_config_profiles.py`,
  in `make test-registry`, pass), each in an empty working directory with the registry
  variables cleared: two profiles layering, the later winning; a profile over `.env` over
  `.env.local`; the process environment over both profiles; no `ACTIVE_PROFILES` loading
  `.env` alone; the resolver variables read from the process environment when no mapping
  is given; a missing profile skipped; the JSON list from a single-quoted line; a hex
  identifier as a string (pydantic's dotenv reader yields strings for a `str` field, so
  this case documents the form rather than guarding a conversion).
- [x] 8.2 The filter-specification path (D16). `registry_filter_spec_path` is a `Settings`
  field aliased to `REGISTRY_FILTER_SPEC_PATH`, unset meaning the packaged
  `filter-spec.yaml`. `api/filter_spec.py` resolves its default path from a `Settings` it
  is given, defaulting to the module's `settings`, and no longer reads `os.environ`. The
  cases in `test_filter_spec.py` and `test_settled_envelope_across_specs.py` that select
  a specification through `monkeypatch.setenv` pass a `Settings` instead (`AGENTS.md`,
  "Tests and diagnostics"). A new case loads a specification a profile file names, with no
  process variable set (the delta's "A profile selects the filter specification").
  Done: `resolve_spec_path(settings=None)` and `load_filter_spec(path=None, *,
  settings=None)` read `registry_filter_spec_path` from the `Settings` given, else the
  config module's `settings`; `filter_spec.py` no longer imports `os`. The served spec
  stays one cached load: `reset_cache(settings=None)` drops it and makes the next load
  resolve from the `Settings` given, the process's when none is. That extends the
  existing test seam (`reset_cache` was already the tests' way to swap the spec); routes
  and `main.py` still call `get_loaded_spec()` with no argument. Unit
  (`test_filter_spec.py`, pass): the two endpoint cases serve their file through
  `reset_cache(Settings(_env_file=None, REGISTRY_FILTER_SPEC_PATH=...))` instead of
  `setenv`; a specification a `config-lane.env` names loads with no process variable; unset,
  the packaged `filter-spec.yaml` (`compute.market`). Application integration
  (`test_settled_envelope_across_specs.py`, the real app and database through
  `RegistryClient` over `ASGITransport`, pass): its fixture writes a profile env file naming
  the API-credit or introductions specification and serves it through
  `reset_cache(load_settings({...}))`, with `REGISTRY_FILTER_SPEC_PATH` removed from the
  process. That proves a profile's path is served by the app; the startup path itself
  (`settings = load_settings()` at import, from a process's `ACTIVE_PROFILES`) is covered
  only by 8.1's process-environment unit case, and by the lanes from section 9.
- [x] 8.3 The unread variables (D16). Remove `ENABLE_HEALTH_CHECKS`,
  `HEALTH_CHECK_INTERVAL`, `ENDPOINT_CHECK_TIMEOUT` and `HEARTBEAT_TTL_SECS` from
  `core/registry/Dockerfile` and `core/registry/.env.docker-compose`, after confirming by
  search that nothing reads them (the chart's copies and `CHAIN_ID` go in section 11).
  Document the profile loading and the setting in `core/registry/README.md`. Bump the
  registry's version and relock if its metadata changed.
  Done. A search found no reader of the four, in code or settings (lowercase forms
  included). Removed from `core/registry/Dockerfile` and `core/registry/.env.docker-compose`
  as planned, and also from the registry's other sample files, which set them for no
  reader: `core/registry/docker-compose.yml`, `core/registry/.env.sample` and the root
  `config.registry.env.example`. Left: `domains/vms/provisioning/iac/README.md` still shows
  them in an example deployment command and describes them as features (lines 1653,
  1686–1689); it is outside this change's files and should be corrected where that document
  is next maintained. `core/registry/README.md` gains "Configuration files". The registry
  goes 0.4.1 → 0.5.0 (new configuration surface; not bumped on this branch before; nothing
  pins it exactly), relocked.
- [x] 8.4 **Verification checkpoint.** Unit and application integration: `make
  test-registry`. `make test`. `make check-packaging` when the version or lock changed.
  End-to-end: none yet — the lane registries take profiles in section 9 and the chart in
  section 11; every lane's publication and discovery scenarios exercise the registry from
  then. None is owed here.
  Owed by validation: `tests.yml`, job `test · test-registry` — passes with the new and
  reworked cases.
  Results: `make test-registry` 139 passed (unit) and 128 passed (application
  integration). `make test`: every suite passed but the pre-existing
  `test_change_workflow_assumptions` failure section 6 records; the targets after it
  (`make -C helm test-render`, `make test-frp-grant-admission`, `make
  test-payments-lane-double`) passed run alone, and `make test-release-tooling` was rerun
  after the sample-file edits with the same single failure. `make check-packaging` passed.
  `make check-change` failed only on section 10's two runner profiles. End-to-end
  confirmed as planned: none yet.

  Handoff: the fresh-context check found the default-then-profile order untested, tests
  reading the working directory's dotenv files, an unset-spec case broken by a shell's
  `REGISTRY_FILTER_SPEC_PATH`, unused parameters, the unread variables surviving in sample
  files, and a pre-existing task-number reference in
  `test_settled_envelope_across_specs.py`'s docstring; all fixed. Kept: the
  `reset_cache(settings)` seam, recorded under 8.2. For section 9: a lane registry's
  `config-<registry>.env` takes the same `REGISTRY_*` names its `environment:` carries
  today, `REGISTRY_FILTER_SPEC_PATH` included, and a JSON value goes on one single-quoted
  line; `/app/shared-env/.env` is still read first if present. For closeout: the
  registry restates `parse_active_profiles`, which `deployment-state`'s architecture
  companion ("Configuration bootstrap boundary") places in `arkhai-kit-config`; its
  promotion should say the registry parses profiles itself until the Dynaconf move.

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
  Done. No base file reads a variable but the domain files' pre-existing defaulted
  operator knobs (`BARE_METAL_*_PORT`, `BARE_METAL_STOREFRONT_IMAGE`) and the VM
  provisioning's `${HOME}/.ssh/id_ed25519`, an operator's real-provisioning key, not a
  committed value, which stays. The configuration binds (`VMS_*_STOREFRONT_CONFIG`,
  `APICREDITS_STOREFRONT_CONFIG`, whose defaults were committed fallbacks), the
  Alkahest address-book binds, every credential, admin-key and secret-overlay bind, the
  bare-metal definition documents and SSH key, and registry-b's key variables left the
  base files. `compose.bare-metal.yml` keeps only `DATABASE_URL` and its `extends`; its
  buyer service moved whole into `compose.bare-metal-local.yml`, as the VM and
  API-credit buyer services already live in their overlays, because its guarded
  `image:` and binds could not be satisfied by a later file (Compose interpolates each
  file before merging). The provisioning services' `ACTIVE_PROFILES` is the literal
  `docker`.
  The bring-up without binds is **unrun**: the implement step may run `docker` only
  through the lane targets (`make -C e2e-tests test-e2e-<lane>`, 9.7), never directly.
  The refusal rests on code reading instead, each service without its overlay's binds:
  a registry rejects missing `REGISTRY_AUTHORITY_*` at startup (`core_registry`'s
  settings); each storefront and provisioning service resolves its signer from
  `ARKHAI_IDENTITY_CREDENTIAL`, which only the overlays' identity files supply; the
  credits service refuses an unreadable `storefront_admin_key_file`
  (`apicredits_service/config.py`) and the sample app an unreadable `*_FILE`
  (`apicredits_middleware/config.py`); the bare-metal site raises `FileNotFoundError`
  for its configured host and pool documents (`services/definition_documents.py`). One
  bind does not stop its service: the bare-metal site starts without its SSH key, which
  only Ansible reads, per job. The site still refuses to start without its overlay as a
  whole, so its guard went with the others, as 9.2's list of overlay binds requires;
  a real-mode deployment that binds its documents and not its key fails at its first
  job instead. Static evidence: unit
  `test_a_base_file_renders_alone_with_no_development_bind` (`scripts/tests/test_lane_compose.py`,
  Compose render): each base file renders with no environment file (and the caller's
  environment less `PROVISIONING_MODE`), mounts nothing under `dev-env/`, `tools/`,
  `kit/`, `provisioning/` or `.e2e-buyer/` and no `.toml`, `.env` or credential file, and
  carries neither `ARKHAI_IDENTITY_CREDENTIAL` nor a `REGISTRY_AUTHORITY_*` value; pass.
  The base registries still load `core/registry/.env.docker-compose` (database, port,
  log level) through `env_file`, which is the registry's defaults, not a deployment's.
- [x] 9.2 Literal overlays (D15). The `-local` and `-lane` overlays bind every committed
  file the base files no longer name, stated relative to the repository root: credential
  and identity files, storefront configurations and secret overlays, the bare-metal host
  and pool documents and SSH placeholder, the lane CA, and the buyer runtime directories
  as `./.e2e-buyer/…` (D18). The VM lane's Bob configuration and the API-credit lane's
  storefront configuration replace the base mount by its target. No overlay reads a
  variable but `PROVISIONING_MODE` (9.4).
  Done. The overlays also bind the dev chain's Alkahest address book, which left the VM
  and API-credit domain files as a development bind (the bare-metal overlay already
  bound it). The buyer services' `image` and `user` are literal (`arkhai:e2e-tests`,
  `1000:1000`), retiring `VMS_BUYER_*`/`APICREDITS_BUYER_*` image and uid variables;
  their comments say the runtime directories must exist first. Unit, Compose render
  (`make test-release-tooling`, pass): `test_every_overlay_bind_names_a_committed_file`
  (each overlay's bind and `env_file` sources contain no `$` and exist, but
  `./.e2e-buyer/…`), and the rendered mount cases in `test_lane_compose.py`,
  `test_bare_metal_compose.py` and `test_committed_stack_values.py`, every stack rendered
  with no environment file.
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
  Done: `dev-env/registry/config-{registry-a, registry-b, api-credits-registry,
  compute-registry, bare-metal-registry, payments-lane}.env`. Values with spaces are
  double-quoted for the dotenv reader. registry-b's profile also carries its read and
  write gates (`REGISTRY_REQUIRE_*_API_KEY`), which were `environment:` values of the
  domain file. `compute-registry` no longer binds `./shared-env`, which only the base
  files' registries keep. The base API-credit registry keeps the bind of its
  specification file; only the path setting moved. Unit, Compose render (pass):
  `test_each_registry_profile_pins_the_credential_its_registry_mounts` (every registry of
  every stack: each `ACTIVE_PROFILES` file exists, and the first one's identifier is
  derived from the mounted credential with `create_signer`),
  `test_the_lane_profile_recommends_the_double_pinned_authority`, and the profile cases
  in `test_lane_compose.py` (lanes end in `payments-lane`, the full stack never loads it).
  System: in all three lane runs (9.7) every registry started from its profiles, and
  each lane's payment option needs the recommendation to be published.
- [x] 9.4 Provisioning site profiles and the mode (D17, D20). `provisioning`,
  `alice-provisioning` and `bare-metal-provisioning` set `CONFIG_DIRECTORY=/app/config`,
  bind the packaged `config.yml` and `config-docker.yml` from
  `provisioning/compute/service/src/compute_provisioning_service/config/` and their site
  profile as single files, and state `ACTIVE_PROFILES=docker,<site>,${PROVISIONING_MODE:-mock}`;
  their `PROVISIONING_*` identity, storefront-identity, site-id and admin-identity
  variables move into the site profiles as quoted YAML strings, and the `@str` comments go.
  The base files keep `ACTIVE_PROFILES=docker`.
  Done: `dev-env/provisioning/config-{vms-bob-site, vms-alice-site, bare-metal-site}.yml`.
  `config-mock.yml` is not bound: the service selects mock delivery by the profile name
  (`container.py`'s `_mock_profile_active`, `main.py`), and the mock runner never reads the
  playbook paths `config-docker.yml` sets, so the lanes now run `docker,<site>,mock`
  where they ran `mock` alone. The storefront callback URLs stay in the base files'
  `environment:`, which overrides `config-docker.yml`'s Bob URL. Until section 10 exports
  it, `PROVISIONING_MODE` reaches Compose only from the caller's environment, as the
  pipeline's `e2e.yml` sets it; unset, it is `mock`. Unit, Compose render (pass):
  `test_vm_provisioning_takes_its_site_profile_then_the_run_mode` (VM lane and full stack,
  mode unset, `mock` and `real`; no `PROVISIONING_*` variable left but the database and
  callback URLs), `test_bare_metal_compose_merges_bindings_and_preserves_mount_paths`
  (base `docker`, overlay `docker,bare-metal-site,<mode>`, the documents bound only by
  the overlay), `test_storefront_authorities_are_isolated` (each VM site profile's
  identity, storefront identity and site id against the storefront profile's peer pins),
  and `test_each_site_profile_pins_its_signer_and_the_runner_pins_the_same`. System: the
  three provisioning services started under mock in the VM and bare-metal runs (9.7),
  whose scenarios hold jobs through the mock's `/test` controls.
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
  Done. The search found no reader of `.env.bob.docker`, `.env.alice.docker` or
  `api-credits.wallet.env` but the overlays and the root `Makefile`'s environment targets,
  which still print their paths until section 10 retires them; all three are removed.
  The full local stack mounts the same three secret overlays: its configurations leave
  payments off (a section holding only `api_key` builds no seller stage,
  `servicing_stage`) and its registries recommend no authority, so the key and Bob's
  credential are inert there; the overlays' comments say so. That needed one more edit,
  found by the fresh-context check: `storefront.credits.toml`'s disabled payments section
  still stated `api_key_env`, and the payments section refuses two key forms whether or
  not it is enabled, so the full stack's credits storefront would have refused its merged
  configuration. The profile now states no key form. `storefront.credits.toml`
  keeps `private_key = ""`, which the overlay overrides. Comments in
  `storefront.bob.toml`, `storefront.alice.toml` and both lane copies that named the
  override variables now name the overlays. Unit (pass): the lane configuration cases in
  `e2e-tests/tests/unit/test_domain_stack_configuration.py` (each lane section states
  `ca_bundle_path` and no key; each lane overlay sets no payments variable and binds the
  CA and its configuration; the shared overlays carry neither the double nor the lane
  profile), `test_no_storefront_reads_a_secret_from_its_environment` (every storefront of
  every stack: environment within `XDG_CONFIG_HOME`, `PYTHONPATH` and the signing
  credential, and a mounted secret overlay), and
  `test_each_storefront_secret_overlay_fits_the_configuration_beside_it` (every storefront
  of every stack, the files its render mounts: the overlay's wallet key signs as the
  configuration's `[Wallet].address`, and beside a payments `api_key` the configuration
  states no other key form). With `api_key_env` put back in `storefront.credits.toml` that
  case fails for the full stack, and passes without it; no test loads the merged
  configuration through a storefront's own loader. System (9.7), the lane runs made
  through the lane targets: in each lane the storefront's
  `check-payments` read the seller's balance with the overlay's key and the configured
  CA, the API-credit storefront settled with its overlay's wallet key, and the VM payment
  deal's stage 2 read `running`, which needs Bob's overlay's dispute credential.
- [x] 9.6 Restated values held to their sources (D21, the stack half). In
  `scripts/tests/`, replacing the compose test modules' checks of variables: each
  registry profile's principal derives from its credential file; the provisioning site
  profiles' pins equal the runner's `config-docker.yml` pins; the secret overlays' tokens
  equal `accounts.toml`; `config-payments-lane.env` equals `dispute-authority.toml`; each
  lane configuration's `ca_bundle_path` is the target its overlay binds the lane CA to;
  every overlay bind's source exists; `docker compose config` renders every lane's and the
  full stack's file list with no environment file, and no rendered base file carries a
  development bind.
  Done: a new `scripts/tests/test_committed_stack_values.py` (unit; the registry, site
  and CA cases render with Compose and skip without it, the others read files), and
  `test_lane_compose.py`, `test_bare_metal_compose.py` and
  `test_multi_storefront_compose.py` rewritten to render with no environment file. The
  site-profile case also derives each site's identity from the credential its environment
  file supplies, and for the bare-metal site checks the runner's storefront pin and site
  id. The VM lane's dispute credential is held to the fixture authority there too.
  `make test-release-tooling` gains `--with pyyaml` for the site profiles and the runner's
  pins. `test_an_unknown_provisioning_mode_fails_the_environment_target` stays, since the
  environment targets do until section 10. Beyond the plan, after the fresh-context check:
  registry-b's bootstrap key held equal across its profile, Bob's overlay,
  `buyer.config.toml` and the runner's `config-docker.yml`, where it once came from one
  Makefile constant; the wallet and key-form case under 9.5; and the registry case now
  selects every `arkhai:registry` service and reads its profiles from its mount. Limits:
  the renders run with the caller's environment less `PROVISIONING_MODE`, not an empty
  one; "exists" means present in the checkout, not tracked; and no test checks overlay
  `environment:` values for a variable (only bind and `env_file` sources), which a read
  of the five overlays confirms. Unit, `make test-release-tooling`: 2222 passed, none
  skipped, so every render ran (the host has Docker Compose).
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

  Evidence, local:
  - Unit: `make test-release-tooling` 2222 passed, none skipped (after the fresh-context
    fixes); `make test-e2e-unit` 538 passed; `make -C helm test-render` passes (it
    validates the edited `storefront.dev.toml` against the bare-metal chart's schema).
  - `make test`: exit 0, every suite, including `test_change_workflow_assumptions`, which
    sections 6–8 recorded failing and `fbe70e3eb` fixed. It ran before the fresh-context
    fixes, which touched `storefront.credits.toml`, `test_committed_stack_values.py`, the
    quickstart, two issue-discovery phase files and these notes; release tooling was
    rerun after them.
  - `make check-change`: everything passes but the documentation citations, which report
    only `e2e-tests/config/config-payments-lane.yml` and `config-bare-metal-lane.yml`,
    which section 10 creates.
  - System, through the lane targets, before the fresh-context fixes (none touches a lane
    run's files but `storefront.credits.toml`, which the API-credit lane replaces with
    its lane copy). The lane targets still write and pass their environment files, which
    the Compose files no longer read: the files interpolate only `PROVISIONING_MODE`,
    which those files do not set, so each stack came up from its Compose files alone,
    under mock. The plan's direct `docker compose … up -d --wait` and the full local
    stack's bring-up are unrun, since the step may not run `docker` directly.
    - `make -C e2e-tests test-e2e-apicredits`: stack up, `credits-storefront`'s
      `check-payments` printed `"outcome": "ok"` for the seller's account; 4 passed —
      `e2e_credits_deal` and all three `e2e_credits_payment_deal` stages, the first run of
      that scenario in a lane, so the refund signer path 4.4 left unrun now passes.
    - `make -C e2e-tests test-e2e-bare-metal`: `check-payments` ok; 64 passed, 2 failed,
      2 skipped. `e2e_bare_metal_payment_deal`'s three stages pass. The failures are
      the two introduction cases 4.9 recorded as `dev`'s #314 fallout (`KeyError:
      'mechanism'`), and the skips follow the first.
    - `make -C e2e-tests test-e2e-vm`: `bob-storefront`'s `check-payments` ok; 152
      passed, 1 failed, 2 skipped. `e2e_vm_payment_deal`'s stages 1–2 pass, past the
      listing for the first time (30 V2's fix), stage 2 reading `running`; stages 3–4
      skip (the run printed no skip reasons; their one skip path is the
      `mediation_target` fixture, 4.6). The failure is `e2e_vm_introduction`'s
      `test_03_the_unbacked_listing_offers_only_an_introduction`, the same #314
      `KeyError: 'mechanism'` 4.9 predicted. Every other VM marker passed.

  End-to-end confirmed: `e2e_credits_payment_deal`, `e2e_bare_metal_payment_deal` and
  `e2e_vm_payment_deal` (stages 1–2) exercise this section's secret overlays,
  `ca_bundle_path` and Bob's dispute credential, and pass; every lane marker runs on these
  stacks. The introduction failures predate the change.
  Owed by validation, confirmed and extended: `tests.yml`, job
  `test · test-deployment-packaging` — `make test-release-tooling`'s compose render cases
  and `test_committed_stack_values.py` pass; `tests.yml`, job `test · test-e2e-unit` — the
  reworked static stack cases pass.

  Fresh-context check. Fixed:
  - The full stack's credits storefront would have refused its configuration
    (`api_key_env` beside the overlay's `api_key`, 9.5), with a test that catches it.
  - `docs/bare-metal-seller-quickstart.md` told operators to export variables the wrapper
    no longer reads; it now gives an operator overlay, registry profile and site profile.
    No task named the quickstart; closeout's documentation compliance should confirm it.
  - `tools/issue-discovery`'s two `compose_up` phases set the retired
    `VMS_PROVISIONING_ACTIVE_PROFILES`; they set `PROVISIONING_MODE` now. Their default
    compose arguments still name `docker-compose.yml` alone, which never started bare and
    still does not; left as it was.
  - Tests for registry-b's bootstrap key, the wallet keys and the registry selection, and
    notes that overstated (9.1, 9.6) or did not say how the system runs were made.
  Declined:
  - Keeping the bare-metal SSH key's guard (9.1 says why).
  - Returning `REGISTRY_FILTER_SPEC_PATH` and registry-b's read and write gates to the
    domain files: 9.3 moves every `REGISTRY_*` value into the profiles, and the base file
    still binds the API-credit specification at the path the profile names.
  - Replacing the VM base file's `${HOME}/.ssh/id_ed25519` bind, which predates the change
    and is an operator's real key, not a committed value.
  - Pinning `pyyaml` in `test-release-tooling`, whose other `--with` packages but
    `eth-account` are unpinned too.

  Handoff to section 10 and closeout:
  - Comments section 10 makes true or must fix: the overlays' headers say the lane
    targets "do exactly this" with no `--env-file`, true once 10.3 lands; the root
    `Makefile`'s mode comment says the compose files default to real, while the overlays
    default to `mock`; `docker-compose.yml`'s header (10.6).
  - `tools/payments-lane-double/README.md` and `e2e-tests/README.md` still describe
    `SSL_CERT_FILE`, `PAYMENTS_LANE_*` and the env-file wiring; 10.6 rewrites them.
    `dev-env/identities/README.md` is already rewritten for the stack; its runner
    paragraph (lane_env.py `runner`, the env targets, the Makefile seed) is 10.6's.
  - `lane_env.py compose` has no reader once 10.4 retires the targets.
  - For closeout: `DEPLOYMENT_AND_CONFIG.md` "Bare-metal role configuration" ("The
    Compose wrapper mounts the operator's storefront.toml…") and "Per-domain stack
    composition"'s `VMS_`/`BARE_METAL_PROVISIONING_ACTIVE_PROFILES` paragraph are now
    false; the first is not in the promotion list.
  - The full local stack was not brought up here.

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
  bare-metal-lane}.yml`, every value a quoted string but the numbers and booleans, so
  no `@str` is needed. `settings.toml`'s `[default.payments]` header now says the lanes
  set the section in these profiles and an external run states its token in a secret
  profile. Unit (`tools/payments-lane-double/tests/integration/test_lane_env.py`, pass):
  10.5's profile cases, which read each file with `yaml.safe_load`; and, through the
  runner's own loader (`e2e_harness.settings`' bootstrap over the committed config
  directory), `test_a_lane_runner_loads_a_complete_payments_section` (each lane's
  `docker,payments-lane,<lane>-lane` merges into every setting the payment scenarios
  require, the lane's seller key its storefront's identity file) and
  `test_a_runner_without_the_lane_profiles_has_no_payments_target`, both in
  `e2e-tests/tests/unit/test_domain_stack_configuration.py`. System (10.7): each lane's runner loaded
  `docker,payments-lane,<lane>-lane` and its payment scenario reached the double.
- [x] 10.2 The helper (D14, D6). The payments helper writes `PAYMENTS.BUYER_API_KEY` into
  the `market` subprocess's environment under the variable `PAYMENTS.API_KEY_ENV` names,
  as provisioning writes `ANSIBLE_CONFIG` from its settings; the readiness probe trusts
  `PAYMENTS.CA_BUNDLE_PATH` with proxies still disabled; the shared buyer-configuration
  writer passes `ca_bundle_path` into the buyer's `[Settlement.arkhai_payments]`. The probe
  no longer reads `SSL_CERT_FILE`. Unit cases in `test_payments_helper.py`: the token
  reaches the subprocess environment and no other; the probe trusts the configured bundle
  and fails on a missing one; the buyer configuration carries `ca_bundle_path`.
  Done, with one difference from the plan's wording, which named the `market`
  subprocess only: the payment scenarios also approve, snapshot and read refunds with
  in-process payments clients, which resolved the key from the runner's own environment.
  The helper hands the key to both kinds of buyer and writes it into no process
  environment: `buyer_payments_environment(config)` returns `{API_KEY_ENV: BUYER_API_KEY}`
  (empty with development authentication or no key), which `create_profiled_buyer_cli`
  takes as a new `credential_environment` and merges into the `market` process's
  environment, and `buyer_payments_client(config, owner)` builds the kit's client with
  that mapping over `os.environ` as the environment its key resolution reads. The VM,
  API-credit and bare-metal payment scenarios use them (the VM scenario's
  `PaymentApproval` through its `client_for_owner`), files beyond the plan's list.
  Provisioning's `ANSIBLE_CONFIG` writes `os.environ` once; doing that here would put
  the token in the runner's environment, which the delta forbids. `configured_payments`
  reads `CA_BUNDLE_PATH` into the config, and its default readiness probe is
  `target_ready(url, ca_bundle=config.ca_bundle_path)`; `target_ready` lost its `environ`
  seam. `payment_config_toml` writes `ca_bundle_path` when set. Unit
  (`e2e-tests/tests/unit/test_payments_helper.py`, in `make test-e2e-unit`, 551 passed):
  the probe trusts exactly the configured bundle with proxies off, ignores a process
  `SSL_CERT_FILE`, and is unready on a missing or malformed bundle; the default probe gets
  the configured bundle; through the default probe answering healthy, a lane-owned target
  is ready under the lane CA and fails by name under a missing bundle, the probe never
  asked; the key is handed over under `API_KEY_ENV`, never written into `os.environ`; it
  reaches the `BuyerCli`'s `credential_env` through `create_profiled_buyer_cli` (that
  `BuyerCli.run` merges `credential_env` into the subprocess environment is read from
  the code, not tested; no subprocess is started); no key is handed over without one or
  with development
  authentication; an in-process client sends `Bearer <key>` with no variable set (the
  real client over `httpx.MockTransport` at a loopback origin); the serialized buyer
  table carries `ca_bundle_path` and `api_key_env`. System (10.7): the three payment
  scenarios approved and read at the double under these profiles.
- [x] 10.3 Lane targets (D18, D20, D14). In `e2e-tests/Makefile`: each `test-e2e-<lane>`,
  `e2e-<lane>-down` and `e2e-<lane>-logs` names its Compose files and project only, with
  `PROVISIONING_MODE` exported to Compose; `test-buyer-machine` takes `RUNNER_PROFILES`
  (each lane target sets `docker,payments-lane,<lane>-lane`; unset, `docker` alone) and one
  literal lane-CA mount, and passes no environment file; `e2e_env_if_missing`, the
  environment-file variables and the stale "deadlines" comment go. `check-payments` at
  setup keeps `lane_env.py seller-account`.
  Done. The `mock`/`real` check 10.4 keeps moved here, as
  `E2E_REQUIRE_PROVISIONING_MODE`, the first step of each `test-e2e-<lane>`: these are
  the targets that bring a stack up, and no root target does now. `PROVISIONING_MODE`
  defaults to `mock` and is exported, so a lane run and the pipeline's `e2e.yml`, which
  sets it, reach Compose the same way. `e2e_up` and `e2e_check_payments` lost their
  environment-file argument. The lane CA mount is always present in
  `test-buyer-machine`, unused by a run without the lane profiles. Unit
  (`scripts/tests/test_lane_compose.py`, `make -n` with `MAKE=:`, so a recursive call is
  printed and not made, in `make test-release-tooling`, 2226 passed):
  `PROVISIONING_MODE=hosted` fails each lane target naming the rule; each lane target,
  and its `-down` and `-logs`, prints no `--env-file`, and the lane target hands
  `RUNNER_PROFILES=docker,payments-lane,<lane>-lane` to `test-buyer-machine`, which
  runs the runner with `-e ACTIVE_PROFILES=` those profiles (`docker` when unset) and
  mounts the lane CA at the `ca_bundle_path` `config-payments-lane.yml` names. That the
  mode reaches Compose through `export` is shown only by the lane runs. System (10.7):
  the three lane targets ran as written.
- [x] 10.4 Retire the environment targets (D18, D20). In the root `Makefile`: remove
  `e2e-vms-dev-env`, `e2e-apicredits-dev-env`, `e2e-bare-metal-dev-env`, both
  `e2e-*-stack-env` helpers, `e2e-dev-identities`, `e2e-dev-identities-env`, the three
  `e2e-<lane>-payments-env`, their variables, the buyer seed and the `sed` read, and their
  `.PHONY` entries; keep the `PROVISIONING_MODE` `mock`/`real` check for the targets that
  bring a stack up. `.gitignore` drops the generated environment files and keeps
  `.e2e-buyer/`. `.github/workflows/e2e.yml`'s `PROVISIONING_MODE` keeps working unchanged.
  Done; the mode check lives in `e2e-tests/Makefile` (10.3). `e2e.yml`'s value is
  unchanged; its comment, which said the environment targets read it, now says the lane
  targets hand it to Compose. A search finds no reader of the retired targets but the
  permanent documents closeout owns (`DEPLOYMENT_AND_CONFIG.md`'s "Per-domain stack
  composition", by name, and `TESTING.md`'s lane paragraph on `PROVISIONING_MODE`, by
  description: "each lane's environment target, which prints the stack's provisioning
  profiles") and dated records under `docs/attachments/`; the runbook's §0 bullet, also
  by description, is corrected here. Correction to the plan, found by the fresh-context
  check: `.gitignore` keeps one pattern, `.e2e-*.env`, rather than none, since a local
  environment file an earlier run wrote holds paths from the contributor's machine and
  must never be committed. Unit: 10.3's dry-run cases; the old environment-target mode
  case is gone with the targets.
- [x] 10.5 `lane_env.py` (D21). It keeps only `seller-account` and `seller-token`; the
  `compose` and `runner` modes, `CA_MOUNT`, `BUYER_API_KEY_ENV` and `_setting` go.
  `test_lane_env.py` follows, and gains the runner half of D21: the runner profiles' tokens,
  accounts, receipt identity and fee equal `accounts.toml`, and each lane profile's seller
  key equals the `ARKHAI_IDENTITY_CREDENTIAL` of the identity file its storefront signs
  with (`bob.identity.env`, `api-credits.identity.env`).
  Done; `SERVICE_URL` stays, which `helm/tests/test_release_topology.py` reads.
  The double's dev group gains `pyyaml>=6` for the profiles, relocked (`make lock`; only
  the double's lock changed). Beyond the plan: `helm/tests/test_release_topology.py`
  compared the e2e-tests chart's profile with `lane_env.runner_lines` and
  `BUYER_API_KEY_ENV`, which are gone; it now compares it with the fixtures and with
  `config-payments-lane.yml`, read as the flat mapping of JSON scalars it is, since that
  suite has no YAML parser. Unit and library integration (`make test-payments-lane-double`,
  `check-tls` and 49 passed): the script's standard-library imports; run isolated, its two
  modes print the fixture's seller account and token; the shared profile's service URL
  and identity, fee, livemode, `lane_owned`, both accounts, buyer token and CA path equal
  the fixtures and constants, and its `api_key_env` carries no `ARKHAI_` prefix; each lane
  profile's seller key equals its storefront's identity file and states nothing the shared
  profile does. Chart render (`make -C helm test-render`): pass.
- [x] 10.6 Documents the targets named (D18). `docker-compose.yml`'s header and
  `VALIDATION_RUNBOOK.md` §8 give the full stack's `docker compose -f docker-compose.yml -f
  compose.vms-local.yml -f compose.apicredits-local.yml up -d`, the runbook's buyer step
  creating `.e2e-buyer/…` first and §6's note naming `PROVISIONING_MODE`;
  `dev-env/identities/README.md`'s table lists each stack's overlays and profiles instead
  of a target, and its fixture statements cover the new secret overlays and profiles;
  `e2e-tests/README.md`'s "Shared payment-scenario configuration" and lane passages and
  `tools/payments-lane-double/README.md` describe the profiles and secret overlays. Dated
  records under `docs/attachments/` keep their wording.
  Done. The runbook has no step that runs a buyer by hand; §8 gains the note that a
  buyer service's `.e2e-buyer/` directories must be created first. `dev-env/identities/README.md`'s
  table and fixture statements were rewritten in section 9; here its runner paragraph
  now names the runner profiles. The double's README's Helm passage, which still
  describes the `seller-payments-key` Secret, is section 12's (12.2). Also corrected:
  `e2e-tests/config/config-docker.yml`'s bare-metal comment named the retired target.
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

  Evidence, local:
  - Unit: `make test-e2e-unit` 551 passed; `make test-release-tooling` 2226 passed, none
    skipped; `make test-payments-lane-double`, `check-tls` and 49 passed, after `make
    lock` (only the double's lock changed); `make -C helm test-render` passes, with the
    reworked runner-profile comparison.
  - `make test`: exit 0, every suite. It ran before the fresh-context fixes, which
    touched tests (`test_lane_compose.py`, `test_payments_helper.py`,
    `test_domain_stack_configuration.py`), comments, `.gitignore`, the runbook and the
    README, and these notes; the three unit suites above were rerun after them.
  - `make check-packaging`: all checks OK. `make check-change`: every check passes,
    documentation citations included, now that the runner profiles exist.
  - System, through the lane targets as rewritten, before the fresh-context fixes (none
    touches a file a lane run reads but the e2e Makefile's comment order):
    - `make -C e2e-tests test-e2e-apicredits`: `check-payments` ok; the runner ran under
      `ACTIVE_PROFILES=docker,payments-lane,apicredits-lane`; 4 passed, all three
      `e2e_credits_payment_deal` stages among them, no skips.
    - `make -C e2e-tests test-e2e-bare-metal`: `check-payments` ok; 64 passed, 2 failed,
      2 skipped; the three `e2e_bare_metal_payment_deal` stages pass. The failures and
      skips are the two introduction cases' `KeyError: 'mechanism'` (`dev`'s #314, 4.9).
    - `make -C e2e-tests test-e2e-vm`: `check-payments` ok; 152 passed, 1 failed, 2
      skipped; `e2e_vm_payment_deal`'s stages 1–2 pass, approving at the double with the
      key the harness handed its in-process client, and stages 3–4 skip. The failure is
      `e2e_vm_introduction`'s same #314 case.
    No environment file was written or read in these runs.

  End-to-end confirmed: `e2e_bare_metal_payment_deal` and `e2e_credits_payment_deal` pass
  without skips, `e2e_vm_payment_deal`'s stages 1–2 pass and 3–4 skip (their only skip
  path is the `mediation_target` fixture; the run printed no reasons), each lane's
  `check-payments` passed at setup, and every other lane marker passed but the three
  introduction cases that fail on `dev` already.
  Owed by validation, confirmed: `tests.yml`, jobs `test · test-e2e-unit`,
  `test · test-payments-lane-double` (with the relocked environment) and
  `test · test-deployment-packaging` (release tooling's dry-run and render cases, and
  `make -C helm test-render`'s topology comparison) — each passes.

  Fresh-context check. Fixed:
  - `.gitignore` would have exposed this checkout's leftover `.e2e-*.env` files, which
    hold local paths, to a blanket `git add`; it keeps `.e2e-*.env` (10.4).
  - The Makefile dry-run tests walked the whole build chain, since `make -n` runs
    `$(MAKE)` lines; they pass `MAKE=:` now, and assert the runner's `ACTIVE_PROFILES`,
    the CA mount against the shared profile, and `-down`/`-logs` (10.3).
  - The missing-bundle case could not fail (a closed port is unready anyway); it now
    runs the default probe answering healthy, with the lane CA as control (10.2).
  - A test through the runner's own loader that the profiles merge into a complete
    section (10.1).
  - The runbook's §0 bullet; a profile comment calling every value quoted; the
    Makefile's mode lines under the wrong paragraph; a README sentence; overstated notes.
  Declined:
  - Moving the runner-profile cases out of the double's `tests/integration/`: the plan
    and D21 put them in `test_lane_env.py`, beside the script's cases.
  - Replacing `test_payments_helper.py`'s patch of the module's `target_ready` with the
    `ready` seam: the case exists to show what the default probe receives.
  - Hardening the mode check against a multi-word value; `filter` reads `mock real` as
    allowed, and a run passing that has asked for both.

  Handoff to sections 11–12 and closeout:
  - The local Helm release's e2e-tests chart profile has no `ca_bundle_path` and no
    buyer key; it serves no payment scenario (D11). `helm/tests/test_release_topology.py`
    now holds its public keys to `config-payments-lane.yml` as well as the fixtures.
  - The double's README Helm passage still describes the `seller-payments-key` Secret;
    12.2 retires it.
  - Closeout destinations this section made false: `DEPLOYMENT_AND_CONFIG.md`'s
    "Per-domain stack composition" (the environment targets and
    `*_PROVISIONING_ACTIVE_PROFILES`) and "Bare-metal role configuration" (section 9's
    handoff), `TESTING.md`'s lane paragraph on `PROVISIONING_MODE` and its "Private
    Service Dependencies" account of the runner's payments settings.
  - The session is large: two sections, six lane runs and two fresh-context checks.
    Sections 11 and 12 should start in a fresh session.

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
  Done: new `templates/configmap.yaml` (`<fullname>-config`), each line
  `NAME='value'` from a `registry.envLine` helper that doubles backslashes and escapes
  quotes, the only two sequences the registry's dotenv reader decodes in a single-quoted
  value (read from its `dotenv/parser.py`); the lines are joined and indented as one
  block, so a value holding a newline stays inside it. An unset value renders no line.
  The rendered keys: the three identity keys, `REGISTRY_AUTHORITY_CREDENTIAL_FILE`, the
  filter specification path, the three descriptor keys, the pointer and the
  recommendation (`toJson`) when set, `DATABASE_URL`, `PORT`, `HOST`, `LOG_LEVEL`,
  `ROOT_PATH`, and the two API-key gates. A `registry.credentialFile` helper names the
  credential path for both the profile and the Secret's mount, so they cannot disagree.
  The profile mounts by `subPath` at `/app/config/config-production.env`, as the
  provisioning chart mounts its profile. Beyond the plan: the pod template carries a
  `checksum/config` annotation over the ConfigMap. Without it, a values change would no
  longer roll the registry, which it did while the values were pod variables. The
  posture checks stay in `deployment.yaml`. Both `values.yaml` files drop the four unread
  `config` keys, and the umbrella's registry schema stays open, so a file stating them
  renders. `CHAIN_ID` is gone with the `global.rpc` branch.
  The helper refuses, naming the setting, the two values the reader cannot read back,
  both found by the fresh-context check and confirmed in the installed python-dotenv:
  - a value ending in a backslash, whose escaped form ends `\'`, so the reader's
    single-quote pattern runs on into the next line and drops both settings;
  - one holding `${`, since `dotenv_values` interpolates every value, quoted or not, and
    pydantic-settings calls it with interpolation on.
  Also beyond the plan's files, from the same check:
  - `core/registry/Dockerfile` loses `ENV PORT`, which, as a process variable, would
    override the profile's `PORT` (the settings default it to 8080; `EXPOSE` keeps the
    `ARG`). The image's `CMD` still hard-codes `--port 8080`, a mismatch with a
    non-default `service.port` that predates this section. Nothing here builds the
    image; validation's lane and Helm runs do.
  - `core_registry/config.py`'s `root_path` comment, which said the value came from a
    pod variable set in a values overlay, now says a profile states it.
- [x] 11.2 `secretProfile` (D16). `secretProfile: {secretName, profile}` mounts
  `config-<profile>.env` from that existing Secret under `/app/config` and appends the
  profile to `ACTIVE_PROFILES`; `auth.bootstrapKeySecret` and `auth.adminKeySecret` with a
  name set fail rendering naming `secretProfile`. The umbrella's registry aliases drop
  their empty `auth` blocks. The Deployment's `env` holds only `CONFIG_DIRECTORY` and
  `ACTIVE_PROFILES`.
  Done. The Secret's key is mounted by `subPath` beside the rendered profile, and
  `registry.activeProfiles` gives `production,<profile>`. Beyond the plan, two refusals:
  a `secretName` without a `profile` is refused, and so is the profile `production`,
  which would mount over the rendered file. A retired key with an empty name still
  renders, so an existing values file carrying the empty blocks works. Beyond the plan's
  files: the umbrella schema's `registryInstance` gains a closed `secretProfile`
  (strings, the profile a file-name-safe word or empty), and
  `helm/fixtures/two-registries-values.yaml`, which named both retired Secrets and would
  now fail, names a `secretProfile` instead (`credits-registry-keys`, `credits-keys`).
  The registry chart's `values.yaml` documents `secretProfile` where `auth` was.
- [x] 11.3 Render cases (D16; the delta's scenarios) in `helm/scripts/test-render.sh` or
  `helm/tests/test_release_topology.py`, where registry rendering is asserted today: the
  rendered profile's lines for the default and the API-credit alias, each with its own
  filter specification path; the Deployment's environment holding exactly the two
  variables; a `secretProfile` mounted and appended; each retired key refused by name; the
  posture checks still failing as before.
  Done. Chart render, in `helm/tests/test_release_topology.py` (run by `test-render.sh`),
  pass. A `_registry_profile` helper decodes the profile's lines as the dotenv reader
  decodes a single-quoted value, `\\` and `\'` only, and refuses any line not in that
  form. That matches the reader only for values the chart renders: it does not reproduce
  the reader's trailing-backslash and interpolation behaviour, which the chart refuses.
  New cases:
  - `test_each_registry_renders_its_settings_as_a_profile_and_sets_only_the_resolver_variables`:
    release 1 with the API-credit alias enabled. For each registry, the profile's key set
    is exact, with its own authority, filter specification and display name. `PORT` is the
    Service's port. The credential path is the Secret mount's directory and item path.
    The container `env` is exactly `CONFIG_DIRECTORY=/app/config` and
    `ACTIVE_PROFILES=production`. The profile mounts from the release's ConfigMap. The
    exact key set and the exact environment are what show that no unread variable or
    `CHAIN_ID` renders.
  - `test_a_values_file_stating_settings_nothing_reads_renders`: the four keys and empty
    `auth` blocks render, and none reaches the profile.
  - `test_a_registry_secret_profile_is_mounted_beside_the_rendered_one_and_layered_after_it`:
    the mount, the Secret item, `production,keys`, the two template refusals above, and
    the values schema refusing a profile with a comma and an unknown key, each error
    naming `secretProfile`.
  - `test_a_retired_registry_key_secret_is_refused_naming_secret_profile`: both keys.
  - `test_a_registry_setting_its_profile_cannot_carry_is_refused`: a trailing backslash
    and a `${`, each naming its setting.
  - `test_the_registry_posture_checks_refuse_a_mismatched_descriptor`: both refusals by
    message, and a gated registry's pointer and gate in the profile.
  - `test_the_rendered_registry_profile_loads_with_the_registry_loader`, beyond the plan
    (TESTING.md, "parse one rendered instance with the service's own parser"):
    - Input: release 1's profile rendered with a non-default value for every setting with
      a default (port 8081, root path, `debug`, both gates on, a pointer), and a display
      name holding a newline, `\\` and `\'`. Beside it, a `config-keys.env` stating
      `REGISTRY_ADMIN_API_KEY` and `LOG_LEVEL='warning'`.
    - Load: through `core_registry.config.load_settings` under `REGISTRY_PYTHON`, which
      `test-render.sh` sets when `core/registry/.venv` exists, from an empty working
      directory and environment.
    - Shown: each identity, descriptor, filter, credential, database and host value
      arrives as the profile states it, the display name exactly, the recommendation as
      the fixture's list, and port, root path and gates as set. The second profile adds
      the key and overrides `LOG_LEVEL`.
    - Without the interpreter it prints a skip. The `test · test-deployment-packaging`
      job builds no registry environment, so there it skips, as the storefront loader
      checks do.
  The existing cases that read registry pod variables now read the profile:
  - in the topology suite, the trust pins, the smoke profile's pins, the database URL,
    and the recommendation;
  - in `test-render.sh`, the descriptor, filter specification, recommendation and
    wallet-free identity, now as whole profile lines, with the Secret and chain checks
    kept on the Deployment;
  - also in `test-render.sh`, three new dual-render assertions: the alias's secret
    profile mounted from its Secret, `production,credits-keys`, and none for the compute
    registry.
  Templates broken once while writing the tests: with the profile mount removed, the
  first and third cases failed. With backslash doubling dropped, the loader case
  failed, once its value held `\\`: a lone backslash before a space is literal to
  dotenv, so the first value tried could not show it. Both breaks were restored.
- [x] 11.4 **Verification checkpoint.** Chart render: `make -C helm test-render`. Unit:
  `make test-release-tooling`. `make test`.
  End-to-end: no pipeline marker exercises the chart; validation's Helm part deploys the
  release, whose registry must start from the rendered profile for its scenario pod and
  payments check to pass.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — `make -C helm
  test-render` passes with the registry cases.
  Results:
  - `make -C helm test-render` passes: every umbrella assertion and chart suite, with the
    registry loader case run, not skipped.
  - `make test-release-tooling`: 2226 passed.
  - `make test`: ran every target to its end with no failure.
  - `make check-change` passes.
  - After the fresh-context fixes, which touched the chart's helper and comments, the
    topology tests, the registry's Dockerfile and one `config.py` comment:
    `make -C helm test-render` passes again; `make test-registry` passes, 139 unit and
    128 application integration; `make check-packaging` is all OK. `make test` was not
    rerun after them.
  - No dependency or lock changed.
  End-to-end confirmed as planned: none. Validation's Helm deploy is the first run of a
  registry pod on the rendered profile, and of the registry image without `ENV PORT`; the
  Compose lanes run that image too. Owed by validation, confirmed as written.

  Fresh-context check. Fixed:
  - The trailing-backslash and `${` refusals.
  - The Dockerfile's `ENV PORT` and the `root_path` comment (11.1).
  - The loader case: non-default values, so a dropped line would show; a newline; a key
    in both profiles to show precedence.
  - The values schema's `secretProfile` refusals, now tested.
  - The test helper's docstring, which claimed the reader's decoding outright.
  - A manifest-wide `CHAIN_ID` search inside the per-chart loop, removed.
  - Two test names and a docstring framed as "still … as before".
  Declined: none.

  Handoff to section 12 and closeout:
  - Closeout destinations this section made false, beyond 13.9's "Registry descriptor
    configuration" (which already covers `DEPLOYMENT_AND_CONFIG.md`'s "Helm and Compose
    surfaces set … through `REGISTRY_DESCRIPTOR_*`" and its "API-key Secret references …
    are instance-local"):
    - `TESTING.md`'s "Chart Render Tests" lists each loader check by its interpreter
      variable and should gain `REGISTRY_PYTHON`.
    - `DEPLOYMENT_AND_CONFIG.md`'s "Kubernetes: ConfigMap and Secret mounting" says a
      new non-secret key needs only a `values.yaml` change. That holds for the
      provisioning chart, not the registry's, which maps each value to its variable by
      name (D16 keeps the values' shape). Promotion should state the registry as that
      exception, and that its profile is a dotenv file rather than YAML.
  - The registry image's `CMD` hard-codes port 8080 whatever `service.port` says;
    pre-existing, left.

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

- [ ] 12.1 The CA option derives `ca_bundle_path` (D3). With the option set, each chart
  mounts the bundle as before and adds `[Settlement.arkhai_payments].ca_bundle_path`,
  naming the mounted file, to the rendered configuration where `config` states none, and
  fails rendering naming both paths where `config` states another; it sets no
  `SSL_CERT_FILE`. Unset, it adds neither mount nor setting.
- [ ] 12.2 The key in the secret overlay (D19, D11). Remove both charts' `paymentsKey`
  option, its helpers, its `api_key_env` checks and its environment entry, from the
  Deployment and the payments-check pod alike; the values schemas no longer accept it.
  `helm/local-values.yaml` and `helm/bare-metal-release-values.yaml` drop `paymentsKey` and
  `api_key_env`; `topology-secrets.sh` writes the seller token as
  `[Settlement.arkhai_payments].api_key` into each storefront's runtime Secret's
  `storefront.secrets.toml` (`arkhai-bob-runtime` and the bare-metal release's) from
  `lane_env.py seller-token`, instead of creating `seller-payments-key`, which leaves
  `LOCAL_SECRETS`. `helm/fixtures/payments-ed25519-values.yaml` follows.
- [ ] 12.3 The payments-check pod (D12). It mounts the configuration, the secret overlay
  and the CA bundle, and carries the identity credential and no payments variable, from
  the helpers the Deployment uses.
- [ ] 12.4 Render cases (D3, D11, D12, D19; the deltas' scenarios), in both charts'
  `tests/test_render.py` and `helm/tests/test_release_topology.py`: the derived
  `ca_bundle_path` from a ConfigMap and from a Secret source; a stated different path
  refused naming both; neither mount nor setting when unset; no `SSL_CERT_FILE` and no
  payments variable in the Deployment or the check pod; a `config` stating `api_key`
  refused by the values schema; the bare-metal pod environment holding only the
  configuration directory and the signing credential, with and without the CA option
  (the MODIFIED requirement's scenario); the payments-only case and the check pod mounting
  no data volume, as before; the local topology's Secrets without `seller-payments-key`.
- [ ] 12.5 **Verification checkpoint.** Chart render: `make -C helm test-render`. Unit:
  `make test-release-tooling`, `make test-payments-lane-double`. `make test`.
  End-to-end: no pipeline marker exercises the charts; validation's Helm part deploys the
  release and runs every `-payments-check` pod (D12), which must pass with the key from the
  runtime secret overlay and trust from the derived `ca_bundle_path`. Serving payment
  scenarios on Helm is not owed (D11).
  Owed by validation: `tests.yml`, jobs `test · test-deployment-packaging` — `make -C helm
  test-render` and release tooling pass with the new cases — and
  `test · test-payments-lane-double` — passes.

## 13. Closeout

Replanned against the redesign: replaces the unstarted section-6 closeout this plan first
ended with. Confirm and promote the verified design, then archive last (D1–D23 and every
delta requirement). The eleven parts follow `openspec/README.md#plan-closeout-requirements`
in order. Closeout changes no code: a part needing a code, lock, chart, or test change
returns the change to implementation.

- [ ] 13.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every
  comment and docstring sections 1–12 added: the kit's `access_check.py`, key resolution
  and balance view; the mediation credential and dispute credential; the registry's
  loader; the double's modules, fixtures and generator; the storefront CLIs' subcommands;
  the Compose files, profiles and secret overlays and the lane targets; the helper; the
  charts' values and templates. Each states current behaviour and every fixture value's
  label is present. A needed correction returns to implementation.
- [ ] 13.2 **Import placement — confirm.** Every import sections 1–12 added is at module
  level unless a verified cycle or recorded lazy-load reason keeps it local. A needed move
  returns to implementation.
- [ ] 13.3 **Documentation compliance.** Check D1–D23 against `openspec/README.md`'s
  placement rules and the promotion record below, recording a disposition per decision,
  and check every promoted statement against the code.
- [ ] 13.4 **Narrative compression.** Compress section notes to final behaviour,
  validation evidence, deferred work, and destinations, moving durable rationale into
  `design.md` first.
- [ ] 13.5 **Roadmap currency.** In `docs/development/ROADMAP.md`:
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
- [ ] 13.6 **Campaign index currency.** In `openspec/changes/README.md`, set this change's
  row to its archived state and link, and update the Reach hosts campaign's graph lines
  naming it. Note in `qualify-real-provisioning-by-scenario`'s row that its storefront
  chart CA option is delivered here as a chart-derived `ca_bundle_path`, the storefront's
  payments key being `api_key` in its secret overlay, and that its delta's same-named
  requirement must be dropped or reduced to a MODIFIED at its reverification; note in
  `add-arkhai-payments-lane-double`'s row its D1/D7 revision, the fixture-identity guard it
  owns, and the `MediationCredential` carrying a resolved token it inherits. Run
  `make check-change-index`. Archive cleanup, not closeout, releases the dependents.
- [ ] 13.7 **Packaging.** Run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=add-mvp-payments-lane-double`. No `.agents/`,
  `.claude/` or `.codex/` edit is planned; if one was made, run `make check-agent-skills`.
- [ ] 13.8 **End-to-end pipeline.** Confirm the pipeline passes on the closeout candidate
  and record the run, its result, and the scenarios exercising this change:
  `e2e_bare_metal_payment_deal` and `e2e_credits_payment_deal` passing without skips,
  `e2e_vm_payment_deal`'s stages 1–2 passing and 3–4 reporting the mediation blocked
  skip, each lane's `check-payments` at setup, and every lane's other markers green on the
  stacks configured from committed files; and the Helm part's payments check with the
  registry started from its rendered profile. A pipeline that cannot run for an unrelated
  reason is recorded as a blocker naming its cause and owner, and what it gates is unrun.
- [ ] 13.9 **Promotion.** Write and record in the promotion record:
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
- [ ] 13.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=add-mvp-payments-lane-double` after promotion and
  resolve every match, then `openspec validate add-mvp-payments-lane-double --strict`.
- [ ] 13.11 **Archival.** `openspec archive add-mvp-payments-lane-double -y`, merging the
  four deltas into `openspec/specs/`; then point the index row at the archive directory.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 The double's project and its place among tools | `tools/README.md`; `tools/payments-lane-double/README.md` |
| D2 Lanes running the double; the VM scenario's mediation prerequisite and dispute credential | `openspec/specs/test-compatibility/spec.md` (delta); `openspec/specs/test-compatibility/architecture.md`, "Payment evidence ownership"; `e2e-tests/README.md` |
| D3 Committed lane CA and leaf; the CA option deriving `ca_bundle_path` | `tools/payments-lane-double/README.md`; `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Kubernetes: ConfigMap and Secret mounting" |
| D4 No production guard; the unusable pinned authority | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`, "Private Service Dependencies"; `docs/development/ROADMAP.md` |
| D5 The balance read | `openspec/specs/market-composition/spec.md` (delta); `kit/arkhai-payments/README.md` |
| D6 Lane-owned targets fail | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`, "Private Service Dependencies" |
| D7 The pinned authority through the registry | `docs/development/TESTING.md`, "Private Service Dependencies"; `e2e-tests/README.md` |
| D8 The double mirrors the service | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`; `docs/development/ARCHITECTURE.md`, "Testing strategy" |
| D9 Lane configuration in committed files, never generated by Make (principle 4) | `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition"; `docs/development/ARCHITECTURE.md`, "Deployment topology" |
| D10 Round 1's implementation cadence | change history only |
| D11 The local release's payments rehearsal | `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Release topology"; `docs/operator-handbook.md`, "Payments access"; `docs/development/ROADMAP.md` (the Helm-serving gap) |
| D12 `check-payments` | `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover"; `docs/operator-handbook.md`, "Payments access" |
| D13 The cleanup in this change | change history only; `docs/development/ROADMAP.md` (the registry's Dynaconf gap) |
| D14 The runner's shared and per-lane payments profiles | `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`, "Private Service Dependencies"; `e2e-tests/README.md`, "Shared payment-scenario configuration" |
| D15 Development binds in the overlays; base files keep topology | `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition"; `dev-env/identities/README.md` |
| D16 The registry's profile env files and chart | `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Registry descriptor configuration"; `docs/operator-handbook.md`, "Registry secret profile"; `core/registry/README.md` |
| D17 Provisioning site profiles | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition"; `dev-env/identities/README.md` |
| D18 The environment targets retired | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition"; `docs/development/VALIDATION_RUNBOOK.md`, "Bring Up Local Stack"; `docker-compose.yml`'s header; `e2e-tests/README.md` |
| D19 Secrets through secret overlays; trust through configuration (principle 3) | `openspec/specs/settlement-configuration/spec.md` (delta); `openspec/specs/deployment-state/spec.md` (delta); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Profile-based configuration" and "Kubernetes: ConfigMap and Secret mounting"; `docs/development/ARCHITECTURE.md`, "Deployment topology"; `kit/arkhai-payments/README.md`; `kit/arkhai-mediation/README.md`; `docs/development/ROADMAP.md` (the signing-credential gap) |
| D20 The provisioning mode | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition"; `docs/development/TESTING.md`'s lane paragraph |
| D21 Tests holding restated values | change history only; the tests are their own record |
| D22 Implementation cadence | change history only |
| D23 Storefront wallet keys in the secret overlays | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition"; `dev-env/identities/README.md` |
