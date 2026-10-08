# VM payments first use

`payment_smoke.py` uses the real buyer approval stage, seller receipt verifier,
SQLite evidence/progress records, and signed seller HTTP settlement route. The
payments HTTP service and VM delivery are controlled in-process. It creates and
removes its own temporary database; no account credentials or running services
are needed.

From the repository root:

```sh
make dist
make -C domains/vms/storefront reinit
uv run --project domains/vms/storefront --locked --find-links .dist \
  --with "$PWD/.dist/arkhai_vms_buyer-0.7.0-py3-none-any.whl" \
  --with "$PWD/.dist/arkhai_kit_arkhai_payments-0.2.0-py3-none-any.whl" \
  python domains/vms/storefront/examples/payment_smoke.py
```

The observed sequence is `pending` with zero deliveries before approval,
`provisioning` after approval, and `ready` with one delivery on retry. This is a
local diagnostic, not a live ledger or VM acceptance run. For the real payments
service setup see [`kit/arkhai-payments/README.md`](../../../../kit/arkhai-payments/README.md#local-first-use).

## Buyer and seller configuration

Both roles enable `arkhai.payments.v1` in the strict settlement root and pin the
same trusted service policy. The service URL comes from operator configuration,
never from the listing. For example, in each role's public TOML:

```toml
[Settlement]
schema_version = 1
priority = ["arkhai.payments.v1", "alkahest.v1"]

[Settlement.arkhai_payments]
enabled = true
service_url = "https://payments.example.com"
fee_bps = 200
dispute_authority = "00000000-0000-4000-8000-000000000013"
api_key_env = "ARKHAI_PAYMENTS_API_KEY"

[Settlement.arkhai_payments.service_identity]
scheme = "ed25519"
identifier = "<trusted-service-public-identity>"
```

Set the named environment variable to that role owner's WorkOS user-scoped API
key. For loopback development only, replace `api_key_env` with
`development_auth = true` and use the development service origin. Never put an
API key value in TOML.

The VM buyer additionally supplies its Arkhai account, separate from its
marketplace signing identity:

```toml
[vms]
payer_account = "00000000-0000-4000-8000-000000000011"
```

It adds this account to the selected payment option's `SettlementSelection.params`;
the accepted Agreement carries it in `settlement_params`. The seller publishes a
payment option with its payee account, asset, hold window, and deposit policy:

```text
mechanism=arkhai.payments.v1 asset=USD/2 rate=1/hour arkhai_payments.payee_account=00000000-0000-4000-8000-000000000012 arkhai_payments.window=P7D arkhai_payments.deposit_agreement=true
```

Publication rates use display units; the payment option's wire rate and accepted
amount are integer minor units (`USD/2`: 100 minor units per dollar). Explicit VM
buyer negotiation prices for payments are minor units. Choose payment listings
with `--settlement 'mechanism=arkhai.payments.v1 asset=USD/2'`; an Alkahest-only
selection keeps the EVM escrow path.

The seller's `/api/v1/settle/<negotiation_id>` takes only `negotiation_id` and the
authenticated `buyer_principal` for payments. It derives the transaction ID from
the accepted mandate, waits for a matching signed receipt, and then invokes the
existing selected-site VM fulfillment path. Retried approval uses the same
mandate; retried settlement resumes the same durable physical request. VM
progress uses the existing local progress table without a chain, escrow address,
settlement plan, or settlement obligation.
