# payments-lane-double

An HTTP double of the Arkhai payments service, run inside the end-to-end lanes and
the local Helm release so a payment scenario has a payments target to settle
against. It is a lane collaborator: it may import the repository's internal kits,
and nothing imports it.

## What it is

The double serves the payments service's HTTP API over the payments kit's
clock-injected engine, `PaymentsAuthority`
(`kit/arkhai-payments/src/market_arkhai_payments/fixtures/authority.py`), the same
engine the kit's in-process `FakePaymentsClient` runs, so there is one ledger
implementation for both. The clock is wall time. State is in memory in one
process, one lock serialising requests, and is lost on restart: a run lives only
as long as its lane.

It mirrors the service's API — its routes, bearer authentication, approval
admission, read authorization, idempotency and error codes — and serves whatever
the engine serves, rate parts and `start`, `stop`, `extend` and `lift` included.

| Route | Behaviour |
|---|---|
| `GET /health` | `{"status": "ok"}`, unauthenticated |
| `POST /transactions` | approves a mandate, with optional deal attachments, and returns the signed receipt |
| `GET /transactions/{id}` | the signed transaction snapshot |
| `GET /transactions/{id}/mandate` | the approved mandate |
| `POST /transactions/{id}/attachments` | stores the Agreement the engine checks against the deal hash |
| `POST /transactions/{id}/events` | submits an event, `Idempotency-Key` as the engine's request ID |
| `GET /balances/{account}` | the caller's own balance |

- **Authentication.** `Authorization: Bearer <token>` names an account through the
  fixture account file. A missing or unknown token is 401
  `authentication_required`; a malformed body or path is 400 `invalid_request`.
- **Approval.** In order: authentication; the caller is the mandate's `from`, else
  403 `caller_not_authorized`; an exact repeat of an approved mandate returns its
  original receipt whatever the clock or the payer's balance now says, so a payer
  can retry a lost response; and, for a new approval only, admission refuses 409
  `mandate_expired`, 422 `unsupported_asset` (anything but `USD/6`), 422
  `fee_mismatch` (against 250 bps), and 404 `account_not_found` (`from` or `to`
  outside the account file), then the engine refuses 409 `insufficient_funds` and
  409 `deal_mismatch`. Admission lives in the double, not the engine, because the
  in-process fake seeds its approvals directly and has none.
- **Reads.** A transaction's snapshot and mandate answer its parties and any
  account a part names in any of its authorities; anyone else gets 403. A balance
  answers only the caller's own account.
- **Errors.** Every error body is the published `ApiError`, `{"error": "<code>"}`,
  with the service's status for its code. Where the engine never raises a code,
  the status follows the engine's convention: 422 for a mandate the service will
  not accept, 404 for an account it does not know.
- **Receipts.** Signed with the fixture receipt key, always `livemode: false`, so a
  live-configured role refuses every receipt the double signs.
- **Funding.** The buyer is funded once at startup from the account file. There is
  no funding route: funding is topology.

## What it claims

Its suite, and any result against it, claims only the once-only surface:
approval, Agreement attachment, signed receipts, transaction snapshots, the seller's
reverse, and the balance read. Rate parts, stops and holds are served because the
engine serves them, not qualified. A scenario passing against the double
establishes this repository's use of the payments boundary, never the payments
service's ledger, funding or availability.

## Fixtures

Every value under `fixtures/` and `tls/` is a public development value, committed
for lanes and local releases. Never use one on a public network.

- `fixtures/accounts.toml` — the asset and fee policy, the receipt-signing seed and
  the identity it yields (distinct from `FakePaymentsClient`'s), and the buyer,
  seller and dispute authority accounts with their bearer tokens and the buyer's
  seed balance. The dispute authority's account has no token, so nothing can
  authenticate as it.
- `fixtures/dispute-authority.toml` — the pinned dispute authority lanes and the
  local release recommend through their registries: interface
  `arkhai.mediation.v1`, origin `https://dispute.invalid`, under a top-level domain
  reserved never to resolve, its account, a record key with no usable private half,
  and an advertisement whose mechanisms include `arkhai.payments.v1` and whose
  minimum dispute window every lane's options meet. Nothing can ever answer as it.

## TLS

`tls/generate.py` derives the lane CA's and the double's keys from fixed seeds and
writes the CA certificate (`lane-ca.pem`), the double's leaf certificate
(`double.pem`, for `payments-double`, `localhost` and `127.0.0.1`) and its key
(`double.key.pem`), with fixed serials and validity ending 9999-12-31. Ed25519
signatures are deterministic, so the output is the same bytes on every run. The CA's
private key is never written to a file, but its seed is in the generator, so anyone
can issue a certificate under the lane CA: it is trusted only inside lanes and local
releases. `make check-tls`, part of `make test`, regenerates
into a temporary directory and fails unless the committed files are identical;
`make tls` rewrites them.

Callers trust the lane CA alone, through `SSL_CERT_FILE`; the kit's client keeps
its production transport rules — HTTPS outside loopback, no verification bypass.

## Running it

The image, `arkhai:payments-lane-double`, carries the fixtures and TLS files at
`/opt/payments-lane-double`, so it runs with no mounts and no configuration, serving
HTTPS on port 8443 under the service name `payments-double`. A deployment supplying
its own server certificate mounts it over `tls/double.pem` and `tls/double.key.pem`
there. Outside the image, `python -m payments_lane_double` reads
`PAYMENTS_LANE_DOUBLE_FIXTURES`, `PAYMENTS_LANE_DOUBLE_TLS`,
`PAYMENTS_LANE_DOUBLE_HOST` and `PAYMENTS_LANE_DOUBLE_PORT`.

- `make test` (here) checks the TLS files and runs the unit and library integration
  suite: the kit's real `PaymentsClient` against the app through an in-process
  transport, with an injected clock. From the repository root,
  `make test-payments-lane-double` runs it, as part of `make test` and the Tests
  workflow's matrix.
- `make build-payments-lane-double`, from the repository root, builds the image
  from the repository wheelhouse and this project's committed lock;
  `make build-dev` and each lane's `build-e2e-*` target build it.
