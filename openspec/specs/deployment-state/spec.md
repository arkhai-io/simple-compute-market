# Deployment and State Specification

## Purpose

Define service topology, persistence ownership, migration execution, packaging, and rollout compatibility.

## Requirements

### Requirement: Marketplace deployment never owns payment-provider state

Marketplace profiles MAY configure payment-service origin, receipt identity, fee/dispute policy, public account inputs, buyer profile path, and credential references. They MUST NOT configure or persist Stripe secrets or provider IDs, bank/card data, webhooks, payment-service database/migrations, ledger reconciliation, or cash-provider recovery.

#### Scenario: Marketplace configuration contains a provider secret

- **WHEN** a profile supplies a Stripe key, webhook secret, or provider account identifier
- **THEN** validation rejects it rather than deploying it to a marketplace workload

### Requirement: Role-separated deployment
Production topology MUST support independently operated registries, seller storefront/provisioning stacks, and ephemeral or long-running buyers; the local Anvil environment MUST remain a development-only fixture.

#### Scenario: Provider joins an existing market
- **WHEN** a provider deploys its node
- **THEN** it can point at an externally operated registry instead of requiring a private registry instance

### Requirement: Explicit persistence ownership
Each service MUST own its database and migration history; cross-service identifiers MUST cross APIs/events rather than relational foreign keys between service databases.

#### Scenario: A deal crosses a service boundary
- **WHEN** storefront settlement invokes provisioning
- **THEN** correlation identifiers cross the API while provisioning retains ownership of its allocation records

### Requirement: Service-owned migration history
Each stateful service MUST run and record its own ordered migration chain against its owned database; a deployed provisioning service MUST apply pending migrations before application startup and MUST reject schema drift from its normal startup path instead of applying migrations in-process.

#### Scenario: Database initialization is repeated
- **WHEN** a service initializes a database whose migrations are already applied
- **THEN** initialization leaves the schema at the same current version without duplicate schema changes

#### Scenario: Provisioning deployment has pending migrations
- **WHEN** a provisioning pod is created with an older owned database
- **THEN** its migration init container applies the ordered migration chain before the application container starts

#### Scenario: Provisioning application sees schema drift
- **WHEN** the application process starts against a database missing the latest known migration
- **THEN** startup fails with an actionable schema-drift error and does not mutate the schema

#### Scenario: A service has no separate deployment step for migrations
- **WHEN** a stateful service has no Kubernetes init container or standalone migration CLI to apply migrations ahead of the application process (for example, the API-credit service, which has no Helm chart)
- **THEN** it MAY apply its own ordered migration chain in-process at application startup, before serving requests, rather than rejecting drift from its normal startup path — this is a valid instantiation of service-owned migration history for a service without the provisioning service's deployment topology, not an exception to it

### Requirement: Installable package boundaries
Published wheels MUST resolve internal runtime dependencies by distribution version or a supplied wheel directory and MUST NOT encode parent-directory monorepo paths in customer-facing lock metadata.

#### Scenario: Wheel is installed outside the monorepo
- **WHEN** its dependencies are available from PyPI or `--find-links`
- **THEN** installation succeeds without the repository's relative directory layout

### Requirement: Independently deployable bare-metal seller role
The bare-metal storefront MUST be buildable as a wheel from the repository `.dist` artifact set and as a dedicated image containing its declared domain and shared-role dependencies. It MUST own a writable database distinct from every other storefront, with separate immutable agreement-artifact, fulfillment-lifecycle, and reservation-to-site routing tables. Operator configuration MUST bind every stable site identifier to one exact authority URL and canonical principal, while signer credentials and complete routing records remain Secret-injected and diagnostics remain URL/credential-free.

#### Scenario: Bare-metal storefront package is installed
- **WHEN** the distribution is installed from staged wheels outside the source checkout
- **THEN** the `bare-metal-storefront` entry point and `market.storefront_contributions` hook load without editable sibling packages

#### Scenario: Operator enables only bare-metal
- **WHEN** the bare-metal seller role is enabled and VM storefront is disabled
- **THEN** the role starts with its own persistence and trusted-site configuration without waiting for or referencing a VM storefront

#### Scenario: Operator enables both compute storefronts
- **WHEN** VM and bare-metal seller roles use one provisioning service
- **THEN** they remain separate processes with separate writable storefront databases and explicit public service URLs or gateway paths

#### Scenario: Site configuration is diagnosed
- **WHEN** health or operator status reports configured bare-metal site bindings
- **THEN** it reports stable site IDs and canonical authority principals but no authority URL, signer credential, provider configuration, or private inventory

#### Scenario: Helm deploys the one-domain role
- **WHEN** an operator supplies public seller identity, existing signer and site-binding Secret references, one persistent volume, and a pinned dedicated image to `helm/charts/bare-metal-storefront`
- **THEN** the chart renders one unprivileged storefront process with startup, liveness, and readiness probes and no wait or import dependency on the VM storefront

### Requirement: Installable compute provisioner

The extracted compute-provisioning distribution MUST install outside the repository layout with all declared runtime dependencies and MUST expose supported commands for its API and worker roles.

#### Scenario: Wheel is installed from built artifacts

- **WHEN** an operator installs the compute provisioner and selected adapter extras from built wheels without editable parent-directory sources
- **THEN** API and worker commands resolve their dependencies and start using the supplied configuration

### Requirement: Extracted service image

The repository MUST provide one destination compute-provisioning image whose startup, routes, background lifecycle, persistence, and shutdown behavior match the migrated service.

#### Scenario: Destination image starts

- **WHEN** the image starts with VM and bare-metal adapters and an existing compatible database
- **THEN** migrations initialize once, readiness becomes healthy, configured background tasks run, and graceful shutdown cancels them without corrupting job or lease state

### Requirement: Coordinated deployment cutover

Deployment manifests and operator configuration MUST reference the destination package, commands, and image, and MUST NOT retain the old VM-owned generic service after cutover.

#### Scenario: Repository deployment references are checked

- **WHEN** package, image, command, and manifest references are scanned after migration
- **THEN** all active deployments use the compute-owned service and no runtime path depends on the repository's parent-directory layout

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

### Requirement: Identity configuration separates public and secret material

Private identity credentials MUST arrive through role-scoped Secret references and MUST NOT enter committed values, ConfigMaps, manifests, run logs, public principal fields, public URLs, or generated evidence. Payment consumer profiles MUST keep provider credentials and bank/card data out of marketplace roles. Owner-scoped API credentials are separate from marketplace signing credentials. Runtime MUST derive the public principal from the credential and compare it with configured public identity before readiness.

#### Scenario: Public identity configuration contains a private credential

- **WHEN** a values file, ConfigMap, release artifact, readiness response, log, or conformance fixture contains private identity material
- **THEN** validation fails and the value is not deployed or published

#### Scenario: Payment credential enters public values

- **WHEN** a public ConfigMap contains the resolved payments API key
- **THEN** validation fails before deployment

#### Scenario: Fiat-only storefront is rendered

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

### Requirement: Deployment uses one settlement hierarchy

Role TOML, committed defaults, environment overlays, Helm values/schema/templates, Compose, examples, and generated configuration MUST use the same typed `[Settlement]` root and mechanism subsection names. Marketplace deployment MUST keep public identity, wallet/chains, and mechanism trust/policy separate from Secret-injected credentials, and MUST reject payment-provider/admin/webhook secrets or payment-service-owned state.

#### Scenario: Payment-only role starts

- **WHEN** marketplace identity, trusted Arkhai payments consumer policy, and owner-scoped credentials are supplied with Alkahest disabled
- **THEN** the role does not construct a wallet, chain, or RPC client

#### Scenario: Legacy environment variable remains

- **WHEN** startup receives a removed settlement configuration path after cutover
- **THEN** readiness fails with the corresponding new path and migration command rather than applying hidden precedence

### Requirement: Configuration cutover is atomic and coordinated

Migration tooling MUST be deployable before runtime rejection, and production cutover MUST preview, back up, migrate, and validate every role file, Secret mapping, Helm value, Compose environment, and automation caller before enabling the clean-cutover release. Old and new names MUST NOT be accepted concurrently by runtime. Rollback before activation MUST restore the matching config and prior artifacts together.

#### Scenario: Helm values and image contract differ

- **WHEN** a new image receives old settlement values or an old image receives new settlement values
- **THEN** schema validation or startup readiness fails before publication or settlement mutation

### Requirement: Generated configuration has one source of truth

Typed configuration metadata MUST generate role-appropriate init templates, dotted-path editing validation, environment/Helm schema fragments, and reference tables. Generated outputs MUST be checked for drift in CI and MUST omit secret values and fields not applicable to the role.

#### Scenario: Mechanism field changes

- **WHEN** a mechanism's typed configuration adds or removes an operator field
- **THEN** drift validation requires the applicable templates, schema, and reference output to change together

### Requirement: Buyer profile deployments separate XDG state and provider secrets

Buyer public configuration, mutable profile metadata, run logs, and credential material MUST occupy separate deployment mounts. `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME` MUST be explicit for one-shot and long-running buyer roles. Profile-store directories/files MUST deny group/other writes; strict credential files MUST be regular non-symlink files owned by the buyer process with no group/other permission bits.

Compose and Helm buyer jobs MUST persist the profile metadata directory across restart and mount the exact provider secret only into the buyer process. Generated TOML, ConfigMaps, arguments, evidence, and release artifacts MUST omit secret values and removed buyer `[Identity]` fields.

#### Scenario: A headless buyer pod restarts

- **WHEN** the pod is recreated with the same profile PVC and strict credential Secret
- **THEN** it selects the same stable profile and resumes version-3 runs without reconstructing identity from a wallet or public config

### Requirement: Legacy buyer identity migration activates atomically

An operator MUST preview and explicitly import legacy buyer identity into one exact profile before removed fields are deleted. Profile-store and all run-log candidates MUST validate before activation; an incomplete durable migration manifest blocks buyer work and supports complete restoration before profile-based effects occur.

#### Scenario: Migration is interrupted

- **WHEN** replacement fails after one candidate was written
- **THEN** startup refuses mixed state and recovery restores every recorded original before retry

### Requirement: Multi-domain storefront configuration is explicit

A compute-family storefront deployment MUST configure a non-empty public list of domain registrations, each naming one contribution, offering mode, exact domain identity, and supported contract version. The image MUST contain the shared shell and every enabled contribution as staged immutable wheels. Helm and Compose MUST run one process against one single-writer SQLite volume, render trusted sites independently, and keep signer credentials, provider settings, SSH material, and private results in Secret-only channels.

#### Scenario: Combined storefront is rendered

- **WHEN** VM and bare-metal registrations are configured with complete trusted sites
- **THEN** the rendered workload starts one common storefront command and database with both public registrations and no private credential in ConfigMaps, arguments, or image layers

#### Scenario: Registration package is absent

- **WHEN** preflight cannot find a configured contribution or its complete exact contract
- **THEN** activation remains quiesced and reports the missing contribution/mode/domain/version without serving new work

### Requirement: Legacy storefront domain migration is transactional

An operator MUST quiesce effects and run the explicitly selected contribution's migration adapter in read-only check mode before write. Write MUST require a restrictive same-directory backup, fsync the complete validated replacement, atomically replace the source, and retain stable listing, negotiation, settlement, obligation, reservation, fulfillment, operation, and provider identities. Missing provenance, mixed kinds, orphan relationships, collision, binding disagreement, or unsupported version MUST abort without partial source mutation. No adapter may infer a domain from payload shape or from having one installed contribution.

#### Scenario: A valid VM database is activated

- **WHEN** every legacy derived row proves its site and pool or Physical Resource provenance and the configured registration matches exactly
- **THEN** migration records common listing/thread/fulfillment bindings, retires the old mapping as a writable authority, and an idempotent check succeeds after replacement

#### Scenario: A legacy row is ambiguous

- **WHEN** a row lacks trusted site/provenance, conflicts with public mode, is orphaned, duplicates a derivation identity, or names another contract
- **THEN** check and write fail with redacted diagnostics while the source database and backup set remain unchanged

#### Scenario: Replacement is interrupted

- **WHEN** failure occurs after the original backup but before atomic replacement
- **THEN** the original database remains byte-identical, the restrictive backup is retained for recovery, and startup does not activate mixed state

### Requirement: Deployable stack per market domain

Every market domain intended for deployment MUST have a stack definition that
stands its services up through the repository's ordinary images and public
process contracts. Domain stack definitions MUST follow the same topology
conventions, select an exact domain contribution and version, persist each
authority's state independently, and carry credentials only through explicit
role-scoped Secret references. A domain without such a stack MUST NOT be
described as deployable.

#### Scenario: A domain is stood up

- **WHEN** an operator stands up a market domain's services
- **THEN** its stack definition composes the exact registry, storefront, domain authorities, and optional buyer role without source sharing, provider shortcuts, or committed secret values

#### Scenario: A domain's deployment topology changes

- **WHEN** a domain contribution moves between a standalone storefront and a shared multi-domain storefront process
- **THEN** only the stack's contribution/config binding changes while public domain identity, selected-site routing, and scenario endpoints remain exact

### Requirement: Domain payment persistence is role-owned

Storefront databases MUST persist exact Agreement bytes and opaque settlement data in `negotiation_threads`; domain receipt and fulfillment/grant progress MUST remain under that storefront's ordered migrations. The payments service MUST own transaction, ledger, hold-release, fee, and dispute state. VM and bare-metal MUST retain selected-site authority bindings independently of payment trust. API credits MUST retain the separate registry, credits authority, gated application, storefront, and buyer roles.

#### Scenario: Seller restarts after payment approval

- **WHEN** the storefront reloads an accepted payment negotiation
- **THEN** it retrieves the same mandate and transaction ID from its negotiation state and resumes domain progress without migrating a Stripe profile, credential, or operation ID
