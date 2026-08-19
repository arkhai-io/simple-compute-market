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
| `stripe_restricted_key` | Test-mode provider key. Release v0.2.1 requires an `sk_test_` key — it validates the prefix against its own Stripe mode and refuses a restricted `rk_test_` key. A live key is refused downstream. |
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

### `authority_env` minimum

The released authority reads its whole configuration from the environment and
exits on the first required setting it cannot find. The broker owns the half
that is a secret or is the environment's own identity:

| Key | Meaning |
|---|---|
| `HOSTED_SETTLEMENT_AUTHORITY_ID` | The authority's own identifier. |
| `HOSTED_SETTLEMENT_AUTHORITY_IDENTITY_SCHEME` | `eip191` or `ed25519`. |
| `HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY` | Its signing credential, which **must** be independent of the release authority's key — the harness rejects reuse. |
| `HOSTED_SETTLEMENT_ENCRYPTION_KEYS` | Comma-separated Fernet keys (32 bytes, urlsafe base64) encrypting stored provider data. The first encrypts; the rest decrypt, so a rotation lists the outgoing key too. |

The harness supplies the rest itself, and its values win over the payload's,
because they are fixed by the topology it builds rather than by whoever issued
the credentials: `HOSTED_SETTLEMENT_ENVIRONMENT` (the environment the run pins
everywhere else), `HOSTED_SETTLEMENT_DATABASE_PATH` (inside the Compose named
volume), `HOSTED_SETTLEMENT_STOREFRONT_CALLERS` (the storefront the harness
itself built, without which the authority refuses every escrow that storefront
opens), and the checkout and account-link callback allowlists, which point at
the loopback storefront and must not repeat a URL between them.

### Identities the topology already pins

Five of the credentials are not free. `compose.vms-fiat.yml`,
`e2e-tests/config/hosted-storefront.toml`, and
`e2e-tests/config/hosted-buyer.toml` each pin the public half of the registry-A,
registry-B, storefront, provisioning, and administrator identities, and a
service refuses to start when the credential it is handed derives a different
one. A broker therefore returns the keys behind exactly those committed
identities, in the schemes they declare (`ed25519` for all five).

Local assembly cannot do that — it has no committed private keys — so it
generates the five and rewrites every pin: both configuration files, and the
Compose overlay through the `VMS_*_IDENTITY_IDENTIFIER` variables whose defaults
are the committed values.

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
