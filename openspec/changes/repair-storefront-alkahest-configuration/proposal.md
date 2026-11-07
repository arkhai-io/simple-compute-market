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

The three configuration gaps above:

- Supply `STOREFRONT_WALLET__PRIVATE_KEY` for both VM storefronts under the
  name the service reads, in the file that already carries development
  identities.
- Bind-mount the Alkahest address configuration to a fixed path and point both
  path settings at it, following the convention the API-credits storefront
  already uses.

## Scope as implemented

This section is the honest record of what the change became, and it is much
larger than the three gaps above. That growth was accepted deliberately rather
than drifted into, and recording it is owed under this repository's rule that
a discovery changing the acceptance boundary updates the proposal.

Fixing settlement did what the original Impact predicted: it let the e2e suite
reach deal stages that had never executed. Every stage it reached was a first
execution, and each one surfaced production defects that had been latent
behind the startup failure. The change then followed them, because a stack
that settles was the goal and each defect stood between the suite and that
goal. The task file is a sequential record of that campaign, sections `3b`
through `3ax`.

The production work, by cluster:

- **Signed authority boundaries.** The registry's response-body
  authentication, the remaining authenticated-read drift, and then the
  API-credits site authority end to end: the gated application's middleware
  and the storefront's credits client both sign, the service verifies, and
  signed authentication is enabled on every credits route. Identity
  resolution moved to the kit that owns it, with the credentials it needs.
- **Wire representation.** Uint256 amounts do not survive canonical JSON as
  integers; negotiated values are now decimal strings on the wire, which
  implements an existing permanent requirement rather than inventing one.
  Fixtures were repriced at the asset's real decimals, which reached further
  and exposed more seams.
- **Lifecycle control.** The pause and advance controls were restored and
  then extended: the capacity-events loop and the reconciliation loop became
  steppable, the reconciliation loop moved to the kit that owns it, and the
  fifth loop was gated through the kit rather than around it.
- **Negotiation and settlement paths.** Buyer identity on the negotiation
  path, fan-in conversion, `resource_id`'s meaning for a pool, pool-declared
  delivery, the SSH key as a negotiated term, and the settlement mechanism
  the buyer CLIs had never had enabled.
- **Scenario surface.** Deleted stages restored, faults in the restored
  stages fixed, and twin scenarios swept so a stage fix reached every
  scenario carrying that stage.

## What does not change

The three gaps in `Why` are configuration, and the code reads the values it
always intended to read. This section previously said "No production Python"
of the change as a whole; that was true of those three gaps and is not true of
the change, and the claim is withdrawn rather than qualified.

The multi-storefront Alice path is not delivered here: the provisioning
topology trusts one storefront principal, and
`repair-multi-storefront-scenario` owns that limitation. The TypeScript and
Rust API-credit middlewares do not sign and cannot authenticate to a credits
service with signed authentication enabled;
`sign-multi-language-credits-middleware` owns that, validation-first. Neither
is proven by this change's green run and neither should be described as such.

## Impact

Settlement becomes ready, so listings publish and the on-chain escrow phases
run. The end-to-end pipeline now reports a full green run across the VM deal
paths and the API-credits buy, use and top-up flow — the first time either
has executed end to end.

The original Impact said to expect genuine deal-stage results rather than a
green run. That was right, and the distance between those two states is the
production work catalogued above.

## Permanent documentation impact

- [x] No permanent documentation change

### Knowledge to promote

None. The API-credits storefront already demonstrates the mount convention and
the `@str` requirement is already documented where it is used. The durable
question this raises — that compose configuration is assembled differently from
the Helm charts and less coherently — is recorded as deferred work rather than
promoted, because this change deliberately does not resolve it.
