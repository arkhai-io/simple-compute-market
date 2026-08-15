# Deployment and State Specification

## Purpose

Define service topology, persistence ownership, migration execution, packaging, and rollout compatibility.
## Requirements

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

### Requirement: Manifest-pinned external settlement authority
Marketplace deployment MUST consume one exact hosted client/adapter contract
and independently deployed service release. Enabled startup MUST verify the
expected manifest digest, API version, and required capabilities; marketplace
Helm renders only storefront consumer URL, trust, resolver identifiers, and
request credential configuration and MUST NOT render the hosted API, worker,
migration, database, ingress, or provider secrets.

#### Scenario: Hosted consumer pin is incomplete
- **WHEN** hosted settlement is enabled without its URL, authority, exact
  manifest/API pin, request credential, or required capabilities
- **THEN** storefront startup fails closed before accepting traffic

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

### Requirement: Identity migrations are coordinated and fail closed

Each owning service MUST migrate its identity-bearing rows through its own ordered migration chain while preserving cross-service opaque IDs and provider-operation identity. Versioned buyer run logs MUST have an explicit migration path. Authorities MUST reject old schema, old signature versions, drift, ambiguous principals, or partially migrated state; production cutover MUST quiesce authenticated mutations until all required authorities and clients report the new identity capability.

#### Scenario: One authority remains on the old signature contract

- **WHEN** deployment readiness detects a registry, storefront, service peer, or hosted authority that lacks the pinned identity version
- **THEN** the affected workflow remains unavailable rather than downgrading or submitting a legacy proof

#### Scenario: Migration encounters conflicting owners

- **WHEN** two address-only rows would create an invalid active-principal ownership relation
- **THEN** that service migration rolls back completely and readiness remains false

### Requirement: Hosted identity release is pinned as one contract

Marketplace packaging and deployment MUST consume the exact hosted client wheel and identity capabilities bound by one verified hosted release manifest. The marketplace MUST reject editable sibling sources, copied hosted signing modules, compatible-major substitution, or a service/client identity-version mismatch.

#### Scenario: Marketplace wheel carries the wrong hosted client

- **WHEN** the installed hosted client hash differs from the verified manifest used by the service deployment
- **THEN** packaging verification or startup preflight fails before a fiat option is published

### Requirement: Deployment uses one settlement hierarchy

Role TOML, committed defaults, environment overlays, Helm values/schema/templates, Compose, examples, and generated configuration MUST use the same typed `[Settlement]` root and mechanism subsection names. Marketplace deployment MUST keep public identity, wallet/chains, and mechanism trust/policy separate from Secret-injected credentials, and MUST reject hosted provider/admin/webhook secrets or service-owned state.

#### Scenario: VM chart enables hosted settlement only

- **WHEN** the chart receives a valid public hosted consumer configuration and identity Secret reference
- **THEN** it renders the Stripe mechanism subsection and no wallet, chain, RPC, provider, webhook, database, or hosted migration configuration

#### Scenario: Legacy environment variable remains

- **WHEN** startup receives a removed hosted or Alkahest configuration path after cutover
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

### Requirement: Protected hosted test composition uses the production release

A protected marketplace-hosted test composition MUST inject role-scoped Stripe test credentials only into the hosted execution environment, exact manifest-pinned public hosted coordinates into marketplace roles, isolated marketplace signer credentials into their owning roles, and selected buyer payer/profile fixtures through direct client setup. The protected workflow MUST execute at least one exact ordinary `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1` lifecycle plus an off-session `requires_action` fallback through released marketplace and hosted artifacts. It MUST retain authoritative service state across selected consumer restarts and MUST keep provider credentials, payer/instrument data, action URLs, raw requests/events, and provider IDs out of marketplace storage, logs, and reports.

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

### Requirement: Stripe test-mode activation fails closed

Protected hosted startup MUST prove the exact marketplace consumer commit and
hosted release identity, a test-mode secret (`sk_test` or least-privilege
`rk_test`), non-live returned objects,
Stripe API connectivity, expected allowlisted test-account ownership and
capabilities, loopback-only webhook delivery to the exact authority endpoint,
and browser availability. A mismatch or unavailable prerequisite MUST stop
before the relevant publication, acceptance, Checkout, transfer, or refund
mutation. Local focused evidence MUST NOT replace a failed prerequisite.

#### Scenario: Live credential is supplied

- **WHEN** protected hosted E2E receives a live-mode Stripe credential or observes a live provider object
- **THEN** preflight fails before creating any payment, transfer, refund, or marketplace settlement mutation and redacts the credential

#### Scenario: Connected account is unready

- **WHEN** the selected test connected account lacks the expected ownership binding, charge/transfer capability, or readiness required by the scenario
- **THEN** preflight reports an account-readiness failure before publication of a Stripe option or payment creation

#### Scenario: Release identity is incomplete

- **WHEN** a protected run cannot bind its manifest digest, client wheel hash, service image digest, signed release repository/workflow reference/source commit, or separate protected producer workflow run identity
- **THEN** startup fails before Compose creates the authority or marketplace services and no partial identity is reported as system evidence

### Requirement: Hosted test secrets remain role-scoped

Stripe provider, webhook, hosted authority, release acquisition, marketplace
signer, and browser-test credentials MUST be supplied only to the process that
consumes them. Marketplace storefront and buyer configuration MUST contain no
hosted provider or administrator endpoint or credential, webhook secret,
connected-account provider identifier, or raw provider state. Default and fork
workflows MUST receive no protected hosted artifact or Stripe credential.
Process output and reports MUST exclude credentials, Checkout or Account Link
URLs, account/customer/card data, raw webhook bodies, and unrestricted provider
payloads.

#### Scenario: Public or fork workflow runs

- **WHEN** untrusted contributor code executes
- **THEN** no protected artifact credential, Stripe credential, connected-account identifier, webhook secret, raw event, Checkout action, or secret-bearing report is available

#### Scenario: Stripe CLI forwards webhooks

- **WHEN** an authorized protected run starts Stripe CLI forwarding to the loopback-only hosted webhook mapping
- **THEN** the signing secret is delivered only to the authority webhook process, is never printed or persisted in marketplace state, and is destroyed with the run environment

### Requirement: Hosted test deployment has no alternate provider surfaces

Active marketplace Compose, Make, workflow, packaging, configuration,
release-verification, schema, and permanent documentation surfaces MUST expose
only the ordinary production hosted client/service artifacts for financial E2E.
They MUST NOT contain or select a provider substitute distribution, image,
manifest, protocol, endpoint, credential, state store, controlled clock or
event service, synthetic provider worker, or alternate hosted profile.
Historical change artifacts MAY retain provenance but MUST NOT be executable or
referenced by current production or test entry points.

#### Scenario: Deployment surfaces are inspected

- **WHEN** active hosted test and packaging surfaces are examined
- **THEN** only the ordinary production hosted release and protected Stripe test prerequisites remain and no alternate provider artifact can be selected or started

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

## Evidence

- Configurable registry endpoints and independently composed role stacks: core buyer registry configuration plus domain Compose and Helm manifests.
- Service-owned persistence, provisioning migration init, and schema-drift rejection: registry Alembic tests, `provisioning/compute/service/tests/unit/test_database.py`, and `helm/charts/provisioning/templates/deployment.yaml`.
- Wheel-directory dependency resolution without parent-path UV sources: package `pyproject.toml` files and package Makefiles using `--find-links`.
- Extracted compute API/worker packaging and image lifecycle: `provisioning/compute/service/pyproject.toml`, `provisioning/compute/service/Dockerfile`, and its composition, worker, and image smoke tests.
- Bare-metal staged-wheel/image boundary and installed contribution: `domains/bare_metal/storefront/pyproject.toml`, `domains/bare_metal/storefront/Dockerfile`, `domains/bare_metal/storefront/tests/test_package.py`, `test_import_boundaries.py`, and `test_app_composition.py`.

Repository-wide migration entrypoints and compatibility-preserving non-additive registry rollout remain proposed in `add-database-migration-commands` and `migrate-registry-to-postgres`.

## Internal wheel development contract

Internal Python distributions MUST be built into the repository `.dist` directory and consumed with `--find-links`. A project MUST NOT add editable relative sibling sources as its normal local-development dependency mechanism.

A touched project's `init` or `reinit` target MUST explicitly upgrade and reinstall changed internal distributions from `.dist`. Docker stages that resolve internal packages MUST copy `.dist` from the build context so wheel changes invalidate the relevant layer.

The aggregate kit test target MUST build prerequisite kit wheels and invoke every kit subproject's default test suite. Standalone targets MAY remain for focused development, but aggregate coverage MUST not silently omit a kit.
