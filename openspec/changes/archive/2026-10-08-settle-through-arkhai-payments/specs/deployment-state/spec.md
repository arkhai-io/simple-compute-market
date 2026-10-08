## ADDED Requirements

### Requirement: Domain payment persistence is role-owned

Storefront databases MUST persist exact Agreement bytes and opaque settlement data in `negotiation_threads`; domain receipt and fulfillment or grant progress MUST stay under that storefront's ordered migrations. The payments service owns transaction, ledger, hold-release, fee, and dispute state. VM and bare metal MUST keep selected-site authority bindings independent of payment trust. API credits MUST keep its registry, credits authority, gated application, storefront, and buyer roles separate.

#### Scenario: Seller restarts after payment approval

- **WHEN** the storefront reloads an accepted payment negotiation
- **THEN** it retrieves the same mandate and transaction ID from its negotiation state and resumes domain progress without migrating a Stripe profile, credential, or operation ID

### Requirement: Marketplace deployment never owns payment-provider state

Marketplace profiles MAY configure payment-service origin, receipt identity, fee/dispute policy, public account inputs, buyer profile path, and credential references. They MUST NOT configure or persist Stripe secrets or provider IDs, bank/card data, webhooks, payment-service database/migrations, ledger reconciliation, or cash-provider recovery.

#### Scenario: Marketplace configuration contains a provider secret

- **WHEN** a profile supplies a Stripe key, webhook secret, or provider account identifier
- **THEN** validation rejects it rather than deploying it to a marketplace workload

## MODIFIED Requirements

### Requirement: Deployment uses one settlement hierarchy

Role TOML, committed defaults, environment overlays, Helm values/schema/templates, Compose, examples, and generated configuration MUST use the same typed `[Settlement]` root and mechanism subsection names. Marketplace deployment MUST keep public identity, wallet/chains, and mechanism trust/policy separate from Secret-injected credentials, and MUST reject payment-provider/admin/webhook secrets or payment-service-owned state.

#### Scenario: Payment-only role starts

- **WHEN** marketplace identity, trusted Arkhai payments consumer policy, and owner-scoped credentials are supplied with Alkahest disabled
- **THEN** the role does not construct a wallet, chain, or RPC client

#### Scenario: Legacy environment variable remains

- **WHEN** startup receives a removed settlement configuration path after cutover
- **THEN** readiness fails with the corresponding new path and migration command rather than applying hidden precedence

### Requirement: Generated configuration has one source of truth

Typed configuration metadata MUST generate role-appropriate init templates, dotted-path
editing validation, environment schema fragments, and reference tables. Generated
outputs MUST be checked for drift in CI and MUST omit secret values and fields not
applicable to the role.

A chart that passes a service's configuration through MUST carry a values-schema
fragment generated from that service's typed configuration models, refusing under the
pass-through configuration every field the models mark secret or not applicable to the
role, and every field a typed section's model does not have, each in every spelling
the service's loader reads, and MUST accept every other typed field in every such
spelling. The fragment MUST NOT carry defaults, MUST NOT require a field's presence,
and MUST NOT constrain settings the service reads untyped. A secret the
service reads without a typed model MUST be declared by the service with the same
secret marker, so the generated fragment refuses it. A section that carries public
identity MUST be declared closed to its public keys, so the generated fragment admits
those keys and refuses every other.

#### Scenario: Mechanism field changes

- **WHEN** a mechanism's typed configuration adds or removes an operator field
- **THEN** drift validation requires the applicable templates, schema, reference
  output, and generated values-schema fragment to change together

#### Scenario: A secret is placed in pass-through configuration

- **WHEN** a storefront agent's configuration values carry a secret-marked setting,
  such as a wallet private key or a registry write token
- **THEN** values-schema validation fails before render, naming the setting
- **AND** no ConfigMap is produced

#### Scenario: Private identity material is placed in pass-through configuration

- **WHEN** a storefront agent's configuration values carry a key under `Identity`,
  at any level, that the public identity declaration does not name
- **THEN** values-schema validation fails before render, naming the key
- **AND** no ConfigMap is produced

#### Scenario: Payer data is placed in pass-through configuration

- **WHEN** a storefront agent's configuration values declare a payer profile,
  payment instrument, payment method, mandate, bank detail, or action URL in a
  settlement section
- **THEN** values-schema validation fails before render, naming the field

#### Scenario: A typed field is spelled differently

- **WHEN** a storefront agent's configuration values spell a typed field
  differently from its model, such as `Settlement.Priority`
- **THEN** values-schema validation accepts it, as the storefront's loader does
- **AND** a secret-marked or retired key spelled differently is still refused,
  naming the key

#### Scenario: A typed section gains a field

- **WHEN** a storefront's settlement mechanism adds a public operator field and the
  fragment is regenerated
- **THEN** the field passes through the chart with no template or hand-written schema
  change

### Requirement: Identity configuration separates public and secret material

Private identity credentials MUST arrive through role-scoped Secret references and MUST NOT enter committed values, ConfigMaps, manifests, run logs, public principal fields, public URLs, or generated evidence. Payment consumer profiles MUST keep provider credentials and bank/card data out of marketplace roles. Owner-scoped API credentials are separate from marketplace signing credentials. Runtime MUST derive the public principal from the credential and compare it with configured public identity before readiness.

#### Scenario: Public identity configuration contains a private credential

- **WHEN** a values file, ConfigMap, release artifact, readiness response, log, or conformance fixture contains private identity material
- **THEN** validation fails and the value is not deployed or published

#### Scenario: Payment credential enters public values

- **WHEN** a public ConfigMap contains the resolved payments API key
- **THEN** validation fails before deployment

#### Scenario: Payments-only storefront is rendered

- **WHEN** a profile enables only Ed25519 marketplace identity and Arkhai payment settlement
- **THEN** Helm/Compose rendering requires the identity Secret reference but no wallet, chain, RPC, deployed-address, or gas configuration

#### Scenario: Identity secret is missing

- **WHEN** a role has a public principal but cannot load matching private credential material
- **THEN** startup fails before serving authenticated routes, publishing, negotiating, or submitting settlement operations

#### Scenario: A service-peer profile is rendered

- **WHEN** a storefront and provisioning authority are configured to trust one another
- **THEN** ordinary configuration contains each exact scheme-tagged public principal and site trust binding, while each role's matching signer credential is supplied only through its own Secret boundary

### Requirement: Identity migrations are coordinated and fail closed

Each owning service MUST migrate its identity-bearing rows through its own ordered migration chain while preserving cross-service opaque IDs and provider-operation identity. Versioned buyer run logs MUST have an explicit migration path. Authorities MUST reject old schema, old signature versions, drift, ambiguous principals, or partially migrated state; production cutover MUST quiesce authenticated mutations until all required authorities and clients report the new identity capability.

#### Scenario: One authority remains on the old signature contract

- **WHEN** deployment readiness detects a registry, storefront, service peer that lacks the pinned identity version
- **THEN** the affected workflow remains unavailable rather than downgrading or submitting a legacy proof

#### Scenario: Migration encounters conflicting owners

- **WHEN** two address-only rows would create an invalid active-principal ownership relation
- **THEN** that service migration rolls back completely and readiness remains false

### Requirement: Marketplace deployment config contains consumer data only

Arkhai payment consumers MUST use `[Settlement.arkhai_payments]` for trusted service origin, Ed25519 receipt identity, fee and dispute policy, and an environment-variable name for the owner's API key. The API key MUST reach only its owning buyer or seller process. Outside loopback the service origin MUST use HTTPS. Public renderings MUST omit resolved credentials and contain no payment authority, provider, database, or worker deployment.

#### Scenario: Payments consumer is rendered

- **WHEN** an operator enables Arkhai payments
- **THEN** only consumer policy and credential references enter marketplace configuration, while the independently operated payments service owns its ledger and provider roles

### Requirement: Packaging preserves provider separation

Marketplace builds MUST install `arkhai-kit-arkhai-payments` from the staged wheelhouse and consume its generated public JSON Schema models. Marketplace packages MUST NOT import payment-service implementation source or include Stripe SDKs or provider credentials. Internal dependency updates MUST rebuild `.dist` and explicitly reinstall changed wheels at reinit.

#### Scenario: Payments kit changes

- **WHEN** a consumer is reinitialized after a payments-kit update
- **THEN** it installs the rebuilt wheel rather than an editable sibling source or stale installed distribution

## REMOVED Requirements

### Requirement: A development run needs no release infrastructure

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: A diagnostic code is readable where the run allows it

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: A hosted run declares its release mode

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: API-credit hosted deployment is wallet-free and authority-separated

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Bare-metal hosted roles remain independently secret-scoped

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Expanded hosted config cutover is explicit and atomic

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Hosted identity release is pinned as one contract

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Hosted test deployment has no alternate provider surfaces

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Hosted test secrets remain role-scoped

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Immutable hosted release consumption

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Manifest-pinned external settlement authority

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Marketplace deployment never owns payer/provider state

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Protected hosted test composition uses the production release

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Stripe test-mode activation fails closed

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: The asserted hosted contract comes from the bound release

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.
