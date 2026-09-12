# repair-storefront-alkahest-configuration

## Why

The VM storefronts cannot settle. Alkahest is their only enabled settlement
mechanism, it never becomes ready, and settlement composition refuses any
listing once its sole mechanism is suppressed. Ten of the eleven failures
remaining after `repair-e2e-fixture-drift` are this one fault, and it has been
latent since mid-August behind the startup failure and then behind fixture
errors.

Three configuration gaps, each independently sufficient to break settlement:

1. **The storefront never receives its EVM credential.** The wallet env files
   supply `AGENT_PRIV_KEY`, which `kit/config`'s buyer-side loader resolves.
   The storefront resolves `wallet.private_key` through Dynaconf under the
   `STOREFRONT` prefix, so that name never reaches it, `build_alkahest_clients`
   reports `wallet.private_key` missing and returns no clients, and
   `checks.alkahest` reports `unconfigured`.
2. **`Settlement.alkahest.address_config_path` points into a source tree the
   image does not contain.** It names `/app/src/market_storefront/data/...`,
   while the storefront Dockerfile states that repository source trees are
   never copied into the image. The file cannot be loaded, so readiness carries
   `alkahest.address_config_invalid`.
3. **`Chains.anvil` declares no `alkahest_address_config_path`.** The clients
   are built per chain from that key, so it would remain unset even after the
   first two gaps close.

## What changes

- Supply `STOREFRONT_WALLET__PRIVATE_KEY` for both VM storefronts under the
  name the service reads, in the file that already carries development
  identities.
- Bind-mount the Alkahest address configuration to a fixed path and point both
  path settings at it, following the convention the API-credits storefront
  already uses.

## What does not change

No production Python. All three gaps are configuration; the code reads the
values it always intended to read.

## Impact

Settlement becomes ready, so listings publish and the on-chain escrow phases
run for the first time since mid-August. Expect the e2e suite to surface
genuine deal-stage results that have never been observed, not a green run.

## Permanent documentation impact

- [x] No permanent documentation change

### Knowledge to promote

None. The API-credits storefront already demonstrates the mount convention and
the `@str` requirement is already documented where it is used. The durable
question this raises — that compose configuration is assembled differently from
the Helm charts and less coherently — is recorded as deferred work rather than
promoted, because this change deliberately does not resolve it.
