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
provisioning SSH, payment account, and buyer credentials are independent
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
provider settings, SSH material, tenant credentials, payment-provider objects,
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
until every participating registry, storefront, service peer, and exact client reports the pinned version and capabilities.
Rollback is limited to the boundary before the identity schema cutover and
before provider or settlement mutations resume. After version 2 effects run
against migrated state, operators recover by rolling forward from current
identity history and operation journals rather than restoring stale state.


## Settlement consumer configuration and cutover

Marketplace roles resolve one strict `[Settlement]` root. `schema_version`
selects the configuration contract, `priority` orders mechanism IDs, and peer
`[Settlement.alkahest]`, `[Settlement.arkhai_payments]`, and `[Settlement.contact]` tables contain only
mechanism-owned consumer settings. Arkhai payments resolves trusted service origin, Ed25519 receipt identity, fee/dispute policy, and an `api_key_env` reference through the shared kit's `settlement_config.py`. The owner-scoped WorkOS credential reaches only its consuming process; HTTPS is required outside loopback. Buyer `payer_account` is separate domain input, carried in selection params and the accepted Agreement, not inferred from marketplace identity. Buyer marketplace identity comes only from
the selected durable profile referenced by `[BuyerProfile]`; storefront and
service-role principals retain their role-owned public identity configuration.
EVM credentials and networks remain in `[Wallet]` and `[Chains]`.
Generated TOML, ConfigMaps, status output, and run logs contain only public
configuration projections.

Stripe consumer settings are rejected with removal diagnostics; they are not migrated to Arkhai accounts, credentials, or transactions. Role CLIs reject legacy settlement keys and expose the same explicit migration contract. The storefront additionally rejects legacy publication pricing that would synthesize options from `min_price`, `token`, or raw `accepted_escrows`. A check is read-only and reports paths and actions with values redacted. A write requires `--backup`, validates the complete candidate before mutation, creates a restrictive same-directory `.bak`, fsyncs, and atomically replaces the source. Conflicting old and new values fail rather than choosing one. Repeating a completed migration is a no-op.

Publication config and inventory CSV migrate separately from the `[Settlement]` hierarchy. The migration converts an unambiguous single-mechanism legacy price into one complete typed clause. It refuses a dual-mechanism source whose one scalar price has no authoritative asset scale, and refuses CSV rows whose legacy `accepted_escrows` lack a resolvable rate. Resource `settlements` replace command/config defaults as a whole after cutover.


For each buyer and storefront configuration overlay, use this production
sequence:

1. Stage the release containing the migration commands without activating the
   new workload.
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
   schema check or image/config schema check fails.
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


## Current limits

This document describes the pattern as implemented for services with
their own Deployment and profile-resolved settings. A service without a
Kubernetes deployment topology (no Helm chart) does not yet have an
equivalent deployment-config story — see the "Migrations at startup"
section above and the relevant subsystem's `architecture.md` for how
such a service currently starts up instead.
