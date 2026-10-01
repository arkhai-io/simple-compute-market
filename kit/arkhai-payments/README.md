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

The buyer constructs the same `MandatePolicy` from its accepted Agreement and
selected option, calls `check(mandate, agreement_json, policy)`, then approves:

```python
from market_arkhai_payments import PaymentsClient, check

check(mandate, agreement_json, buyer_policy)
with PaymentsClient(service_url, api_key=workos_user_api_key) as client:
    receipt = client.approve(
        mandate,
        agreement=agreement_json if attach_agreement else None,
    )
```

Approval retries send the identical mandate and therefore retain the same
transaction identity. For a local development service, use the explicit
`development_account` authentication option; it sends `X-Account-ID` and is
not available outside the service's development authenticator.

## Settlement configuration integration

`create_arkhai_payments_registration()` provides a typed mechanism registration for
publication input, public option construction, and buyer-side option filtering.
It intentionally has no conditional-escrow client, accepted-obligation builder, or
settlement verifier: payment approval and receipt servicing remain in the domain
stage that owns the accepted Agreement.

`ArkhaiPaymentsConfig` keeps the service origin, pinned Ed25519 receipt identity,
fee policy, dispute authority, API-key environment-variable name, and local
development-auth switch in trusted role configuration. The API key value is read
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

```python
from market_arkhai_payments import PaymentsClient, verify_receipt

with PaymentsClient(service_url, api_key=workos_user_api_key) as client:
    snapshot = client.poll(transaction_id(mandate), timeout=60)
    signed_receipt = snapshot.snapshot.receipt
    if not verify_receipt(
        signed_receipt,
        trusted_service_identity,
        mandate=mandate,
        agreement_json=agreement_json,
    ):
        raise ValueError("payments receipt does not prove this Agreement")
    client.ensure_agreement_attached(
        transaction_id(mandate), agreement_json, option
    )
    # Provision only after the verified receipt above.
    client.reverse(transaction_id(mandate))
```

`get_transaction` reads the signed current snapshot. `poll` retries only the
not-yet-created transaction response; it stores no cursor or state. The
receipt verifier checks the pinned Ed25519 service identity, the
`arkhai.payments.receipt.v1` framing via `market_identity`, and the mandate's
transaction ID and Agreement deal hash. `reverse` uses a deterministic
transaction-scoped idempotency key, so an exact retry cannot create a second
reverse event.

## Checks

From this directory:

```sh
make test
make build
```

`make test` checks static typing, unit tests for settlement configuration and
registration, and the upstream mandate, receipt, attachment, and approval vectors.
The vector runner is also available as `python scripts/check_vectors.py`.

## Local first use

The committed `examples/local_e2e.py` runs approval, buyer and seller polling,
seller-side Agreement deposit, receipt verification, and reverse against the
service's local development authenticator. Start the payments repo's checkout-
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
