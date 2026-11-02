# Arkhai payments client

`arkhai-kit-arkhai-payments` is a stateless Python client for the external
`arkhai.payments.v1` HTTP service. The payments service owns the ledger,
credential validation, fee policy, hold release and cash operations;
this kit persists no settlement state and runs no background worker.

The JSON Schema and test vectors are the payments service's published wire
contract, vendored and identified by the content hashes recorded in
[`schema/SOURCE.md`](schema/SOURCE.md). `src/market_arkhai_payments/models.py`
is generated from that schema with `python scripts/generate_models.py`.

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
authorities. The hold is the time from
acceptance to start, plus the service duration and the option window. The fixed
nonce is `arkhai.payments.v1`; repeated derivation for the same inputs gives the
same transaction ID. Mandate approval expires at `accepted_at + window`.

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
    advertised_option=listing_option,
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
keeps its HTTP binding, delivery, and recovery.

`ArkhaiPaymentsConfig` keeps the service origin, pinned Ed25519 receipt identity,
fee policy, dispute authority, API-key environment-variable name, local
development-auth switch, and the buyer-only `attach_agreement` setting (off by
default; a seller configuration that sets it fails preflight) in trusted role
configuration. The API key value is read
only when a client is created. `payments_client_for_owner(config, owner_account)`
validates the owner account and uses it for loopback development authentication;
normal service calls use the configured environment variable:

```python
from market_arkhai_payments import create_arkhai_payments_registration
from market_arkhai_payments import payments_client_for_owner

registration = create_arkhai_payments_registration()
with payments_client_for_owner(config, owner_account) as client:
    snapshot = client.get_transaction(transaction_id)
```

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
transaction ID and Agreement deal hash. `get_transaction` reads the signed
current snapshot; sellers trust only the independently signed receipt inside
it, not the snapshot's own proof.

The normal deal flow never refunds. `stage.reverse(agreement, data)` serves
seller-initiated refunds only: it re-checks the receipt first and reports
`Refunded`, `NotPaid`, `NothingToReverse`, or `RefundUnavailable`. `reverse`
uses a deterministic transaction-scoped idempotency key, so an exact retry
cannot create a second reverse event.

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
kit's unit suite proves the receipt fixture reproduces the published vector
byte for byte, which is why tests never sign receipts any other way.

## Checks

From this directory:

```sh
make test
make build
```

`make test` checks static typing; unit tests for mandate derivation, receipt
verification, client response handling, the seller stage, buyer approval,
settlement configuration, and the receipt fixture; and the upstream mandate,
receipt, attachment, and approval vectors.
The vector runner is also available as `uv run python scripts/check_vectors.py`
or `uv run python -m market_arkhai_payments.fixtures.conformance`.
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
