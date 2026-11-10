# payments-lane-double

An HTTP double of the Arkhai payments service. The end-to-end lanes run it so a
payment scenario has a payments target to settle against, and the local Helm
release runs it so its storefronts' payments access can be checked. It is a lane
collaborator: it may import the repository's internal kits, and nothing imports
it.

## What it is

The double serves the payments service's HTTP API over the payments kit's
clock-injected engine, `PaymentsAuthority`
(`kit/arkhai-payments/src/market_arkhai_payments/fixtures/authority.py`), the same
engine the kit's in-process `FakePaymentsClient` runs, so there is one ledger
implementation for both. The engine reads the double's perceived clock (see
Controls). State is in memory in one process, one lock serialising requests, and
is lost on restart: a run lives only as long as its lane.

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
- **Funding.** The buyer is funded once at startup from the account file; the
  funding control credits any account in it later.

## Controls

Beside the API the double serves the lane doubles' control routes under `/test/`
on the same port, authenticated by the fixture `control_token` as a bearer token,
through the shared contract in
[`tools/lane-double-controls`](../lane-double-controls/README.md), whose typed
client calls them. They are lane-private: no lane publishes the port to its host.

- **Rules.** `POST /test/rules` installs a rule matching on `route` (`transactions`,
  `snapshot`, `mandate`, `attachments`, `events`, `balances`), the authenticated
  `account`, an event's kind as `event`, and `transaction` (for an approval, the
  transaction its mandate will have). A rule refuses a matching call with a status
  and a published `ApiError` code, after authentication; drops its response after
  it commits; or, as *unavailable* with `match: {}`, abandons every API response
  while installed. A call meets the first rule it matches, an *unavailable* rule
  before any other, and that rule's listing counts it. `GET /test/rules` lists the
  rules with their counts; `DELETE /test/rules/{rule_id}` removes one. The control
  and health routes are never faulted.
- **Clock.** The engine reads a perceived clock, wall time plus an offset.
  `POST /test/clock/advance` moves it forward, and the engine's due state — a
  notice stop taking effect, funding exhaustion, a matured hold — shows at the
  next read, with nothing running in the background; `POST /test/clock/reset`
  returns it to wall time. Admission reads it too.
- **Funding.** `POST /test/funding` credits an account in the account file with
  minor units of `USD/6`; any other account is 404 `account_not_found`.
- **Signer rotation.** `POST /test/signer/rotate` signs every later receipt and
  snapshot with the fixture's `rotation_seed`; a receipt signed before keeps its
  signature, and a snapshot embedding it verifies under both keys.
- **Status.** `GET /test/status` reports the perceived now, the offset and the
  SHA-256 of each installed contract resource, read from the payments kit wheel.

A control refusal is `{"code", "message"}`: 401 `authentication_required` without
the control token, 422 `invalid_request` for a malformed or unsupported rule,
409 `rule_exists`, 404 `rule_not_found`.

## What it claims

Its suite drives the payments kit's real client against the app through an
in-process transport, and over loopback HTTP for the transport faults, with the
clock moved through the control, and claims what the engine serves: approval, Agreement
attachment, signed receipts, transaction snapshots, reverses and the balance read;
and the rate and hold surface — rate parts and payee-only `start`, `stop` with
notice and the earliest pending stop taking effect when the clock reaches it,
per-part `end`, funding exhaustion at funded-through, `afterStop` holds releasing
once the clock passes them, partial `reverse` before and after a stop, and
`extend` and `lift` with `hold_not_extendable`, `extension_not_found` and
`extension_closed`. Each answer is the engine's. A scenario passing against the
double establishes this repository's use of the payments boundary, never the
payments service's ledger, funding or availability.

## Fixtures

Every value under `fixtures/`, and the lane CA and leaf it serves with, is a
public development value, for lanes and local releases. Never use one on a public
network. The fixtures and the certificates are committed; the leaf key is
generated from the generator's seed (see TLS).

- `fixtures/accounts.toml` — the asset and fee policy, the receipt-signing seed and
  the identity it yields (distinct from `FakePaymentsClient`'s), the rotation seed,
  the control token, and the buyer,
  seller and dispute authority accounts with their bearer tokens and the buyer's
  seed balance. The dispute authority's account is the mediation lane double's
  ([`tools/mediation-lane-double`](../mediation-lane-double/README.md)), which
  extends, reverses and lifts with its token as the authority the lanes'
  registries recommend.

## TLS

The lane CA is the lane doubles' one CA, generated in the controls project
([`tools/lane-double-controls/tls/`](../lane-double-controls/README.md#tls)),
which also issues the mediation double's leaf. The double serves its leaf,
`payments-double.pem`, for `payments-double`, `localhost` and `127.0.0.1`. The
certificates are committed; the leaf key is not, since the repository's secret
gate refuses a private key block: the image build runs the generator and takes
`payments-double.key.pem` from it, the same bytes every time, and places the leaf
and its key at `tls/double.pem` and `tls/double.key.pem`.

Callers trust the lane CA through their payments configuration's
`ca_bundle_path`, which the kit's client verifies the double against alone; it
keeps its production transport rules — HTTPS outside loopback, no verification
bypass — and no process trust store changes.

## Running it

The image, `arkhai:payments-lane-double`, carries the fixtures, the certificates and
the leaf key generated at build at
`/opt/payments-lane-double`, so it runs with no mounts and no configuration, serving
HTTPS on port 8443 under the service name `payments-double`. A deployment supplying
its own server certificate mounts it over `tls/double.pem` and `tls/double.key.pem`
there. Outside the image, `python -m payments_lane_double` reads
`PAYMENTS_LANE_DOUBLE_FIXTURES`, `PAYMENTS_LANE_DOUBLE_TLS`,
`PAYMENTS_LANE_DOUBLE_HOST` and `PAYMENTS_LANE_DOUBLE_PORT`.
`PAYMENTS_LANE_DOUBLE_TLS` names a directory holding the leaf and its key under
the image's names, `double.pem` and `double.key.pem`: `make tls` in the controls
project writes them as `payments-double.pem` and `payments-double.key.pem`, to be
copied there under those names.

- The VM, bare-metal and API-credit lanes run the image as the Compose service in
  `compose.payments-double.yml`, with no host port. Each lane's overlay mounts its
  payment storefront's lane configuration, which points at the double and names
  the lane CA as its `ca_bundle_path`, and binds the CA there; the storefront's
  key is `[Settlement.arkhai_payments].api_key` in its secret overlay under
  `dev-env/identities/`, and its registries layer the shared
  `dev-env/registry/config-payments-lane.env`, recommending the mediation lane
  double as the dispute authority. The test runner reads the lane's payments
  settings from committed profiles, `e2e-tests/config/config-payments-lane.yml`
  and the lane's `config-<lane>-lane.yml`, with the lane CA mounted where they
  name it. Every one of those files restates a value here: the storefront
  configurations the receipt identity, fee, service URL and the seller's account
  (`e2e-tests/tests/unit/test_domain_stack_configuration.py`), the secret
  overlays the seller's token and the mediation double's fixture the dispute
  authority's token (`scripts/tests/test_committed_stack_values.py`), and the
  runner profiles the accounts, tokens, control token, identity and fee
  (`tests/integration/test_lane_env.py`),
  each test holding the copy to the fixture. `scripts/lane_env.py` prints the two
  values read at run time: `seller-account`, which each lane target passes to its
  storefront's payments check, and `seller-token`. Its callers run it with the
  host's `python3 -I`, which must be 3.11 or newer, so it imports only the
  standard library; it is not part of the package the image runs.
- The local Helm release runs the image through the `payments-lane-double`
  subchart (`helm/charts/payments-lane-double`), which `helm/local-values.yaml`
  enables and no release values do, behind a Service named `payments-double` in
  every release, so a namespace runs one double. Its `tls.existingSecret` names a
  `kubernetes.io/tls` Secret to serve instead of the committed leaf. The release's
  storefronts reach it through the values a deployment supplies: their payments
  configuration; a CA bundle ConfigMap holding the lane CA, which each chart
  mounts and names as the configuration's `ca_bundle_path`; and the seller's
  token as `[Settlement.arkhai_payments].api_key` in each storefront's runtime
  Secret's overlay. `make -C helm topology-secrets` creates the ConfigMap and
  writes the token, from these fixtures with `scripts/lane_env.py seller-token`.
  The release's
  values repeat the receipt identity, fee, service URL and the accounts, and
  `helm/tests/test_release_topology.py` holds them to these fixtures, and the
  registry's recommended authority to the mediation double's. It serves no
  payment scenario there; each storefront's `helm test`
  payments check reads the seller's balance.
- `make test` (here) runs the unit and application integration suite: the kit's real
  `PaymentsClient` and the controls' typed client against the app through an
  in-process transport, with an injected wall clock, and the transport faults
  against the app served by uvicorn on loopback, since only a real server
  abandons a response. From the repository root,
  `make test-payments-lane-double` runs it, as part of `make test` and the Tests
  workflow's matrix.
- `make build-payments-lane-double` in `tools/` builds the image from the
  repository wheelhouse and this project's committed lock; the root's
  `make build-tools`, part of `make build-dev` and each lane's `build-e2e-*`
  target, builds it.
