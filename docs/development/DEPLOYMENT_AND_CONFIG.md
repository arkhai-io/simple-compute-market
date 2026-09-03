# Configuration and Deployment

This document defines how services in this repository resolve
configuration and how that resolution maps onto Kubernetes deployment.
It is distinct from `docs/configuration.md`, which documents the
negotiation/fulfillment *policy plugin* system (how a seller or buyer
writes a custom pricing or negotiation hook) — a different, unrelated
meaning of "configuration." This document is about how a service reads
its own settings at startup and how an operator supplies them.

Read this alongside `docs/development/ARCHITECTURE.md` (system shape)
and `openspec/README.md` (documentation placement). Like those
documents, this one describes current practice and should be corrected
in place when practice changes, not layered with historical commentary.

## Profile-based configuration

Every service in this repository uses the same configuration shape,
built on [Dynaconf](https://www.dynaconf.com/): a committed
`settings.toml` supplies base defaults, one or more profile-specific
`config-<profile>.yml` files layer overrides on top, and environment
variables under a service-specific prefix are the highest-priority
override.

**Resolution order, highest priority first:**

1. `<PREFIX>_*` environment variables — last-resort escape hatch only,
   never the normal way to supply configuration.
2. `config-<profile>.yml` files, one per entry in `ACTIVE_PROFILES`,
   applied in order.
3. `config.yml` files, default values.
3. `settings.toml` — Empty variable names.

Each service picks its own `envvar_prefix` (for example, the compute
provisioning service uses `PROVISIONING`; the API-credits storefront
uses `APICREDITS_STOREFRONT`) and constructs its `Dynaconf` instance
with `environments=False` — this repository uses named profiles
instead of Dynaconf's built-in environment concept, layered through
`includes=[...]`, `merge_enabled=True`.

**Why environment variables are not used for application config, beyond
the escape hatch:** environment variables are the highest-priority
override layer. Baking application settings into a Dockerfile's `ENV`
instructions, or setting them as individual Kubernetes pod env vars,
silently overrides anything an operator configures through a profile
file — the opposite of the profile system's purpose. A Dockerfile or
pod spec should set only the profile resolver variables
(`ACTIVE_PROFILES`, `CONFIG_DIRECTORY`) and any variable an external
subprocess reads directly from `os.environ` rather than through this
codebase's own settings object (for example, `ANSIBLE_CONFIG`, which
the `ansible-playbook` subprocess reads itself and so cannot travel
through Dynaconf — it is read from the resolved settings at startup and
written into `os.environ` once, explicitly, rather than set as a pod env
var).

## Kubernetes: ConfigMap and Secret mounting

All application configuration travels through mounted files, never
individual pod `env` entries — this rule applies equally to the
application Deployment and to Helm test pods.

**Pattern:**

- Non-secret configuration renders from the chart's `values.yaml` into
  a ConfigMap, mounted at `CONFIG_DIRECTORY` as a `config-<profile>.yml`
  file. Adding a new non-secret key requires only a `values.yaml`
  change — no Deployment template change.
- Secret material (key material, credentials) that cannot go in a
  ConfigMap renders into a Kubernetes Secret whose data contains its own
  `config-<profile>.yml` key, mounted at the same `CONFIG_DIRECTORY`.
  The Dynaconf loader sees no difference between a file mounted from a
  ConfigMap and one mounted from a Secret — the profile name is simply
  added to `ACTIVE_PROFILES` alongside the non-secret profiles.
- A pod sets only `ACTIVE_PROFILES` (the list of profile names to layer,
  comma-separated) and `CONFIG_DIRECTORY` (where the mounted files live)
  as environment variables.

**Toggling a mock/test profile:** A boolean chart value (for example
`mockMode`) can conditionally append a profile name to
`ACTIVE_PROFILES` in the Deployment template, causing the service's own
composition root to select a mock implementation of an external
dependency instead of the real one. The corresponding
`config-<profile>.yml` supplies safe no-op values for that mode. This is
the same mechanism Helm test pods use to layer in test-only
configuration: the shared non-secret values merge through one profile,
and a pod needing secret material mounts an additional Secret-backed
profile on top.

## Marketplace identity configuration

Service roles configure canonical public principals and trust pins in ordinary
configuration, with role-owned credentials supplied through their Secret
boundary. Buyers are different because they require durable local lifecycle:
public buyer TOML references `[BuyerProfile].store_path`, while the versioned
XDG data store holds stable profile UUIDs, canonical principal history,
redacted credential references, selection, lifecycle, and authority-scoped
opaque payer bindings.

Buyer providers are exact: OS keyring, an absolute owner-only regular secret
file, or one explicitly named environment variable. There is no fallback.
Profile metadata, run state, public config, and provider secrets use separate
mounts. Compose/Helm set `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and
`XDG_STATE_HOME`, persist the profile directory, and mount the selected
credential only into the buyer process. Invalid owner/mode, symlink, missing
secret, unsupported store version, or principal mismatch fails before buyer
work.

Ed25519 is the wallet-free default. Optional EIP-191 wallet/RPC/chain inputs are
separate mechanism resources and never determine profile selection. ConfigMaps,
arguments, image layers, run logs, evidence, output, and examples contain no
resolved signing value.

## Registry descriptor configuration

The registry is a Pydantic-settings service rather than a Dynaconf role. Its
Helm and Compose surfaces set the public descriptor fields through
`REGISTRY_DESCRIPTOR_BASE_URL`, `REGISTRY_DESCRIPTOR_DISPLAY_NAME`, and
`REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY`. When
`REGISTRY_REQUIRE_READ_API_KEY=true`, the deployment must also set
`REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER`; a public registry must omit
that pointer. Startup rejects missing fields and either posture mismatch.

These values are public operator assertions. The service derives the
descriptor's authority principal from the credential-backed active signer and
derives its schema identity from the loaded filter specification. Helm keeps
the descriptor values in ordinary values while mounting the signer credential
from a Secret. Compose wrappers likewise carry public descriptor values beside
public identity pins and keep signer credentials in role-owned file mounts.

The umbrella chart enables the compute registry by default and keeps the
`api-credits-registry` alias disabled. Enabling the alias instantiates the same
schema-opaque registry chart a second time. The compute instance selects
`/app/filter-spec.yaml` (`vms.compute`); the API-credits instance selects
`/app/filter-spec-apicredits.yaml` (`api_credits`). Both specifications are
packaged in the registry image, but each process loads exactly one. Identity,
credential Secret, descriptor, API-key Secret references, Service, and PVC
values are instance-local. `global.registryIdentity` continues to configure
the compute storefront's trust pin and does not constrain the alias signer.

## Per-domain stack composition

Each domain stack owns its public topology while consuming shared core/kit
authorities:

- `compose.vms.yml` composes the VM storefront and compute authorities.
- `compose.apicredits.yml` composes the API-credit registry, credits authority,
  gated sample service, and API-credit storefront.
- `compose.bare-metal.yml` composes the dedicated bare-metal storefront with a
  compute-family registry and the selected-site provisioning authority.

Storefront images install their distributions from the staged `.dist`
wheelhouse; runtime images do not resolve editable sibling source. API-credit
and bare-metal SQLite/queue/registry stores occupy separate named volumes.

Stack files carry public URLs, canonical principals, explicit Resource Pool
offering modes, and exact selected-site bindings. Signer, API-admin,
provisioning SSH, hosted-authority, and buyer credentials are independent
role-scoped file references with no committed fallback. Missing identity,
inventory, pool declaration, site authority, or credential blocks startup or
scenario preflight; it never selects a test signer, default site, payload-
guessed domain, direct executor, or provider simulator.

The bare-metal image currently exposes the signed publication command seam but
does not autonomously publish to the registry, and a public settlement address
alone does not compose a settlement authority. Its stack may be brought up for
operator integration, but it is not release-qualified or discoverable-deal
evidence until accepted publication and settlement lifecycles are ready and
the installed buyer completes real access and revocation.

## Stateful service persistence

Each service owns its own database; there is no shared database between
services (see `openspec/specs/deployment-state/spec.md`'s "Explicit
persistence ownership"). A SQLite-backed, single-writer service uses
`Recreate` deployment strategy with a `ReadWriteOnce` volume — SQLite's
single-writer model does not tolerate the overlapping old/new pod
window a `RollingUpdate` strategy would otherwise produce against a
shared volume.

### Combined compute-family storefront

The storefront image installs the shared `arkhai-core-storefront` shell plus
each enabled domain contribution from staged `.dist` wheels. Public
configuration contains a non-empty `storefront_domains` list; every row names
one contribution, exact offering mode, domain identity, and contract version.
Trusted provisioning authorities remain separately configured site bindings.
The Helm chart and Compose profile run one storefront process against one
single-writer SQLite volume; they do not start one container per domain.

`storefront_domains` is public routing metadata only. Signing credentials,
provider settings, SSH material, tenant credentials, hosted provider objects,
and private domain results remain in role-owned Secret channels and never enter
ConfigMaps, command arguments, images, listing bindings, or migration reports.
Startup rejects missing wheels, duplicate modes/identities, assertion mismatch,
unsupported versions, incomplete capabilities, or recoverable bindings that
the frozen registry cannot resolve.

Before enabling the combined image over an existing database, quiesce effects
and run `market-storefront migrate-storefront-domains --contribution <id>` in
check mode. Write mode requires the same explicit contribution and creates a
restrictive same-directory backup before fsync and atomic replacement.
Mixed/ambiguous rows, missing site or pool/resource provenance, public-mode
conflicts, orphan relationships, and derivation collisions fail without
mutating the source. Once accepted effects use common bindings, rollback is
forward recovery under those bindings, not restoration of an unbound schema.

## Definition documents

A service may be given the path to a YAML document describing resources it
should hold — pools, relays. The document is mounted like any other
configuration file and is not a Secret: it carries endpoints, windows, and the
*names* of profile keys, never a credential.

Two settings name such a document. `pool_definitions_path` is read by the
provisioning service; no chart supplies it, so declarative pools are opt-in for
a deployment that sets it directly. `relay_definitions_path` is derived by the
provisioning chart from the presence of `definitions.relays` rather than
configured beside it, because two independent settings can disagree and the
failure when they do is silent: the document renders, the volume mounts, and
the service skips an unset path while everything looks configured.

### Reconciliation follows the document, not the process

Import treats its document as authoritative. It overwrites entries that differ
from what is stored and, for pools, disables entries the document does not
name. That authority belongs to an operator submitting a document.

**A process start is not a submission.** Import is idempotent with respect to
the document, not the database: re-running it against state something else
changed reverts that change, because a diff against the document is exactly what
detects it. Applied on every startup it would silently undo administrative work
on eviction, drain, and crash recovery.

So a service records the digest of the document it last reconciled and applies a
document only when the current one differs. The digest is written in the same
transaction as the apply — recorded separately, a digest that committed after an
already-committed apply is indistinguishable at the next startup from one
recorded before a crash. An explicit import request reconciles regardless of the
digest, because the operator has asked.

The practical consequences for a deployment:

- Editing a mounted document and rolling the deployment applies the edit.
- Restarting against an unchanged document changes nothing, so anything set
  through the API survives.
- A failed apply records no digest, so the next start retries it.

### Relays and pools differ in one rule

A pool absent from the document is **disabled**: the document declares what the
deployment offers, and a pool it does not name should not be scheduled.

A relay absent from the document is **retained**. Disabling one would break
every pool referencing it and every live tunnel on it, which is a far worse
outcome than a stale row and is not what an operator editing an unrelated entry
is asking for. A relay established from a document and then administered through
the API is one relay, not two.

### Secrets are named, not carried

A relay entry may name which key of the deployment's secrets profile holds its
admission token. The service resolves that key **when the relay is created** and
never re-reads it, so a token rotated through the API is not reverted by a later
reconciliation of a document that still names the key holding the old value.

An entry naming a key the profile does not carry fails the import, naming the
key. Creating the resource with an empty credential instead would defer the
failure to the point of use, where it appears as a remote service refusing a
connection rather than as a configuration error where the configuration is
wrong.

## Migrations at startup

A deployed service applies its pending migrations before serving
requests, and the specific mechanism depends on the service's own
deployment topology:

- A service with a Kubernetes init container applies migrations there,
  before the application container starts, and the application's own
  startup path rejects schema drift rather than applying migrations
  in-process — see `openspec/specs/deployment-state/spec.md`'s
  "Service-owned migration history" for the full requirement, including
  the exception for a service without that deployment topology yet.
- A service without a separate deployment step for migrations applies
  its own ordered migration chain in-process at application startup,
  before serving requests — a valid instantiation of the same
  requirement for a service that doesn't yet have the first option's
  topology, not an exception to it.

See `docs/development/TESTING.md` for how migration behavior itself is
validated (fresh bootstrap, idempotent rerun, drift detection).

Identity-bearing database migrations validate the complete service-owned
population and commit canonical principals, replay state, and ownership
history transactionally while preserving public cross-service and operation
identifiers. Malformed or conflicting owners, partial relationships, schema
drift, and old signature versions fail closed. Versioned buyer run logs have
their own explicit migration before recovery.

For an identity-contract cutover, authenticated mutations remain quiesced
until every participating registry, storefront, service peer, hosted
authority, and exact client reports the pinned version and capabilities.
Rollback is limited to the boundary before the identity schema cutover and
before provider or settlement mutations resume. After version 2 effects run
against migrated state, operators recover by rolling forward from current
identity history and operation journals rather than restoring stale state.


## Settlement consumer configuration and cutover

Marketplace roles resolve one strict `[Settlement]` root. `schema_version`
selects the configuration contract, `priority` orders mechanism IDs, and peer
`[Settlement.stripe]` and `[Settlement.alkahest]` tables contain only
mechanism-owned consumer settings. Buyer marketplace identity comes only from
the selected durable profile referenced by `[BuyerProfile]`; storefront and
service-role principals retain their role-owned public identity configuration.
EVM credentials and networks remain in `[Wallet]` and `[Chains]`. A hosted-only
buyer therefore needs no wallet, chain, RPC, balance, or gas configuration.
Generated TOML, ConfigMaps, status output, and run logs contain only public
configuration projections.

Role CLIs reject legacy settlement keys and expose the same explicit migration contract. The storefront additionally rejects legacy publication pricing that would synthesize options from `min_price`, `token`, or raw `accepted_escrows`. A check is read-only and reports paths and actions with values redacted. A write requires `--backup`, validates the complete candidate before mutation, creates a restrictive same-directory `.bak`, fsyncs, and atomically replaces the source. Conflicting old and new values fail rather than choosing one. Repeating a completed migration is a no-op.

Publication config and inventory CSV migrate separately from the `[Settlement]` hierarchy. The migration converts an unambiguous single-mechanism legacy price into one complete typed clause. It refuses a dual-mechanism source whose one scalar price has no authoritative asset scale, and refuses CSV rows whose legacy `accepted_escrows` lack a resolvable rate. Resource `settlements` replace command/config defaults as a whole after cutover.

Expanded hosted configuration uses exact funding-profile clauses rather than `payment_method_types` or provider method strings. One seller clause names one of `card.v1`, `us_bank_transfer.v1`, or `us_ach_debit.v1`, its lowercase currency, positive rate, interaction capability, and typed condition input. Config may declare all three; preflight reports readiness per profile and suppresses only the clauses whose profile/currency/country/authority contract is unavailable. Buyer config carries the same exact client/API `0.2.0`/schema `5`/capability pins and references the owner-restricted local buyer profile store. The opaque authority/environment payer binding is stored only in that profile; saved instrument refs remain authority-side or transient.

The expanded cutover coordinates buyer and storefront config, the exact hosted client wheel, signed manifest and service-image coordinate, generated templates, Compose/Helm values, and role-scoped marketplace signer Secrets. A legacy unambiguous card publication clause migrates to `card.v1`; accepted historical card obligations are not rewritten. Before the first new publication or purchase authorization, rollback restores the matching prior artifacts and config together. After an effect begins, recovery rolls forward under the accepted funding profile, authorization, and marketplace operation identities.

Marketplace schemas reject provider credentials and IDs, Customer/PaymentMethod/mandate/bank/card data, stable instruments in storefront state, action URLs, webhooks, hosted databases/migrations, provider reconciliation, and recovery controls. The hosted authority remains the only process that receives those inputs.

For an API-credit hosted-only role, set settlement priority to
`fiat.stripe.v1`, provide an Ed25519 marketplace identity through the normal
role credential Secret, and leave wallet/chains absent. The storefront requires
the public hosted authority/release pins, seller account, exact funding-profile
clauses, credits-service URL plus admin-key file, and portable issuance-evidence
resolver trust. The buyer requires its selected durable profile and matching
opaque authority binding. API bearer secrets are returned only through the
authenticated buyer result route; they do not belong in TOML, environment
variables, listings, settlement evidence, logs, images, or ConfigMaps.

The API-credit storefront distribution and image install
`arkhai-kit-hosted-settlement` and the released hosted client from the staged
wheelhouse. The storefront owns the settlement operation journal, private
buyer-result table, and signed issuance-evidence table; the credits service
independently owns keys, request-digested grants, balances, quota, credentials,
and its migration history. Restart either authority against its own volume.
Never source-share a sibling package or mount one service's database into the
other.

For each buyer and storefront configuration overlay, use this production
sequence:

1. Stage the release containing the migration commands and the exact signed
   hosted client and manifest artifacts, without activating the new workload.
2. Preview every mounted or generated file. Select a storefront file with the
   root `--config` option; select a buyer overlay through its normal
   `XDG_CONFIG_HOME` mount.

   ```console
   market-storefront --config /path/storefront.toml config migrate \
     --scope settlement --check
   XDG_CONFIG_HOME=/path/to/buyer-overlay market config migrate \
     --scope settlement --check
   ```

3. Resolve every reported conflict and legacy environment-name rename. Then
   create backups and migrate every overlay atomically.

   ```console
   market-storefront --config /path/storefront.toml config migrate \
     --scope settlement --write --backup
   XDG_CONFIG_HOME=/path/to/buyer-overlay market config migrate \
     --scope settlement --write --backup
   ```

   Preview and migrate storefront publication defaults and every inventory:

   ```console
   market-storefront --config /path/storefront.toml config migrate \
     --scope publication --check
   market-storefront --config /path/storefront.toml config migrate \
     --scope publication --write --backup
   market-storefront --config /path/storefront.toml config migrate \
     --scope publication --inventory /path/resources.csv --check
   market-storefront --config /path/storefront.toml config migrate \
     --scope publication --inventory /path/resources.csv --write --backup
   ```

4. Repeat `--check` for every file and render the Helm or Compose deployment.
   Do not proceed if a migration, typed configuration validation, generated
   schema check, hosted manifest check, or image/config schema check fails.
5. Quiesce publication, negotiation, settlement, and recovery automation.
   Deploy the coordinated marketplace configuration, wheels, image, Secret,
   and ConfigMap set. Keep automation quiesced while every storefront reports
   at least one ready mechanism:

   ```console
   market-storefront --config /path/storefront.toml settlement status --json
   ```

6. Resume automation only after the configured ready mechanisms and blocker
   set match the intended overlay. Before activation or new settlement effects,
   rollback restores each same-directory `.bak` and the previous pinned
   artifacts together. After effects resume, recover forward from accepted
   settlement plans and operation identities; never change mechanism priority
   to redirect an accepted deal.

The marketplace Helm chart renders only consumer settings. It does not deploy
the hosted API, worker, hosted migrations, database, ingress, EAS signer,
Stripe credentials, or provider state. Those belong to the hosted service's
independent release and chart. Marketplace packages consume the exact hosted
client wheel and identity interface bound by that signed release manifest;
editable sibling sources and compatible-major substitution are rejected.

### Bare-metal hosted role configuration

`arkhai-bare-metal-buyer` is an installed core buyer-domain wheel. Its TOML contains a registry URL, registry authority/trust pins, and bounded public defaults only; the XDG buyer profile service resolves the fresh or run-recorded signer. The `bare-metal` commands use authenticated discovery and the shared schema-opaque hosted storefront transport. Raw payer/instrument/provider values and action material are not domain configuration or durable CLI output.

The bare-metal storefront accepts one strict shared settlement JSON root through `BARE_METAL_STOREFRONT_SETTLEMENT`. Hosted-only configuration leaves `BARE_METAL_STOREFRONT_EVM_ADDRESS` empty and constructs no Alkahest wallet, chain, or RPC client. Publication additionally requires authenticated registry trust, exact typed clauses, per-profile funding deadlines, offer/fulfillment bounds, fresh signed selected-site projections, and a maximum lease duration. The Compose wrapper exposes those as public/config inputs; the Helm chart mounts the settlement JSON from an existing Secret. Neither deployment surface carries Stripe credentials or hosted provider state.

The hosted authority remains a separately verified deployment. The storefront needs its public URL, authority/environment trust, seller account reference, contract fingerprint, supported profile/currency/country policy, and exact manifest/client/API capability pins through the shared settlement config. The selected-site authority keeps inventory, executor routing, provisioning SSH credentials, and teardown ownership. The buyer, storefront, site authority, and hosted authority each retain independent signer credentials and databases.


Local cross-repository Compose uses the same verified supply-chain path.
`make prepare-hosted-compose` verifies the configured trust policy, signed
manifest, manifest-bound artifacts, and exact client wheel, then atomically
generates `.dist/hosted-settlement-compose.env` with an immutable
`HOSTED_SETTLEMENT_VERIFIED_IMAGE=<repository>@sha256:<digest>`.
`make hosted-compose-up` passes that file to `compose.vms-fiat.yml`. The stack
runs the hosted service-owned migration, API, and single reconciliation worker
against one shared volume; it never builds or imports sibling service source.

### Protected hosted Stripe test execution

Hosted financial system E2E has one operator lane:

```console
make hosted-stripe-test \
  HOSTED_RELEASE_TRUST=/path/to/release-trust \
  HOSTED_RELEASE_MANIFEST=/path/to/production-release/release-manifest.json \
  HOSTED_CLIENT_WHEEL=/path/to/production-release/client.whl \
  HOSTED_COMPOSE_ENV=.dist/hosted-settlement-compose.env \
  HOSTED_PRODUCTION_MANIFEST_SHA256=<sha256> \
  HOSTED_PRODUCTION_CLIENT_WHEEL_SHA256=<sha256> \
  HOSTED_PRODUCTION_IMAGE_DIGEST=sha256:<digest> \
  HOSTED_PRODUCTION_SOURCE_COMMIT=<full-hosted-commit> \
  HOSTED_PRODUCTION_WORKFLOW_REF=<signed-producer-workflow-ref> \
  HOSTED_PRODUCTION_WORKFLOW_RUN_ID=<producer-run> \
  HOSTED_MARKETPLACE_COMMIT=<full-marketplace-commit> \
  HOSTED_STRIPE_TEST_RUN_REF=<unique-run-reference> \
  HOSTED_STRIPE_TEST_SCENARIO=<scenario> \
  HOSTED_STRIPE_TEST_ACCOUNT_REF=<allowlisted-account-reference> \
  HOSTED_STRIPE_TEST_AUTHORITY_ENVIRONMENT=<environment-name> \
  HOSTED_STRIPE_TEST_AUTHORITY_ENV_FILE=/path/to/protected-authority.env
```

Supply `STRIPE_SECRET_KEY` and `STRIPE_CONNECTED_ACCOUNT_ID` only through the
approved protected Secret/environment boundary, not as command-line literals.
`HOSTED_STRIPE_TEST_EVIDENCE` may select the sanitized report destination.

The target uses `hosted-preflight` to verify the signed production manifest,
trust policy, exact client wheel, service image digest, migration schema,
OpenAPI/conformance artifacts, provenance, signed repository and workflow
reference, and hosted source commit. Preflight emits only the allowlisted
non-secret coordinates `HOSTED_SETTLEMENT_VERIFIED_IMAGE`,
`HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256`,
`HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST`,
`HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256`,
`HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR`,
`HOSTED_SETTLEMENT_VERIFIED_REPOSITORY`,
`HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF`, and
`HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT`. The protected gate compares the
independently trusted signed-release `HOSTED_PRODUCTION_*` assertions to those
values. `HOSTED_PRODUCTION_WORKFLOW_RUN_ID` remains separate orchestration
evidence; it is not promoted to a signed-manifest field. No service starts
until the complete identity agrees. The stack then runs the ordinary hosted
migration, API, and one reconciliation worker against
one authority volume; it never builds, mounts, imports, or installs sibling
hosted source and has no alternate provider, clock, event-control, or test
service artifact.

Protected activation additionally requires a test-mode secret (`sk_test` or
least-privilege `rk_test`), Stripe connectivity and non-live returned objects,
the expected allowlisted connected account with required
ownership/capabilities/readiness, the Stripe CLI forwarding to
`http://127.0.0.1:18080/webhooks/stripe`, and Chromium. Failure stops before
the relevant publication or financial mutation. The target derives an
ephemeral storefront configuration only from the verified release
authority/manifest coordinates, mounts it for the run, and removes it on every
outcome. The authority API/worker receive only their provider, account, and
protected authority-environment inputs; the webhook process receives only the
ephemeral signing secret, Stripe CLI receives only its provider credential,
and marketplace storefront/buyer profiles receive only release-pinned public
consumer coordinates and their own signer credentials.

Selected restart scenarios retain the authority volume and original operation
identities while restarting only ordinary API/worker roles or webhook
forwarding. `make hosted-stripe-test-stop` stops the protected stack while
preserving that volume for maintained connected-account binding and authorized
recovery. Clean execution and every workflow outcome remove transient
configuration, processes, webhook material, and browser state. Accepted
external financial objects are recovered, transferred, or refunded through
their original durable identities rather than being deleted or recreated.

The protected matrix runs and attributes `card.v1`, `us_bank_transfer.v1`, `us_ach_debit.v1`, and off-session `requires_action` separately. Each selected rail must have its exact signed-release, account, currency/country, instrument or funding path, mandate where applicable, transient browser/action, and supported Stripe test-mode prerequisite. A missing prerequisite makes only that assertion unavailable and cannot be replaced by another profile, a provider-port script, or a credential-free marketplace result.

The sanitized report keeps the marketplace repository/commit independent from hosted manifest/client/image/API/schema/migrations/provenance/repository/workflow/source identities and the protected workflow run. It contains only selected profile/currency, public lifecycle stages, normalized outcomes, attempts/timestamps, failure class, and bounded hashed opaque correlations. Recursive canary validation rejects credentials, provider/customer/payment-method/mandate/bank/card data, raw actions or URLs, provider payloads/events/requests, source-bearing local paths, and marketplace configuration secrets before evidence is signed.

Default and fork workflows do not receive protected release access, Stripe
credentials, connected-account identifiers, webhook secrets, or browser
payment inputs and do not probe this lane. Alkahest E2E is invoked
independently as documented in `TESTING.md`. Local EAS/allowlisted-arbiter
checks are condition-boundary work only; there is currently no standalone
hosted local-EAS operator target.

## Current limits

This document describes the pattern as implemented for services with
their own Deployment and profile-resolved settings. A service without a
Kubernetes deployment topology (no Helm chart) does not yet have an
equivalent deployment-config story — see the "Migrations at startup"
section above and the relevant subsystem's `architecture.md` for how
such a service currently starts up instead.
