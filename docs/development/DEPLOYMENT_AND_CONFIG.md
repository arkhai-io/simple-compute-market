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

Every authenticated role configures a canonical public marketplace principal
(`scheme` plus `identifier`) and any service-peer trust pins in ordinary
profile data. Its matching private credential is supplied through a separately
mounted Secret-backed profile and is consumed only by the composition root
that constructs the signer. Startup fails before authenticated routes,
publication, negotiation, or settlement become available when the scheme is
unsupported, the secret is absent, or the derived public principal does not
match configuration.

Ed25519 is the wallet-free default. EIP-191 is an explicit marketplace
identity choice. Wallet, RPC, chain ID, deployed address, and gas settings are
separate optional configuration rendered only for a selected EVM effect; a
non-EVM storefront or buyer profile does not require or infer them.

ConfigMaps, rendered command arguments, image layers, release artifacts, logs,
probes, and examples contain no private signing material. Public principals
and trust pins may appear in those public carriers. Provisioning and other
service-peer connections pin the exact expected principal and role alongside
their operator-configured site binding; there is no administrator-key,
address-body, or private-key fallback.

## Stateful service persistence

Each service owns its own database; there is no shared database between
services (see `openspec/specs/deployment-state/spec.md`'s "Explicit
persistence ownership"). A SQLite-backed, single-writer service uses
`Recreate` deployment strategy with a `ReadWriteOnce` volume — SQLite's
single-writer model does not tolerate the overlapping old/new pod
window a `RollingUpdate` strategy would otherwise produce against a
shared volume.

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
mechanism-owned consumer settings. Marketplace identity remains in
`[Identity]`; EVM credentials and networks remain in `[Wallet]` and
`[Chains]`. A hosted-only buyer therefore needs no wallet, chain, RPC, balance,
or gas configuration. Secret or environment input supplies signing material;
generated TOML, ConfigMaps, status output, and run logs contain only public
configuration projections.

Role CLIs reject legacy settlement keys and expose the same explicit migration
contract. A check is read-only and reports paths and actions with values
redacted. A write requires `--backup`, validates the complete candidate before
mutation, creates a restrictive same-directory `.bak`, fsyncs, and atomically
replaces the source. Conflicting old and new values fail rather than choosing
one. Repeating a completed migration is a no-op.

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

The sanitized report identifies the marketplace repository and exact commit
separately from the hosted manifest digest, client wheel hash, service image
digest, and signed release repository/workflow reference/source commit. It
records the protected producer workflow run identity separately as
orchestration evidence and includes only allowlisted scenario/stage, opaque
operation identity, normalized
state/amount/currency/cardinality, failure class, and bounded diagnostics. It
contains no credentials, action URLs, account/customer/card data, raw
webhooks, unrestricted provider payloads, or marketplace configuration secrets.

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
