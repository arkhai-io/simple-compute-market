## Why

Hosted settlement 0.3.0 declares `payer-direct-instrument-setup.v1`: one endpoint that
lets a payer finish a bank-funded instrument setup by submitting the microdeposit
evidence their own bank showed them. Nothing on the marketplace side can reach it.
The payer facade has `start_setup` and `setup_status` and no verification operation,
so `us_bank_transfer.v1` has no saved-instrument path at all and the bank profile that
does have one is bound to a browser for a flow the provider settles by microdeposit.

The same run cannot even get that far. The consumer half writes down which hosted
release it expects — `expected_api_version = "0.2.1"`, `expected_schema_version = 5`,
and a seventeen-entry capability list — in `e2e-tests/config/hosted-storefront.toml`
and `hosted-buyer.toml`, and repeats the version in four Makefiles. This is the defect
`build-hosted-producer-locally` removed from the producer half, one layer out: a
consumer that names one release in its own source cannot admit the next one, and
reports a genuine contract mismatch as a config edit that was forgotten. A run that
binds a correct 0.3.0 authority stops at the marketplace's own check.

## What Changes

- The consumer's expected hosted contract — API version, schema version, and required
  capabilities — is rendered from the release the run bound, alongside the authority
  identity, manifest digest, base URL, and funding profile the renderers already fill
  in. A disagreement still fails closed; only the source of the expectation moves.
- The hosted release artifacts the build names — trust config, client wheel, OpenAPI,
  conformance, and migration filenames — are derived from the bound release version
  rather than spelled `0.2.1` in `Makefile`, `domains/vms/storefront/Makefile`, and
  `kit/hosted-settlement/Makefile`.
- `HostedPayerFacade` gains `verify_setup`, carrying payer-held microdeposit amounts or
  a descriptor code against one pending setup; the payer CLI gains the matching command;
  the setup projection carries verification-pending readiness.
- A `saved_instrument` lane completes a bank-funded setup by submitting that evidence
  when the bound release declares `payer-direct-instrument-setup.v1`, and keeps the
  existing browser path when it does not. `us_bank_transfer.v1` gains a saved-instrument
  path it does not have today.
- **BREAKING (packaging).** `arkhai-hosted-settlement-client` moves from `==0.2.1` to
  `==0.3.0` in `kit/hosted-settlement`, `domains/bare_metal/storefront`, and
  `domains/bare_metal/buyer`, with affected lockfiles refreshed. Consuming a capability
  means depending on the release that declares it.

## Capabilities

### New Capabilities

None. Every behavior here belongs to a capability that already exists.

### Modified Capabilities

- `settlement-configuration`: the expanded-release pins a hosted consumer asserts are
  read from the bound release rather than written into consumer configuration; buyer
  payer readiness admits a setup awaiting payer-held verification; a new requirement
  covers submitting that verification as a consumer operation carrying no provider
  material.
- `settlement-servicing`: the hosted payer consumer reaches setup verification through
  the pinned client's own interface, adding it to the behavior the marketplace must not
  reimplement.
- `test-compatibility`: the Stripe-backed hosted evidence lane completes a bank-funded
  saved-instrument setup without a browser when the bound release declares the
  capability.

## Impact

- **Code**: `kit/hosted-settlement/src/market_hosted_settlement/payer.py`,
  `payer_cli.py`; `e2e-tests/src/hosted_real_stripe/runtime.py` (config renderers),
  `driver.py` (`_validate_payer_fixture`, saved-instrument stage), `gates.py`
  (capability requirements per scenario); `e2e-tests/tests/e2e/roles/scenarios/vms/hosted/`
  lifecycle bridge.
- **Configuration**: `e2e-tests/config/hosted-storefront.toml`,
  `e2e-tests/config/hosted-buyer.toml`.
- **Build**: `Makefile`, `domains/vms/storefront/Makefile`,
  `kit/hosted-settlement/Makefile`.
- **Dependencies**: three `pyproject.toml` pins and the `uv.lock` files that resolve
  them; the wheelhouse review test that asserts the pinned version.
- **Deferred and externally blocked.** The protected lane cannot exercise this
  capability until hosted settlement 0.3.0 is published: it requires a signed manifest
  and no signed 0.3.0 release exists. This change invents no trust config to stand in
  for one. The development lane delivered by `build-hosted-producer-locally` — a
  locally built producer bound by `--local-hosted-image` and `--hosted-artifacts` —
  runs it end to end today, which is what that change existed to make possible.

### Non-Goals

- No signed 0.3.0 trust config is written by hand or generated locally.
- No weakening of protected evidence, protected inputs, or fail-closed behavior.
- Safety gates — test-mode-only credentials, refusal of live objects, loopback-only
  webhook delivery, connected-account readiness — stay unconditional in every mode.
- No range-loosening of the client pin; the consumer depends on one exact version.
- No change to how the marketplace persists payer state: instrument and setup
  references stay opaque and operation-scoped.
