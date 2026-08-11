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

## Hosted settlement consumer configuration

Hosted fiat settlement is disabled by default. Enabling
`[hosted_settlement]` requires an HTTPS service URL (loopback HTTP is
development-only), authority/environment identity, exact manifest digest and
contract version, required capability list, request-signing credential, and
operator-owned resolver IDs. Resolver entries may select a configured
marketplace chain and evidence mode; negotiated data never supplies an RPC
URL, service URL, or signing key.

The marketplace Helm chart renders only these storefront consumer settings.
It does not deploy the hosted API/worker, migrations, database, ingress, EAS
signer, Stripe credentials, or provider state. Those belong to the hosted
service's independent release and chart. Enabled storefront startup verifies
the exact health manifest/API/capabilities before accepting traffic.

Local cross-repository E2E runs the normal VM stack with
`compose.hosted-settlement.yml`. The overlay accepts only an image reference
plus verified `sha256:` digest, a staged signed-release directory, and
operator-generated service/storefront configuration files. It runs the
service-owned migration, API, and single reconciliation worker against one
shared volume; it never builds or imports the sibling service source.

## Current limits

This document describes the pattern as implemented for services with
their own Deployment and profile-resolved settings. A service without a
Kubernetes deployment topology (no Helm chart) does not yet have an
equivalent deployment-config story — see the "Migrations at startup"
section above and the relevant subsystem's `architecture.md` for how
such a service currently starts up instead.
