# Hosted protected-run credential payload

The protected Stripe harness does not read stored secrets. It asks a credential
broker for one short-lived payload and consumes only that. The broker is
addressed by the `HOSTED_E2E_CREDENTIAL_BROKER_URL` repository variable and
answers `GET /v1/hosted-stripe-test` authenticated by a GitHub OIDC token.

No implementation of that service exists in this repository. This document
records the payload it must return, because that shape — not the service — is
what the harness depends on. A development run assembles the same payload
locally (`scripts/assemble-hosted-credentials.py`); a broker, when written,
substitutes for that assembly without the harness changing.

## Response

A JSON object. Every value is a string unless noted.

| Key | Meaning |
|---|---|
| `expires_at_unix` | Integer expiry. The workflow requires it to be in the future and no more than an hour away. |
| `stripe_restricted_key` | Test-mode provider key. `sk_test_` or, preferably, a least-privilege `rk_test_`. A live key is refused downstream. |
| `connected_account_id` | The allowlisted `acct_…` the scenario transacts against. |
| `account_ref` | Opaque reference recorded in evidence in place of the account id. |
| `authority_environment` | Name of the authority environment the run targets. |
| `registry_read_token` | Token used for `docker login ghcr.io` to pull the released image. |
| `buyer_identity_credential` | Buyer signing credential. |
| `buyer_identity_scheme` | `eip191` or `ed25519`. |
| `storefront_identity_credential` | Seller storefront signing credential. |
| `admin_identity_credential` | Admin signing credential. |
| `evidence_signer_credential` | Signs the sanitized evidence report. |
| `evidence_signer_scheme` | `eip191` or `ed25519`. |
| `evidence_signer_identifier` | Public identifier the signature must verify against. |
| `registry_a_identity_credential` | First registry's signing credential. |
| `registry_b_identity_credential` | Second registry's signing credential. |
| `provisioning_identity_credential` | Provisioning service signing credential. |
| `registry_admin_api_key` | Registry admin API key. |
| `registry_bootstrap_api_key` | Registry bootstrap API key. |
| `authority_env` | Object of `NAME` → value written verbatim as the hosted authority's base environment file. Keys must match `^[A-Z_][A-Z0-9_]*$` and values must contain no newline. |

## Credential encoding

A credential is the raw private key for its scheme:

- `eip191` — 32 bytes hex-encoded, `0x` prefix accepted.
- `ed25519` — 32 bytes in canonical unpadded base64url.

The harness derives the public identity from the credential, so a payload never
carries both.

## What the harness does with it

`stripe_restricted_key` and `connected_account_id` become `STRIPE_SECRET_KEY`
and `STRIPE_CONNECTED_ACCOUNT_ID`. The identity credentials become
`HOSTED_SETTLEMENT_E2E_*` environment variables and, for the registry,
provisioning, and storefront roles, files referenced by `VMS_*_FILE` variables.
`authority_env` is written to a file passed as `--hosted-service-env-base`, onto
which the harness layers the provider, webhook, and release values it derives
itself.

Everything lands in a private temporary directory and is removed on exit. No
value from this payload belongs in the repository, a log, or an evidence report.
