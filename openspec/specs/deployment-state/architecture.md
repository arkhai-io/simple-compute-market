# Deployment and State Architecture

The [normative contract](spec.md) defines established deployment, persistence, migration, and package behavior. This document explains the operational boundaries those rules protect.

## Independently operated topology

Registry, seller stack, and buyer are operated independently. A buyer is normally a one-shot CLI or long-running agent, not a service required to keep the seller stack healthy. A seller composition owns its storefront and physical or quota authorities; a registry may be operated separately.

Local development composes domain stacks with development-only dependencies such as the local chain. Deployment charts compose the same services conditionally without making test fixtures part of the production authority model. The payments lane double is such a fixture: the end-to-end lanes run it, and the local release enables its subchart through its own values so that payments are configured through exactly the values a deployment supplies — agent configuration, the runtime secret overlay, the CA bundle option — never through a development-only mode. Release values never enable it.

Each stack's configuration is in committed overlay, profile and secret-overlay files; a Makefile selects which configuration loads and carries none of it, and a base Compose file holds only what its topology fixes, with no committed fallback for a credential or definition document, so a base stack without its overlay refuses to start rather than running on development values.

One umbrella release may instantiate the schema-opaque registry service more than
once. The primary `registry` instance selects the compute filter specification;
the optional `api-credits-registry` alias selects the API-credit specification.
The alias changes Kubernetes resource identity, while instance-local values
keep signer authority, credential reference, descriptor, API-key posture, and
SQLite volume independent. `global.registryIdentity` remains a compute
storefront trust input rather than a shared signer constraint on every
registry.

## State ownership

Each stateful service owns its database and migration history. Cross-service relationships use public identifiers and APIs rather than foreign keys into another service's database. This keeps backup, rollout, failure, and authority boundaries aligned.

SQLite-backed deployed services use one writer with ReadWriteOnce storage and `Recreate` rollout semantics. Retained, existing, and ephemeral volumes have different durability consequences and must remain explicit deployment choices rather than hidden application behavior. The Helm charts make retention one such choice, `persistence.retainOnUninstall`, which local development deployments turn off so a reinstall starts from no state (see [`DEPLOYMENT_AND_CONFIG.md`](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#stateful-service-persistence)).

## Migration and initialization boundary

Schema migration and runtime initialization solve different problems:

- migration deterministically transforms the data model and may seed only rows required by a schema invariant;
- runtime initialization reconciles operator configuration and inventory idempotently without overwriting later operator changes.

Every stateful service — compute provisioning, the VM, bare-metal, API-credit and inference storefronts, the API-credit and inference services, and the registry — has an explicit migration phase. Its packaged command, `<service command>-migrate`, applies its chain; a Helm chart runs it as an init container from the application's image over the application's configuration and data volume, and Compose runs it before the application in the same container (`sh -c "<service>-migrate && exec <service command>"`, stated by the stack or, for the inference service and storefront, by the image's own command). The application's startup only checks: it opens the database read-only, issues no DDL, and refuses anything but a compatible database with a message naming the command and the migration IDs that differ. A migration failure is therefore deployment preparation that fails visibly, not an application crash loop, and `--check` lets an operator see what an upgrade will apply, or verify a restored backup, without changing anything. A migration command reads only its database location and log level, so a migration takes only its database and applies identically under every configuration; configuration-driven seeding, such as the API-credit service's `default` pool, runs at startup once the check passes.

### One engine, one contract

The in-house services use one engine, `kit/schema-migrations` (`market_schema_migrations`), a market-neutral foundation kit: a `Migration` is an ID and a function of a connection, a `Chain` names its service, its command, its baselines, its later migrations and its floor, and `migrate` applies each pending migration and records its ID in the `schema_migrations` ledger in one transaction, so a failed migration leaves the migrations before it recorded and no trace of itself. Adapters serve a `sqlite3` connection and a SQLAlchemy connection. Every package that owns tables exports its migrations, and each service's composition declares its chain from them in a fixed order — core storefront, each composed kit, the domain — so the composition owns ordering, and a kit present in two databases, such as `kit/site` in compute provisioning's and the API-credit service's, contributes the same migrations to both.

A chain's floor is a required `Floor`: the release the chain is supported from, by its whole name, since the kit names no market, and the IDs that release's chain recorded. The engine refuses to construct a chain without one, so a chain missing its floor fails every import and every test of its service; a test's chain declares one too, since a default floor, even for tests, would reopen the way around the requirement. Floors may differ between chains, each the release that chain is supported from. A chain with no earlier history declares `Floor("0.0.0")`, recording nothing, and adopts no database. The constructor holds only that a floor is declared: that it is the right one is held by each service's chain test comparing it with its floor fixture, and, for a new chain, by guidance and review. A repository test deriving each service's chain from its command and checking its floor was rejected, since it would reach into every service's layout across the package layers. Every result names the floor release, the registry's from its own floor, so one `refusal_message` words every service's refusals without knowing its chain.

The registry keeps Alembic, its route to PostgreSQL, and maps its revision onto the same check result and refusal message, behind the same command form and deployment phase. The operator-facing contract — command, `--check`, result, message, phase — does not depend on the engine, so the in-house services can later adopt Alembic, from a baseline, by replacing only the kit's engine. Alembic was not adopted for them now: its decisive advantage, portability between databases, is unused while they are single-writer SQLite.

### Compatibility is the exact set

The check compares the recorded IDs with the chain, and only equality is *compatible*. Fewer is *behind*, listing what is pending. A database recording the chain's baselines and an ID the chain does not list is *ahead* — for the registry, which records only its head, one revision that is neither in its chain nor in its history up to its floor revision — listing the unknown IDs and any pending ones. Only an image newer than this one leaves such a ledger, since every image of the engine records the baselines, whether it builds a database or adopts one: this image cannot vouch for the database, and the remedy is the backup or the image that wrote it, so the command refuses it and applies nothing, rather than deepening the divergence. No file, or no table but an empty ledger, is *absent*. Anything else holding tables is *unsupported*, for one of two causes, and its refusal says only what the ledger shows:

- **Older than the floor, or another service's sharing its history:** a ledger recording some of the floor's IDs but not all and none of the baselines, or a registry revision of its history before its floor. Every chain shares one ledger table and the three storefronts share core storefront's migrations, so another storefront's floor database records most of this one's floor and cannot be told by its ledger from an older database of this service's own. The refusal names the floor release and the IDs the database lacks, says the command cannot tell the two apart, and directs the operator, once the database is confirmed as the service's, to upgrade it through the floor release first.
- **Not this chain's database:** tables with no ledger, a ledger recording none of the floor's IDs — every non-empty database a `0.0.0` chain did not build among them — or, for the registry, more than one recorded revision, which no registry image leaves. The command did not build it, so the refusal names neither a fresh database nor an upgrade.

Reserving the upgrade instruction for each chain's known pre-floor IDs was rejected: it is release history kept by hand, and the IDs the storefronts share defeat it anyway. So was one neutral refusal for every unsupported ledger, which would withhold the remedy from an older database of the service's own. An image rolled back over a migrated database is therefore refused, and recovery is restoring the pre-upgrade backup or rolling forward. A last-ID check, which this replaces, let an older image serve a database a newer release had changed, and passed a table added without a migration.

Shape is held by tests rather than at startup: each service's chain run on a fresh database reproduces its committed floor fixture with its later migrations applied, and opening every store of a migrated storefront leaves its schema unchanged ([`migration-chain-tests.md`](../../../docs/guidance/repository/migration-chain-tests.md)). Nothing issues DDL outside a chain: constructing a database client, opening a store, or starting an application changes no schema, so a table a store needs is created by a migration.

### The baseline and adoption

Each in-house chain begins with baseline migrations, one per package whose tables the database holds, whose bodies are fixed DDL — not `create_all` over current models, which would change silently with every model edit. For compute provisioning, the VM, bare-metal and API-credit storefronts, and the API-credit service the baselines reproduce the schema the marketplace v0.3.0 release builds at startup, the API-credit service's but for one index (below); the registry's chain begins with one Alembic revision, `v0_3_0_baseline`, reproducing its v0.3.0 schema. Every in-house chain's floor is marketplace 0.3.0. Each floor is a committed fixture generated by running the release's published packages on a fresh database.

A database the floor release ran on — one recording every migration ID the v0.3.0 chain recorded and none of the baselines, or, for the registry, at revision `018_listing_resource_column` — is *behind* with its baseline to be adopted, whatever else it records. The command adopts it in one transaction: it forgets every recorded ID the chain does not list, the floor's and any others, and records the baseline IDs without running the baselines, then applies the migrations after the baseline. `--check` names the floor release whose records adoption replaces, lists every other record it sets aside, and lists the pending migrations, so an operator verifying a backup sees the IDs that differ between databases. The floor's own records are named by their release rather than listed: they are the same on every database the floor release built, and committed in each floor fixture.

The rule exists because v0.3.0's runner applied its own list and ignored every other record, so a database an earlier release built and v0.3.0 then ran on carries records v0.3.0 retired: seven, on a VM storefront database built under v0.2.x. It is sound by construction. No image of the engine leaves a ledger without the baselines, so an extra record on a database recording none was written in the floor release's era or before it, never by a newer image. It is a permanent rule of every floor, not a path for v0.3.0 alone, and so it has no retirement. Adoption rests on recorded IDs alone, with no schema inspection. Declaring each chain's retired records was rejected: it is release history kept by hand, and a single miss strands a deployment. So was checking the schema at adoption, since v0.3.0 databases legitimately differ. The cost of declaring nothing is that the image vouches for records it cannot name. Where a forgotten migration created what a later migration also creates, that later migration fails in its own transaction, named, and the preview listed the record beforehand.

A database older than the floor upgrades through the floor release first — that release's service run on it — and then to the current release. The chain carries no history before its floor, since the floor release carries it, nor the unversioned bootstrap the storefronts once ran before their chains. Starting fresh is never the remedy for a database that can upgrade, since it discards the deployment's state.

Recorded IDs prove a chain ran, not what a release created outside it. A v0.3.0 storefront created some tables when a store first opened — deal servicing's journal tables first appear at a deal's delivery, and the bare-metal lifecycle cursor when its lifecycle store opens — so an adopted database may lack them. One migration after each storefront's baseline creates those tables and their indexes with `IF NOT EXISTS`, the only migration that tolerates objects already present; on a fresh database it simply creates them. Data a supported database holds that the release cannot serve is likewise repaired by an ordinary migration after the baseline: compute provisioning's rewrites every host's `ssh` connection stored at version 1, which the v0.3.0 chain wrote and v0.3.0 refuses, to version 2 ([physical provisioning](../physical-provisioning/architecture.md#the-host-registry-owns-the-connection)). The tables v0.3.0 kept frozen for extraction — VM's earlier inventory tables and bare metal's accepted site generations — are dropped by a migration after the baseline. So, where present, are the tables an earlier release's retired migrations created and nothing reads: the VM storefront's `derived_compute_listings`, the listing-to-site mapping `storefront_listing_bindings` holds, and bare metal's `bare_metal_hosted_lifecycle`, the hosted-card lifecycle no release since v0.3.0 reads. Adoption issues no DDL, so it drops nothing itself. Migrations a later change adds go after the baseline too.

A database that reached the floor by upgrading may differ from a fresh one where SQLite cannot repair it safely. The columns v0.3.0 appended by `ALTER TABLE` to the VM storefront's `negotiation_threads`, a table an earlier release created, come last rather than mid-table. Every read and write addresses them by name. Reordering them would rebuild a table three others reference, which no migration can do safely, because SQLite ignores `PRAGMA foreign_keys` inside the engine's transaction. The VM storefront's chain test, over a real database v0.2.29 built and v0.3.0 then ran on, names that difference and otherwise ends with a fresh database's schema and ledger.

The API-credit service's baselines include the site ledger's, written from compute provisioning's v0.3.0 schema, which names the index `uq_capacity_buckets_host_id`. The v0.3.0 service built the ledger from its models without it, although the table's own `UNIQUE (host_id)` enforces the same rule. A kit contributes the same migrations to every chain composing it, so the baseline is not forked. Instead the site ledger exports a repair, `20261126_001_capacity_bucket_host_index`, which it leaves out of its `MIGRATIONS` and which only the API-credit service's chain composes, after them. The repair drops the index where present and creates it, so a fresh database ends unchanged and an adopted one gains it. Only its drop tolerates absence. That chain's baseline test names the difference, as the exception beside this document records ([Migration chains](migration-chains.md)).

The API-credit storefront and service are a pair. The service holds the keys, request-digested grants and balances that the storefront's issued credentials refer to. Both therefore have the floor, and an existing pair upgrades in place together, never one started fresh beside the other. They upgrade in the order their Compose deployment already enforces, with no coordination of their own. The storefront depends on the service being healthy, and each container runs its migration before its application, so the service migrates first. A failed service migration leaves the storefront not started and its database untouched. A failed storefront migration after the service adopted leaves the storefront not started, so no credential is issued against a mixed pair, and recovery is the earlier release over both backups.

The floor is a release-time decision: whether a later release becomes a new floor is weighed when it is promoted ([the release handbook, "The migration floor"](../../../docs/release-handbook.md#the-migration-floor)).

## Artifact and package boundary

Internal Python boundaries are exercised as distributions. Prerequisite packages are built into `.dist`, consumers install from that wheelhouse, and every environment, image, and lock refreshes its internal packages explicitly. Images include `.dist` in the builder stages that resolve internal packages; runtime stages receive only the finished environment.

The refreshed set is derived from each project's lock when the operation runs, never listed. Hand-maintained lists drifted in every place they were kept, and one Makefile silently dropped a package because a help comment continued with a backslash swallowed the flag. A rebuilt wheel keeps its version, so two refreshes are needed: reinstalling replaces installed code, and upgrading re-reads the wheel's metadata so the lock records dependencies the wheel gained. `uv sync --locked` succeeds without the latter and leaves a dependency missing, so project environments upgrade and may rewrite their lock, which is then committed.

Images install that committed lock unchanged, with `--locked`, from a layout that mirrors the project's depth below the repository root; the same derivation reinstalls internal packages so a persistent build cache cannot reuse a same-version build. An image therefore contains what the project's tests ran against. Because `--locked` cannot see a same-version wheel's changed requirements either, the guarantee rests on the lock-currency check comparing each lock's records with the wheels' metadata, not on the build.

One root `.python-version` fixes the interpreter: uv does not read it from a nested project, so every Makefile, CI job, and image reads it explicitly. The conventions are [`python-version.md`](../../../docs/guidance/repository/python-version.md) and the packaging files beside it, and their checks [`packaging-checks.md`](../../../docs/guidance/repository/packaging-checks.md).

The architectural purpose is reproducibility: package metadata and wheel contents, not checkout-relative imports, determine what a consumer receives. Pure-Python wheel checks prevent a host-built native artifact from being mistaken for a target-platform image dependency.

## Configuration bootstrap boundary

For compute provisioning and e2e, profile-based Dynaconf construction is a foundation concern where the mechanics are deterministic: trimming the ordered active-profile selector, resolving the base file before profile files, optionally filtering absent include paths, and creating the settings object from explicit options. `arkhai-kit-config` owns those shared mechanics for these two consumers. It deliberately does not read `CONFIG_DIRECTORY` or `ACTIVE_PROFILES`; each composition root remains responsible for process-environment lookup and passes the resulting values into the foundation layer.

Settings and secret files, supported dotenv behavior, environment prefixes, missing-file tolerance, typed wrappers, validators, and exported accessors remain consumer policy. Compute provisioning therefore filters absent YAML includes before construction and uses normal Dynaconf `.env` discovery without adding `.env.local`, while e2e preserves every requested include path, adds its project `.secrets.toml`, and points dotenv loading at the project `.env`. Dotenv-sourced prefixed values participate in Dynaconf's environment layer, with already-set process variables taking precedence. Keeping those differences above the shared bootstrap prevents a code-deduplication change from becoming an implicit configuration migration. Unsupported constructor arguments that never affected runtime behavior are not promoted into the shared contract.

The registry takes the same resolver variables without the shared bootstrap. Its settings are a `pydantic_settings` class, not Dynaconf, so it parses `ACTIVE_PROFILES` itself and layers `config-<profile>.env` dotenv files from `CONFIG_DIRECTORY` after its default dotenv files, a later profile winning and the process environment above every file. The files therefore have provisioning's selection and layering but not its format; moving the registry onto the shared bootstrap would change only the profiles' format. Its chart renders its values into one such profile and layers an operator's `secretProfile` after it, as the provisioning chart renders its YAML profile.

## Bare-metal seller artifact

The bare-metal storefront is a separately installable service distribution and dedicated image. The image installs only staged wheels, runs as an unprivileged user, persists seller state and reservation-to-site routing tables in one SQLite database of its own, and invokes the `bare-metal-storefront` command. It includes the bare-metal domain and shared storefront, identity, policy, site-client, settlement-runtime, and compute-provisioning client boundaries; it does not include or import the VM storefront implementation.

The service accepts public seller identity and stable site identifiers independently from signer Secrets. Each site record contains an exact canonical authority principal and a private routing URL. Startup checks that `bare-metal-storefront-migrate` has migrated its database, then parses and validates the entire set before constructing clients or opening the API. The dedicated `helm/charts/bare-metal-storefront` chart references both signer material and the complete site-binding JSON from existing Secrets, mounts one persistent data boundary, and configures `/health` startup, liveness, and readiness probes. Health and operator diagnostics report the canonical seller principal plus each site ID and authority principal, but never a routing URL or signer material.

VM-only, bare-metal-only, and combined deployments select storefront processes independently. A combined seller may connect both processes to the same provisioning authority, but each storefront owns its database, health, service URL, and migration boundary. Disabled services have no readiness dependency, volume, Secret mount, or service reference from enabled peers.

## Compatibility posture

Schema evolution is additive by default. A non-additive change needs an explicit expand/contract plan that identifies the period in which old and new readers or writers coexist. Public package and wire compatibility similarly belong to the owning capability rather than being inferred from a shared repository version.

Persisted accepted evidence can outlive the writer that produced it. Preserve its protocol-owned representation while records remain retained, and make any incompatible reader or writer transition explicit across the supported lifetime. A typed application view is derived from the verified representation; it does not replace the retained bytes or relax digest/signature checks. Deletion, tombstoning, and reader support floors remain owned by the relevant capability. Zero nonterminal contracts does not establish that a reader is unused: retained terminal evidence and supported buyer recovery may still require it. This bounded rule does not establish cross-domain artifact discovery or automatic retirement tooling.

## Identity credential delivery

Public identity and secret credentials have different deployment carriers because they have different disclosure and authority properties. Supported public principals and trust pins are safe to render in ordinary profiles and ConfigMaps and must be inspectable so operators can audit the trust target. Possession of a private signing credential grants the ability to impersonate that principal, so it is mounted from an approved Secret boundary and exposed only to the role's composition root when it constructs the signer.

Wallet, RPC, chain, deployed-address, and gas settings describe optional chain effects, not marketplace identity. Keeping them separate prevents Ed25519 and non-EVM payment profiles from acquiring unused chain dependencies or secret material. A role that explicitly uses EIP-191 may share underlying key material with a wallet only when its configuration deliberately selects that arrangement; no role derives one credential from the other.

Startup verifies that private material matches the configured public principal before the role serves authenticated routes, publishes options, negotiates, or submits settlement operations. Rendered arguments, image layers, release artifacts, logs, probes, and examples remain public-safe.

Service-peer profiles carry exact scheme-tagged public principals beside operator-owned site and route bindings. Those bindings select the expected counterparty before verification; request bodies and callers cannot supply or replace the trust target. Each peer receives only its own Secret-backed signer credential, so neither side possesses shared impersonation material.

## Transactional identity cutover

Every stateful service's supported database already holds canonical principals: the conversion of address-shaped actors to canonical `eip191` principals is part of each service's v0.3.0 floor, and a database from before it is refused as unsupported. Authorities still reject old schema, old signature versions, drift, ambiguous principals, and partially migrated state rather than reinterpreting them. Versioned buyer run logs follow an explicit migration before recovery.

Deployment quiesces authenticated mutations while authority and client upgrades run. Readiness is an identity-contract gate, not merely a process-liveness check: every participating marketplace registry, storefront, and service peer must report the pinned identity capability. A missing or mismatched capability keeps the affected workflow unavailable, because accepting an old proof or allowing a partially migrated writer would make ownership and operation history ambiguous.

Rollback is valid only before the identity schema cutover and before authenticated provider or settlement mutations resume. Once version 2 effects run against migrated identities, recovery rolls forward from the current operation journals and identity history rather than restoring stale databases or run logs.


## Settlement configuration cutover

Storefront and buyer TOML, generated defaults and references, environment overlays, Helm values, Compose, and automation all consume the same typed `[Settlement]` hierarchy; the storefront charts pass it through with null-valued keys removed rather than rendering it key by key. A values-file `null` means removal independently of Helm's merge behavior; the chart's schema accepts it for accepted keys while continuing to refuse secret and retired keys. See [the storefront chart contract](spec.md#requirement-a-storefront-chart-passes-service-configuration-through) and [operator configuration](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration). Public mechanism policy and trust pins may render through ordinary configuration; private signer, wallet, and a storefront's payments-key and dispute-credential material come from approved Secret overlays, never from an environment variable a configuration names; only the buyer's payments key is named by variable, for its own provider. Payment-provider, administrator, webhook, ledger database, and service-migration settings remain owned by the payments service and are not marketplace deployment inputs.

The settlement cutover deliberately rejects runtime aliases. Migration tooling is deployed first, then operators preview and back up every affected configuration file and overlay, quiesce publication and configuration automation, migrate and validate the complete population, and activate the matching image and configuration together. A schema/image mismatch fails before publication or settlement mutation. Rollback restores prior artifacts and backups only before the new configuration is activated; after new effects begin, recovery rolls forward from pinned plans and operation journals.

Typed settlement metadata generates role-appropriate templates, edit validation, environment schema fragments, and reference output. Each storefront chart's values schema carries a generated definition that refuses secret-marked, role-inapplicable, and unknown typed fields under the pass-through configuration, in any spelling, with no defaults and no required fields; the storefronts' generators also refuse the payments `api_key_env` and every `[[DisputeCredential]]` entry there, since no variable the chart sets holds a key and a credential entry is incomplete without its token. Drift checks keep those surfaces aligned while omitting secrets and role-inapplicable fields.

A chart passing a service's configuration through carries no schema of that configuration, which the service validates at startup ([`helm.md`, "A chart's values schema types the chart's own values"](../../../docs/guidance/engineering/helm.md#a-charts-values-schema-types-the-charts-own-values)): the provisioning chart's schema refuses under its `config` only the keys the chart derives itself or delivers from a Secret, and retired ones, so a section the service adds, such as `[Events]`, deploys through values alone. The storefront charts' generated definitions stand in for refusals the storefront's loader does not yet make — a secret in its public file, an unknown key, a key stated in two spellings — and no requirement asks for them. Moving those refusals into the loader and removing the definitions, their generator runs and drift tests is unowned work recorded in the [change index](../../changes/README.md), as is the provisioning loader's refusal of a secret sink setting stated in its public profile.



## Multi-domain storefront activation

The deployment unit is one shared storefront shell, one single-writer SQLite
database, and a set of installed domain contribution wheels. Public config
names each contribution, mode, domain identity, and contract version; trusted
site bindings are independent. Image, Compose, and Helm surfaces install and
render the same set and never embed signer/provider/SSH/private-result data.
The composition's chain runs core storefront's migrations, then each composed
kit's, then each domain's; the database records one chain, and once common
bindings have participated in effects, rollback is forward recovery using those
immutable bindings.



## Arkhai payment consumers

The independently operated payments service owns ledger, transactions, hold
release/extensions, fees and provider operations. The independent Agreement-named
dispute authority owns cases, outcomes and their payment effects. SCM installs `arkhai-kit-arkhai-payments` from `.dist`; its wire models come from the published JSON Schema rather than service implementation imports.

Buyer and seller roles configure trusted payment origin, Ed25519 receipt identity,
fee policy, an optional CA bundle path and the API key under
`[Settlement.arkhai_payments]`. A storefront states its key as `api_key` in its
secret overlay, which a deployment supplies from a Secret; a buyer names the
environment variable its provider reads with `api_key_env`. One key resolution
serves the client, readiness and the payments check, and the CA bundle is trusted
by the payments client alone, never by replacing the process's trust store. Ordered
root `[[Dispute]]` preferences and separate full-identity `[[DisputeCredential]]`
bindings configure dispute participation; a storefront's credential entries, token
included, live in its secret overlay, and the mediation client receives the token
the entry resolved rather than reading the environment itself. Because readiness
never contacts the payments service, each storefront CLI's `check-payments` reads
the seller's own balance from the storefront's container, proving its CA mount,
key and service URL together; the storefront charts render it as a Helm test.
For the same reason — the VM storefront builds its mediation client only at a
payment deal's first dispute servicing — its `check-mediation --origin` makes one
authenticated respondent read at a named dispute authority with the credential
the storefront would use, its `ca_bundle_path` included, from its own container,
asserting nothing about the answer; the VM storefront chart renders it as a Helm
test where an agent names the authority to check. A dispute credential names its
own CA bundle, trusted by that authority's mediation client alone. The local
release copies Bob's credential from his Compose overlay into a runtime Secret
the chart never renders, so the out-of-band step that writes the Secret rewrites
the copy's `ca_bundle_path` to the chart's CA file, and the Helm test proves the
rewrite, the Service name, the certificate's name and the token together. The
payments and mediation lane doubles run only where the local release's values
enable their subcharts; release values never do.
Signed registry descriptors may recommend authorities; buyers explicitly opt in,
local identity vetoes prevail and recommendations stay registry-specific. WorkOS user-scoped API keys reach only the owning process, separately from marketplace signer Secrets. HTTPS is required outside loopback. Generated public config and images contain no resolved API key, provider object, or payment-service persistence.

Storefront-owned migrations persist exact Agreement bytes and opaque settlement data together in negotiation threads; domain receipt and physical/grant progress remain separately owned by their own services. VM and bare-metal trust the accepted selected-site provisioner independently of payment trust. API-credit deployments retain a separate credits authority and gated application. Payment-only Ed25519 buyers and sellers require no wallet or chain configuration.

Legacy Stripe consumer settings are rejected, not mapped to Arkhai accounts, mandates, or transaction IDs. Accepted Arkhai recovery uses its original Agreement, mandate, transaction identity, and domain progress rather than a priority fallback.

## Lifecycle state and coordinated rollout

Seller evidence, end/admission/effect journals and cursors live in the storefront's
own database and ordered migrations. Buyer exact-byte evidence and retry plans
live under a composition-supplied profile-adjacent root, not in replay caches.
The site's lease-end records, its signed lease-end reports and the provisioning
service's event store live in provisioning persistence, where a lease-end report's
delivery and a capacity-released callback's belong to separate consumers, each
acknowledged on its own. These stores contain evidence or physical
progress, never a copy of authority ledger/case state to decide money from.

The option envelope is a forward-only wire boundary: coordinate registries,
storefronts and buyer clients, republish every mechanism's listings and discard
incompatible disposable accepted state only with explicit operator ownership.
No old-key reader or priority failover reinterprets an accepted deal. Site/report
receiver and buyer/end endpoint pairs upgrade together; there is no legacy
teardown fallback. Unsupported report pushes park for the original peer and
remain recoverable by authenticated pull until explicit resumption after upgrade.

Payment receipt pins support bounded current/retiring identity windows. Dispute
origin/record-key pins do not: accepted deals remain bound to the old origin/key,
including unbounded case life. Public renderings contain public trust projections,
not credential references or resolved secrets. See
[operator authority configuration](../settlement-configuration/configuration.md#dispute-authority-preferences).

## Current limits

The repository does not yet have one universal configuration-delivery mechanism for every service. The in-house migration engine serves single-writer SQLite only; a service moved to PostgreSQL or to more than one writer adopts Alembic from a baseline, as the registry already uses it. Adoption trusts recorded IDs and does not inspect schema, so a supported database altered by hand outside its chain is not detected at startup. Removal of all local source overrides and a repository-wide typed-client versioning policy remain separate decisions.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Testing and compatibility](../test-compatibility/spec.md)
