# Deployment and State Architecture

The [normative contract](spec.md) defines established deployment, persistence, migration, and package behavior. This document explains the operational boundaries those rules protect.

## Role-separated topology

Registry, seller stack, and buyer are independently operable roles. A buyer is normally a one-shot CLI or long-running agent, not a service required to keep the seller stack healthy. A seller composition owns its storefront and physical or quota authorities; a registry may be operated separately.

Local development composes domain stacks with development-only dependencies such as the local chain. Deployment charts compose the same roles conditionally without making test fixtures part of the production authority model.

One umbrella release may instantiate the schema-opaque registry role more than
once. The primary `registry` instance selects the compute filter specification;
the optional `api-credits-registry` alias selects the API-credit specification.
The alias changes Kubernetes resource identity, while instance-local values
keep signer authority, credential reference, descriptor, API-key posture, and
SQLite volume independent. `global.registryIdentity` remains a compute
storefront trust input rather than a shared signer constraint on every
registry.

## State ownership

Each stateful service owns its database and migration history. Cross-service relationships use public identifiers and APIs rather than foreign keys into another service's database. This keeps backup, rollout, failure, and authority boundaries aligned.

SQLite-backed deployed services use one writer with ReadWriteOnce storage and `Recreate` rollout semantics. Retained, existing, and ephemeral volumes have different durability consequences and must remain explicit deployment choices rather than hidden application behavior.

## Migration and initialization boundary

Schema migration and runtime initialization solve different problems:

- migration deterministically transforms the data model and may seed only rows required by a schema invariant;
- runtime initialization reconciles operator configuration and inventory idempotently without overwriting later operator changes.

Where a service has an explicit migration phase, deployment runs it before application startup and startup verifies schema compatibility rather than mutating the schema. This makes a migration failure diagnosable as deployment preparation instead of an application crash loop. That separation is not yet uniform across every service.

## Artifact and package boundary

Internal Python boundaries are exercised as distributions. Prerequisite packages are built into `.dist`, consumers install from that wheelhouse, and every environment, image, and lock refreshes its internal packages explicitly. Images include `.dist` in the builder stages that resolve internal packages; runtime stages receive only the finished environment.

The refreshed set is derived from each project's lock when the operation runs, never listed. Hand-maintained lists drifted in every place they were kept, and one Makefile silently dropped a package because a help comment continued with a backslash swallowed the flag. A rebuilt wheel keeps its version, so two refreshes are needed: reinstalling replaces installed code, and upgrading re-reads the wheel's metadata so the lock records dependencies the wheel gained. `uv sync --locked` succeeds without the latter and leaves a dependency missing, so project environments upgrade and may rewrite their lock, which is then committed.

Images install that committed lock unchanged, with `--locked`, from a layout that mirrors the project's depth below the repository root; the same derivation reinstalls internal packages so a persistent build cache cannot reuse a same-version build. An image therefore contains what the project's tests ran against. Because `--locked` cannot see a same-version wheel's changed requirements either, the guarantee rests on the lock-currency check comparing each lock's records with the wheels' metadata, not on the build.

One root `.python-version` fixes the interpreter: uv does not read it from a nested project, so every Makefile, CI job, and image reads it explicitly. The conventions and their checks are described in [`BUILD_AND_PACKAGING.md`](../../../docs/development/BUILD_AND_PACKAGING.md).

The architectural purpose is reproducibility: package metadata and wheel contents, not checkout-relative imports, determine what a consumer receives. Pure-Python wheel checks prevent a host-built native artifact from being mistaken for a target-platform image dependency.

## Configuration bootstrap boundary

For compute provisioning and e2e, profile-based Dynaconf construction is a foundation concern where the mechanics are deterministic: trimming the ordered active-profile selector, resolving the base file before profile files, optionally filtering absent include paths, and creating the settings object from explicit options. `arkhai-kit-config` owns those shared mechanics for these two consumers. It deliberately does not read `CONFIG_DIRECTORY` or `ACTIVE_PROFILES`; each composition root remains responsible for process-environment lookup and passes the resulting values into the foundation layer.

Settings and secret files, supported dotenv behavior, environment prefixes, missing-file tolerance, typed wrappers, validators, and exported accessors remain consumer policy. Compute provisioning therefore filters absent YAML includes before construction and uses normal Dynaconf `.env` discovery without adding `.env.local`, while e2e preserves every requested include path, adds its project `.secrets.toml`, and points dotenv loading at the project `.env`. Dotenv-sourced prefixed values participate in Dynaconf's environment layer, with already-set process variables taking precedence. Keeping those differences above the shared bootstrap prevents a code-deduplication change from becoming an implicit configuration migration. Unsupported constructor arguments that never affected runtime behavior are not promoted into the shared contract.

## Bare-metal seller artifact

The bare-metal storefront is a separately installable role distribution and dedicated image. The image installs only staged wheels, runs as an unprivileged user, persists seller state and reservation-to-site routing tables in one role-owned SQLite database, and invokes the `bare-metal-storefront` command. It includes the bare-metal domain and shared storefront, identity, policy, site-client, settlement-runtime, and compute-provisioning client boundaries; it does not include or import the VM storefront implementation.

The role accepts public seller identity and stable site identifiers independently from signer Secrets. Each site record contains an exact canonical authority principal and a private routing URL. Startup parses and validates the entire set before constructing clients or opening the API; database construction applies the role's ordered migrations before serving. The dedicated `helm/charts/bare-metal-storefront` chart references both signer material and the complete site-binding JSON from existing Secrets, mounts one persistent data boundary, and configures `/health` startup, liveness, and readiness probes. Health and operator diagnostics report the canonical seller principal plus each site ID and authority principal, but never a routing URL or signer material.

VM-only, bare-metal-only, and combined deployments select storefront processes independently. A combined seller may connect both processes to the same provisioning authority, but each storefront owns its database, health, service URL, and migration boundary. Disabled roles have no readiness dependency, volume, Secret mount, or service reference from enabled peers.

## Compatibility posture

Schema evolution is additive by default. A non-additive change needs an explicit expand/contract plan that identifies the period in which old and new readers or writers coexist. Public package and wire compatibility similarly belong to the owning capability rather than being inferred from a shared repository version.

## Identity credential delivery

Public identity and secret credentials have different deployment carriers because they have different disclosure and authority properties. Supported public principals and trust pins are safe to render in ordinary profiles and ConfigMaps and must be inspectable so operators can audit the trust target. Possession of a private signing credential grants the ability to impersonate that principal, so it is mounted from an approved Secret boundary and exposed only to the role's composition root when it constructs the signer.

Wallet, RPC, chain, deployed-address, and gas settings describe optional chain effects, not marketplace identity. Keeping them separate prevents Ed25519 and non-EVM payment profiles from acquiring unused chain dependencies or secret material. A role that explicitly uses EIP-191 may share underlying key material with a wallet only when its configuration deliberately selects that arrangement; no role derives one credential from the other.

Startup verifies that private material matches the configured public principal before the role serves authenticated routes, publishes options, negotiates, or submits settlement operations. Rendered arguments, image layers, release artifacts, logs, probes, and examples remain public-safe.

Service-peer profiles carry exact scheme-tagged public principals beside operator-owned site and route bindings. Those bindings select the expected counterparty before verification; request bodies and callers cannot supply or replace the trust target. Each peer receives only its own Secret-backed signer credential, so neither side possesses shared impersonation material.

## Transactional identity cutover

Registry, storefront, and other stateful authorities migrate their own identity-bearing rows through their ordered migration chains. Each migration validates the complete population first, converts valid address-shaped actors to canonical `eip191` principals, preserves cross-service opaque IDs and provider-operation identity, and commits as one service-local transaction. Validation-before-commit prevents a partial ownership graph from becoming authoritative while preserving the durable references needed by other services. Malformed, conflicting, ambiguous, partially related, or drifted state aborts and rolls back the transaction. Versioned buyer run logs follow an explicit equivalent migration before recovery.

Deployment quiesces authenticated mutations while migrations and authority/client upgrades run. Readiness is an identity-contract gate, not merely a process-liveness check: every participating marketplace registry, storefront, and service peer must report the pinned identity capability. A missing or mismatched capability keeps the affected workflow unavailable, because accepting an old proof or allowing a partially migrated writer would make ownership and operation history ambiguous.

Rollback is valid only before the identity schema cutover and before authenticated provider or settlement mutations resume. Once version 2 effects run against migrated identities, recovery rolls forward from the current operation journals and identity history rather than restoring stale databases or run logs.


## Settlement configuration cutover

Role TOML, generated defaults and references, environment overlays, Helm values, Compose, and automation all consume the same typed `[Settlement]` hierarchy; the VM storefront chart passes it through unchanged rather than rendering it key by key. Public mechanism policy and trust pins may render through ordinary configuration; private signer or wallet material comes from approved Secret overlays. Payment-provider, administrator, webhook, ledger database, and service-migration settings remain owned by the payments service and are not marketplace deployment inputs.

The settlement cutover deliberately rejects runtime aliases. Migration tooling is deployed first, then operators preview and back up every affected role file and overlay, quiesce publication and configuration automation, migrate and validate the complete population, and activate the matching image and configuration together. A schema/image mismatch fails before publication or settlement mutation. Rollback restores prior artifacts and backups only before the new configuration is activated; after new effects begin, recovery rolls forward from pinned plans and operation journals.

Typed settlement metadata generates role-appropriate templates, edit validation, environment schema fragments, and reference output. The VM storefront chart's values schema carries one generated definition that refuses secret-marked, role-inapplicable, and unknown typed fields under an agent's pass-through configuration, in any spelling, with no defaults and no required fields. Drift checks keep those surfaces aligned while omitting secrets and role-inapplicable fields.



## Multi-domain storefront activation

The deployment unit is one shared storefront shell, one single-writer SQLite
database, and a set of installed domain contribution wheels. Public config
names each contribution, mode, domain identity, and contract version; trusted
site bindings are independent. Image, Compose, and Helm surfaces install and
render the same set and never embed signer/provider/SSH/private-result data.

Legacy state is an explicit expand/contract boundary, not an automatic startup
guess. Operators quiesce effects, select one migration adapter, inspect its
complete read-only report, then request restrictive backup plus atomic
replacement. Only rows with exact site and pool/resource provenance migrate.
Once common bindings have participated in effects, rollback is forward
recovery using those immutable bindings.



## Arkhai payment consumers

The independently operated payments service owns its ledger, transactions, hold release, fees, disputes, and provider operations. SCM installs `arkhai-kit-arkhai-payments` from `.dist`; its wire models come from the published JSON Schema rather than service implementation imports.

Buyer and seller roles configure the trusted service origin, Ed25519 receipt identity, fee and dispute policy, and a credential environment-variable name under `[Settlement.arkhai_payments]`. WorkOS user-scoped API keys reach only the owning process, separately from marketplace signer Secrets. HTTPS is required outside loopback. Generated public config and images contain no resolved API key, provider object, or payment-service persistence.

Storefront-owned migrations persist exact Agreement bytes and opaque settlement data together in negotiation threads; domain receipt and physical/grant progress remain separately role-owned. VM and bare-metal trust the accepted selected-site provisioner independently of payment trust. API-credit deployments retain a separate credits authority and gated application. Payment-only Ed25519 buyers and sellers require no wallet or chain configuration.

Legacy Stripe consumer settings are rejected, not mapped to Arkhai accounts, mandates, or transaction IDs. Accepted Arkhai recovery uses its original Agreement, mandate, transaction identity, and domain progress rather than a priority fallback.

## Current limits

The repository does not yet have one universal configuration-delivery mechanism or migration phase for every service. Publication authority between private artifact registries and public package releases, removal of all local source overrides, and a repository-wide typed-client versioning policy remain separate decisions.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Testing and compatibility](../test-compatibility/spec.md)
