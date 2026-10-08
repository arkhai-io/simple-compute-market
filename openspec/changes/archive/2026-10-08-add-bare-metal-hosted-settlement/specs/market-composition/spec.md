## ADDED Requirements

### Requirement: Bare-metal hosted adoption is prerequisite-gated

Bare-metal hosted implementation and activation MUST fail closed unless the checkout and permanent current-state contracts contain a runnable bare-metal buyer, runnable storefront composition, trusted selected-site scheduling, durable physical fulfillment/result/recovery/teardown, completed shared domain/storefront composition seams, and the implemented expanded hosted consumer. Planning status, a referenced but absent change, test-only composition, verified-only settlement, fake/no-op fulfillment, or an unpromoted active-change claim MUST NOT satisfy the gate.

#### Scenario: Runnable buyer is absent

- **WHEN** implementation or release qualification checks the bare-metal hosted prerequisites and no shipped buyer package can complete discovery through real access/reclaim
- **THEN** later implementation/activation tasks remain blocked and no placeholder buyer or narrowed acceptance is used

#### Scenario: Active prerequisite reports completed tasks only

- **WHEN** its durable behavior is absent from permanent specs/current code or its required integration evidence is missing
- **THEN** the gate reports that exact unmet contract rather than treating task checkboxes as acceptance

### Requirement: Bare-metal roots compose hosted only through shared seams

After the prerequisite gate passes, runnable bare-metal buyer and storefront roots MUST install Alkahest and `fiat.stripe.v1` through the shared settlement configuration registry, hosted kit/client, identity, buyer transport, storefront route/runtime, and fulfillment contracts. Hosted-only Ed25519 roots MUST start without wallet, chain/RPC, EVM, or Alkahest construction. Bare-metal packages MUST NOT import VM composition, copy hosted wire/signature/action/provider behavior, or create domain-local settlement runtime variants.

#### Scenario: Hosted-only bare-metal stack starts

- **WHEN** exact hosted, identity, site, provisioner, and domain config are valid with Alkahest disabled
- **THEN** buyer/storefront publication, negotiation, authorization, servicing, and physical fulfillment are ready without wallet or chain dependencies

#### Scenario: Both mechanisms are enabled

- **WHEN** one listing publishes valid Alkahest and hosted alternatives
- **THEN** shared exact selection pins one mechanism/profile and recovery never falls back

### Requirement: Bare-metal domain owns physical interpretation only

Shared orchestration MUST remain opaque to bare-metal demand, Physical Resource, site, pool, executor machine, access, lease, and teardown models. The bare-metal domain/composition MUST interpret trusted listing and accepted terms into a provider-neutral fulfillment request and portable public result. Site and provisioning authorities remain independently authoritative; the storefront MUST NOT infer, fabricate, or persist provider outcomes as fulfillment success.

#### Scenario: Shared settlement runtime is inspected

- **WHEN** bare-metal hosted servicing is installed
- **THEN** generic runtime carries opaque domain fulfillment input/reference and imports no bare-metal, site, provisioner, or executor model
