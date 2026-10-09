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

### Requirement: Schema-isolated registry composition

One Helm release MAY compose multiple registry instances by aliasing the same
registry role. Each enabled instance MUST select exactly one filter
specification and MUST have independent authority identity, credential Secret,
descriptor, authentication, Service, persistence, and workload coordinates.
Disabling an optional instance MUST emit no resource for that instance and MUST
preserve the existing compute-registry render.

The compute-family instance MUST select its filter specification by the schema
identity naming the family rather than one domain within it, since that
specification carries bare-metal, virtual-machine, and container listings alike. A
deployment MUST NOT select the retired single-domain identity, and because buyer
commands declare the schema identity they understand, a registry and the buyers
querying it MUST move together.

#### Scenario: Compute and API-credit registries are enabled

- **WHEN** an operator enables compute and API-credit registry instances with
  their respective filter specifications
- **THEN** Helm renders two independently named registry workloads, Services,
  PVCs, signer Secret references, descriptors, and schema paths

#### Scenario: API-credit registry is disabled

- **WHEN** an operator renders the default umbrella values
- **THEN** only the existing compute registry resources are emitted and they
  select the `compute.market` filter specification

#### Scenario: Registry identities differ

- **WHEN** two registry aliases configure different authority principals
- **THEN** each registry process uses its own identity and credential Secret
  without requiring either to equal an umbrella-global identity

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

### Requirement: Shared Dynaconf bootstrap preserves consumer policy

Compute provisioning and e2e MUST use the shared `arkhai-kit-config` bootstrap for profile parsing, base-then-profile include resolution, and Dynaconf construction. The shared bootstrap MUST receive configuration-directory and active-profile values explicitly from each composition root and MUST preserve consumer-owned settings-file, dotenv, secret-file, environment-prefix, nested-key, merge, and missing-include policy rather than imposing one common policy on those consumers.

#### Scenario: Compute provisioning loads optional profiles

- **WHEN** compute provisioning supplies no `CONFIG_DIRECTORY` override and selects one or more `ACTIVE_PROFILES`
- **THEN** the shared bootstrap resolves the service-local config directory, orders `config.yml` before selected profile files, filters missing include files, and constructs Dynaconf with the provisioning settings file, `PROVISIONING` environment prefix, supported normal `.env` discovery, disabled Dynaconf environments, and merge enabled; it does not add `.env.local` loading

#### Scenario: E2E loads profile and secret layers

- **WHEN** e2e supplies a config-directory override and selects one or more active profiles
- **THEN** the shared bootstrap orders `config.yml` before every requested profile path without filtering missing includes and constructs Dynaconf with project `settings.toml` followed by `.secrets.toml`, the project `.env` path, the `ARKHAI` environment prefix, disabled Dynaconf environments, and merge enabled; dotenv-sourced `ARKHAI_*` values participate at environment precedence without overwriting already-set process values

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

### Requirement: A storefront chart passes service configuration through

A storefront chart MUST render an agent's service configuration from its values
without enumerating the service's keys, so a setting or settlement mechanism the
storefront gains deploys through values alone with no template or hand-written schema
change. The chart MUST NOT supply a default for a service setting and MUST NOT
implement a service's semantic validation of its own configuration.

The chart MAY add a value only the release knows: the agent's port, which MUST equal
the port its container, probes, and Service use; the agent's Service URL as its public
URL; the internal registry's and provisioning service's URLs; a `default` capacity
site bound to the effective provisioning URL; and the database path under the
persistence mount. Except for the port, it MUST add each only where the agent's
configuration does not state it.

A value whose position depends on a name only the release creates — trust for the
internal registry, keyed by that registry's derived URL — MUST be stated by the
operator as a chart-level agent value and written by the chart under the derived key.
Trust MUST be stated by the operator and checked by the chart; the chart MUST NOT add
a principal to a trust list.

The chart MAY refuse a release whose parts disagree with each other: internal-registry
trust whose authority or principals do not include the release's registry identity;
provisioning trust, or a provisioning service peer for a site bound to the internal
provisioning service, that does not include the release's provisioning principal; or a
stated port that differs from the agent's. The chart MAY read the passed-through
configuration to make a Kubernetes decision, such as waiting for a configured chain's
RPC endpoint, or for the internal registry when the agent uses it, before the
storefront starts. The chart MUST match every key it reads or writes as the
storefront's loader matches it, without regard to case, and MUST refuse a
configuration that states one key in two spellings at any depth.

A values file using a retired values shape MUST be refused at render, naming the
retired key, rather than passed through as keys the storefront ignores.

#### Scenario: A storefront gains a settlement mechanism

- **WHEN** an operator adds a mechanism's section and its priority entry to an agent's
  configuration values
- **THEN** the rendered storefront configuration carries the section exactly as
  written
- **AND** no chart template or hand-written values schema changed

#### Scenario: Numbers and strings keep their type

- **WHEN** an agent's configuration carries integers, including ones above a million,
  fractional numbers, and an EVM address
- **THEN** the storefront reads each integer as an integer, each fractional number as
  a number, and the address as a string

#### Scenario: An operator omits a mechanism setting

- **WHEN** an agent's configuration omits a setting the storefront defaults
- **THEN** the rendered configuration omits it and the storefront applies its own
  default

#### Scenario: A setting fails the storefront's semantic validation

- **WHEN** an agent's configuration passes the values schema but carries a value the
  storefront's typed configuration refuses
- **THEN** the chart renders it unchanged and the storefront refuses it at startup

#### Scenario: The release knows a value the agent omits

- **WHEN** an agent's configuration names no registry, no provisioning URL, no
  capacity sites, and no database path
- **THEN** the rendered configuration carries the internal registry's URL with the
  agent's internal-registry trust under it, the provisioning service's URL, a
  `default` site bound to that URL, and a database path under the persistence mount
- **AND** a value the agent states is rendered as stated

#### Scenario: Release parts disagree

- **WHEN** an agent's internal-registry trust or provisioning trust omits the
  release's principal, or its stated port differs from the agent's port
- **THEN** rendering fails with a message naming the disagreement

#### Scenario: A key is stated in two spellings

- **WHEN** an agent's configuration states both `Settlement` and `settlement`, or
  one nested key in two spellings
- **THEN** rendering fails naming both

#### Scenario: A release-owned key is spelled differently

- **WHEN** an agent's configuration states `Port` with a value other than the agent's
  port
- **THEN** rendering fails naming the disagreement

#### Scenario: A values file uses the retired shape

- **WHEN** an agent's values use a retired key such as `seller` or `storefrontDomains`
- **THEN** rendering fails naming the key

### Requirement: A storefront reads chart-rendered configuration between its file and its overlay

A storefront MUST read its public configuration from `storefront.toml`, then
`storefront.json`, then its Secret overlay `storefront.secrets.toml`, under its
configuration directory, with a later file winning on a conflicting key. The rendered
layer is JSON so that every string, including a 160-bit EVM address, is read back as a
string. Its
configuration-reporting commands MUST report the configuration the server loads,
merged by the same rules, including when only the rendered files are present, and
MUST NOT print the Secret overlay verbatim.

#### Scenario: A chart-deployed storefront starts

- **WHEN** the configuration directory holds a rendered `storefront.json` and a
  `storefront.secrets.toml`, and no `storefront.toml`
- **THEN** the storefront loads both, with the overlay's values winning
- **AND** `market-storefront config show` reports the merged configuration

#### Scenario: Two layers spell a section differently

- **WHEN** one layer states `[Chains.anvil]` and a later layer states `[chains.anvil]`
- **THEN** `market-storefront config show` reports one merged `chains` section, as the
  server loads it

#### Scenario: The raw layers are shown

- **WHEN** an operator runs `market-storefront config show --raw`
- **THEN** each public layer present is printed verbatim under its path, in load
  order, and the Secret overlay is not printed

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

Packaged storefront settings MUST NOT select a default registration. The
operator-supplied list is the complete selection after configuration layering,
not an extension of an image-owned domain choice.

#### Scenario: Combined storefront is rendered

- **WHEN** VM and bare-metal registrations are configured with complete trusted sites
- **THEN** the rendered workload starts one common storefront command and database with both public registrations and no private credential in ConfigMaps, arguments, or image layers

#### Scenario: Registration package is absent

- **WHEN** preflight cannot find a configured contribution or its complete exact contract
- **THEN** activation remains quiesced and reports the missing contribution/mode/domain/version without serving new work

#### Scenario: Operator config selects several domains

- **WHEN** an operator overlay selects VM and bare-metal registrations
- **THEN** the effective configuration contains exactly those two registrations, with no packaged registration appended by configuration merging

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

Storefront databases MUST persist exact Agreement bytes and opaque settlement data in `negotiation_threads`; domain receipt and fulfillment or grant progress MUST stay under that storefront's ordered migrations. The payments service owns transaction, ledger, hold-release, fee, and dispute state. VM and bare metal MUST keep selected-site authority bindings independent of payment trust. API credits MUST keep its registry, credits authority, gated application, storefront, and buyer roles separate.

#### Scenario: Seller restarts after payment approval

- **WHEN** the storefront reloads an accepted payment negotiation
- **THEN** it retrieves the same mandate and transaction ID from its negotiation state and resumes domain progress without migrating a Stripe profile, credential, or operation ID

### Requirement: Externally produced dependencies resolve from a declared index

A distribution this repository depends on but does not build MUST be declared as
an ordinary dependency and resolved from a declared package index. It MUST NOT
be obtained by copying a prebuilt artifact into the build output directory, and
no build target may special-case its acquisition.

The build output directory MUST contain only artifacts this repository builds.
An externally produced distribution arriving there is indistinguishable from a
locally built one, which is what allows a build to report success while
producing nothing.

Resolution MUST succeed from a clean checkout with no credential and no access
to the repository that produced the distribution, including from a fork.

#### Scenario: A consuming project is built

- **WHEN** any project depending on an externally produced distribution is
  initialized or tested
- **THEN** the distribution resolves from the declared index, and no target
  stages, copies, or verifies a release to make that possible

#### Scenario: The wheelhouse is built

- **WHEN** the repository builds its distributions
- **THEN** the build output directory contains every distribution built here and
  no distribution produced elsewhere

#### Scenario: A fork builds the repository

- **WHEN** a pull request from a fork builds and tests the repository
- **THEN** it succeeds, because every dependency is publicly resolvable and none
  requires a credential a fork is not given

### Requirement: Release verification is a publication-time activity

Verification of an externally produced signed release MUST NOT be a prerequisite
of building, initializing, or testing. A signed release describes a deployed
service; establishing what a build compiled against is the lockfile's
responsibility, and establishing what a publication contains belongs to
publication.

The verifier itself MUST retain its behaviour. What changes is which targets
invoke it.

#### Scenario: A suite is run without a staged release

- **WHEN** a project's tests are run and no release is staged
- **THEN** the suite runs, because nothing on the path to it verifies a release

#### Scenario: A dependency is modified locally

- **WHEN** a developer builds and tests against a locally modified copy of an
  external dependency
- **THEN** the build and the suite proceed, and no published artifact results
  from them

### Requirement: Deployment documentation states how a dependency is obtained

Deployment and release documentation MUST state, for every distribution this
repository depends on and does not build, which index serves it and how a
developer or a build obtains it.

An undocumented acquisition path survives as folklore and is reconstructed
incorrectly by the next reader, which is how a staging step with no documented
owner came to be a prerequisite of running unit tests.

#### Scenario: A contributor obtains an external dependency

- **WHEN** a contributor needs to know where an externally produced distribution
  comes from
- **THEN** deployment documentation names the index and the resolution path
  without requiring them to read the build system to infer it

### Requirement: Internal distributions are consumed as wheels from the repository wheelhouse

Internal Python distributions MUST be built into the repository wheelhouse (`.dist`)
and consumed from it. A project MUST NOT resolve another repository distribution
through a relative or editable source path, and MUST NOT declare the wheelhouse's
location itself; the tool that syncs or locks the project supplies it. A Docker stage
that resolves internal packages MUST copy the wheelhouse from the build context, so a
wheel change invalidates that stage.

#### Scenario: A consumer resolves a sibling distribution

- **WHEN** a project that depends on another repository distribution is locked
- **THEN** its lock records that distribution from the repository wheelhouse, not from
  a source path or a package index

#### Scenario: A repository distribution resolves from an index

- **WHEN** any lock resolves a distribution that a repository project declares from a
  package index, or from a local registry other than the repository wheelhouse
- **THEN** the packaging check fails and names the lock and the distribution

#### Scenario: A project declares a sibling source

- **WHEN** a project's `pyproject.toml` names a repository distribution through a
  relative source path, or declares a `find-links` location
- **THEN** the packaging check fails and names the project

### Requirement: Each distribution is one flat import package under src

Each repository Python distribution MUST build its wheel from exactly one top-level
import package located at `src/<package>` in its project, and its project environment
MUST install it editable. A project MUST NOT map a directory onto a different import
path, disable editable installation, or declare rebuild cache keys to compensate for
either.

#### Scenario: A module is edited

- **WHEN** a developer edits a module of the project under test
- **THEN** the next test run imports the edited module without a sync

#### Scenario: A project maps its directory onto a nested import path

- **WHEN** a wheel target includes files from outside `src/<package>` or places them
  under another import path
- **THEN** the packaging check fails and names the project

### Requirement: A project environment refreshes exactly the internal packages its lock installs

A rebuilt wheel keeps its version, so a sync keeps both an environment's installed copy
and the lock's recorded dependencies for it unless told otherwise. A project's `reinit`
MUST upgrade and reinstall every package its `uv.lock` resolves from the repository
wheelhouse, and MUST derive that set from the lock when it runs rather than list it.
Upgrading re-reads a same-version wheel's metadata and MAY rewrite the lock's recorded
dependencies; reinstalling replaces its installed code. Packages resolved from an index
or from source are not refreshed. If the set cannot be derived, the sync MUST NOT run.

Every project with tests whose lock resolves a package from the repository wheelhouse MUST
have a `reinit` target, and that target MUST delegate to the shared derivation without
naming packages.

#### Scenario: A rebuilt wheel gains a dependency without a version change

- **GIVEN** an internal wheel rebuilt at the same version with new code and a new
  dependency
- **WHEN** a consumer's `reinit` runs
- **THEN** the consumer environment has the new code and the new dependency, and its
  lock records the dependency

#### Scenario: A new internal dependency is refreshed without editing any list

- **WHEN** a project's lock gains a package resolved from `.dist` and its `reinit` runs
- **THEN** that package is upgraded and reinstalled with no edit to the project's
  Makefile

#### Scenario: The lock cannot be read

- **WHEN** `reinit` runs and the project's lock is missing or unparseable
- **THEN** it fails before syncing rather than syncing with no package refreshed

#### Scenario: A hand-written list is refused

- **WHEN** a `reinit` recipe, or a recipe it depends on in the same Makefile, names a
  package in an upgrade, reinstall, or refresh flag, or syncs without the shared
  derivation
- **THEN** the packaging check fails and names the project

### Requirement: An image installs the committed lock

An image that installs a project's dependencies MUST install them from that project's
committed lock, used unmodified, and MUST NOT relock: the build MUST fail rather than
resolve when the lock does not match the project. It MUST derive the internal packages
the same way the project's `reinit` does and MUST reinstall each, so a persistent
package cache cannot supply a previous build of a same-version wheel. An image that
installs the project's own distribution MUST install it from the wheelhouse alone, at
the version the project declares, without a version literal in the image definition;
every other repository distribution it contains MUST come from the lock. An image
definition MUST NOT list internal packages or rewrite a lock.

#### Scenario: A wheel is rebuilt without a version change

- **GIVEN** a wheel in `.dist` rebuilt with new code at the same version, and an image
  builder whose persistent cache holds the previous build
- **WHEN** the image is built
- **THEN** it contains the new code

#### Scenario: The committed lock does not match its project

- **WHEN** an image is built from a lock that no longer satisfies the project's
  `pyproject.toml`
- **THEN** the build fails rather than relocking

#### Scenario: The project's own wheel is missing from the wheelhouse

- **WHEN** an image installs its own distribution and `.dist` holds no wheel of the
  declared version
- **THEN** the build fails rather than installing from a package index

#### Scenario: A project's version is bumped

- **WHEN** a project's declared version changes and its image is rebuilt
- **THEN** the image installs that version with no edit to the image definition

#### Scenario: An image definition names packages

- **WHEN** a Dockerfile that copies `.dist` names a package in a refresh, upgrade, or
  reinstall flag, spells a repository distribution's version, rewrites a lock, or
  installs from the wheelhouse other than through the shared derivation
- **THEN** the packaging check fails and names the Dockerfile

### Requirement: Locks are refreshed without installing

The repository MUST provide one command that relocks projects against the current
wheelhouse, upgrading every internal package each lock resolves from it, without
creating or modifying any environment. Because `uv lock --check` alone cannot observe a
same-version wheel's changed dependencies, the command MUST relock every project it is
given rather than skipping those a check reports current.

#### Scenario: A dependency is added to a torch-bearing project

- **WHEN** a developer edits the project's dependencies and runs the lock command
- **THEN** its lock is rewritten from package metadata and no dependency is downloaded
  or installed

#### Scenario: Locks are current

- **WHEN** the lock command runs and nothing has changed
- **THEN** no lock changes

### Requirement: One Python version is declared for the repository

The repository MUST declare one Python version for project environments and images in
a single root declaration. Project environments MUST be created with it, and image
definitions MUST default to it. No other declaration of a Python version for syncing or
building MAY disagree with it.

#### Scenario: A project environment is created on a host with a newer Python

- **WHEN** `reinit` runs on a host whose default Python is newer than the declared one
- **THEN** the environment uses the declared version

#### Scenario: A target creates the environment without reinit

- **WHEN** a project's test or service target runs uv and no project environment exists
- **THEN** the environment it creates uses the declared version

#### Scenario: A CI job checks out conditionally

- **WHEN** a CI job's checkout runs only under a condition
- **THEN** the step that reads the Python declaration runs under the same condition, and
  the packaging check fails if it does not

#### Scenario: An image default disagrees

- **WHEN** a Dockerfile's Python version default, a Makefile's `--python` value, or a
  project-level version file differs from the root declaration
- **THEN** the packaging check fails and names the file

### Requirement: Packaging conventions are checked mechanically

One repository target MUST build the repository wheelhouse and then run every
packaging check — environment setup, lock currency, Python version, and project layout —
failing if any fails. Each check MUST also be runnable alone. The checks MUST read only
the committed tree and the built wheelhouse, and MUST NOT resolve dependencies, relock,
or contact a package index; building the wheelhouse retains whatever its isolated builds
need.

Lock currency MUST fail on a lock that no longer satisfies its project; on a lock that
pins an internal package at a version the tree does not build; and on a lock whose
record of an internal package disagrees with that package's wheel in the wheelhouse —
a requirement added or removed, unconditionally or under an extra in use, or
a locked dependency version the wheel's requirement no longer admits.

#### Scenario: A lock pins a superseded internal version

- **WHEN** an internal distribution's declared version is bumped and a consumer's lock
  still pins the previous one
- **THEN** the packaging check fails and names the consumer and the package

#### Scenario: An empty extra a consumer requests gains a requirement

- **GIVEN** a consumer that requests an extra of an internal wheel while that extra has no
  requirements, and the wheel rebuilt at the same version with a requirement under it
- **WHEN** the packaging check runs
- **THEN** it fails and names the consumer, the package and extra, and the requirement

#### Scenario: A same-version wheel gains a requirement

- **GIVEN** an internal wheel rebuilt at the same version with a new requirement, and a
  consumer lock not refreshed since
- **WHEN** the packaging check runs
- **THEN** it fails and names the consumer, the package, and the requirement

#### Scenario: Every convention holds

- **GIVEN** a tree that follows every convention and a built wheelhouse
- **WHEN** the packaging checks run with no network access
- **THEN** they succeed

#### Scenario: An index the locks resolve from is unreachable

- **WHEN** the packaging target runs where the PyTorch index cannot be reached
- **THEN** its result is the same as where it can

### Requirement: Aggregate kit tests cover every kit

The aggregate kit test target MUST build prerequisite kit wheels and invoke every kit
subproject's default test suite. Standalone targets MAY remain for focused development,
but the aggregate MUST NOT silently omit a kit.

#### Scenario: A kit is added

- **WHEN** a kit subproject with a default test suite exists
- **THEN** the aggregate kit test target runs that suite

## Evidence

- Configurable registry endpoints and independently composed role stacks: core buyer registry configuration plus domain Compose and Helm manifests.
- Service-owned persistence, provisioning migration init, and schema-drift rejection: registry Alembic tests, `provisioning/compute/service/tests/unit/test_database.py`, and `helm/charts/provisioning/templates/deployment.yaml`.
- Wheel-directory dependency resolution without parent-path UV sources: package `pyproject.toml` files and package Makefiles using `--find-links`.
- Derived internal-package refresh for environments, images, and locks: `scripts/uv_project.py`, `scripts/tests/test_uv_project.py`, every `reinit` target, and every Dockerfile that copies `.dist`.
- Packaging checks: `scripts/check_uv_setup.py`, `scripts/check_locks.py`, `scripts/check_python_version.py` and their tests under `scripts/tests/`; `make check-packaging`.
- One project layout: `scripts/check_project_layout.py` and its tests; every project's `[tool.hatch.build.targets.wheel]`.
- One Python version: the root `.python-version`, the `UV_PYTHON` export in each Makefile that runs uv, and the CI step that sets it.
- Extracted compute API/worker packaging and image lifecycle: `provisioning/compute/service/pyproject.toml`, `provisioning/compute/service/Dockerfile`, and its composition, worker, and image smoke tests.
- Explicit contribution configuration and secret-free render surfaces: `domains/vms/storefront/tests/unit/test_config_loader.py`, `test_cli.py`, `helm/charts/storefront/templates/tests/storefront-environment-test.yaml`, and Helm schema fixtures.
- Transactional legacy storefront migration, byte-stable refusal, restrictive backup, atomic replacement, and idempotency: `domains/vms/storefront/tests/unit/test_domain_migration.py`.
- Bare-metal staged-wheel/image boundary and installed contribution: `domains/bare_metal/storefront/pyproject.toml`, `domains/bare_metal/storefront/Dockerfile`, `domains/bare_metal/storefront/tests/test_package.py`, `test_import_boundaries.py`, and `test_app_composition.py`.

Repository-wide migration entrypoints and compatibility-preserving non-additive registry rollout remain proposed in `add-database-migration-commands` and `migrate-registry-to-postgres`.
