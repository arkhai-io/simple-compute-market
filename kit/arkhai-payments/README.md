# Arkhai payments client

`arkhai-kit-arkhai-payments` is a stateless Python client for the external
`arkhai.payments.v1` HTTP service. The payments service owns the ledger,
credential validation, fee policy, hold release, disputes, and cash operations;
this kit persists no settlement state and runs no background worker.

The JSON Schema and test vectors are vendored from the recorded upstream
commit in [`schema/SOURCE.md`](schema/SOURCE.md). `src/market_arkhai_payments/models.py`
is generated from that schema with `python scripts/generate_models.py`.

## Seller option and mandate

`PaymentsOptionParams` is the public listing `params` object:

```python
from market_arkhai_payments import PaymentsOptionParams

option = PaymentsOptionParams(
    payee_account="00000000-0000-4000-8000-000000000012",
    asset="USD/2",
    window="P7D",
    deposit_agreement=True,
)
```

The payments service URL is operator configuration on `PaymentsClient`, not a
listing field. A listing-selected URL could redirect the buyer's bearer key to
an attacker. Keep `fee_bps` and `dispute_authority` in the caller's trusted
service policy: the HTTP service validates both against its own current
configuration.

`MandatePolicy` carries the accepted Agreement's payment facts without defining
or parsing a shared Agreement model. `derive_mandate(agreement_json, policy)`
commits to the exact JSON object using RFC 8785, creates one `once` part, and
returns a generated `Mandate`. The hold is the time from acceptance to start,
plus the service duration and the option window. The fixed nonce is
`arkhai.payments.v1`; repeated derivation for the same inputs gives the same
transaction ID. Mandate approval expires at `accepted_at + window`.

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

## Testing with the kit

`market_arkhai_payments.fixtures` provides `build_signed_receipt`, which signs a
receipt for a given mandate with an injected signer using the verifier's own
framing, and `FakePaymentsClient`, an in-memory stand-in for `PaymentsClient`
that tests inject through a stage's or approval's `client_for_owner`. The
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
The vector runner is also available as `python scripts/check_vectors.py`.

## Local first use

The committed `examples/local_e2e.py` exercises the `PaymentsClient` primitives
(approval, buyer and seller polling, Agreement deposit, receipt verification,
and reverse) against the service's local development authenticator, using a
minimal deal object rather than a market Agreement. Start the payments repo's checkout-
owned ledger with `FORMANCE_PORT=3168 bun run ledger:local`, then start its HTTP
service from that repository in another shell with `bun run service` and
`NODE_ENV=development`, `FORMANCE_PORT=3168`, `PAYMENTS_PORT=3180`,
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
