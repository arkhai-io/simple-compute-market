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

Internal Python boundaries are exercised as distributions. Prerequisite packages are built into `.dist`, consumers install from that wheelhouse, and reinitialization explicitly upgrades or reinstalls changed distributions. Images include `.dist` in every stage that resolves internal packages.

The architectural purpose is reproducibility: package metadata and wheel contents, not checkout-relative imports, determine what a consumer receives. Pure-Python wheel checks prevent a host-built native artifact from being mistaken for a target-platform image dependency.

## Bare-metal seller artifact

The bare-metal storefront is a separately installable role distribution and dedicated image. The image installs only staged wheels, runs as an unprivileged user, persists seller state and reservation-to-site routing tables in one role-owned SQLite database, and invokes the `bare-metal-storefront` command. It includes the bare-metal domain and shared storefront, identity, policy, site-client, settlement-runtime, and compute-provisioning client boundaries; it does not include or import the VM storefront implementation.

The role accepts public seller identity and stable site identifiers independently from signer Secrets. Each site record contains an exact canonical authority principal and a private routing URL. Startup parses and validates the entire set before constructing clients or opening the API; database construction applies the role's ordered migrations before serving. The dedicated `helm/charts/bare-metal-storefront` chart references both signer material and the complete site-binding JSON from existing Secrets, mounts one persistent data boundary, and configures `/health` startup, liveness, and readiness probes. Health and operator diagnostics report the canonical seller principal plus each site ID and authority principal, but never a routing URL or signer material.

VM-only, bare-metal-only, and combined deployments select storefront processes independently. A combined seller may connect both processes to the same provisioning authority, but each storefront owns its database, health, service URL, and migration boundary. Disabled roles have no readiness dependency, volume, Secret mount, or service reference from enabled peers.

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

## Protected hosted test composition

Hosted financial system E2E follows the production supply-chain boundary.
Preflight verifies one signed production manifest and its exact client wheel,
service image, migration schema, OpenAPI/conformance artifacts, provenance,
signed release repository and workflow reference, and hosted source commit. It
then emits non-secret
Compose coordinates with a digest-qualified image. A local tag, sibling
checkout, editable source, alternate service distribution, or compatible-major
substitution is not equivalent.

Those coordinates divide into two groups that carry different weight. Provenance
— manifest digest, wheel and artifact hashes, source commit, repository,
workflow reference, and release authority — says who published a half and from
what. Contract — release and API version, migration schema, funding profiles,
and capabilities — says what that half serves. Only the first has no answer
outside a release, and only the first is what a protected run's evidence rests
on. The second is a property of the build, and a build made from a working tree
states it as completely as a release does.

A development run turns on that distinction. Either half may be a published
release or an image the operator built, in any combination; a locally built half
renders the same key set with its provenance group empty and its contract group
read from the artifacts that build generated. Empty is the record: it is visible
in the environment itself rather than only in a mode flag, so a development
environment cannot be mistaken for an attested one by inspection. Any local half
makes the whole run a development run.

The contract a run asserts is read from the release it bound, never restated in
the harness, the preparer, or the Compose readiness check. A contract written
down in any of those places admits exactly one release: the next one is refused
as a corrupt environment or an unready authority, which is indistinguishable
from a genuine mismatch. What is enforced is unchanged — the composed authority
must serve what the run bound, before any service is created — and for a
released half the artifact that expectation is read from is covered by the same
signature as before.

That rule holds on the consumer side too, and holds all the way down. The
storefront and buyer configurations a run renders take their API version,
migration schema, and capability set from the release the run bound, alongside
the manifest digest they already took from it; the committed templates state
none of the three, and an enabled configuration that reaches readiness without
them is unready and says which pin is absent. The consumer's own required
capability set remains its own — it is a floor describing what this marketplace
needs, and a newer release declaring more is admitted rather than refused. The
build derives the client wheel, OpenAPI, conformance, and migration filenames
from the trust configuration that names the release, so choosing a release is
stated once and what follows from it is not restated beside it.

The same rule reaches the wire. The health model a consumer parses carries the
API version and schema version as values, not as types admitting one release,
so a consumer holding one release's client can read another release's readiness
response and report the disagreement as a disagreement. A type that admits one
release turns a version mismatch into an unparseable response and denies the
consumer the one thing it is there to say.

The protected composition starts only the ordinary hosted migration, API, and
reconciliation worker roles against Stripe test mode. The marketplace reaches
the authority through the released client and public authority address; it
does not receive provider or administrator access. Stripe CLI forwards signed
events only to a loopback authority mapping, and Chromium drives the transient
Checkout action without persisting it.

Authority state uses one durable volume. Clean scenarios remove it, while
explicit restart and missed-webhook scenarios retain it so the API or worker
can reconcile authoritative Stripe state under the original durable operation
and idempotency identities. The composition has no second provider, test clock,
event-control service, synthetic provider worker, control network, fixture
release, or test-only production entry point.

Preflight is a mutation boundary. It verifies the exact marketplace commit and
hosted release, test-mode credentials and returned objects, Stripe
connectivity, allowlisted connected-account ownership and capabilities,
loopback webhook delivery, and browser availability before publication or
financial mutation. Each credential is delivered only to its consuming role.
The default and fork workflows receive none of them.

Protected evidence keeps consumer and producer identity independent: the
marketplace repository and exact commit are reported separately from the
hosted manifest digest, client wheel hash, image digest, signed release
repository/workflow reference/source commit, and the separate protected
producer workflow run identity used as orchestration evidence. Reports are
schema-validated allowlists;
they exclude secrets, action URLs, provider account/customer/card data, raw
webhooks, and unrestricted service or provider payloads.

Alkahest E2E remains an independent mechanism composition. Local
EAS/allowlisted-arbiter validation is a condition-boundary concern, not a
hosted financial-provider profile; this repository currently exposes no
standalone hosted local-EAS operator target.

## Expanded consumer cutover and rollback

The expanded consumer activates as one compatibility set: exact hosted client wheel, signed manifest, API `0.2.1`, schema `5`, payer-profile and purchase-authorization capabilities, three exact funding profiles, service image coordinate, marketplace config, and role-scoped signer Secrets. Config migration converts new-publication card method input to `card.v1` clauses and refuses ambiguity; historical accepted card rows remain a recovery concern rather than a runtime alias.

The buyer profile store does not change schema for expanded funding. Its schema-1 authority binding already stores the complete safe consumer projection—authority, environment, opaque binding reference, bound principal, and lifecycle state—so consumer commands update that owner-only field atomically rather than migrating profiles or adding instrument, provider, action, or commercial state. The settlement database separately migrates accepted hosted obligations because it owns immutable profile, authorization, legacy classification, and recovery identity.

Marketplace deployment carries only public authority trust, exact release pins, account/condition references, profile/currency/country policy, local buyer profile locations, and marketplace signer Secret references. Provider credentials, Customer/PaymentMethod/mandate data, stable instrument state, webhooks, hosted databases/migrations, reconciliation, and provider recovery remain outside marketplace packages and workloads.

Before activation, rollback restores the matching prior client, config, image coordinates, and Secret mapping together. After new profile publication or purchase authorization occurs, rollback cannot reinterpret accepted state; operators roll forward using immutable obligation, authorization, and hosted operation identities. Protected profile evidence requires every signed producer artifact and selected Stripe rail prerequisite.

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

## Bare-metal hosted topology

The bare-metal buyer and storefront remain separate released wheels and role processes. The buyer contribution reads only strict public registry/trust/default configuration and resolves its signer from the core profile service. The storefront mounts one shared settlement JSON Secret containing public authority/account/trust/release settings. Hosted-only startup leaves the EVM address empty and creates no wallet, RPC, chain, or Alkahest client. Compose and Helm carry selected-site bindings and provisioning trust separately from financial trust; neither surface mounts Stripe, payer-profile, provider, or buyer SSH private material.

The storefront database owns accepted hosted-binding and bare lifecycle migrations in the role's ordered migration set. Activation may disable hosted before effects; after an accepted hosted mutation, recovery keeps the compatible artifact/config set pinned until financial and physical operation journals are safe. Protected activation additionally verifies the independently signed hosted release and disposable target before publication.

## API-credit hosted topology

The deployable API-credit path consists of independent registry, credits
authority, gated application, storefront, buyer/driver, portable evidence
resolver, and hosted authority roles. Hosted-only buyer/storefront composition
uses Ed25519 marketplace signer Secrets and has no wallet/chain volume. The
marketplace images install the hosted consumer and shared runtime wheels but do
not receive Stripe/provider credentials or hosted persistence.

The credits authority owns canonical owner, immutable fulfillment/grant
digests, key hashes, balance, quota, credential, and consumption migrations.
The storefront owns accepted negotiation, settlement operation, private
buyer-result, and signed issuance-evidence migrations. Public configuration
pins authority/manifest/client/API/schema/capabilities, exact funding profiles,
seller account and evidence resolver. Rollback is safe before accepted hosted
effects; afterward both authorities recover forward under their immutable
identities.

## Current limits

The repository does not yet have one universal configuration-delivery mechanism or migration phase for every service. Publication authority between private artifact registries and public package releases, removal of all local source overrides, and a repository-wide typed-client versioning policy remain separate decisions.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Testing and compatibility](../test-compatibility/spec.md)
