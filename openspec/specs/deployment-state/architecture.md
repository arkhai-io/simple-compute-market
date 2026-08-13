# Deployment and State Architecture

The [normative contract](spec.md) defines established deployment, persistence, migration, and package behavior. This document explains the operational boundaries those rules protect.

## Role-separated topology

Registry, seller stack, and buyer are independently operable roles. A buyer is normally a one-shot CLI or long-running agent, not a service required to keep the seller stack healthy. A seller composition owns its storefront and physical or quota authorities; a registry may be operated separately.

Local development composes domain stacks with development-only dependencies such as the local chain. Deployment charts compose the same roles conditionally without making test fixtures part of the production authority model.

## State ownership

Each stateful service owns its database and migration history. Cross-service relationships use public identifiers and APIs rather than foreign keys into another service's database. This keeps backup, rollout, failure, and authority boundaries aligned.

SQLite-backed deployed services use one writer with ReadWriteOnce storage and `Recreate` rollout semantics. Retained, existing, and ephemeral volumes have different durability consequences and must remain explicit deployment choices rather than hidden application behavior.

## Migration and initialization boundary

Schema migration and runtime initialization solve different problems:

- migration deterministically transforms the data model and may seed only rows required by a schema invariant;
- runtime initialization reconciles operator configuration and inventory idempotently without overwriting later operator changes.

Where a service has an explicit migration phase, deployment runs it before application startup and startup verifies schema compatibility rather than mutating the schema. This makes a migration failure diagnosable as deployment preparation instead of an application crash loop. That separation is not yet uniform across every service.

## Artifact and package boundary

Internal Python boundaries are exercised as distributions. Prerequisite packages are built into `.dist`, consumers install from that wheelhouse, and reinitialization explicitly upgrades or reinstalls changed distributions. Images include `.dist` in every stage that resolves internal packages.

The architectural purpose is reproducibility: package metadata and wheel contents, not checkout-relative imports, determine what a consumer receives. Pure-Python wheel checks prevent a host-built native artifact from being mistaken for a target-platform image dependency.

## Compatibility posture

Schema evolution is additive by default. A non-additive change needs an explicit expand/contract plan that identifies the period in which old and new readers or writers coexist. Public package and wire compatibility similarly belong to the owning capability rather than being inferred from a shared repository version.

## Identity credential delivery

Public identity and secret credentials have different deployment carriers because they have different disclosure and authority properties. Supported public principals and trust pins are safe to render in ordinary profiles and ConfigMaps and must be inspectable so operators can audit the trust target. Possession of a private signing credential grants the ability to impersonate that principal, so it is mounted from an approved Secret boundary and exposed only to the role's composition root when it constructs the signer.

Wallet, RPC, chain, deployed-address, and gas settings describe optional chain effects, not marketplace identity. Keeping them separate prevents Ed25519 and hosted non-EVM profiles from acquiring unused chain dependencies or secret material. A role that explicitly uses EIP-191 may share underlying key material with a wallet only when its configuration deliberately selects that arrangement; no role derives one credential from the other.

Startup verifies that private material matches the configured public principal before the role serves authenticated routes, publishes options, negotiates, or submits settlement operations. Rendered arguments, image layers, release artifacts, logs, probes, and examples remain public-safe.

Service-peer profiles carry exact scheme-tagged public principals beside operator-owned site and route bindings. Those bindings select the expected counterparty before verification; request bodies and callers cannot supply or replace the trust target. Each peer receives only its own Secret-backed signer credential, so neither side possesses shared impersonation material.

## Transactional identity cutover

Registry, storefront, and other stateful authorities migrate their own identity-bearing rows through their ordered migration chains. Each migration validates the complete population first, converts valid address-shaped actors to canonical `eip191` principals, preserves cross-service opaque IDs and provider-operation identity, and commits as one service-local transaction. Validation-before-commit prevents a partial ownership graph from becoming authoritative while preserving the durable references needed by other services. Malformed, conflicting, ambiguous, partially related, or drifted state aborts and rolls back the transaction. Versioned buyer run logs follow an explicit equivalent migration before recovery.

Deployment quiesces authenticated mutations while migrations and authority/client upgrades run. Readiness is an identity-contract gate, not merely a process-liveness check: every participating registry, storefront, service peer, and hosted authority must report the pinned identity capability. A missing or mismatched capability keeps the affected workflow unavailable, because accepting an old proof or allowing a partially migrated writer would make ownership and operation history ambiguous.

Rollback is valid only before the identity schema cutover and before authenticated provider or settlement mutations resume. Once version 2 effects run against migrated identities, recovery rolls forward from the current operation journals and identity history rather than restoring stale databases or run logs.

## Hosted release ownership

Hosted identity wire behavior belongs to the independently released hosted client. Marketplace packages consume the exact client wheel, hash, identity capabilities, and service artifacts bound by one verified hosted manifest. The manifest is the atomic compatibility boundary: it proves that the client and service agree on identity semantics, while explicit capability checks prevent a version number from being mistaken for support. Editable sibling sources, copied signing modules, compatible-major substitution, or a client/service identity mismatch fail packaging verification or startup preflight before hosted publication.

## Settlement configuration cutover

Role TOML, generated defaults and references, environment overlays, Helm values and templates, Compose, and automation all consume the same typed `[Settlement]` hierarchy. Public mechanism policy and trust pins may render through ordinary configuration; private signer or wallet material comes from approved Secret overlays. Hosted provider, administrator, webhook, database, and service-migration settings remain owned by the hosted authority and are not marketplace deployment inputs.

The settlement cutover deliberately rejects runtime aliases. Migration tooling is deployed first, then operators preview and back up every affected role file and overlay, quiesce publication and configuration automation, migrate and validate the complete population, and activate the matching image and configuration together. A schema/image mismatch fails before publication or settlement mutation. Rollback restores prior artifacts and backups only before the new configuration is activated; after new effects begin, recovery rolls forward from pinned plans and operation journals.

Typed settlement metadata generates role-appropriate templates, edit validation, schema fragments, and reference output. Drift checks keep those surfaces aligned while omitting secrets and role-inapplicable fields.

## Optional hosted local composition

Local hosted composition follows the same artifact boundary as deployment.
Preflight verifies a signed production manifest and exact client wheel, then
emits a non-secret Compose environment containing digest-qualified image and
contract coordinates. Hermetic mode additionally verifies a signed,
production-compatible private E2E manifest and exact service/fixture wheels;
it never treats a locally rebuilt tag or sibling checkout as equivalent.

The production-like, hermetic, local EAS, and real Stripe profiles are
deliberately separate. Hermetic mode substitutes only provider, clock, and
event-delivery ports inside the authority assembly. The storefront remains a
normal wallet-free consumer and receives no simulator control or provider
credential. Local EAS adds chain infrastructure only for condition-boundary
conformance. Real Stripe uses the ordinary authority image and its own
secret-bearing operator lane.

Authority state, deterministic provider state, and controlled time use
separate named volumes. Clean execution removes them; restart evidence retains
them to prove recovery from durable operation identities. Control and provider
surfaces stay on isolated internal networks, while any development host
mapping is explicitly loopback-only.

## Current limits

The repository does not yet have one universal configuration-delivery mechanism or migration phase for every service. Publication authority between private artifact registries and public package releases, removal of all local source overrides, and a repository-wide typed-client versioning policy remain separate decisions.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Testing and compatibility](../test-compatibility/spec.md)
