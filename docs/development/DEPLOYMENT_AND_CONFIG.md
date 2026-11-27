---
tags: [repository, configuration, deployment]
---

# Configuration and Deployment

This document describes how services in this repository resolve their
configuration and are deployed: its stacks, its charts, its release topology, its
persistence, and its migrations at startup. The rules a change satisfies in them —
service configuration, the Compose stacks, the charts, local clusters, service
databases, and migrations at startup — are under
[`docs/guidance/repository/`](../guidance/repository/README.md), and what an
operator does is the [operator handbook](../operator-handbook.md).
It is distinct from `docs/configuration.md`, which documents the
negotiation/fulfillment *policy plugin* system (how a seller or buyer
writes a custom pricing or negotiation hook) — a different, unrelated
meaning of "configuration." This document is about how a service reads
its own settings at startup and how an operator supplies them. The engineering
rules those repository rules apply are
[`configuration.md`](../guidance/engineering/configuration.md),
[`deployment.md`](../guidance/engineering/deployment.md),
[`migrations.md`](../guidance/engineering/migrations.md), and their
forms for Python, Kubernetes, and Helm beside them in
[`docs/guidance/engineering/`](../guidance/engineering/README.md).
One capability's own configuration — its settings, its definition documents, what
its services refuse at startup — is that capability's `configuration.md`, beside
its specification under `openspec/specs/`
([`openspec/README.md`, "Documentation placement"](../../openspec/README.md#documentation-placement)).

Read this alongside `docs/development/ARCHITECTURE.md` (system shape)
and `openspec/README.md` (documentation placement).

## Profile-based configuration

Every service in this repository but the registry resolves its
configuration through
[`configuration.md`'s profile layers](../guidance/engineering/configuration.md#profiles-layer-over-committed-defaults),
in their Dynaconf form
([`configuration-python.md`](../guidance/engineering/configuration-python.md)).
The registry is a Pydantic-settings service that reads profile-shaped env
files instead; see
[`deployment-state`'s "Registry profile configuration"](../../openspec/specs/deployment-state/configuration.md#registry-profile-configuration).
The rest of this section describes the Dynaconf services.

The resolver variables are `ACTIVE_PROFILES`, the comma-separated list of
profile names to layer, and `CONFIG_DIRECTORY`, where the profile files
live. Each service picks its own `envvar_prefix`: for example, the compute
provisioning service uses `PROVISIONING`, and the API-credits storefront
uses `APICREDITS_STOREFRONT`.

For compute provisioning and e2e, deterministic profile parsing, ordered
base/profile include resolution, and Dynaconf construction live in
`arkhai-kit-config`. Their composition roots still read `CONFIG_DIRECTORY`
and `ACTIVE_PROFILES` from the process environment and pass those values
explicitly to the shared loader. They also retain service-specific policy: settings
and secret files, environment prefix, dotenv location/discovery, missing-include
handling, wrappers, validators, and exported helpers. This boundary is scoped
to those migrated consumers; other services may still have separate loaders
until an explicit change migrates them.

Dynaconf's dotenv files join the environment layer
([`configuration-python.md`](../guidance/engineering/configuration-python.md#dotenv-values-join-the-environment-layer)).
E2e points Dynaconf at its project `.env`. Compute provisioning uses
Dynaconf's normal `.env` discovery and does not add `.env.local` loading.

What a service takes from its environment, where its secrets and trust are
configured, and how its settings are named are
[`service-configuration.md`](../guidance/repository/service-configuration.md).

### The time source

Every party reads the time of the world from one process time source its
composition root installs from one setting, `"wall"` by default or `"injected"`
([injected time](../../openspec/specs/injected-time/architecture.md)):

| Party | Setting |
|---|---|
| VM, bare-metal, API-credits and inference storefronts | `[Time] source` in `storefront.toml` |
| Compute provisioning service | `time.source` in its profile |
| API-credits service | `time.source` (`APICREDITS_TIME__SOURCE`) |
| Inference service | `time.source` (`INFERENCE_TIME__SOURCE`) |
| Registry | `TIME_SOURCE` in its profile env file |
| API-credits sample app | `APICREDITS_SAMPLE_APP_TIME_SOURCE` |
| Inference gateway | `INFERENCE_GATEWAY_TIME_SOURCE`, with `INFERENCE_GATEWAY_CONTROL_TOKEN` the bearer token of its time control under `"injected"` |
| Payments and mediation lane doubles | `PAYMENTS_LANE_DOUBLE_TIME_SOURCE`, `MEDIATION_LANE_DOUBLE_TIME_SOURCE` |
| Buyer | `[time] source`, with `[time] file` naming its time file under `"injected"` |

Any other value refuses startup, naming the setting and the value. Unset, a party
runs on wall time and mounts no time-setting route. Under `"injected"` a service
starts frozen at the wall instant it started, logs at startup that its time is
injected, reports its instant in its status's time section, and moves only when its
administrator sets it, and a party with an Arkhai payments section whose `livemode`
is `true` also logs a warning; the buyer reads its instant from its time file on
every read, refusing to start when the file is missing or invalid. Nothing refuses injected time, since no party can
recognise production: committed configuration outside the lanes never sets it,
which `scripts/tests/test_committed_time_sources.py` holds for the chart
defaults, the local Helm releases' values, the production examples and the
shipped presets
([`configuration.md`, "A test control the production image carries is off by default"](../guidance/engineering/configuration.md#a-test-control-the-production-image-carries-is-off-by-default)).
Only the Compose lanes set it, in configuration only they load ("Per-domain stack
composition" below).

## Kubernetes: ConfigMap and Secret mounting

What every chart renders for its service is
[`helm-charts.md`](../guidance/repository/helm-charts.md), and what its render tests
assert is [`chart-render-tests.md`](../guidance/repository/chart-render-tests.md).
Where the charts differ:

- The registry chart: the registry is a Pydantic-settings service whose
  profile is a dotenv file, `config-production.env`, and its chart maps
  each value to its variable by name, so a new registry setting also needs
  a line in its ConfigMap template (see
  [`deployment-state`'s "Registry profile configuration"](../../openspec/specs/deployment-state/configuration.md#registry-profile-configuration)).
- The provisioning chart and the umbrella's generated `helm` profile
  write JSON syntax into that YAML profile so 0x-prefixed EIP-191
  identifiers remain strings when Dynaconf reads it
  ([`helm.md`, "A hex value stays a string"](../guidance/engineering/helm.md#a-hex-value-stays-a-string)).
- The provisioning chart passes its `config` through into the service's profile,
  `config-production.yml`, as given, every section alike: its values schema types the chart's own values and refuses
  under `config` only the keys the chart derives itself or delivers from a Secret,
  and retired ones, so a section the service reads deploys through values alone
  ([`helm.md`, "A chart's values schema types the chart's own values"](../guidance/engineering/helm.md#a-charts-values-schema-types-the-charts-own-values)).
  `Events`, the service's operator events, travels there: its sinks, routes,
  retention and delivery settings in `config`, and its secret sink settings — an
  Apprise URL, a webhook URL, an SMTP password — in the
  `config-provisioning-secrets.yml` profile of the runtime Secret
  `sshDecryptionKey.secretName` names, which `ACTIVE_PROFILES` loads after
  `production`. The service, not the chart, validates the section at startup
  ([`physical-provisioning`'s configuration](../../openspec/specs/physical-provisioning/configuration.md)).
- A file a setting names by path, rather than a value, reaches the
  provisioning service through the chart's `configFiles` map: each entry's
  content renders verbatim into the ConfigMap and mounts read-only at
  `/app/config/<name>`, and the operator names that path under `config`, as
  `config.pool_seed_path` names a replacement pool seed. The chart gives the
  file no meaning and derives no setting from it, so it stays config-neutral.
  Its schema takes a single file name Kubernetes accepts as a ConfigMap key,
  and refuses `.` and names beginning `..`, the names the chart mounts itself
  (its definition documents), and `config.yml`, `config-*.yml`, and their
  `.yaml` forms, which the service would load as profiles around the
  rendered one. Each file renders through `toYaml` and each mount's name is
  quoted, so content and name reach the container exactly as given.

What a storefront takes outside its configuration files is
[`service-configuration.md`, "A storefront's configuration"](../guidance/repository/service-configuration.md#a-storefronts-configuration).

The provisioning chart's `mockMode` appends the `mock` profile to
`ACTIVE_PROFILES`
([`helm.md`, "A chart value toggles a mock profile"](../guidance/engineering/helm.md#a-chart-value-toggles-a-mock-profile)).
It also decides the SSH key: without `mockMode` the Deployment mounts
`id_ed25519` from the existing Secret `sshKey.secretName` names at
`/home/appuser/.ssh/id_ed25519`, the path a host's `ssh` connection names as its
`key_path`, and the chart refuses an empty or absent name. Under `mockMode` the
mock runner opens no connection, so no key is mounted, the name may be empty,
and the Secret it names need not exist. The runtime Secret
`sshDecryptionKey.secretName` names is mounted in either mode.

**The umbrella's `helm` profile.** The generated `helm` profile, in the
`<release>-helm-profile` ConfigMap the smoke-test pods, contract validation and
the end-to-end pods mount, carries the topology the release's values state and
those pods read: the
registry pins `registry.authority_id` and `registry.identifier`, which are what the
release's clients trust (`global.registryIdentity`), carried only for the internal
registry and only for an EIP-191 identity, the one scheme the registry smoke test
verifies; `buyer.wallet_address`, from the e2e-tests chart's development buyer
identity; `seller.wallet_address`, from the target agent's `[Wallet].address` when its
configuration states one, and absent when the agent derives its address from
its key; `seller.publisher_scheme` and `seller.publisher_identifier`, the
principal the target agent's `Identity.principal` states, which a test verifying
its responses pins; and
`provisioning.authority_scheme` and `provisioning.authority_identifier`, the
provisioning signer the release's clients trust (`global.provisioningIdentity`),
which the provisioning chart's own identity must equal. The provisioning smoke
test's signed cases also need an administrator credential, which the local
topology's values do not give its pod, so there they skip. The profile refuses a
release whose registry chart signs as an `identity` other than the one its clients
trust. Signing material no values carry reaches a smoke pod
as a profile file from a pre-existing Secret: the registry chart's
`tests.credentialProfile` (`secretName`, `profile`) mounts `config-<profile>.yml`
into the registry smoke pod alone and appends the profile, once, to its
`ACTIVE_PROFILES`. `helm/local-values.yaml` points it at `arkhai-e2e-credentials`'
`e2e-secret` profile, which already carries the buyer's marketplace credential for
the deal test, so one Secret holds one copy. A Secret's profile file quotes every
hex value
([`helm.md`, "A hex value stays a string"](../guidance/engineering/helm.md#a-hex-value-stays-a-string)).

**The e2e-tests profile.** The e2e-tests chart's `config` passes through whole as
the `e2e-tests` profile, `config-e2e-tests.yml` in the chart's own ConfigMap, which
its deal and scenarios pods mount and layer as `ACTIVE_PROFILES=helm,e2e-tests,e2e-secret`,
so an end-to-end setting reaches them without a template line of its own and no
other test pod reads it: the smoke pods and contract validation read `helm` too,
so a setting there would reach them. The profile is a ConfigMap, so
no credential goes there: the chart's schema refuses a key ending in `credential`,
`_key`, `token` or `secret`, in any case, at any depth, and a setting that needs
one names the `e2e-secret` key holding it. `helm/local-values.yaml` states the
release's `lane_time` there: wall mode, and the storefront, provisioning service
and registry the end-to-end session reads the time source of, keyed by name. A
party states none of their topology or credentials: each field ending in
`_setting` names the setting its value is read from, each URL and pin the `helm`
profile's and each credential its `e2e-secret` key. The registry's `/admin/status` takes its
administrator key, which the local release gives it through
`registry.secretProfile` (`arkhai-registry-runtime`'s `config-admin.env`).

### Storefront agents: pass-through configuration

The VM and bare-metal storefronts do not use profiles; each reads up to three files
from `$XDG_CONFIG_HOME/arkhai/`, a later file winning on a conflicting key:
`storefront.toml` (an operator's own file), `storefront.json` (the public
document the chart renders), then `storefront.secrets.toml` (the Secret
overlay). The chart mounts the last two at `/etc/arkhai/`.
`market-storefront config show` reports the files merged as the server merges
them; `--raw` prints each public file and never the overlay.

`storefront.agents` is a map from each agent's name to its entry, not a list
([`helm.md`, "Key a value that overlays change per entry; do not list it"](../guidance/engineering/helm.md#key-a-value-that-overlays-change-per-entry-do-not-list-it)):
an overlay states only what it changes in one agent, and `null` removes a key
or an agent. A list
is refused by the values schema, naming the map, and so is a `name` inside an
entry, whose key is its name. The storefront subchart ships no agent; the
umbrella's `values.yaml` declares Bob, and a values file that replaces Bob with
an agent of its own states `bob: null` beside it.

The supported Helm is the release pinned in
[`.github/workflows/tests.yml`](../../.github/workflows/tests.yml). That release
removes a parent's `null` for a subchart key only where the subchart's own
defaults define the key. The charts remove remaining null-valued keys themselves,
before any template reads an agent, so removal does not depend on Helm's merge.
A `null` assigned to a mapping key in a values file removes that key, at any
depth of an agent, including keys inside list elements; it never sets that
setting to `None`. Null list elements keep their item schema's meaning.
A removed key renders as if it had never been stated: the storefront applies
its default, or the chart adds a release-derived value where it normally would.
A required service setting the chart does not derive remains absent, and the
storefront refuses it at startup. A values file therefore cannot set a setting to
`None`; the storefront's own file and the Secret overlay can, where the storefront
accepts it (the operator handbook's
["Storefront configuration under Helm"](../operator-handbook.md#storefront-configuration-under-helm)).

Removing every agent is refused at render; `storefront.enabled: false` runs
none. Removing an agent's `port` or `identity` is also refused, naming the
agent and missing value, since the chart has neither to default to. Removing
`component` or `configMapName` uses the chart's default; removing a runtime
`secret` or address book mounts none, as does removing its Secret or ConfigMap
name. Other removed keys under those values take their defaults. A key the
values schema refuses, including a secret or retired key, stays refused as
`null`.

Each agent entry carries the storefront's own configuration
in `config`, in the storefront's own key names, and the chart renders it
into `storefront.json` with its null-valued keys removed. A setting or settlement
mechanism the storefront gains deploys through values alone. Keys may be spelled
in any case, as the storefront's loader reads them; a key stated in two spellings is refused
at render. The chart adds only what the release knows, and except for the port
and the CA bundle's path only where `config` does not state it:

| Setting | Derived from |
|---|---|
| `port` | the agent's `port`; always set, and a different stated value is refused |
| `Settlement.arkhai_payments.ca_bundle_path` | the agent's `caBundle`, the file it mounts; set whenever `caBundle` names a source, and a different stated value is refused |
| `base_url` | the agent's Service |
| `registry.urls`, `registry.authorities.<url>` | the internal registry's Service, with the agent's `internalRegistryTrust` written under its URL |
| `provisioning.service_url` | the provisioning Service |
| `capacity.sites` | `{default: <provisioning URL>}` |
| `db_path` | `agent.db` under `persistence.mountPath` |

`internalRegistryTrust` sits outside `config` because its key is the registry's
release-derived URL; it is required while the agent uses the internal registry,
and it must name `global.registryIdentity`'s authority and principal. When the
agent uses the release's provisioning service, the role-`service`
`Identity.service_peers` entry for the site bound to it must include
`global.provisioningIdentity`; the chart checks it and never adds a principal to
a trust list. Those checks relate the release's parts; the chart supplies no
service default and does not validate the storefront's own settings.

An agent's `alkahestAddressBook` (`configMapName`, empty mounting nothing; `key`;
`mountPath`, default `/etc/arkhai/alkahest`) mounts an existing ConfigMap's
address book read-only at `<mountPath>/<key>`, and the agent's `config` names that
file as its chain's entry in `[Settlement.alkahest.address_books]`; the chart
renders the entry as stated and derives none. A retired address-book key —
`alkahest_address_config_path` under a `[Chains]` table, or `address_config_path`
under `[Settlement.alkahest]` — is refused by the storefront's own startup refusal,
which the chart's render tests run over the rendered `storefront.json` (see
[`settlement-configuration`'s "Settlement consumer configuration and cutover"](../../openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover)).
The `dev-env` chart,
which deploys the Anvil state the book describes, renders its copy of
`kit/alkahest`'s development address book as `<release>-dev-env-alkahest-addresses`.

An agent's `caBundle` (`configMapName`, or alternatively `secretName`, never both;
`key`, default `ca-bundle.pem`) mounts an existing ConfigMap's or Secret's key
read-only at `/etc/arkhai/ca/ca-bundle.pem`, and the chart sets
`[Settlement.arkhai_payments].ca_bundle_path` to that file, derived from the
mount
([`helm.md`, "A chart derives a mounted file's path from the mount"](../guidance/engineering/helm.md#a-chart-derives-a-mounted-files-path-from-the-mount)).
Only
the payments client reads the bundle, and the process's own trust store is left as
it is. A `caBundle` is refused when the agent's `config` states no
`[Settlement.arkhai_payments]` section, or an empty one, rather than given a
section of its own, and so is a stated `ca_bundle_path` naming another file. The
chart names no CA of its own and has no default source. The bare-metal chart
takes the same option at its top level. The payments key is never a chart value:
it is `[Settlement.arkhai_payments].api_key` in the agent's Secret overlay.

Where an agent's `config` has a `[Settlement.arkhai_payments]` section and its
`tests.paymentsAccount` names an account, the chart renders a Helm test pod,
`<agent>-payments-check`, running `market-storefront check-payments --account
<account>` directly, not through the entrypoint; the bare-metal chart renders its
own, running `bare-metal-storefront check-payments`. Its environment and its
configuration, overlay, address-book and CA-bundle mounts come from the helpers
the Deployment renders them with, so a mount or variable the storefront lacks
fails the check too. It leaves out the data volume, whose ReadWriteOnce claim a
pod on another node could not attach, and the `/health` probes, and the VM pod
the ZeroTier capabilities and device. The check is described under
[`settlement-configuration`'s "Settlement consumer configuration and cutover"](../../openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover).

The VM chart's `<agent>-mediation-check` pod, from the same helpers and with the
same absences, is rendered where the agent's `tests.mediationOrigin`
names a dispute authority, as
[`helm-charts.md`, "A check of a setting the chart cannot see"](../guidance/repository/helm-charts.md#a-check-of-a-setting-the-chart-cannot-see)
requires, since the agent's `[[DisputeCredential]]` lives in the
runtime Secret's overlay
([deployment-state, "A storefront checks its mediation configuration from its own container"](../../openspec/specs/deployment-state/spec.md#requirement-a-storefront-checks-its-mediation-configuration-from-its-own-container);
the operator handbook's ["Payments access"](../operator-handbook.md#payments-access)).

The chart defaults enable no settlement mechanism, so a release from them alone is
refused at startup, as intended: Alkahest needs a chain and a wallet a production
release supplies. `helm/local-values.yaml`, which `make -C helm deploy-local`
layers, states only what it changes in Bob's agent: Alkahest on the `dev-env`
chart's Anvil, with that chart's address book mounted, Bob's development wallet
address, an Alkahest publication clause on the development chain's test token,
contact exchange with a development contact on a reserved domain, and Arkhai
payments against the release's payments lane double ("Release topology"): a
`[Settlement.arkhai_payments]` section naming the double's Service, receipt
identity and fee policy, `caBundle` on the `payments-ca-bundle` ConfigMap, and
`tests.paymentsAccount` naming the double's seller account. Every address in it
is a well-known development value never for a public network. The out-of-band
`arkhai-bob-runtime` Secret's `storefront.secrets.toml` carries what the chart
never renders: `[Wallet] private_key`, Anvil account 2's published development
key, for Bob's Alkahest client; `[Settlement.arkhai_payments] api_key`, the
double's seller token; and Bob's `[[DisputeCredential]]` toward the dispute
authority the local registry recommends, without which servicing would report his
payment deals `repair_required`. It needs `[registry.auth]` only for a registry
that requires write keys, which the local registry does not. The storefront validates its typed sections at startup; untyped
sections are not checked key by key (see below). Because the Deployment uses
the `Recreate` strategy, a configuration the storefront refuses leaves no
running pod until the release is rolled back (the operator handbook's
["Storefront configuration under Helm"](../operator-handbook.md#storefront-configuration-under-helm)).

`config` is public: it renders into a ConfigMap. The values schema carries one
definition generated from the storefront's typed configuration models
(`make helm-values-schema` regenerates it; a storefront unit test fails when it
is stale). That definition refuses, in any spelling, every field a model marks
secret or not applicable to the seller role, every field a typed section's
model does not have, and every key in `Identity` other than its public
principal, administrators, and service peers. So a wallet private key, a
registry write token, the payments `api_key`, private identity material, and
payer data are refused before anything renders; they belong in the Secret
overlay, or for the signer credential in `identity.credentialSecret`. The
definition also refuses the payments `api_key_env` and every `[[DisputeCredential]]`
entry, whole: the chart sets no variable a public `api_key_env` could name, and a
dispute credential binds a token to an authority, so the entry is incomplete
without its token and belongs in the overlay entire. `api_key_env` stays a field
of the shared payments model, the form a buyer's provider reads, so the storefront
generators refuse it rather than the model. Untyped sections such as
`provisioning`, `negotiation`, and `pricing` pass through unchecked, and a
misspelled key there is ignored by the storefront. A chart passing a service's
configuration through otherwise carries no schema of it, as the provisioning chart
carries none; the storefront charts' generated definitions stand in for refusals the
storefront's loader does not yet make, and moving those refusals into the loader is
unowned work recorded in the [change index](../../openspec/changes/README.md)
([`chart-render-tests.md`, "A chart's values schema types the chart's own values"](../guidance/repository/chart-render-tests.md#a-charts-values-schema-types-the-charts-own-values)).

Retired keys have two homes, one per kind. A key of the storefront's own
configuration that it no longer reads is retired in the storefront's one
catalogue, `market_storefront.retired_settings`: the generated definition refuses
it in any spelling, `market-storefront config set` refuses to write it, naming what
replaces it, and startup refuses a renamed or removed key under its own heading,
"the storefront states retired settings". The catalogue holds the renamed
`claims_sweep_interval` (state `settlement_servicing_interval_seconds`); the removed
`enable_registry_discovery`, refused whatever its value, so an operator who had
turned publication off is not silently switched on, since VM always publishes to
every `[registry].urls` entry; the removed `[provisioning.identity]`, since every
site client verifies against its site's service peer; the removed
`provisioning.fail_on_unreachable` and `provisioning.preflight_timeout`, since the
storefront starts without waiting for its provisioning service; and the local-inventory keys. The VM storefront's retired inventory settings — `resources_csv_path`, `resources_csv_inline`, `[escrow_templates]`, and `capacity.use_site_projection_for_listings`, with the chart's `secret.resourcesCsvInline` value — are refused the same way as retired settlement settings: the chart's values schemas refuse them in any spelling, and `market-storefront config set` refuses to write them, naming the seller quickstart's "Upgrading from CSV inventory". No command migrates them, because inventory moves to provisioning by operator action, and startup does not refuse them. The chart's hand-written block holds only the chart's own retired values
shape, that of storefront chart releases before 0.2.0 — `seller`,
`storefrontDomains`, `registryAuthority`, `registryUrl`, and `configMapName`
under `config`; `agentId`, `autoRegister`, and `rootPath` on an agent; and
`image.settlementConfigSchemaVersion` — and refuses each naming the key.

**Rollback.** An older storefront ignores a key it does not read, so it starts on a
configuration a newer release wrote: an older VM or API-credit storefront ignores
`settlement_servicing_interval_seconds` and services settlement at its 30-second
default. The bare-metal chart's values schema is closed, so an older chart refuses
at render a newer values file stating a key it does not know — `helm upgrade` to
the older chart with the newer values, or with `--reuse-values`, fails until the key
is removed — while `helm rollback`, which restores the older release's own values,
and the storefront's own start are unaffected.

The generated definition also types `[Settlement.contact]` and `[Delivery]`. A
seller's contact is public configuration, so it is accepted in `config`. Each
`[Delivery]` instance is typed by the sink it uses, its `sink` value or its own
name. The sinks typed are those installed in the storefront's image that declare
their settings model, found by discovery when the schema is generated: their secret
settings are refused wherever the instance is named, a table named for one of them
may not state another, and an instance of any other sink stays open. `sink` must be
spelled exactly so: the delivery kit reads no other spelling, and the schema refuses
`Sink` or `SINK` rather than let such an instance escape the typing that keeps
secret settings out of the ConfigMap.
`helm/fixtures/contact-exchange-values.yaml`
is a test overlay enabling contact exchange for Bob with SMTP delivery to the
`dev-env` chart's optional Mailpit (`dev-env.mailpit.enabled`), which a scenario
reads back; `docs/development/VALIDATION_RUNBOOK.md` gives the commands.

`storefront.json` is JSON so every string, including a 160-bit address, is read
back as a string; how a values file writes a large integer is
[`helm-charts.md`](../guidance/repository/helm-charts.md#an-integer-above-253-is-a-string)'s.

## Per-domain stack composition

Each domain stack owns its public topology while consuming shared core/kit
authorities:

- `compose.vms.yml` composes the VM storefront and compute authorities.
- `compose.apicredits.yml` composes the API-credit registry, credits authority,
  gated sample service, and API-credit storefront.
- `compose.bare-metal.yml` composes the dedicated bare-metal storefront with a
  compute-family registry and the selected-site provisioning authority.
- `compose.inference.yml` composes the inference registry, the inference
  service, the gateway in front of a model server, the deterministic model
  stub, and the inference storefront, from `domains/inference/compose.yml`. The
  stub is a test image answering an OpenAI-style API with a digest of the prompt; the
  `vllm` profile adds a CPU model server under the stub's model name, and the
  gateway fronts it when `INFERENCE_MODEL_BASE_URL` names it.
- `docker-compose.yml` is the full local stack: it includes `compose.vms.yml`,
  `domains/apicredits/compose.yml`, and `domains/inference/compose.yml`, so the
  dev chain enters once.

What a base file and an overlay may bind is
[`compose-stacks.md`](../guidance/repository/compose-stacks.md). The overlays, each
of whose headers gives the command it belongs to:

| Overlay | Binds |
|---|---|
| `compose.vms-local.yml` | the VM services' identities; Bob's and Alice's `storefront.toml` and secret overlays; both VM registries' profiles and credentials; both provisioning services' site profiles; the development Alkahest address book; the VM buyer service |
| `compose.apicredits-local.yml` | the API-credit services' identities and admin key; the storefront's `storefront.toml` and secret overlay; the API-credit registry's profile; the credits buyer service |
| `compose.bare-metal-local.yml` | the bare-metal registry's and site's profiles, identities and definition documents; the storefront's development `storefront.toml`, secret overlay, address book and lane CA; the buyer service and Mailpit |
| `compose.inference-local.yml` | the inference services' identities; the storefront's `storefront.toml` and secret overlay; the inference registry's profile; the gateway's signing credential; the inference buyer service |
| `compose.payments-double.yml` | the payments lane double, run by every end-to-end lane and never by the full local stack; both lane doubles on injected time (`PAYMENTS_LANE_DOUBLE_TIME_SOURCE`, `MEDIATION_LANE_DOUBLE_TIME_SOURCE`) |
| `compose.inference-lane.yml` | the inference lane's own bindings: a compute-schema and an API-credit-schema registry of the lane's own, which its schema-filter scenario routes discovery away from; the lane profile on all three registries; the model stub's streaming pace |
| `compose.vms-lane.yml`, `compose.apicredits-lane.yml` | each lane's own bindings: its payment storefront's lane configuration and the lane CA, and the registry profile recommending the double's pinned dispute authority; the API-credit lane also runs a compute-schema registry of its own, which the credits scenario routes discovery away from and the full local stack never runs, since VM's registry fills that role there |
| the lanes' time settings | every party of a lane on injected time, in configuration only the lanes load: the registries' lane profile `dev-env/registry/config-payments-lane.env`; the provisioning services' `dev-env/provisioning/config-lane-time.yml`, layered as the `lane-time` profile through `ACTIVE_PROFILES` by `compose.vms-lane.yml` and `compose.bare-metal-local.yml`; each storefront's lane configuration (`storefront.bob.lane.toml`, `storefront.alice.lane.toml`, `storefront.credits.lane.toml`, `storefront.inference.lane.toml`, and the bare-metal lane's `storefront.dev.toml`); in `compose.apicredits-lane.yml`, the credits service's `APICREDITS_TIME__SOURCE`, its lane `admin` principal, and the sample app's `APICREDITS_SAMPLE_APP_TIME_SOURCE` and control token; and, in `compose.inference-lane.yml`, the inference service's `INFERENCE_TIME__SOURCE`, its lane `admin` principal, and the gateway's `INFERENCE_GATEWAY_TIME_SOURCE` and control token. The full local stack stays on wall time |

The committed sources are: `dev-env/identities/` for every identity and each
storefront's secret overlay (`*.storefront.secrets.toml`, holding its wallet key
and, for the payment storefronts, its payments `api_key` and Bob's
`[[DisputeCredential]]`, which only a lane configuration enabling payments uses);
`dev-env/registry/` for the registry profiles, one `config-<registry>.env` per
registry and `config-payments-lane.env`, which each lane layers last; and
`dev-env/provisioning/` for each site's profile (`config-<site>.yml`), holding its
service, storefront and administrator identities and its site id. Each
provisioning service sets `CONFIG_DIRECTORY=/app/config` and binds single files
into it, the packaged `config.yml` and `config-docker.yml` from their source and
its site profile, the mount shape the provisioning chart uses. A lane's payment
storefront reads a lane copy of its configuration with the payments section —
`domains/vms/storefront/storefront.bob.lane.toml` and
`domains/apicredits/storefront/storefront.credits.lane.toml` — in place of the
full stack's `storefront.bob.toml` and `storefront.credits.toml`; the bare-metal
lane's `domains/bare_metal/storefront/storefront.dev.toml` carries it itself.
Every value is a well-known development value never for a public network;
[`dev-env/identities/README.md`](../../dev-env/identities/README.md) says which
file each lane uses.

The bare-metal storefront reads its settings only from mounted files: the domain
file sets `XDG_CONFIG_HOME=/etc`, and the overlay mounts `storefront.toml` and the
Secret overlay `storefront.secrets.toml` at `/etc/arkhai/` and gives the signer
credential, the one value it reads from its environment, through an `env_file`.
The bare-metal stack also layers `compose.dev.yml` for its dev chain.

The full local stack is

```console
docker compose -f docker-compose.yml -f compose.vms-local.yml -f compose.apicredits-local.yml up -d
```

and each end-to-end lane's target in `e2e-tests/Makefile` names its own
([`compose-stacks.md`](../guidance/repository/compose-stacks.md#a-lane-target-names-only-its-files-its-project-and-its-mode)).

Whether a compute stack provisions through its provisioning service's `mock`
profile is chosen per run, not per stack file and never by a storefront.
`PROVISIONING_MODE` (`mock` or `real`, default `mock`) is the one value a run
supplies. Each overlay states a provisioning service's profiles with the mode
last, `docker,<site>,${PROVISIONING_MODE:-mock}`; `e2e-tests/Makefile` refuses any
other value and exports it to Compose. No `real` profile file exists, and the
loader skips a missing profile file; mock delivery is selected by the profile name
`mock`, so under `real` the service is not mocked. The base files state
`ACTIVE_PROFILES=docker`, real provisioning, as the provisioning Helm chart's
`mockMode` defaults to false. The API-credit stack has no provisioning service
and ignores the setting.

The VM development stack runs Bob and Alice as separate storefronts with
separate provisioning authorities. Each authority has its own service signer,
storefront trust pin, callback destination, database, and process-local job
queue. Both storefronts use the local site alias `default`, resolved against
their respective authorities. `compose.vms-local.yml` supplies deterministic
development credentials.

The bare-metal wrapper extends each service from `domains/bare_metal/compose.yml`
to merge each service's bindings with the domain topology, and declares the named volumes
those services use. Service extension preserves the domain file's relative mount
paths. An `include` cannot be used to import a service and redefine it in the same
wrapper.

How the storefront images install their distributions is
[`images.md`](../guidance/repository/images.md). API-credit
and bare-metal SQLite/queue/registry stores occupy separate named volumes. What a
stack file binds, and that missing material blocks startup rather than taking a
fallback, are [`compose-stacks.md`, "No fallback"](../guidance/repository/compose-stacks.md#no-fallback).

The bare-metal storefront publishes on a timer loop over the site projections it
holds, every `[capacity].publication_interval_seconds` and whenever a poll sees a
site's resource-pool generation change; `bare-metal-storefront publish` runs or
previews one cycle of that loop through the running storefront's administrator
API. A public settlement address alone does not compose a settlement
authority (see "Bare-metal role configuration"). Its end-to-end lane completes
a discoverable deal with mock-provisioned delivery, which is not
release-qualified evidence: that needs the installed buyer to complete real
access and revocation on a real host.

## Stateful service persistence

Who owns each service's state, and how a stateful service is deployed over it, is
[`service-databases.md`](../guidance/repository/service-databases.md).

Registry and compute-provisioning runtime images create `/app/data` owned by
their non-root `appuser`. Fresh Compose named volumes inherit that ownership,
so SQLite can create its database without a root startup process. Bind mounts
and existing volumes must already provide write access to the runtime user.

The Helm charts annotate each service's PVC `helm.sh/resource-policy: keep`, so
`helm uninstall` leaves the volume and a reinstall rebinds it and recovers its
state. A chart's `persistence.retainOnUninstall`, `true` by default, controls the
annotation. `helm/local-values.yaml` sets it `false` for every persistent chart,
and `make -C helm deploy-local` layers that overlay on `values.yaml`: a local
deployment's volumes are deleted with the release, so uninstalling and deploying
again starts every service from no state rather than from a database an earlier
deployment of other code migrated. A PVC whose release was last installed or
upgraded without the overlay still carries the annotation, and survives an
uninstall until it is deleted by hand. Which target deploys a local development
cluster follows from this
([`local-clusters.md`](../guidance/repository/local-clusters.md#a-local-cluster-is-deployed-with-deploy-local)).

### Release topology

Several storefronts per registry is the supported Kubernetes topology: each
storefront runs in its own release of the umbrella chart with its own provisioning
service, publishing to one release's registry. A provisioning service trusts one
storefront principal and calls back one storefront, so a second storefront on the
same provisioning service would have its signed requests refused and its
capacity-released callbacks sent to the first. The umbrella therefore refuses a
release that enables both compute storefronts with the bare-metal storefront bound to
the release's own provisioning service (its derived `default` site, or a stated site on
that URL), naming the second release's overlay; bound only to sites of its own, it
renders. In a release whose VM storefront is disabled and whose dedicated bare-metal
storefront is enabled, the umbrella's `helm` profile checks that provisioning
trusts the bare-metal storefront's `Identity.principal` in place of a VM agent's.

Locally the topology is two releases in one namespace. Release 1 is the umbrella as
`make -C helm deploy-local` installs it: the registry, Bob's VM storefront, its
provisioning service, and the `dev-env` chain. Release 2, `arkhai-bare-metal-seller`,
is the same chart with `helm/local-values.yaml` and then
`helm/bare-metal-release-values.yaml` layered, values only: the
bare-metal storefront and its own provisioning service, with the registry, the VM
storefront, `dev-env`, contract validation, and the e2e-tests chart disabled. Its
`global.registry.host` names release 1's registry Service, whose principal the
storefront's `internalRegistryTrust` pins, and its chain and Alkahest address book are
release 1's `dev-env`. Every identity the overlay names is a well-known development
value (Anvil accounts 8 and 9) never for a public network. Release 2 reuses release
1's provisioning runtime Secret and reads three of its own. Both releases run mock
provisioning, so neither mounts an SSH key or reads a Secret for one.

In the local release
([`local-clusters.md`](../guidance/repository/local-clusters.md#a-local-release-configures-a-service-through-the-values-a-deployment-uses)),
both storefronts settle in `arkhai.payments.v1` against the payments lane double
through `[Settlement.arkhai_payments]` in their `config`, the `caBundle` option on
the `payments-ca-bundle` ConfigMap, and the payments `api_key` in their runtime
Secret's overlay. The double is the `payments-lane-double`
subchart, which `helm/local-values.yaml` enables and no release values do. Its
Service is named `payments-double`, the name its certificate is issued for, in
every release, so a namespace runs one: release 2's values disable the subchart,
and its storefront reaches release 1's double by that name. Beside it runs the
mediation lane double, the `mediation-lane-double` subchart, enabled the same way
and in release 1 alone, behind the Service `mediation-double`; it needs no
configuration in the cluster, reaching the payments double by its Service name
under the lane CA its image carries. Release 1's registry recommends the
mediation double's identity, and Bob's overlay carries his `[[DisputeCredential]]`
for it, as the VM lane's does, with its `ca_bundle_path` naming the storefront
chart's CA file; release 2's storefront carries none, though the bare-metal
lane's overlay carries one. The `payments-ca-bundle` ConfigMap holds the lane CA, which issues both
doubles' certificates. Each storefront's payments check test pod reads the
double's seller account, and Bob's mediation check test pod reads the mediation
double's respondent listing. The release serves no payment or dispute scenario.

The local release runs on wall time, every party in both releases with no time
source set: it serves interactive use, where a frozen release would sit still, and
pre-review validation, whose scenarios set no time. The end-to-end session reads
the time section of release 1's storefront, provisioning service and registry
through the `lane_time` section of the e2e-tests profile, and fails naming any
that reports injected time before a scenario runs; a stage needing an instant the
Agreement does not fix is a blocked skip there.

- `make helm-topology-secrets` creates or replaces, idempotently, every Secret both
  releases read, and the `payments-ca-bundle` ConfigMap, in its namespace, which it
  creates when absent (`make -C helm topology-secrets CHANGE=<change>` for a
  change's validation namespace), deriving each key with `cast` from Foundry's
  default development mnemonic at `helm/Makefile`'s `DEV_ACCOUNT_*` indices
  (development values only); it writes no SSH key Secret, since mock
  provisioning mounts none. It takes the committed lane CA, from
  `tools/lane-double-controls/tls/`, for the ConfigMap, and from the payments lane
  double's committed fixtures the seller's token, which it
  writes as `[Settlement.arkhai_payments] api_key` into both storefronts' runtime
  overlays, and it copies Bob's `[[DisputeCredential]]` from his Compose secret
  overlay, `dev-env/identities/bob.storefront.secrets.toml`, so both stacks hold one
  value, but for each copied entry's `ca_bundle_path`, which names the Compose
  mount and so is rewritten to the storefront chart's CA file
  (`STOREFRONT_CA_BUNDLE_FILE`, `/etc/arkhai/ca/ca-bundle.pem`), as
  [`configuration.md`, "A private CA is mounted once, and each client names it"](../guidance/engineering/configuration.md#a-private-ca-is-mounted-once-and-each-client-names-it)
  requires of a setting in a Secret the chart never renders; an entry stating
  none keeps none. It gives the registry the Compose lanes' development
  administrator key, in `arkhai-registry-runtime`, and repeats it in
  `arkhai-e2e-credentials` for the end-to-end session's read of the registry's
  time source.
  `helm/scripts/topology-secrets.sh` says what each Secret holds. It also
  creates, if absent, the deal test's buyer-profile volume, `arkhai-buyer-profiles`,
  which no chart creates, and leaves an existing claim as it is.
- `make helm-topology-up` installs or upgrades release 1, then release 2, each with
  `--wait`, and then restarts both releases' Deployments — the registry, then the
  provisioning services, then the storefronts, each restart waited on — because local
  images keep bare tags, so an upgrade alone leaves every pod on its old image. It
  never restarts `dev-env`: its Anvil reloads its state file, so the contracts
  survive, but a restart loses every transaction since start-up that the other
  services' volumes still refer to. Nor does it restart the payments or the
  mediation double, which keep every payment and case in memory, so a restart would
  lose each transaction and case the storefronts' databases refer to.
- `make helm-topology-check` runs both releases' `helm test`, each storefront's
  payments check and Bob's mediation check among them, and `make helm-topology-down` removes release 2, then
  release 1. The topology targets refuse an overridden release name, whose Services
  the overlay would not name.
- `check-local-secrets`, which `deploy-local`, the topology targets and the
  single-release `test` and `test-module` run first, names `make
  helm-topology-secrets` when a Secret, a ConfigMap (`LOCAL_CONFIGMAPS`, the
  `payments-ca-bundle` the storefronts mount), or the buyer-profile volume their
  workloads or tests read is missing. It checks that each exists, not what a
  Secret's overlay holds: a runtime Secret written without the payments token is
  reported by the storefront itself, its payments readiness blocked by
  `arkhai_payments.api_key_missing` and its payments check failing at the
  `configuration` step.

The Helm validation scenarios need release 1 alone. What a scenario needing release 2
states is [`local-clusters.md`](../guidance/repository/local-clusters.md#a-scenario-needing-release-2)'s,
and how the releases' Helm test pods are labelled is
[`helm-charts.md`](../guidance/repository/helm-charts.md#helm-test-pods-carry-no-workload-selector-label)'s.

## Migrations at startup

Each stateful service's migration command, and the phase it runs in, are
[`migrations-at-startup.md`](../guidance/repository/migrations-at-startup.md). The command's check mode,
`<service>-migrate --check`, exits 0 only for a compatible database:

| Result | Meaning |
|---|---|
| compatible | the database records exactly the chain's migrations |
| behind | migrations are pending, or a database the floor release ran on awaits adoption |
| ahead | the database records the chain's baselines and a migration this image does not list; for the registry, one revision neither in its chain nor in its history up to its floor |
| unsupported | older than the floor or another service's sharing its history (part of the floor recorded, or a registry revision before its floor), or not this chain's (tables with no ledger, none of the floor recorded, or several registry revisions) |
| absent | no file, or no table but an empty ledger |

The command refuses an ahead or unsupported database and applies nothing. Each
in-house service's chain declares its floor, marketplace 0.3.0 for every service
a release has shipped, and begins at baselines reproducing that release's schema. The API-credit service's
baselines differ from it by one index, which a later migration creates (below).
The command adopts a database marketplace 0.3.0 ran on, whatever else it records.
Such a database records every migration ID that release's chain recorded and none
of the baselines. In one transaction, without running the baselines, the command
forgets every recorded ID the chain does not list and records the baselines in
their place, then applies the later migrations. `--check` previews the adoption:
it names the baselines to be adopted, "replacing the records of marketplace
0.3.0", the records set aside, and the pending migrations. Every in-house service
adopts its v0.3.0 databases, including one an earlier release built. That covers
compute provisioning, the VM, bare-metal and API-credit storefronts, the API-credit
service, and the registry (at Alembic revision `018_listing_resource_column`,
adopted as `v0_3_0_baseline`).
The inference service and storefront, which no release has shipped, run the
same family chains under the floor `0.0.0` and adopt no database.

A database recording part of the floor is refused, naming marketplace 0.3.0 and
the migrations it lacks. So is a registry database at an earlier revision. Its
ledger cannot tell an older database of the service's own from another service's
sharing its history, so the refusal directs an upgrade through marketplace 0.3.0
first, once the operator has confirmed the database is the service's. A database
recording none of the floor's migrations is refused as not the service's. No
refusal directs a fresh database.

The API-credit pair upgrades in the order its Compose stack enforces. The credits
storefront `depends_on` the credits service being healthy, and each container runs
its migration before its application. The service migrates first, and a failed
service migration leaves the storefront's database untouched
(`scripts/tests/test_apicredits_compose.py`). Each in-house migration commits with its record, so a
failure leaves the migrations before it applied and recorded; under Alembic,
SQLite DDL is not transactional, so a fresh registry database whose migration
fails partway is unsupported and is replaced by a fresh one. The family authority's chain ends at
`20261109_001_grant_terms`, which creates the table a grant's accepted terms
are kept in. An image rolled back
over a migrated database is refused as ahead, so an upgrade is rolled back by
restoring the backup taken before it. The operator handbook's
["Upgrading a deployment"](../operator-handbook.md#upgrading-a-deployment) is the
procedure.

See [`migration-chain-tests.md`](../guidance/repository/migration-chain-tests.md) for how the
chains are proven: each against its floor fixture, adoption, the store-open
test, and each service's migration suite.

The migrations after the v0.3.0 baseline, which an adopted database applies:

- Both services hosting the site ledger add the unique reservation placement key
  and its recorded request (`20261106_002_reservation_placement_key`, which
  `kit/site` exports to both chains), with no backfill, since no earlier reserve
  carried a key.
- The API-credit service then creates the site ledger's `uq_capacity_buckets_host_id`
  (`20261126_001_capacity_bucket_host_index`). Its v0.3.0 release left the index out,
  though the table's `UNIQUE (host_id)` already enforced the same rule. `kit/site`
  exports the migration outside its `MIGRATIONS`, and only the `api` family
  authority's chain composes it, so the inference service runs it too. It drops the index first where present, so a fresh database ends
  unchanged.
- Compute provisioning rewrites every host's `ssh` connection stored at version 1
  to version 2 with the same public fields and ciphertext
  (`20261108_001_ssh_connections_version_2`), failing, naming every refused host
  and rewriting nothing, where the fields version 2 and version 3 share are
  refused. A host submission must state its connection's version.
- Compute provisioning then adds a job's `execution_started_at` and `finished_at`
  (`20261118_001_ansible_jobs_execution_instants`), nullable and not backfilled:
  every job the earlier engine recorded reads null in both, and is never
  classified as never started, since that engine recorded no start before it
  acted on the host.
- Compute provisioning then adds a job's structured failure, `ansible_jobs.failure`
  (`20261126_001_ansible_jobs_failure`), nullable and not backfilled: every job the
  earlier engine recorded reads null and keeps its failure text in `error`. This
  and the migration above are the job authority's, which
  `compute_provisioning.jobs.migrations` exports to the chain.
- Compute provisioning then adds `hosts.host_key_adoption_pending` and rewrites
  every host's `ssh` connection stored at version 2 to version 3 with the same
  public fields and protected values and no `host_keys`, marking each host it
  rewrites pending adoption (`20261119_001_ssh_connections_version_3`). It fails,
  naming every refused host and rewriting nothing, where the version-3 codec
  refuses a row or a row already states `host_keys`. The first check of a marked
  host records the key it presents as its pin
  ([`physical-provisioning`, "The host registry owns the connection"](../../openspec/specs/physical-provisioning/architecture.md#the-host-registry-owns-the-connection)).
- Compute provisioning then creates its event store, the eventing component's
  tables and its sequence counter at 0 (`eventing_0001`, the component's schema
  step for version 1, applied under the step's own name; see
  [`ARCHITECTURE.md`, "Events"](ARCHITECTURE.md#events)).
- Compute provisioning then carries its two storefront outboxes into the event
  store and drops them (`20261126_002_storefront_outboxes_to_event_store`). Every
  signed report of `lease_end_report_outbox` moves to `lease_end_reports`. Each
  undelivered report becomes a `site.lease_ended` event under its own event
  identity, in the order the reports were created, pending to the peer it was
  signed for with its attempts and last error, that peer's destination parked if
  the peer had parked its reports. Each undelivered row of
  `capacity_release_callback_outbox` whose reservation is released becomes a pending
  `site.capacity_released` delivery to the storefront; one whose reservation was
  never released was never due and is dropped. Delivered rows need no event. Both
  storefront consumers are registered past every moved event. An undelivered
  report naming no recorded lease end, or a callback whose release records no time
  or lease end, refuses the migration, which then writes nothing. The signed report
  and the callback keep their wire forms.
- Each compute storefront creates the tables v0.3.0 created only when a store
  opened — deal servicing's, and the bare-metal lifecycle cursor — with
  `IF NOT EXISTS`, leaving any present as they are
  (`20261109_001_vm_store_open_tables`, `bare-metal-storefront-0017-store-open-tables`).
- Each compute storefront then creates deal servicing's
  `servicing_payment_observations`, empty, which tolerates no table already present
  (`20261115_001_vm_payment_observations`,
  `bare-metal-storefront-0019-payment-observations`). A rate deal past its delivery
  deadline before the upgrade has its deadline recorded only after the first payment
  observation the upgraded storefront makes.
- Each compute storefront then creates deal servicing's `servicing_page_position`,
  each servicing loop's page position, empty, which tolerates no table already
  present (`20261116_001_vm_servicing_page_position`,
  `bare-metal-storefront-0020-servicing-page-position`); the bare-metal migration
  drops the lifecycle cursor in the same step, so its first cycle after the upgrade
  starts from the first deal.
- The storefronts drop the tables v0.3.0 kept frozen: the VM storefront's
  `compute_allocations`, `resources`, `hosts`, `resource_transition_events`,
  `compute_pool_members`, and `compute_capacity_pools` or
  `compute_inventory_pools` (`20261109_002_vm_frozen_inventory_dropped`), and the
  bare-metal storefront's `bare_metal_accepted_site_generations`
  (`bare-metal-storefront-0018-drop-accepted-site-generations`). Their rows are
  discarded; inventory is declared at provisioning.
- The storefronts drop, where present, the tables an earlier release's retired
  migrations created that nothing reads, discarding their rows. A database holds
  them only if a release before v0.3.0 built it:
  - the VM storefront's `derived_compute_listings`, each derived listing's site,
    pool and resource, which `storefront_listing_bindings` holds
    (`20261126_001_vm_derived_listings_dropped`);
  - the bare-metal storefront's `bare_metal_hosted_lifecycle`, each hosted-card
    deal's binding and its physical, financial, recovery and teardown states, with
    its indexes and trigger (`bare-metal-storefront-0021-drop-hosted-lifecycle`).
- The VM storefront adds `vm_delivery_records.activated_at_utc` and renames the
  stored phase `activate` to `ready` (`20261106_001_vm_delivery_activation`); the
  bare-metal storefront adds `bare_metal_fulfillment_lifecycle.activated_at_utc`
  and marks a delivery left with its request saved but no fulfillment as
  dispatched (`bare-metal-storefront-0016-delivery-activation`). A deal available
  before the upgrade is never activated retroactively; its null activation means
  only that none is recorded.
- The same storefront migrations clear stored access material. Core's
  `auth_replay_reservations` records no route, so each storefront clears its
  access shape from every recorded body: VM removes the `tenant_credentials`
  member, and bare metal removes `host`, `port` and `username` from a body whose
  `method` is `ssh`; no other route's body has those fields. A stripped body is
  still a recorded body, so the record stays completed and an exact retry still
  resolves to its operation. VM also clears `tenant_credentials` from its
  delivery records and escrows and deletes core `credentials` rows for listings
  no other offering mode binds (`20261106_002_vm_credentials_cleared`).

How these migrations fail is
[`migrations-at-startup.md`, "Migrations fail forward"](../guidance/repository/migrations-at-startup.md#migrations-fail-forward).

Every supported database already holds canonical principals, since each
service's v0.3.0 floor converted its identity-bearing rows; authorities still
reject old schema, old signature versions, drift, and partially migrated state.
Versioned buyer run logs have their own explicit migration before recovery.

For an identity-contract cutover, authenticated mutations remain quiesced
until every participating registry, storefront, service peer, and exact client reports the pinned version and capabilities.
Rollback is limited to the boundary before the identity schema cutover and
before provider or settlement mutations resume. After version 2 effects run
against migrated state, operators recover by rolling forward from current
identity history and operation journals rather than restoring stale state.


## Bare-metal role configuration

`arkhai-bare-metal-buyer` is an installed core buyer-domain wheel. Its TOML contains registry URLs, authority trust pins, and bounded public defaults; the XDG buyer profile service resolves the fresh or run-recorded signer. The `bare-metal` commands use authenticated discovery and the shared storefront transport.

The bare-metal storefront reads its configuration as every storefront does: `$XDG_CONFIG_HOME/arkhai/storefront.toml` (an operator's own file), `storefront.json` (the document a chart renders), and the Secret overlay `storefront.secrets.toml`, a later file winning on a conflicting key, over the packaged `settings.toml`, which states every default once. Its keys are VM's for the same concepts — `[Identity]`, `[Settlement]`, `[registry]`, `[capacity]`, `[pricing]`, `[negotiation]`, `[Delivery]`, `[Wallet]`, `[Chains]`, `base_url`, `port`, `db_path`, and the interval and timeout keys — and its loader's override layer is VM's, `STOREFRONT_` with `__` between levels, an operator's escape hatch only. Section and key names read in any case; a key the storefront does not read is ignored, so an older release starts on a newer configuration, and the chart's values schema, not startup, refuses a misspelling. A setting that cannot be read refuses startup by its key, never echoing a value. The signer credential, `ARKHAI_IDENTITY_CREDENTIAL`, is the only value the storefront reads from its environment besides the configuration directory, and it never enters settings. The image sets no application setting: its database is the packaged relative `db_path`, under the image's working directory, the data volume, and its command is `bare-metal-storefront serve`, which binds the configured `port` (8000 by default) unless `--port` overrides it.

A registry that gates writes behind a bearer token is given its token in the Secret overlay's `[registry.auth]`, a map from each configured `[registry].urls` entry to its token, matched by normalized URL. The storefront sends it beside its signed request, never in its place, on publication and on its status read alike. The chart's values schema refuses the table in public configuration, and an empty token is no token.

`[capacity.sites]` maps each site to its authority URL, and each site is bound to exactly one `[Identity.service_peers.<peer>]`, seeded at the server's start and rotated through the identity routes (see [`site-capacity`'s "Each site is trusted through its service peer"](../../openspec/specs/site-capacity/configuration.md#each-site-is-trusted-through-its-service-peer)). Health and status report each site by its ID, its service peer, and the peer's active principals, primary first, never its URL; a site's error text in status may name the URL, which is public configuration refused at startup when it carries credentials. `[capacity].poll_interval` (5 s), `[capacity].publication_interval_seconds` (30 s), and `[capacity].source_confirmation_seconds` (three poll intervals unless stated) time the projection poller, the publication loop, and the opening recheck's confirmation window. `[pricing].settlements` compile when the storefront starts, so a clause that cannot be read refuses startup naming the key; an empty list is not a refusal. `[negotiation].policies` names the seller chain.

`[Settlement]` is the strict shared settlement root. A configured Alkahest section, enabled or disabled, settles with at least one chain (`[Chains.<name>]` and its `rpc_url`, with an optional address book under `[Settlement.alkahest.address_books]`) and the wallet key (`[Wallet].private_key`, in the Secret overlay only), whose account is the seller's address; `[Wallet].address` may state it, and one naming another account is a blocker (see [`settlement-configuration`'s "Settlement consumer configuration and cutover"](../../openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover)). A section missing any input starts, and Alkahest readiness names each missing input as a blocker, since disabled sections still service accepted obligations. Those inputs supplied with no Alkahest section are refused at startup. Payments-only configuration supplies none of them and constructs no Alkahest wallet, chain, or RPC client; its payment credentials remain behind the secret boundary. The storefront delivers the `recipient` and `oracle_gated` release models; a section listing `interruptible`, enabled or not, refuses startup (see [`settlement-configuration`'s "Alkahest release models"](../../openspec/specs/settlement-configuration/configuration.md#alkahest-release-models)). Publication additionally requires authenticated registry trust, exact typed clauses, freshly confirmed site projections for its source checks, and a maximum lease duration per pool.

Under Compose, `compose.bare-metal.yml` holds topology only; a deployment's overlay mounts its `storefront.toml` and Secret overlay at `/etc/arkhai/` and gives the identity credential through an environment file, as `compose.bare-metal-local.yml` does for the lane, and nothing gives either a fallback (see "Per-domain stack composition"). The Helm chart, `helm/charts/bare-metal-storefront`, is the storefront chart's agent shape with one agent's keys at its top level: `config` rendered into `storefront.json` in a ConfigMap with null-valued keys removed (see "Storefront agents: pass-through configuration"); `secret` naming an existing Secret whose key is mounted as `storefront.secrets.toml`; `identity.credentialSecret`; `alkahestAddressBook` mounting an existing ConfigMap read-only; `caBundle`, mounting the payments CA bundle and deriving `[Settlement.arkhai_payments].ca_bundle_path` as the storefront chart's option does; `tests.paymentsAccount`, the account its payments check test pod reads; `port`, which the container, probes, and Service share; persistence; and scheduling. The pod's environment carries only `XDG_CONFIG_HOME` and the credential, and service links are off. The chart derives only what the release knows, and only where `config` states none: `port` always (a different stated value refused), `base_url` as the Service's URL, `db_path` under `persistence.mountPath`, `ca_bundle_path` whenever `caBundle` names a source (a different stated value refused), and, in an umbrella release, the internal registry's URL with the chart-level `internalRegistryTrust` under it and `[capacity.sites]` as `{default: <provisioning URL>}`. A site bound to the release's provisioning service must have a role-`service` peer naming `global.provisioningIdentity`, which the chart checks and never adds. Installed alone, with no umbrella globals, it derives all but the last two and refuses `internalRegistryTrust`. Its values schema is closed: the top level refuses every value it does not know, retired ones by name, and `config` is typed by a definition generated from the storefront's settings models, each section closed, so a misspelled or secret key is refused at render. A key stated in two spellings is refused at render too, since the loader would merge them silently. The chart validates no service semantics; the storefront's startup refusal does.

The selected-site authority owns inventory, executor routing, provisioning credentials, and teardown. The payments authority owns financial state. Buyer, storefront, site, and payment credentials retain their separate authority boundaries.

## Current limits

This document describes the pattern as implemented for services with
their own Deployment and profile-resolved settings. A service without a
Kubernetes deployment topology (no Helm chart), such as the API-credit
storefront and service, runs only under Compose: it migrates through the same
command before its application (see "Migrations at startup"), but has no
equivalent of a chart's configuration delivery.
