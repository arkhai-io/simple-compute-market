## ADDED Requirements

### Requirement: Expanded hosted config cutover is explicit and atomic

Marketplace config migration MUST replace new-publication `payment_method_types` with ordered exact funding-profile clauses, add buyer authority/environment payer-binding and optional bounded automation references, and pin the expanded signed hosted release capability set. Migration MUST reject ambiguous method/profile, currency/country, authority, or credential placement and MUST be idempotent. Buyer and storefront config, installed client wheel, expected manifest, image/release coordinates, and role Secret references MUST activate or roll back together before new profile publication or purchase authorization.

#### Scenario: Legacy card config is migrated

- **WHEN** an existing seller has one valid card-only hosted clause
- **THEN** migration produces one explicit `card.v1` clause with the same effective rate/currency/account/condition and no public legacy alias

#### Scenario: Partial rollout reaches publication

- **WHEN** storefront config advertises a profile or payer/authorization capability absent from the installed exact client/manifest
- **THEN** preflight fails before new publication or financial mutation and operators restore matching artifacts/config together

### Requirement: Marketplace deployment never owns payer/provider state

Compose, Helm, and bare process profiles MAY configure hosted public authority URL/identity, exact release pins, safe profile policy, public account reference, condition reference, buyer local profile path, and Secret references for marketplace signers. They MUST NOT configure or persist Stripe credentials, provider IDs, Customer/PaymentMethod/mandate/bank/card data, payer/instrument refs in storefront state, webhooks, hosted database/migrations, reconciliation, or provider recovery.

#### Scenario: Helm values contain a Stripe secret

- **WHEN** values or generated ConfigMaps/Secrets include a Stripe key, webhook secret, provider account ID, Customer ID, PaymentMethod ID, or raw setup/payment action
- **THEN** schema/render/package validation fails rather than deploying it to a marketplace workload

## MODIFIED Requirements

### Requirement: Immutable hosted release consumption

Every deployable service MUST be bound to one immutable signed manifest containing exact wheel hashes and versions, image digest, API and schema versions, ordered database migration IDs and checksums, public capability IDs/versions, source commit and repository identity, and build workflow/ref identity. A marketplace hosted consumer MUST additionally pin the exact hosted client wheel/manifest, payer-profile, funding-profile, funding-authorization, action, identity, and conditional-escrow capabilities it consumes, plus the expected hosted image/release identity as an independently recorded coordinate. Deployment and startup MUST fail if any exact value or signature differs; mutable tags and compatible-major substitution are insufficient.

#### Scenario: Consumer expects another funding contract

- **WHEN** a consumer pins a payer profile, funding profile, authorization, action, schema, or client capability absent from the signed manifest
- **THEN** consumer preflight fails before publication, setup, authorization, or financial mutation

#### Scenario: Manifest artifact identity is changed

- **WHEN** a wheel, image, schema, migration, source, repository, or workflow identity does not match the signed manifest
- **THEN** deployment fails before schema mutation or serving traffic

#### Scenario: Client wheel and image originate from different manifests

- **WHEN** artifact hashes do not match one signed manifest
- **THEN** packaging and deployment fail before the storefront starts or runs conformance tests

#### Scenario: Hosted readiness is checked

- **WHEN** the storefront starts with hosted settlement enabled
- **THEN** `/health/ready` reports the exact expected manifest, API version, and required capabilities

### Requirement: Marketplace deployment config contains consumer data only

Marketplace deployment configuration MUST contain only hosted public client inputs: HTTPS authority URL, expected authority principal, selected condition/evaluator contract, opaque public account reference, exact funding-profile and currency/country policy, exact client/manifest/API/schema/capability pins, local buyer profile location, and marketplace signer Secret references. It MUST NOT contain provider API keys, webhooks, Stripe account/customer/payment-method/mandate IDs, payer/instrument refs outside owner-only local profile metadata, hosted database or migration settings, provider retry/reconciliation policy, or provider recovery controls. Profile-specific readiness failures MUST remain safe public diagnostics.

#### Scenario: Marketplace profile declares provider credentials

- **WHEN** a storefront or buyer config contains a Stripe secret, provider ID, stable instrument ID, webhook, or hosted persistence field
- **THEN** typed validation rejects it before process startup

#### Scenario: Marketplace profile declares three exact profiles

- **WHEN** public config and the signed release admit card, US bank transfer, and US ACH under USD/US policy
- **THEN** readiness evaluates each exact profile independently without receiving provider configuration

#### Scenario: VM chart renders with hosted settlement enabled

- **WHEN** trusted hosted release values are supplied
- **THEN** the chart configures only the storefront client/adapter and renders no hosted API, worker, migration, Secret, ingress, database, or service PVC

### Requirement: Packaging preserves provider separation

Marketplace builds MUST consume the hosted client only as an exact manifest-pinned wheel from release artifacts, not through editable sibling source, copied models, service wheel, source mounts, or a shared environment. Marketplace release records MUST pin marketplace source separately from the hosted manifest, client wheel, service image, public contract/schema, migration/provenance, repository/workflow, source, and capability identities. Updating the hosted client MUST explicitly rebuild, upgrade, and reinstall the exact wheel before marketplace package, type, or protected checks.

#### Scenario: Developer initializes hosted support

- **WHEN** marketplace dependency initialization runs
- **THEN** it installs the exact verified client wheel into the marketplace environment without mounting or importing hosted service source

#### Scenario: Expanded client pin changes

- **WHEN** payer/profile/authorization consumption requires a new client release
- **THEN** marketplace lock and release evidence update the exact wheel/manifest together and stale environments fail verification

#### Scenario: Release artifacts are inspected

- **WHEN** marketplace wheels and storefront images are built
- **THEN** they contain no Stripe SDK, hosted service package, EVM gateway implementation, provider credential, or copied hosted model and signature module

### Requirement: Protected hosted test composition uses the production release

A protected marketplace-hosted test composition MUST inject role-scoped Stripe test credentials only into the hosted execution environment, exact manifest-pinned public hosted coordinates into marketplace roles, isolated marketplace signer credentials into their owning roles, and selected buyer payer/profile fixtures through direct client setup. The protected workflow MUST execute at least one exact ordinary `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1` lifecycle plus an off-session `requires_action` fallback through released marketplace and hosted artifacts. It MUST retain authoritative service state across selected consumer restarts and MUST keep provider credentials, payer/instrument data, action URLs, raw requests/events, and provider IDs out of marketplace artifacts and reports.

#### Scenario: Protected profile matrix starts

- **WHEN** the signed hosted release, role credentials, connected account, resolver, and exact three funding profiles pass preflight
- **THEN** buyer and storefront exercise profile selection, accepted authorization, materialization, authoritative funding, VM fulfillment, condition, collection/reclaim, status, and selected restart/recovery boundaries through ordinary production paths

#### Scenario: One external prerequisite is unavailable

- **WHEN** Stripe test mode cannot supply a required rail/account/mandate/action outcome or the signed release is unverifiable
- **THEN** the report marks that exact assertion unavailable with its prerequisite and does not substitute credential-free, simulated, or another-profile evidence

#### Scenario: Protected Stripe composition starts

- **WHEN** an authorized operator supplies a compatible production release, test-mode Stripe access, a verified loopback webhook-forwarding path, Chromium, and a ready allowlisted connected account
- **THEN** release verification and migration complete before the ordinary authority API and worker become ready, marketplace consumers use the public authority address and released client, and no alternate provider or test-control service exists

#### Scenario: Authority process restarts

- **WHEN** a hosted recovery scenario restarts the ordinary authority API or reconciliation worker without resetting the scenario
- **THEN** the authority store and accepted operation identities remain available and reconciliation resumes against authoritative Stripe test-mode state

### Requirement: Identity configuration separates public and secret material

Private identity credentials MUST arrive through role-scoped Secret references and MUST NOT enter committed values, ConfigMaps, manifests, run logs, public principal fields, public URLs, or generated evidence. Hosted consumer profiles MUST additionally keep provider credentials and provider/customer/payment-method/mandate/bank/card data out of all marketplace roles; opaque payer binding belongs only to owner-restricted local buyer profile state, while stable instrument refs remain authority-side or transient direct-client state. Runtime MUST derive the public principal from the credential and compare it with configured public identity before readiness.

#### Scenario: Public identity configuration contains a private credential

- **WHEN** a values file, ConfigMap, release artifact, readiness response, log, or conformance fixture contains private identity material
- **THEN** validation fails and the value is not deployed or published

#### Scenario: Hosted payer data enters storefront values

- **WHEN** a storefront deployment declares a payer profile, instrument, Customer, PaymentMethod, mandate, bank detail, or action URL
- **THEN** schema validation fails before render or startup

#### Scenario: Fiat-only storefront is rendered

- **WHEN** a profile enables only Ed25519 marketplace identity and hosted non-EVM settlement
- **THEN** Helm/Compose rendering requires the identity Secret reference but no wallet, chain, RPC, deployed-address, or gas configuration

#### Scenario: Identity secret is missing

- **WHEN** a role has a public principal but cannot load matching private credential material
- **THEN** startup fails before serving authenticated routes, publishing, negotiating, or submitting settlement operations

#### Scenario: A service-peer profile is rendered

- **WHEN** a storefront and provisioning authority are configured to trust one another
- **THEN** ordinary configuration contains each exact scheme-tagged public principal and site trust binding, while each role's matching signer credential is supplied only through its own Secret boundary
