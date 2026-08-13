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

### Optional hosted local profiles

Hosted local execution remains artifact-based. `make hosted-preflight`
verifies the signed production manifest and exact client wheel.
`make hosted-hermetic-preflight` additionally verifies the signed private E2E
manifest, production compatibility, exact service and fixture wheels, image
digests, schemas, protocols, and capabilities. Both atomically generate only
non-secret Compose coordinates; they do not build or mount sibling source.

`make hosted-hermetic` starts a clean digest-pinned authority/simulator
assembly, admits the configured fixture account, runs the wallet-free
marketplace lifecycle, and removes the authority, simulator, and controlled
clock volumes on exit. The restart target retains those named volumes so
recovery tests can resume the same operation identities. Simulator control and
provider surfaces remain on isolated internal networks. Marketplace
storefront/buyer profiles receive only public principals, release pins,
resolver identifiers, and their own signer credentials.

`make hosted-local-eas` adds local chain infrastructure only for
condition-boundary conformance. `make hosted-real-stripe` instead uses the
ordinary production-like authority image and separately injected Stripe,
webhook, account, and operator secrets. These profiles produce distinct
evidence and never fall back to one another. Public and fork workflows run
without private artifact, simulator-control, or provider credentials.

## Current limits

This document describes the pattern as implemented for services with
their own Deployment and profile-resolved settings. A service without a
Kubernetes deployment topology (no Helm chart) does not yet have an
equivalent deployment-config story — see the "Migrations at startup"
section above and the relevant subsystem's `architecture.md` for how
such a service currently starts up instead.
