# Arkhai payments client

`arkhai-kit-arkhai-payments` is a stateless Python client for the external
`arkhai.payments.v1` HTTP service. The payments service owns the ledger,
credential validation, fee policy, hold release and cash operations;
this kit persists no settlement state and runs no background worker.

The standalone JSON Schema and current producer conformance vectors are vendored
by content hash. Historical vectors remain separate raw signing and hashing
regressions. [`schema/SOURCE.md`](schema/SOURCE.md) records publication hashes,
the neutral schema identifier, generation checks and evidence limits.
`src/market_arkhai_payments/models.py` is generated with the pinned generator using
`python scripts/generate_models.py`.

Models accept effective part ends and zero gross snapshots and receipts while
retaining unknown-field refusal and numeric/string bounds. Required nullable
maximum hold extensions remain present as null; absent optional ends stay omitted
through approval serialization, canonical identities and signature verification.
Exact service compatibility is checked before consumer deployment; local producer
vectors do not prove provider funding or physical delivery.

## Seller option and mandate

`PaymentsOptionParams` validates the payment-owned fields stored flat beside
`schema = "arkhai.payments.v1"` in an option's `settlement` envelope. Its asset
appears only in the option's separate `price`, with its commercial rates:

```python
from market_arkhai_payments import PaymentsOptionParams

option = PaymentsOptionParams(
    payee_account="00000000-0000-4000-8000-000000000012",
    window="P7D",
    deposit_agreement=True,
)
```

The payments service URL is operator configuration on `PaymentsClient`, not a
listing field. A listing-selected URL could redirect the buyer's bearer key to
an attacker. Keep `fee_bps` in the caller's trusted service policy. The dispute
authority comes from the selected option's `lifecycle.adjudication.dispute`;
`[Settlement.arkhai_payments].dispute_authority` is rejected with a diagnostic
naming root `[[Dispute]]` preferences. See
[dispute authority preferences](../../docs/development/DEPLOYMENT_AND_CONFIG.md#dispute-authority-preferences)
for local preferences, registry recommendations and identity-bound credentials.
Authorities are explicit per-part permissions; the service has no implicit
privileged dispute account.

Receipts carry a signed `livemode`, true only from a live payments service.
`verify_receipt` takes the mode the caller expects, and `ArkhaiPaymentsConfig.livemode`
(default `false`) supplies it for the buyer and seller stages. Set
`livemode = true` against a live service; a receipt from the other mode is refused.

`MandatePolicy` carries the accepted Agreement's payment facts without defining
or parsing a shared Agreement model. `derive_mandate(agreement_json, policy)`
commits to the exact JSON object using RFC 8785, creates one `once` part, and
returns a generated `Mandate`. The generated models also carry the contract's
`rate` parts; the once-only builder does not derive them. Every part carries its
own authorities and hold-extension cap. A once-only mandate has no start or stop
permission, and preserves the seller and accepted option's dispute authority as reverse
authorities. Only the dispute authority can extend or lift a hold. Each once
part encodes the absolute Agreement term end and holds until that end plus
`lifecycle.adjudication.dispute_window_seconds`, with the agreed nullable
`case_hold_max_seconds` cap. Either part's `maxHoldExtension` is required and may be
null; the models are generated so, and every wire form the kit produces keeps the
null (see [`schema/SOURCE.md`](schema/SOURCE.md#required-nullable-durations-and-optional-values)). Fractional ends round up to the wire's whole second;
late approval clamps the effective end at the authority without changing the
mandate. `derive_part_terms` also supplies setup ends and rate permissions: only
entitlements grant party stops, preserving notice and treatment, while the
dispute authority receives a zero-notice chosen-treatment entry. Bonds and
once-only early termination refuse. The fixed nonce is `arkhai.payments.v1`;
repeated derivation gives the same transaction ID. Mandate approval expires at
`floor(accepted_at) + window`, independently of the dispute window.

Domains do not assemble mandates themselves. The seller returns
`PaymentSellerStage.settlement_data(agreement)`, one `{mandate, transaction_id}`
shape, and the buyer approves through `PaymentApproval`, which re-derives the
mandate from the exact Agreement bytes under the buyer's own trusted policy,
checks the seller's transaction ID and the advertised option, and attaches the
Agreement only when the buyer's `attach_agreement` setting is on:

```python
from market_arkhai_payments import PaymentApproval

transaction = PaymentApproval(config, payer_account).approve(
    agreement_bytes,
    settlement_data,
)
```

Approval retries send the identical mandate and therefore retain the same
transaction identity. For a local development service, use the explicit
`development_account` authentication option; it sends `X-Account-ID` and is
not available outside the service's development authenticator.

## Settlement configuration integration

`create_arkhai_payments_registration()` provides a typed mechanism registration for
publication input, public option construction, and buyer-side option filtering.
It has no conditional-escrow client, accepted-obligation builder, or settlement
verifier: Arkhai payments settles from the accepted Agreement alone. The kit's
`PaymentSellerStage` and `PaymentApproval` carry the mechanism; each domain
keeps its HTTP binding, delivery, and recovery. A publication clause supplies
`dispute_window_seconds`, optional `case_hold_max_seconds` (omission is unbounded),
and `delivery_deadline_seconds` for compute. Compositions supply their offered
`dispute_authorities` and installed `dispute_interfaces`; the first authority
advertising payments is selected, its minima are checked, and adjudication is
included in the option hash. An empty list builds no hosted option. The payments
kit names no concrete dispute interface.

`ArkhaiPaymentsConfig` keeps the service origin, pinned Ed25519 receipt identity,
fee policy, optional receipt identity history, the API key, an optional CA bundle,
the local development-auth switch, and the buyer-only `attach_agreement` setting
(off by default; a seller configuration that sets it fails preflight) in trusted
role configuration. The key takes one of two forms, which are mutually exclusive
and each exclusive with `development_auth`:

- `api_key`, the key itself, a secret setting a service states in its secret
  overlay (a storefront's `storefront.secrets.toml`). It is a `SecretStr`, so it
  never appears in the model's `repr` or a dump, and it is marked secret, so a
  storefront chart's generated values schema refuses it in public `config`.
- `api_key_env`, the name of the environment variable a buyer's credential
  provider reads the key from.

`resolve_payments_api_key(config)` is the one resolution of the key: `api_key`
when stated, otherwise the variable `api_key_env` names, read only when it is
called. Client construction, readiness and the access check all use it, and it
raises `ArkhaiPaymentsConfigurationError` naming the form that is missing or
unavailable, never the key. `ca_bundle_path` names a PEM bundle the payments
client verifies the service against instead of the default trust store, for that
client alone: no other client's trust, and no process setting such as
`SSL_CERT_FILE`, changes. `payments_client_for_owner(config, owner_account)`
validates the owner account and uses it for loopback development authentication;
normal service calls use the resolved key, and the client is given the configured
bundle as `PaymentsClient(..., ca_bundle=...)`:

```python
from market_arkhai_payments import create_arkhai_payments_registration
from market_arkhai_payments import payments_client_for_owner

registration = create_arkhai_payments_registration()
with payments_client_for_owner(config, owner_account) as client:
    snapshot = client.get_transaction(transaction_id)
```

`client.get_balance(account)` reads `GET /balances/{account}` and returns the
generated `Balance`: spendable `available` by asset, from which outgoing escrow
has already left, and the `held` money the account is owed as payee. The service
answers only for the credential's own account and refuses any other with 403
`caller_not_authorized`, which the client raises as a `PaymentsAPIError`.

Readiness never contacts the service, so `check_payments_access(section,
account)` is how a role proves its payments access: it builds the client exactly
as `payments_client_for_owner` does, from the role's own configuration and
environment, reads the account's balance, and returns a `PaymentsAccessOutcome`.
A failure names its step — `configuration` (no section, an invalid or disabled
one, no `service_url`, neither key form, or a `ca_bundle_path` that is missing,
unreadable or malformed, reported before any request), `credential` (the key
variable unset, empty or not a single line), `transport` (unreachable, an
untrusted certificate, a process `SSL_CERT_FILE` that cannot be loaded, or an
answer outside the contract), or `refused` with the service's code.
`outcome.json_line()` renders it as one JSON line that never contains the key or
a bundle's path:

```console
{"check": "payments", "outcome": "ok", "service_url": "https://payments.example",
 "account": "00000000-0000-4000-8000-000000000012", "assets": ["USD/6"], "held": 0}
```

A role's command runs it through `check_configured_payments_access(read_section,
account)`, giving it the function that reads the section from the configuration
the role serves with: a configuration that cannot be read at all is the
`configuration` step too, its message withheld since it may quote a value. Each
storefront CLI's `check-payments --account <id>` is this call.

## Seller servicing

`PaymentSellerStage` requires the full trusted policy at construction, so an
enabled but incomplete configuration fails at startup. Each receipt check is
one read of the transaction; the buyer's settlement retries are the polling
loop. Domains map the typed outcomes to their responses:

```python
from market_arkhai_payments import (
    PaymentSellerStage,
    ReceiptInvalid,
    ReceiptPending,
    ReceiptUnavailable,
)

stage = PaymentSellerStage(config)
agreement, data = stage.accepted(agreement_bytes, stored_settlement_data)
outcome = await stage.check_receipt(agreement, data)
if isinstance(outcome, ReceiptPending):
    ...  # retryable: no payment yet
elif isinstance(outcome, ReceiptUnavailable):
    ...  # retryable: service unreachable or outside its contract
elif isinstance(outcome, ReceiptInvalid):
    ...  # refuse without recording state: the receipt does not prove the Agreement
else:
    await stage.deposit_if_advertised(agreement, data)  # before any delivery
    ...  # deliver
```

The verifier checks the pinned Ed25519 service identity, the
`arkhai.payments.receipt.v1` framing via `market_identity`, and the mandate's
transaction ID and Agreement deal hash. Receipt-only checks trust the
independently signed receipt inside `get_transaction`. Lifecycle observations
and refunds additionally require verification of the snapshot's own proof
before consuming its balances, event history or extensions.

The normal deal flow never refunds. `stage.reverse(agreement, data)` serves
seller-initiated refunds only: it re-checks the receipt and signed authority
state, then translates each remaining held part into a voluntary lifecycle
`reverse {part, amount}` with its own stable operation key. It reports `Refunded`,
`NotPaid`, `NothingToReverse`, `RefundUnavailable` or `RefundBlocked`. A lost
response is recovered by verified read and same-key retry. It does not send an
exceptional-end claim or compute a dispute remedy. `stage.payment_adapter`
exposes the same payee adapter for lifecycle composition; its verifier factory
can be injected for key rotation.

`reconcile_accepted_payments` still advances every domain-supplied accepted
candidate, including a buyer that approved and never sent commit. The domain's
idempotent settle callback decides whether to serve or refund; a crash or one
candidate failure does not discard the remaining candidates.

## Once payment lifecycle

`market_arkhai_payments.adapter.PaymentAdapter` binds one exact accepted
Agreement and its stored `PaymentSettlementData`. It supports voluntary
`reverse` commands with exactly `payload={"part": "0", "amount": "100"}`:
part references and positive minor-unit amounts are canonical decimal strings.
Only the part's reverse authorities may send them. Rate commands, supplied
`at`, and exceptional-end fields refuse before I/O. Exceptional seller ends
belong to the dispute adapter, not to this payment adapter.

Construction takes the acting account, `client_for_owner`, a required
`verify_snapshot(signed, minimum_sequence) -> bool`, and an optional durable
`minimum_sequence` floor. The composition owns key rotation and cursor storage;
`pinned_snapshot_verifier(agreement, data, config)` binds the current single
receipt identity for deployments without key rotation. Reads reject unverified,
cross-commitment, incomplete or regressing authority records. They return all
per-part events for the seller watch to replay, and open extensions independently
by ref and case. Partial refunds never imply a delivery end. Once-only delivery
authorization verifies commitment evidence; billing start makes no financial
operation.

Every part request uses `OperationKeys.part_event`. Submit reads before sending
to recover an earlier lost answer and reject changed content; after sending it
reads again, because an unsigned POST response does not prove the outcome.
An unreachable or unverifiable post-write read is `unknown`, resolved by read
and an identical-key retry, never by assuming the money moved or did not move.
Callers use the foundation's durable operation store before submit; the adapter
keeps no ledger, cursor store or daemon.

From the repository root, `make dist && make -C kit/arkhai-payments first-use`
starts an invocation-owned fixture and demonstrates a lost reverse response,
signed-read recovery and a same-key replay, plus observation-only scripted case
effects and overlapping extensions. No service, secrets or network are needed.

## Testing with the kit

`market_arkhai_payments.fixtures` provides `build_signed_receipt`, which signs a
receipt for a given mandate with an injected signer using the verifier's own
framing, and `FakePaymentsClient`, an in-memory stand-in for `PaymentsClient`
that tests inject through a stage's or approval's `client_for_owner`.
`build_signed_receipt` signs in the `livemode` it is given, default `false`;
the fake's own `livemode` applies only to the receipts it signs on approval,
and a receipt handed to `serve()` keeps the mode it was signed with. So a test
can play a live service against a stage configured for either mode. The
kit's unit suite proves the receipt fixture's framing reproduces the published
vector's message and signature byte for byte, which is why tests never sign receipts any other way.

## Checks

From this directory:

```sh
make test
make build
```

`make test` checks static typing; unit tests for mandate derivation, receipt
verification, client response handling, the seller stage, buyer approval,
settlement configuration, the receipt fixture, and the mandate against a literal
request in the current wire; current producer mandate, receipt, snapshot, event
and attachment conformance; and the historical publication's raw signing and hash
framing, whose obsolete mandates and receipt the current models must refuse.
The vector runner is also available as `uv run python scripts/check_vectors.py`,
which replays the current publication and then checks the historical one, or as
`uv run python -m market_arkhai_payments.fixtures.conformance` for the replay alone.
From the repository root, this builds and drives the installed wheel rather than
an editable/source import (no services, seed files or credentials required):

```sh
make dist && env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 \
  no_proxy=localhost,127.0.0.1 uv run --no-project --find-links .dist \
  --with .dist/arkhai_kit_arkhai_payments-0.3.0-py3-none-any.whl \
  python -m market_arkhai_payments.fixtures.conformance
```
It replays the producer's signed snapshots and both partial-reversal and
lost-response stop-retry scenarios through the shared fixture authority, comparing
the complete signed bytes. This is offline conformance, not HTTP or live evidence.

### Installed contract and authority fixture

`market_arkhai_payments.contracts.get_contract("published")` returns one immutable
selection with `schema_bytes`, `vector_bytes`, `models` and `metadata` (publication
status, schema ID, schema/vector SHA-256). These resources ship in the wheel from
the canonical inputs by `make generate-models`; `check-generated` rejects drift
between those inputs and the packaged bytes. No network or
sibling checkout is required. There is no missing payments capability requiring an
unpublished candidate, so `"proposed"` refuses by name rather than broadening the
published model. Mediation contracts are not payments resources.

`market_arkhai_payments.fixtures.PaymentsAuthority` is the single clock-injected
authority used by `FakePaymentsClient` and available for an HTTP double to wrap.
Inject a signer and integer-second `clock`, explicitly `fund(account, asset,
amount)`, then `approve(mandate, account=payer)` and `submit(transaction,
{account, requestId, event})`. `snapshot(transaction)` signs the published frame.
`balance(account)` first brings every transaction the account is a party to up to
the clock, as a snapshot does, then returns the published `Balance`: the
account's `available` funds, matured earnings net of fee included, and, where it
is the payee, one `held` entry per part and maturity, addressed
`hold:<transaction>:<part>:<releaseAt seconds>`, with a part's lots that have no
maturity yet in one `hold:<transaction>:<part>:until` entry held until `stop` or
`lift`. `FakePaymentsClient.get_balance` serves the same view.
`advance(transaction)` performs due stops, maturity and reservation refill;
reads/commands apply due stops without driving the refill scheduler, matching the
producer's read boundary. The caller owns HTTP, authentication, controls and
mediation composition; the kit imports none of that tooling.

The fixture applies only the permissions encoded in each part: no favourable
stop, notice waiver, seller restitution entry or payer early release is inferred.
It supports notice deadlines, chosen/event and term-end partial-period rules,
funding exhaustion, repeated partial reversals, extension refs, independent lifts
and capped/unbounded holds. Rate earnings are earned at period end or stop;
partial-period prorating rounds down in the payer's favour. A same-key retry returns
the original event even after its notice deadline; changed content refuses before
effects. These are deterministic contract semantics, not external ledger evidence.

`FakePaymentsClient.engine` exposes this same authority. Its convenience approval
and `serve(receipt)` controls seed immutable approvals without exercising admission,
expiry or funding; use the authority directly for those scenarios. Receipt-only
seeding is once-only; use `serve(receipt, mandate=mandate)` (or `engine.load`)
for exact fees and lifecycle terms, including every rate fixture.
Snapshot proofs are real fixture signatures, not placeholders. Default fixture
identities are public deterministic development values and must never be used on
a public network. Production clients and transport/authentication checks are unchanged.

## Local first use

The committed `examples/local_e2e.py` exercises the `PaymentsClient` primitives
(approval, buyer and seller polling, Agreement deposit, receipt verification,
and reverse) against the service's local development authenticator, using a
minimal deal object rather than a market Agreement. Start the payments repo's checkout-
owned ledger with `FORMANCE_PORT=3168 bun run ledger:local`, then start its HTTP
service from that repository in another shell with `bun run service` and
`PAYMENTS_MODE=development`, `FORMANCE_PORT=3168`, `PAYMENTS_PORT=3180`,
`ARKHAI_DISPUTE_AUTHORITY`, `RECEIPT_SIGNING_KEY`, and `DEV_OPERATOR_TOKEN`
set. Both service and client need the same `RECEIPT_SIGNING_KEY`; the operator
funding request and client need the same `DEV_OPERATOR_TOKEN`.

Before running the example, make the payee a ledger party through the service's
development-only operator route. `DEV_OPERATOR_TOKEN` must be set in this shell
to the same value as the service process:

```sh
curl --fail-with-body http://127.0.0.1:3180/operator/test-funds \
  -H "Authorization: Bearer $DEV_OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"account":"00000000-0000-4000-8000-000000000012","asset":"USD/2","amount":"1","requestId":"arkhai-payments-kit-e2e-payee"}'
```

The request ID makes repeating setup idempotent. In the package directory,
build and install the internal identity wheel, then run the example against
that wheel source:

```sh
make reinit
PAYMENTS_URL=http://127.0.0.1:3180 \
uv run --project . --locked --find-links ../../.dist --python 3.12 -- \
  python examples/local_e2e.py
```

The example refuses non-loopback targets. In local development only, it uses
`RECEIPT_SIGNING_KEY` to derive the service's public receipt identity; ordinary
clients pin that public identity from trusted configuration and never need the
service's signing secret. Stop the service, then run
`FORMANCE_PORT=3168 scripts/ledger-local.sh down` from the payments-service
checkout when finished.
