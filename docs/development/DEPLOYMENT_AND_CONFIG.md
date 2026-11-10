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

Every service in this repository but the registry uses the same
configuration shape, built on [Dynaconf](https://www.dynaconf.com/): a
committed `settings.toml` supplies base defaults, one or more
profile-specific `config-<profile>.yml` files layer overrides on top, and
environment variables under a service-specific prefix are the
highest-priority override. The registry is a Pydantic-settings service
that reads profile-shaped env files instead; see
[Registry descriptor configuration](#registry-descriptor-configuration).
The rest of this section describes the Dynaconf services.

**Resolution order, highest priority first:**

1. `<PREFIX>_*` environment variables — last-resort escape hatch only,
   never the normal way to supply configuration.
2. `config-<profile>.yml` files, one per entry in `ACTIVE_PROFILES`,
   applied in order.
3. `config.yml` files, default values.
4. `settings.toml` — committed defaults.

Each service picks its own `envvar_prefix` (for example, the compute
provisioning service uses `PROVISIONING`; the API-credits storefront
uses `APICREDITS_STOREFRONT`) and uses `environments=False` — this
repository uses named profiles instead of Dynaconf's built-in environment
concept, layered through `includes=[...]`, `merge_enabled=True`.

For compute provisioning and e2e, deterministic profile parsing, ordered
base/profile include resolution, and Dynaconf construction live in
`arkhai-kit-config`. Their composition roots still read `CONFIG_DIRECTORY`
and `ACTIVE_PROFILES` from the process environment and pass those values
explicitly to the shared loader. They also retain service-specific policy: settings
and secret files, environment prefix, dotenv location/discovery, missing-include
handling, wrappers, validators, and exported helpers. This boundary is scoped
to those migrated consumers; other services may still have separate loaders
until an explicit change migrates them.

Dynaconf dotenv loading contributes prefixed variables to the environment
layer rather than creating a file layer below profile includes. An already-set
process variable wins over the same dotenv key; otherwise a dotenv-sourced
prefixed variable overrides settings, secrets, base config, and profiles just
like any other environment value. E2e points Dynaconf at its project `.env`.
Compute provisioning uses Dynaconf's normal `.env` discovery and does not add
`.env.local` loading.

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

**Secrets travel in a secret profile or overlay file, never in a variable the
configuration names.** A service takes each secret it needs — an API key, a
bearer token, a wallet key — as a setting in a file its configuration system
layers: a Secret-backed `config-<profile>.yml` (or the registry's
`config-<profile>.env`) added to `ACTIVE_PROFILES`, or a storefront's
`storefront.secrets.toml` overlay. On a cluster that file is a Kubernetes Secret
key, which External Secrets writes; under Compose it is a bind-mounted file. A
setting that names an environment variable holding the secret is a second, weaker
channel beside the one a cluster already writes, so a service's configuration
does not name one, and trust follows the same rule: a private CA is a configured
bundle path the one client that needs it reads (such as
`[Settlement.arkhai_payments].ca_bundle_path`), never `SSL_CERT_FILE`, which would
replace the whole process's public trust. The one secret outside the rule is the
signing credential `ARKHAI_IDENTITY_CREDENTIAL`, which the identity specification
keeps from the loader, so it reaches a service as a variable sourced from a Secret.
A buyer's `api_key_env`, in its payments section or a `[[DisputeCredential]]`, is
not a service's configuration but the buyer's own exact named-variable provider,
beside its keyring and secret-file providers (see "Marketplace identity
configuration").

**A setting that belongs to one domain is named for it.** The compute
provisioning service reads the VM playbook from `vm_playbook_path` and the
bare-metal playbook from `bare_metal_playbook_path`; neither has an alias. A
renamed setting is refused rather than ignored, because an ignored key would
silently fall back to a default the operator meant to replace: the service's
first startup step refuses a configuration stating the retired `playbook_path`
in any layer, environment included, naming `vm_playbook_path`, and the
provisioning chart's values schema refuses `config.playbook_path`. The same step
refuses the retired `inventory_ini` and `inventory_path`, whatever value either
states, naming `host_definitions_path` (the operator handbook's
["Upgrading from an INI inventory"](../operator-handbook.md#upgrading-from-an-ini-inventory)
gives the upgrade). A setting
retired because the service stopped needing it, such as
`default_pool_inventory_group` and `default_host_id`, is not refused, since
ignoring it changes nothing the service does.

Before a package reaches 1.0.0, the meaning of a configuration key it reads may
change incompatibly in a minor release (see
[`RELEASING.md`, "Versioning policy"](RELEASING.md#versioning-policy)).

## Kubernetes: ConfigMap and Secret mounting

All application configuration travels through mounted files, never
individual pod `env` entries — this rule applies equally to the
application Deployment and to Helm test pods.

**Pattern:**

- Non-secret configuration renders from the chart's `values.yaml` into
  a ConfigMap, mounted at `CONFIG_DIRECTORY` as a `config-<profile>.yml`
  file. Adding a new non-secret key requires only a `values.yaml`
  change — no Deployment template change. The registry chart is the
  exception: the registry is a Pydantic-settings service whose profile is a
  dotenv file, `config-production.env`, and its chart maps each value to its
  variable by name, so a new registry setting also needs a line in its
  ConfigMap template (see "Registry descriptor configuration").
  The provisioning chart and the umbrella's generated smoke-test profile
  write JSON syntax into that YAML profile so 0x-prefixed EIP-191
  identifiers remain strings when Dynaconf reads it: Helm's YAML encoder
  leaves a 160-bit address unquoted, and a YAML loader reads it as an
  integer.
- Secret material (key material, credentials) that cannot go in a
  ConfigMap renders into a Kubernetes Secret whose data contains its own
  `config-<profile>.yml` key, mounted at the same `CONFIG_DIRECTORY`.
  The Dynaconf loader sees no difference between a file mounted from a
  ConfigMap and one mounted from a Secret — the profile name is simply
  added to `ACTIVE_PROFILES` alongside the non-secret profiles.
- A pod sets only `ACTIVE_PROFILES` (the list of profile names to layer,
  comma-separated) and `CONFIG_DIRECTORY` (where the mounted files live)
  as environment variables.
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

**The rule behind the pod rule.** Every configuration value of a storefront
reaches it through its configuration system: its configuration files and its
loader's documented override layer. A value travels outside that system only
when it controls which configuration is loaded — the configuration directory and
the profiles to layer — or when it must be kept from the loader, as the signing
credential `ARKHAI_IDENTITY_CREDENTIAL` is. A chart knows a configuration value
only where the deployment itself needs it for a stated reason, such as the port
its container, probes, and Service share, or the path of a file it mounts, such as
the CA bundle whose `ca_bundle_path` the storefront charts derive, and supplies
outside the configuration system only values of those two kinds. A storefront's
secrets — its wallet key, a registry write token, its payments `api_key`, its
`[[DisputeCredential]]` entries — are settings in its Secret overlay, never pod
variables, so a storefront pod's environment holds only `XDG_CONFIG_HOME` and the
signing credential. Conformance is a property of the source and
charts, judged there, never a runtime refusal: a storefront does not refuse to
start because a value reached it through its environment, and the override layer
stays available to an operator correcting a development cluster. Both storefront
charts set `enableServiceLinks: false`, because Kubernetes would otherwise inject
variables for every Service in the namespace, and one named `storefront…` would
land in the storefronts' `STOREFRONT_` override layer.

**A deployment does not wait on a service's dependencies.** No chart holds a
service back with an init container that waits for or validates an external
dependency — a chain, a registry, a site, or another service — and no service
waits for one in process either. The service starts with its dependencies
unreachable, reports each one it cannot reach in its system status as degraded,
and its own loops retry it; a misaddressed dependency is indistinguishable at
start from one that is down, so it is reported the same way rather than refused.
The one init container a chart runs for a service is that service's own
migration — the provisioning service's, each storefront agent's, the bare-metal
storefront's, and each registry instance's — which acts on the service's own
state (see "Migrations at startup"). What stops a
service is its own configuration or stored state being incoherent (see
"Storefront startup and site trust"), since waiting does not repair either. Both
storefront charts give their container a `startupProbe` on `/health`, so a slow
start holds the liveness and readiness probes off rather than being judged by
them; `/health` is a process check that calls no dependency. Each storefront
chart's render tests assert that no `wait-for-` container renders, that exactly
one init container does — the storefront's migration command from the
application's image over its data volume — and that the `startupProbe` does; the
provisioning and registry charts' render tests assert their migration init
container the same way.

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

**The umbrella's smoke-test profile.** The generated `<release>-test-config`
profile carries what its smoke hooks read and the release's values state: the
registry pins `registry.authority_id` and `registry.identifier`, which are what the
release's clients trust (`global.registryIdentity`), carried only for the internal
registry and only for an EIP-191 identity, the one scheme the registry smoke test
verifies; `buyer.wallet_address`, from the e2e-tests chart's development buyer
identity; `seller.wallet_address`, from the target agent's `[Wallet].address` when its
configuration states one, and absent when the agent derives its address from
its key; and
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
hex value, because a YAML loader reads an unquoted `0x`-prefixed value as an
integer.

### Storefront agents: pass-through configuration

The VM and bare-metal storefronts do not use profiles; each reads up to three files
from `$XDG_CONFIG_HOME/arkhai/`, a later file winning on a conflicting key:
`storefront.toml` (an operator's own file), `storefront.json` (the public
document the chart renders), then `storefront.secrets.toml` (the Secret
overlay). The chart mounts the last two at `/etc/arkhai/`.
`market-storefront config show` reports the files merged as the server merges
them; `--raw` prints each public file and never the overlay.

`storefront.agents` is a map from each agent's name to its entry, not a list,
because Helm merges maps key by key and replaces lists whole: an overlay states
only what it changes in one agent, and `null` removes a key or an agent. A list
is refused by the values schema, naming the map, and so is a `name` inside an
entry, whose key is its name. The storefront subchart ships no agent; the
umbrella's `values.yaml` declares Bob, and a values file that replaces Bob with
an agent of its own states `bob: null` beside it. The same holds for any chart
value that overlays change per entry: key it, do not list it.

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
storefront refuses it at startup. To set a value to `None` where the storefront
accepts it, use the storefront's own file or the Secret overlay instead.

Removing every agent is refused at render; set `storefront.enabled: false` to
run none. Removing an agent's `port` or `identity` is also refused, naming the
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
"Settlement consumer configuration and cutover"). The `dev-env` chart,
which deploys the Anvil state the book describes, renders its copy of
`kit/alkahest`'s development address book as `<release>-dev-env-alkahest-addresses`.

An agent's `caBundle` (`configMapName`, or alternatively `secretName`, never both;
`key`, default `ca-bundle.pem`) mounts an existing ConfigMap's or Secret's key
read-only at `/etc/arkhai/ca/ca-bundle.pem`, and the chart sets
`[Settlement.arkhai_payments].ca_bundle_path` to that file: the path is derived
from the mount rather than configured beside it, so the two cannot disagree. Only
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
the ZeroTier capabilities and device. The check is described under "Settlement
consumer configuration and cutover".

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
running pod; recover with `helm rollback`.

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
misspelled key there is ignored by the storefront.

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
storefront starts without waiting for its provisioning service; and the local-inventory keys,
which startup does not refuse (see "Settlement consumer configuration and
cutover"). The chart's hand-written block holds only the chart's own retired values
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
back as a string. Every number in a values file passes through a float on its
way into Helm, so write an integer above 2^53 as a string.

## Storefront startup and site trust

**A storefront that cannot publish refuses to start.** The VM and bare-metal
storefronts derive their listings from site projections, and each refuses to start,
naming every problem, when publishing is impossible for the whole storefront:
`[registry].urls` is empty, or a registry lacks its `[registry.authorities]` pin; no
`[Settlement]` mechanism is enabled, or the root does not resolve; `[capacity.sites]`
is empty, a site is bound to no `[Identity.service_peers]` peer or to several, or a
site's URL is not an HTTP(S) origin. The bare-metal storefront also refuses a
`[registry.authorities]` pin or a `[registry.auth]` token naming a URL that is not among
`[registry].urls`, and two tokens naming one registry once normalized, naming the table
and the URL and never the token. The refusal runs before the storefront opens its
database or builds a signer, so it leaves no database file and starts no loop.
Missing storefront-wide terms are not a refusal: an empty `[pricing].settlements` or
an absent `[pricing].default_max_duration_seconds` leaves the terms to each pool's
override or hint. A pool that resolves no lease bound is held and reported in system
status's `publication_derivation`; a candidate whose pool resolves no settlement
clause is refused as `no_settlement_option`, and its open listing is closed through
reconciliation and reopened under the same identity once a clause resolves (see
"Storefront listing shapes and pool overrides"). Retired settings are refused under their own
heading, apart from these, since a stale key is not a reason publication is
impossible. A storefront that only services deals already accepted is not a supported
deployment. A storefront chart cannot check any of this, which is why each chart's
render tests run the storefront's own refusal over a rendered `storefront.json`.

**A service refuses to start on its own incoherent state, never on a dependency.**
A service refuses to start when its own configuration contradicts itself or its
stored state cannot be served as it stands, since waiting repairs neither; a
dependency it cannot reach is reported, not refused (see "Kubernetes: ConfigMap and
Secret mounting"). Every storefront refuses an Alkahest section, enabled or not,
listing a release model its domain cannot deliver (see "Alkahest release models"),
and the bare-metal storefront
refuses Alkahest inputs — `[Wallet].address`, `[Chains]`, `[Wallet].private_key` —
stated with no Alkahest section. The provisioning service refuses to start while a
stored resource pool lacks valid advertisement and backing declarations, or names a
provider no handler in its build serves, naming each pool and provider: handlers are
fixed by the build and every write refuses an unknown provider, so such a row comes
from outside the service's write paths, and no pool document can repair it.

**A storefront starts with its dependencies unreachable.** None waits for its
registry, chain, site, or credits service. The VM storefront's
`[seller.provisioning]` and the API-credit storefront's `credits` sections have no
reachability preflight: their removed `fail_on_unreachable` and `preflight_timeout`
keys are retired settings, refused at startup and, for VM, by the values schema and
`market-storefront config set`. A storefront started with its registry unreachable
reports the registry check unreachable and itself `degraded`, and its publication
cycle still completes, each listing it could not publish recording
`registry_not_converged` until a later cycle publishes it. One started with its site
unreachable holds no projection of that site, so its cycle holds the site's listings
and closes none, and its fulfillment and settlement calls to the site fail
retryably. API credits' configured seed listing is created by its `listing-seed`
loop step, which waits while the credits service cannot be reached or a mechanism
its clauses use is unknown, and gives up, logging once, on a configuration failure.

**An Alkahest section that cannot settle makes Alkahest unready.** A section that
parses but under which no deal could settle is reported through Alkahest readiness
blockers, its options are not published, and the storefront's other mechanisms run:
`oracle_gated` with no `trusted_oracle_addresses`, `interruptible` with no
`interruptible_oracle_addresses`, a release oracle equal to the seller wallet, a
seller wallet with no address, no private key where the storefront signs, no
`[Chains]` entry, an address configuration that cannot be loaded, or a release
model the storefront's domain does not deliver (bare metal delivers `recipient` and
`oracle_gated`). A section that does not parse stops startup, as all configuration
does. A disabled section reports, after `disabled`, the configuration blockers that
would keep it from settling. Readiness governs publication only: an address, chains,
or key removed while Alkahest deals are open leaves the seller unable to service or
collect them, the buyer's escrow staying reclaimable at expiry, and the blocker
naming what is missing is the operator's signal. Every readiness blocker states its
`kind`: `configuration`, which the storefront's own settings cause, or
`reachability`, when the mechanism's chain or service could not be reached;
publication reads the kind to decide whether an open listing left with no option is
closed or held (see "Storefront listing shapes and pool overrides").

**Alkahest probes its chains.** Readiness makes no chain call. Each storefront
composing Alkahest runs an `alkahest-chain-probe` lifecycle loop that, once per
`[Settlement.alkahest].probe_interval_seconds` (30 by default), reads each
configured chain's `eth_chainId` and the code at each contract its address
configuration requires, each call bounded by `rpc_timeout_seconds` (5 by default);
both are seller settings and positive seconds. An RPC that errors or times out reads
as the reachability blocker `alkahest.chain_unreachable`; a different chain ID is
`alkahest.chain_id_mismatch`, and a required contract with no code
`alkahest.contract_missing`, both configuration blockers. A chain not yet probed
since start reads as unreachable, so a freshly started storefront holds its open
Alkahest listings rather than closing them; a result does not expire, so while the
loop is held readiness reads the last one however old. Startup constructs no chain
client: the probe constructs each at its first step, waiting no longer than the RPC
timeout, and again at each probe until one succeeds, so a storefront recovers
without a restart, and a chain whose client cannot be constructed reads
unreachable whatever its RPC answers. The probe calls a `ws://` or `wss://`
`rpc_url` over `http://` or `https://` at the same host, port, and path, so a
provider serving the two on different endpoints reads as unreachable. Status
readiness judges every configured chain, so `ready` there means every one is
reachable and deployed; publication judges the chains a candidate's escrows name,
and one unreachable chain among them withholds the candidate's Alkahest options on
all of them.

**A site's authority URL is an origin.** Each `[capacity.sites]` URL is parsed by the
WHATWG URL standard (pydantic's `AnyHttpUrl`) and must have an `http` or `https`
scheme and no credentials, path other than `/`, query, or fragment; an ASCII control
character anywhere in the value is refused before parsing, since the standard would
drop it rather than refuse it. The site's clients are given the normalized origin
(scheme and host lowercased, an international host as punycode, a default port
omitted, no trailing `/`). A refusal names the site's key and never echoes the URL.
The check is the storefront's at startup, not the chart's values schema; a host the
standard accepts but nothing resolves fails at the first poll.

**Each site is trusted through its service peer.** Every configured site is bound to
exactly one `[Identity.service_peers.<peer>]` (`role = "service"`, `site_id`, and
`principals`). The storefront seeds the peer into its durable identity state when the
server starts, and the durable state then owns its principals: the site's responses
and callbacks are verified against the peer's active principals, and they rotate
through the storefront's identity routes with bounded overlap, reaching verification
as the rotation commits. Configuration must keep covering them: startup refuses
configuration that no longer names a seeded peer's durable primary and every
principal active in an overlap, so a restart after a rotation needs configuration
naming the replacement. The service-role read of system status is accepted from any
configured site's peer. There is no storefront-wide provisioning trust set; VM refuses
a configuration stating `[provisioning.identity]`. The bare-metal storefront's
administrators stay in configuration, so its identity routes refuse to rotate one.

**Durations are positive seconds.** The typed durations — bare metal's intervals and
timeouts (`[capacity].poll_interval`, `[capacity].publication_interval_seconds`,
`[capacity].source_confirmation_seconds`, `negotiation_timeout_seconds`,
`negotiation_watchdog_interval`, `settlement_servicing_interval_seconds`,
`payment_reconciliation_interval`), VM's `[capacity].poll_interval`,
`[capacity].source_confirmation_seconds`, `settlement_servicing_interval_seconds`, and
contact retention's `retention_sweep_interval_seconds`, and the API-credit
storefront's `settlement_servicing_interval_seconds`, `[capacity].poll_interval`, and
watchdog and payment-reconciliation intervals — are positive, finite numbers of
seconds that can be applied to an instant without leaving `datetime`'s range: at most
the span from year 1 to the Unix epoch, about 1,969 years, and at least a
microsecond. A value outside that is refused by its key when the storefront starts.
`[capacity].source_confirmation_seconds` is how old a site's last successful
projection poll may be for a listing-source check to confirm a listing against it;
unstated, it is three poll intervals, and a poll interval whose derived window could
not be represented is refused by the interval's key. A storefront whose loops are held
while it trades refuses sources older than the window as retryable, until an operator
steps `site-projections`; the end-to-end lanes and the local Helm release widen it to
an hour, a development value.

**The settlement servicing interval.** VM's and the API-credit storefront's servicing
sweep reads `settlement_servicing_interval_seconds` (30 by default), as bare metal's
does; a configuration still stating `claims_sweep_interval` refuses startup, naming
its replacement. The API-credit storefront has no chart, so its startup refusal is the
only guard there. It also refuses, by key and before its signer or database, capacity
sites whose authorities are not valid principals and a capacity poll interval that is
not positive seconds.

**System status.** Each storefront's system status reports its lifecycle loops as
`lifecycle`: each loop's state and last cycle's outcome, a failure's stage and error
type, and its message only for the storefront's own configuration and publication
errors. Each also reports `settlement`, every composed mechanism's readiness as its
registration projects it — `mechanism`, `ready`, and each blocker's `code` and
`kind` — with Alkahest's carrying each chain's last probe result and when it was
taken (`chain_probe`); and `status` is `degraded`, rather than `ok`, while a check
such as the registry's fails, the process itself still serving. The VM and
bare-metal storefronts also report each site's projection families and its
`publication_derivation`, in one shape for both: per site, the `holds`, `refusals`,
and `reports` the last real publication cycle made, each entry a reason code with
the pool or Physical Resource it concerns and any detail. Only a publication cycle
records it — a preview, a listing-source check, and capacity-event reconciliation
do not — so a configured site no cycle has derived since start is absent, and a site
present with empty lists derived cleanly. The storefront logs each entry as a
warning when it first appears and at info when it clears, and never logs a standing
entry again or a preview, so a condition that lasts many cycles is logged once. A
cycle that cannot read a site at all records a hold naming no pool, and the site's
other entries from the last cycle that read it stand beside that hold until a cycle
reads the site again. The API-credit storefront's status is the
administrator's signed read (`admin_system_status`), as VM's and bare metal's are;
`/health` stays unauthenticated and is a process check.

## Marketplace identity configuration

Services configure canonical public principals and trust pins in ordinary
configuration, with service-owned credentials supplied through their Secret
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

The registry is a Pydantic-settings service rather than a Dynaconf service, but it
takes the profile resolver variables the Dynaconf services take. Each setting is
read by its variable name from, a later source winning on a key both state: the
dotenv files `.env.local`, `.env` and `/app/shared-env/.env`, each skipped when
absent; then `<CONFIG_DIRECTORY>/config-<profile>.env` for each entry of
`ACTIVE_PROFILES`, in order, each skipped when absent; then the process
environment. A profile file has the dotenv form, so a JSON value goes on one
single-quoted line. The registry parses `ACTIVE_PROFILES` itself rather than
through `arkhai-kit-config`, which builds only Dynaconf loaders. The filter
specification is a setting, `REGISTRY_FILTER_SPEC_PATH`, unset meaning the
packaged `filter-spec.yaml` ([`core/registry/README.md`](../../core/registry/README.md)
lists the sources and settings).

Every Compose registry takes its `REGISTRY_*` values from committed profiles in
`dev-env/registry/` ("Per-domain stack composition"). The registry chart renders
its values — identity, descriptor, `config.*`, `service.port`, the credential
file's path and the filter specification path — into a ConfigMap key,
`config-production.env`, mounted at `/app/config/config-production.env`, and the
Deployment's environment holds only `CONFIG_DIRECTORY=/app/config` and
`ACTIVE_PROFILES`. Secret settings — the bootstrap key
`REGISTRY_BOOTSTRAP_API_KEY` and the administrator key `REGISTRY_ADMIN_API_KEY` —
arrive as `secretProfile: {secretName, profile}`: a pre-existing Secret holding
`config-<profile>.env`, as External Secrets writes one, mounted beside the
rendered profile and appended to `ACTIVE_PROFILES` after `production`, so a
setting it states overrides the rendered one. The profile may not be named
`production`. `auth.bootstrapKeySecret` and `auth.adminKeySecret` are refused at
render, naming `secretProfile`; the operator handbook's
["Registry secret profile"](../operator-handbook.md#registry-secret-profile) gives
the move.

The public descriptor fields are `REGISTRY_DESCRIPTOR_BASE_URL`,
`REGISTRY_DESCRIPTOR_DISPLAY_NAME`, and `REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY`,
the chart's `descriptor.baseUrl`, `displayName` and `operatorIdentity`. When
`REGISTRY_REQUIRE_READ_API_KEY=true`, the deployment must also set
`REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER`; a public registry must omit
that pointer. Startup rejects missing fields and either posture mismatch.

These values are public operator assertions. The service derives the
descriptor's authority principal from the credential-backed active signer and
derives its schema identity from the loaded filter specification. Helm keeps
the descriptor values in ordinary values while mounting the signer credential
from a Secret. Compose profiles likewise carry public descriptor values beside
public identity pins, and the overlays keep signer credentials in service-owned
file mounts.

An operator may also supply `REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES`
(a JSON array), or Helm `descriptor.recommendedDisputeAuthorities`. Each item has
an authority's full identity, interface-owned `params`, and an `advertisement`
copy as described under [Dispute authority preferences](#dispute-authority-preferences).
The signed descriptor exposes them in preference order as
`recommendedDisputeAuthorities`; an empty or unconfigured list is omitted.
No registry code or chart ships an authority. Recommendations are public
operator assertions, not credentials and not an instruction to override a role's
local policy. Roles verify the descriptor under that registry URL's configured
identity pins before using it.

The umbrella chart enables the compute registry by default and keeps the
`api-credits-registry` alias disabled. Enabling the alias instantiates the same
schema-opaque registry chart a second time. The compute instance selects
`/app/filter-spec.yaml` (`compute.market`); the API-credits instance selects
`/app/filter-spec-apicredits.yaml` (`api_credits`). Both specifications are
packaged in the registry image, but each process loads exactly one. Identity,
credential Secret, descriptor, `secretProfile`, Service, and PVC values are
instance-local. `global.registryIdentity` continues to configure
the compute storefront's trust pin and does not constrain the alias signer.

## Per-domain stack composition

Each domain stack owns its public topology while consuming shared core/kit
authorities:

- `compose.vms.yml` composes the VM storefront and compute authorities.
- `compose.apicredits.yml` composes the API-credit registry, credits authority,
  gated sample service, and API-credit storefront.
- `compose.bare-metal.yml` composes the dedicated bare-metal storefront with a
  compute-family registry and the selected-site provisioning authority.
- `docker-compose.yml` is the full local stack: it includes `compose.vms.yml`
  and `domains/apicredits/compose.yml`, so the dev chain enters once.

**A stack's configuration lives in committed files.** Every value a stack runs
with is in a committed profile, overlay, values or secret-overlay file. A Makefile
chooses which configuration loads — the Compose files, a profile, a mode — and
never generates or carries configuration itself. A value the base topology fixes
stays in the base file; a deployment's own values are in its overlay.

Each base file — the domain files and `compose.bare-metal.yml` — composes topology
only: images, ports, volumes, health checks, the database paths, `REDIS_URL`, a
callback URL naming a service, and the container paths of definition documents.
It binds no identity, configuration file or secret and gives none a fallback, so a
service brought up without an overlay refuses to start for want of its
credential or document, rather than Compose refusing at parse time. Every
development binding lives in a root-level overlay layered with `-f`, stated
literally and relative to the repository root, the project directory of every
`-f` file:

| Overlay | Binds |
|---|---|
| `compose.vms-local.yml` | the VM services' identities; Bob's and Alice's `storefront.toml` and secret overlays; both VM registries' profiles and credentials; both provisioning services' site profiles; the development Alkahest address book; the VM buyer service |
| `compose.apicredits-local.yml` | the API-credit services' identities and admin key; the storefront's `storefront.toml` and secret overlay; the API-credit registry's profile; the credits buyer service |
| `compose.bare-metal-local.yml` | the bare-metal registry's and site's profiles, identities and definition documents; the storefront's development `storefront.toml`, secret overlay, address book and lane CA; the buyer service and Mailpit |
| `compose.payments-double.yml` | the payments lane double, run by every end-to-end lane and never by the full local stack |
| `compose.vms-lane.yml`, `compose.apicredits-lane.yml` | each lane's own bindings: its payment storefront's lane configuration and the lane CA, and the registry profile recommending the double's pinned dispute authority; the API-credit lane also runs a compute-schema registry of its own, which the credits scenario routes discovery away from and the full local stack never runs, since VM's registry fills that role there |

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

and each end-to-end lane's target in `e2e-tests/Makefile` (`test-e2e-vm`,
`test-e2e-bare-metal`, `test-e2e-apicredits`) names only its compose project and
files and the run's mode; its `-down` and `-logs` targets name the same. Each
overlay's header gives the command it belongs to.

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

Storefront images install their distributions from the staged `.dist`
wheelhouse; runtime images do not resolve editable sibling source. API-credit
and bare-metal SQLite/queue/registry stores occupy separate named volumes.

Stack files carry public URLs, canonical principals, explicit Resource Pool
offering modes, and exact selected-site bindings. Signer, API-admin,
provisioning SSH, payment account, and buyer credentials are independent
service-scoped file references with no committed fallback. Missing identity,
inventory, pool declaration, site authority, or credential blocks startup or
scenario preflight; it never selects a test signer, default site, payload-
guessed domain, direct executor, or provider simulator.

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

Each service owns its own database; there is no shared database between
services (see `openspec/specs/deployment-state/spec.md`'s "Explicit
persistence ownership"). A SQLite-backed, single-writer service uses
`Recreate` deployment strategy with a `ReadWriteOnce` volume — SQLite's
single-writer model does not tolerate the overlapping old/new pod
window a `RollingUpdate` strategy would otherwise produce against a
shared volume.

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
uninstall until it is deleted by hand.

Deploy to a local development cluster with `make -C helm deploy-local`, never with
`make -C helm deploy` or the root `make deploy`, whether a person or an agent is
deploying. A local cluster is redeployed with whatever code is checked out, and a
retained volume keeps the state that code wrote — a database another branch
migrated — for the next deployment to start from. Pre-review validation run in
`default` refuses to deploy over a release volume that carries the annotation and
stops to ask, so a local deploy without the overlay costs the next validation a
decision; a change's validation runs in its own namespace instead and deletes its
volumes itself ("Validation namespaces", below). `make -C helm deploy` is for a
deployment whose state must survive reinstalling.

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
storefront is enabled, the umbrella's smoke-test profile checks that provisioning
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
1's provisioning SSH and runtime Secrets and reads three of its own.

**A local release configures a service through the values a deployment uses.**
The local release is where a deployment's shape is rehearsed, so it configures
each service through the same values, files and Secrets a deployment supplies,
never through a development-only mode. Payments are the example: both
storefronts settle in `arkhai.payments.v1` against the payments lane double
through `[Settlement.arkhai_payments]` in their `config`, the `caBundle` option on
the `payments-ca-bundle` ConfigMap, and the payments `api_key` in their runtime
Secret's overlay, never `development_auth`. The double is the `payments-lane-double`
subchart, which `helm/local-values.yaml` enables and no release values do. Its
Service is named `payments-double`, the name its certificate is issued for, in
every release, so a namespace runs one: release 2's values disable the subchart,
and its storefront reaches release 1's double by that name. Release 1's registry
recommends the double's pinned dispute authority, and Bob's overlay carries his
`[[DisputeCredential]]` for it, as the VM lane's does; release 2's storefront
carries none, as the bare-metal lane's does. Each storefront's payments check test
pod reads the double's seller account. The release serves no payment scenario.

- `make helm-topology-secrets` creates or replaces, idempotently, every Secret both
  releases read, and the `payments-ca-bundle` ConfigMap, in its namespace, which it
  creates when absent (`make -C helm topology-secrets CHANGE=<change>` for a
  change's validation namespace), deriving each key with `cast` from Foundry's
  default development mnemonic at `helm/Makefile`'s `DEV_ACCOUNT_*` indices
  (development values only); provisioning's SSH key is the committed mock
  placeholder, `PROVISIONING_SSH_KEY_FILE`. It takes the committed lane CA, from
  `tools/lane-double-controls/tls/`, for the ConfigMap, and from the payments lane
  double's committed fixtures the seller's token, which it
  writes as `[Settlement.arkhai_payments] api_key` into both storefronts' runtime
  overlays, and it copies Bob's `[[DisputeCredential]]` from his Compose secret
  overlay, `dev-env/identities/bob.storefront.secrets.toml`, so both stacks hold one
  value. `helm/scripts/topology-secrets.sh` says what each Secret holds. It also
  creates, if absent, the deal test's buyer-profile volume, `arkhai-buyer-profiles`,
  which no chart creates, and leaves an existing claim as it is.
- `make helm-topology-up` installs or upgrades release 1, then release 2, each with
  `--wait`, and then restarts both releases' Deployments — the registry, then the
  provisioning services, then the storefronts, each restart waited on — because local
  images keep bare tags, so an upgrade alone leaves every pod on its old image. It
  never restarts `dev-env`: its Anvil reloads its state file, so the contracts
  survive, but a restart loses every transaction since start-up that the other
  services' volumes still refer to. Nor does it restart the payments double, which
  keeps every payment in memory, so a restart would lose each transaction the
  storefronts' databases refer to.
- `make helm-topology-check` runs both releases' `helm test`, each storefront's
  payments check among them, and `make helm-topology-down` removes release 2, then
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

An end-to-end scenario that needs release 2 states `make helm-topology-up` on its
Makefile target and in its suite module's docstring; the Helm validation scenarios
need release 1 alone.

**Helm test pods carry no workload selector label.** Each chart labels its Helm
test pod through its own `<chart>.testLabels` helper: chart, version, managed-by,
instance, and `app.kubernetes.io/component: test`, but never
`app.kubernetes.io/name`, which every Deployment selector requires. So
`kubectl logs -l <selector>` or `kubectl logs deploy/<name>` finds only the
service's pods, and no Service routes traffic to a test pod. Adding `component`
to the Deployment selectors instead is not available: a selector is immutable, and
changing one forces each release to recreate its Deployments.
`helm/tests/test_release_topology.py` renders both topology releases and asserts
that no Pod annotated `helm.sh/hook: test` carries all of any Deployment's
`matchLabels` or any Service's selector, and that each release renders its expected
test pods.

### Validation namespaces

A change's pre-review validation deploys release 1 into a namespace of the change's
own, so several changes are validated side by side on one development cluster
without uninstalling each other's release (this repository's part of the change
workflow, `openspec/specs/market-change-workflow/spec.md`, MCW-fnuh "Each Helm
validation deploys into its change's namespace under its change's tag").

- **The namespace.** `validate-<change>`, cut to 63 characters with the first eight
  hex digits of the full name's SHA-256 appended when longer
  (`scripts/change_namespace.py`). Every `helm/Makefile` target that takes
  `NAMESPACE=` also takes `CHANGE=`, deriving the namespace the same way; giving
  both is refused. Release names do not change with the namespace, so the in-cluster
  Service names `local-values.yaml` states resolve in every one, and the two-release
  topology fits in it.
- **Image tags.** Every build target appends `IMAGE_SUFFIX`, empty by default:
  `make build-dev IMAGE_SUFFIX=-<change>` builds `arkhai:storefront-<change>` and its
  siblings, and the deploy names them through a values overlay naming every `arkhai`
  image `helm/values.yaml` sets (`change_namespace.py <change> --image-overlay
  <path>`); a render test holds the overlay to every image the chart renders, so an
  image added later cannot deploy under its bare tag. Compose, the pipeline lanes,
  and your own deployments keep bare tags. A namespace alone would not isolate
  images, since every image is pulled `IfNotPresent` from the one Docker daemon the
  cluster reads. The tag is fixed per change, never per commit: commit-suffixed tags
  caused repeated image-not-found failures deploying Helm, and a rebuilt image under
  a fixed tag rolls out by restarting pods. A suffixed build writes no commit tag; a
  bare build still writes `arkhai:<tag>-<sha>`, which `make push-images` reads.
- **Upgraded from zero over deleted volumes.** Each validation of the change scales
  the release's workloads to zero if a crashed run left any up, deletes its pods,
  its volume claims, and the deal test's `arkhai-buyer-profiles`, and waits until
  they are gone; creates the namespace's Secrets with `topology-secrets`; and runs
  `helm upgrade --install` with `local-values.yaml` and the change's image overlay,
  then restores each workload's replica count and waits for its rollout. Every pod
  starts new, on the images just built, against empty volumes. An upgrade the chart
  refuses (`field is immutable`) falls back to uninstalling and installing.
- **Scaled to zero afterwards.** Once the scenarios have run, validation keeps
  every pod's log and the namespace's events, then scales the namespace's
  Deployments and StatefulSets to zero, keeping objects and volumes, so resident
  memory does not grow with the active changes. `make -C helm resume CHANGE=<change>`
  scales them back to the replica counts the installed release states, rendering
  nothing from the checkout.
- **Manual access.** `make -C helm forward CHANGE=<change>` forwards that
  namespace's services on the usual ports (8545, 8080, 8001, 8081) for running e2e
  targets by hand. The ports are the same for every namespace, so one namespace is
  forwarded at a time: a port another checkout already forwards fails to bind, and
  `forward` names it and stops. Validation itself forwards nothing.
- **Capacity.** The node's memory is the one resource the namespaces share.
  `helm/validation-capacity.toml` records the memory one release needs, when, and
  from which change's validation it was measured; before deploying, validation
  compares that figure, times the releases that would then be running, with the
  node's allocatable memory, and stops for a deployment that would not fit. The
  check is an estimate that reserves nothing. The figure is measured through the
  cluster's metrics API and written at archive cleanup (`make record-capacity`)
  only when the change's latest validation measured one; on a cluster with no
  metrics source none is recorded, and the check warns that it was skipped. Where
  two branches' figures conflict at a merge, keep the one whose `measured_at` is
  later.
- **Teardown.** Archive cleanup runs `make -C helm teardown CHANGE=<change>`,
  which deletes the change's namespace in `HELM_CONTEXT` (`docker-desktop` by
  default), with every release, volume, and Secret in it, and removes each image the
  change's validation build tagged. It takes `CHANGE=` only, so it never deletes
  `default`.

### Combined compute-family storefront

The storefront image installs the shared `arkhai-core-storefront` shell plus
each enabled domain contribution from staged `.dist` wheels. Public
configuration contains a non-empty `storefront_domains` list; every row names
one contribution, exact offering mode, domain identity, and contract version.
Trusted provisioning authorities remain separately configured site bindings.
The Helm chart and Compose profile run one storefront process against one
single-writer SQLite volume; they do not start one container per domain. Under
Helm the list is each agent's `config.storefront_domains`, passed through as
written (see "Storefront agents: pass-through configuration").

`storefront_domains` is public routing metadata only. Signing credentials,
provider settings, SSH material, tenant credentials, payment-provider objects,
and private domain results remain in service-owned Secret channels and never enter
ConfigMaps, command arguments, images, listing bindings, or migration reports.
Startup rejects missing wheels, duplicate modes/identities, assertion mismatch,
unsupported versions, incomplete capabilities, or recoverable bindings that
the frozen registry cannot resolve.

Each listing binding records its capacity backing, and each closed listing records
whether its seller or reconciliation closed it. Both columns are enforced by
triggers: the required-backing insert trigger
`storefront_listing_binding_backing_required`, and the two closure-reason triggers
`listing_closed_by_consistent_insert` and `listing_closed_by_consistent_update`.
A registry that publishes the backing field keeps it; an older reader ignores it.

The combined storefront's publication loop publishes VM; bare-metal publication
runs in the dedicated bare-metal storefront's own loop. Storefront-wide terms of sale are configuration — `[pricing].settlements` and the per-model
`[pricing.defaults.gpu.<model>].settlements`, `default_max_duration_seconds`, and
the family rates `[pricing.defaults.gpu.<model>].rates` and
`[pricing.defaults.<family>].rates` (see "Storefront listing shapes and pool
overrides") — beneath each pool's own `pricing` declaration and the storefront's
per-pool overrides. `[pricing].default_min_price` is the negotiation floor for a
selected settlement option that advertises no rate, in base units per hour as
decimal text; a fractional number is refused when a negotiation first needs it.
The storefront refuses to start with a configured family rate it cannot read.
`default_token_address` and per-model `min_price` and `token` configure nothing; the
storefront names any it finds at startup. A change to any of them reaches open listings on the next publication
cycle; `market-storefront publish` runs or previews that cycle and takes no terms
of its own.

## Definition documents

A service may be given the path to a YAML document describing resources it
should hold — relays, pools, hosts, capacity declarations. The document is
mounted like any other configuration file and is not a Secret: it carries
endpoints, addresses, windows, quantities, and the *names* of profile keys and
key files, never a credential.

Four settings name such a document, all read by the provisioning service:
`relay_definitions_path`, `pool_definitions_path`, `host_definitions_path`, and
`capacity_definitions_path`. The provisioning chart derives each from the
presence of its value under `definitions` (`relays`, `pools`, `hosts`,
`capacity`) rather than configuring it beside the document, because two
independent settings can disagree and the failure when they do is silent: the
document renders, the volume mounts, and the service skips an unset path while
everything looks configured. The chart's schema refuses every one of the four
paths under `config` for that reason. Every value is empty by default, so a
deployment that supplies none is managed entirely through the API.

Startup imports them in dependency order: relays, then pools (which may name a
relay), then the pool seed on a fresh site, then the check of every stored pool,
then hosts (whose entries may name a pool), then capacity (whose declarations
name a pool and may name a host). Every pool a host or capacity document names
must exist when it is imported: already stored, or created by the pool document,
or, on a fresh site with none, by the seed.

### The method a document kind follows

This is the method a document kind is held to. The pool, host, and capacity
kinds each have a paragraph below naming the setting and where the kind's own
rules are: its specification, and the
[operator handbook](../operator-handbook.md#definition-documents) for its
format and the procedures around it. The host document follows all of the
method, and a new kind follows it. The others diverge in part: the capacity
document has no export, the relay document has no import route or export, and
the pool document validates at its own route and its import and export answer
in their own shapes.

- **One path setting, derived by the chart.** `<kind>_definitions_path` is set
  by the provisioning chart from `definitions.<kind>`, rendered into its
  ConfigMap so that an edit rolls the pod through the ConfigMap checksum,
  refused under `config`, and mounted under a name `configFiles` refuses.
- **A digest kind, recorded in the apply's transaction.** A startup applies a
  document only when its digest differs from the one recorded under its kind
  (see "Reconciliation follows the document, not the process").
- **A session-scoped apply that fails whole.** Validation is strict and runs in
  two stages, reporting every problem with its location; any problem leaves the
  document unapplied, fails startup, and records no digest. An entry equal to
  stored state writes nothing.
- **An explicit import that always reconciles.** The kind's import route records
  no digest and offers `validate_only`, answering one response: whether it
  applied, the planned or applied changes, and every problem with a path and a
  code. An applying request with any problem answers 422 and applies nothing;
  `validate_only` answers 200.
- **Validate before the release.** Submit a changed document to its validation
  route — its import route with `validate_only`, or for pools
  `POST /api/v1/pools/validate` — before the release that mounts it: the chart
  replaces the pod with `Recreate`, so a document the service refuses at
  startup leaves nothing serving, while the pre-flight reports the same
  problems against live state without applying anything.
- **A stated rule for entries it stops naming** (see "What a document does to
  entries it stops naming").
- **No credential.** A secret is named by its profile key or file path.
- **A slot in startup's dependency order**, above.
- **A canonical export where the kind round-trips**, so an existing site can
  produce a first document that reproduces its state.

### Pool definitions

`pool_definitions_path` names the pool document, a top-level `pools` list; the
provisioning chart sets it from `definitions.pools`. A site that configures none
and stores no pool is seeded once from the document `pool_seed_path` names,
packaged as `seed/pools.yaml` beside the service's `settings.toml`; under Helm
another seed is supplied through `configFiles`. The contract is
[resource-pool management](../../openspec/specs/resource-pool-management/spec.md);
the format, the seed, and the steps for moving a pool's members to another
provider are in the operator handbook's
["Pool definitions"](../operator-handbook.md#pool-definitions).

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

### What a document does to entries it stops naming

A pool absent from the document is **disabled**: the document declares what the
deployment offers, and a pool it does not name should not be scheduled.

A relay absent from the document is **retained**. Disabling one would break
every pool referencing it and every live tunnel on it, which is a far worse
outcome than a stale row and is not what an operator editing an unrelated entry
is asking for. A relay established from a document and then administered through
the API is one relay, not two.

A capacity declaration absent from the document is **retained**, as a relay is.
An unnamed declaration may have been registered through the API, derived from a
host's inventory by a migration of the v0.3.0 floor, or be backing a live reservation, and
none of those is what an operator editing an unrelated entry means to switch off. A capacity document
therefore adds and updates declarations and never removes one; disabling is an
explicit `enabled: false`, in the document or through the API.

A host absent from the document is **retained**, its enabled state included, and
each apply reports it as registered and not named: in the startup log, and in
the import response's `not_named`. Hosts registered through the API, as every
end-to-end lane registers them, coexist with the document, and disabling every
host a document stopped naming would take them out of service. Disabling a host
is an explicit `enabled: false`, in the document or through the API; it keeps
new deliveries off the host while work already placed there runs, as the
operator handbook's "Host definitions" describes.

### Host definitions

`host_definitions_path` names the host document, a top-level `hosts` list whose
entries have the host registration API's field names; the provisioning chart
sets it from `definitions.hosts`, and the Compose stacks set
`PROVISIONING_HOST_DEFINITIONS_PATH` to the document they mount. The retired
`inventory_ini` and `inventory_path` are refused (see "Profile-based
configuration"). The contract is the
[`physical-provisioning` specification](../../openspec/specs/physical-provisioning/spec.md);
the format, the export and import routes, and the upgrade from an INI inventory
are in the operator handbook's
["Host definitions"](../operator-handbook.md#host-definitions).

### Capacity definitions

`capacity_definitions_path` names the capacity document, a top-level
`resources` list whose entries are whole declarations with the capacity
registration API's field names; the provisioning chart sets it from
`definitions.capacity`. The contract is the `physical-provisioning` requirement
["Capacity definitions are imported from a mounted document"](../../openspec/specs/physical-provisioning/spec.md#requirement-capacity-definitions-are-imported-from-a-mounted-document)
with [`site-capacity`](../../openspec/specs/site-capacity/spec.md); the format
and the rules for VM and bare-metal declarations are in the operator handbook's
["Capacity definitions"](../operator-handbook.md#capacity-definitions).

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

A relay entry's `grant_key_secret_key` names the profile value containing the
Ed25519 private key as one-line standard base64 PKCS#8 DER. The importer strips
surrounding whitespace and refuses a missing, malformed or non-Ed25519 value
without echoing it. The profile key is resolved at relay creation; after API
rotation the API-held key remains authoritative during document reconciliation.
Keep the supplied profile key current when an empty-database reinstall must
recreate the plugin's trust. A service-generated key is recoverable only from
the service database.

Relay grant signing keys have the same create-time profile resolution rule. An
API key rotation is authoritative; a later relay-definition import does not
replace it from the named profile key. The provisioning service's
`relay_grant_expiry_grace_seconds` (default 3600 seconds) extends the lease end
for the signed grant, while `relay_port_reuse_margin_seconds` (default 300
seconds) delays reuse after that grant expiry. The allocator applies a raised
reuse margin to already released ports. Keep the grace at least the lease
watchdog's grace period plus a teardown job's retries and their backoff, so a
grant never expires while the teardown that revokes it is still due; the default
covers the default watchdog and retry settings. The service refuses to start
with a negative grace or a reuse margin that is not positive. Keep the relay
and provisioning clocks synchronized with skew well below the reuse margin; the
relay plugin checks expiry against its own clock with no leeway. These values
are service settings, not pool fields or buyer inputs.

## Migrations at startup

Every stateful service applies its migrations in a deployment phase before its
application starts, through its own packaged command, and its application only
checks the database; the rules are `deployment-state`'s
["Service-owned migration history"](../../openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history)
and the requirements beside it, and the design is its companion's
["Migration and initialization boundary"](../../openspec/specs/deployment-state/architecture.md#migration-and-initialization-boundary).

| Service | Command | Deployment phase |
|---|---|---|
| Compute provisioning | `compute-provisioning-migrate` | init container in `helm/charts/provisioning`; before the service under Compose |
| VM storefront | `market-storefront-migrate` | init container per agent in `helm/charts/storefront`; before the storefront under Compose |
| Bare-metal storefront | `bare-metal-storefront-migrate` | init container in `helm/charts/bare-metal-storefront`; before the storefront under Compose |
| API-credit storefront | `apicredits-storefront-migrate` | before the storefront under Compose |
| API-credit service | `apicredits-service-migrate` | before the service under Compose, and in its image's command |
| Registry | `registry-migrate` | init container in `helm/charts/registry`, for each instance; before the registry under Compose, and in its image's command |

Each service's `Makefile` has a `migrate` target running its command. Under
Helm the init container runs from the application's image with the
application's environment, configuration mounts and data volume — the VM
storefront's without `entrypoint.sh`, which only starts ZeroTier — and is the
only init container a chart renders for a service (see "Kubernetes: ConfigMap
and Secret mounting"). Under Compose the service's command is
`sh -c "<service>-migrate && exec <service command>"`, so the application starts
only once the migration succeeds; the VM storefront runs it through
`./entrypoint.sh`, and the bare-metal storefront, whose image's entrypoint is its
CLI, states it as its `entrypoint`. The registry chart's application container
states its own `uvicorn` command, since the image's command migrates first for
Compose.

A migration command reads only its database location and log level — the
bare-metal storefront's only its `db_path`, logging at INFO — from the
service's layered settings, without resolving anything else, so it needs no
secret mounted and one database migrates to the same schema and rows under any
profile. What a deployment configures — a site's pools, their seed, its
playbooks, the API-credit service's `default` pool — is applied by the
service's startup after its check passes. Migration creates no pool.

The application's startup opens its database read-only, issues no DDL, and
refuses any database but a compatible one, naming the command and every
migration ID that differs. `<service>-migrate --check` prints the same result
and changes nothing: it exits 0 only for a compatible database, and otherwise
lists the pending IDs, the unknown IDs, or the baseline to be adopted, so an
operator can preview an upgrade or verify a restored backup.

| Result | Meaning | Remedy |
|---|---|---|
| compatible | the database records exactly the chain's migrations | none |
| behind | migrations are pending, or a v0.3.0 database awaits adoption | run the command |
| ahead | the database records a migration this image does not list | restore the pre-upgrade backup, or deploy the image that wrote it |
| unsupported | tables the chain did not build, part of the floor, or a database older than v0.3.0 | start from a fresh database |
| absent | no file, or no table but an empty ledger | run the command |

The command refuses an ahead or unsupported database and applies nothing. Each
in-house service's chain begins at baselines reproducing its v0.3.0 schema; the
command adopts a database recording every migration ID the v0.3.0 chain
recorded by recording the baselines in their place, in one transaction and
without running them, then applies the later migrations. Compute provisioning,
the VM and bare-metal storefronts, and the registry (at Alembic revision
`018_listing_resource_column`, adopted as `v0_3_0_baseline`) adopt their v0.3.0
databases; the API-credit storefront and service have no floor, so any existing
API-credit database is refused as unsupported. A database from before v0.3.0 is
refused the same way. Each in-house migration commits with its record, so a
failure leaves the migrations before it applied and recorded; under Alembic,
SQLite DDL is not transactional, so a fresh registry database whose migration
fails partway is unsupported and is replaced by a fresh one. An image rolled back
over a migrated database is refused as ahead: take a database backup before every
upgrade, and roll back by restoring it. The operator handbook's
["Upgrading a deployment"](../operator-handbook.md#upgrading-a-deployment) is the
procedure.

See [`TESTING.md`, "Migration Tests"](TESTING.md#migration-tests) for how the
chains are proven: each against its floor fixture, adoption, the store-open
test, and each service's migration suite.

The migrations after the v0.3.0 baseline, which an adopted database applies:

- Both services hosting the site ledger add the unique reservation placement key
  and its recorded request (`20261106_002_reservation_placement_key`, which
  `kit/site` exports to both chains), with no backfill, since no earlier reserve
  carried a key.
- Compute provisioning rewrites every host's `ssh` connection stored at version 1
  to version 2 with the same public fields and ciphertext
  (`20261108_001_ssh_connections_version_2`), failing, naming every refused host
  and rewriting nothing, where the version-2 codec refuses one. A host submission
  must state its connection's version.
- Each compute storefront creates the tables v0.3.0 created only when a store
  opened — deal servicing's, and the bare-metal lifecycle cursor — with
  `IF NOT EXISTS`, leaving any present as they are
  (`20261109_001_vm_store_open_tables`, `bare-metal-storefront-0017-store-open-tables`).
- The storefronts drop the tables v0.3.0 kept frozen: the VM storefront's
  `compute_allocations`, `resources`, `hosts`, `resource_transition_events`,
  `compute_pool_members`, and `compute_capacity_pools` or
  `compute_inventory_pools` (`20261109_002_vm_frozen_inventory_dropped`), and the
  bare-metal storefront's `bare_metal_accepted_site_generations`
  (`bare-metal-storefront-0018-drop-accepted-site-generations`). Their rows are
  discarded; inventory is declared at provisioning.
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

These migrations are fail-forward: an older image cannot serve the migrated
schema and refuses it as ahead, and rolling back means restoring the backup taken
before the upgrade. No two versions of a service share a database: each chart
deploys its service with `strategy: Recreate` over one ReadWriteOnce volume.

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


## Storefront listing shapes and pool overrides

A VM storefront publishes one listing per shape a pool offers. Beyond a pool's
own `listing_shapes`, the storefront operator may state its own terms for one
pool at one site, in one offering mode, through the administrator API or
`market-storefront pool-override` (`set --file`, `get`, `list`, and `delete`,
with `--mode` never defaulted). An override states listing shapes, settlement
clauses, asking rates, and the market's terms (for VM: `sla`,
`max_duration_seconds`, and `pricing` family rates); it cannot state region or
capacity backing. A write stating the retired `min_price` or `token` is refused; a
stored override that still carries them keeps applying its other terms, and
system status names the retired keys.

- **Family rates price a listing by its shape.** A rate is stated per capacity
  family in the pricing hint's nesting —
  `pricing: {gpu: {H100: {rates: [...]}}, cpu: {rates: [...]}, memory: {rates: [...]}, storage: {rates: [...]}}`
  — each entry an `asset`, a positive decimal-text `rate` per unit of the family
  (per card, vCPU, or GiB), and a time unit `per`. The same nesting serves a pool's
  `pricing` hint, an override's `pricing` term, and the storefront's
  `[pricing.defaults]`; each family resolves from its own highest tier, whose list
  replaces lower tiers' whole. A listing for which any family resolves rates is
  shape-priced: its settlement clauses state no `rate`, and each clause's rate is
  the listing's shape priced at the family rates in that clause's asset. A family
  without a rate is not charged, and system status lists it per asset; a listing
  whose rate would be zero in a clause's asset is refused. Without family rates a
  clause's own `rate` is the listing's rate, whatever its shape. The provisioning
  service refuses a pool write whose rate lists are malformed; a rate the storefront
  still cannot read holds the pool's listings at their last-published terms and is
  named, with its tier and family, in system status.

- **Asking rates are declared per shape.** A pool states them in its
  `asking_rates` policy tag, keyed by offering mode, each entry naming the shape
  it prices with an `amount` (positive decimal text, no exponent), an `asset`,
  and a `period` (`hour`). A listing publishes the rate for its own shape, or
  none. An override's `asking_rates` replace the pool's list whole; an empty list
  withholds every rate. No storefront setting supplies a rate. A declaration or
  override the storefront cannot read holds that pool's listings and is named in
  system status, as is a rate for a shape the pool does not publish. A changed or
  withdrawn rate refreshes the listing in place.

- **A stated shape may bound what an agreed shape states.** In a pool's
  `listing_shapes` or an override's, any quantity field may take a constraint
  mapping in place of its scalar, holding `offer`, `min`, `max`, or any of them:

  ```yaml
  listing_shapes:
    vm:
      - gpu:    { model: H100, count: { offer: 1, min: 1, max: 4 } }
        cpu:    { count: 16 }
        memory: { gib: { max: 512 } }
  ```

  The listing publishes each field's `offer` (here one GPU, 16 vCPUs, and no
  memory); `min` and `max` bound only what an agreed shape may state, and are never
  published. A plain scalar is shorthand for an `offer`, and an `offer` alone says
  nothing about negotiability: write a fixed value with `min` and `max` equal to it.
  Each value is a positive integer, `min` is not above `max`, an `offer` lies within
  its own range, a mapping states at least one key, and any other key is refused.
  Constraints apply to quantities only; `gpu.count` and `gpu.model` are required
  together, so a shape that states a `gpu` family always gives `gpu.count` an
  `offer`. Changing only a range keeps the listing's identity.

- **The storefront's configured default fills unconstrained bounds.**
  `[admissibility.defaults.vm]` in the VM storefront's settings uses the same family
  nesting and field syntax, without `offer`:

  ```toml
  [admissibility.defaults.vm.gpu]
  count = { min = 1, max = 16 }

  [admissibility.defaults.vm.memory]
  gib = { max = 512 }
  ```

  For each field's `min` and `max`, a stated shape's own bound wins, including a
  wider one, and a bound it does not state is the default's. An override's shapes
  replace the hint's whole and do not inherit its constraints. Generated shapes
  take the default alone, so the default generator yields only the GPU counts it
  admits. `settings.toml` ships none, and absent and an empty table both mean no
  default. A malformed table — an unknown key, `min` above `max`, an `offer`, or a
  constraint on a field that is not a quantity or is undefined — stops the
  storefront at startup, naming each problem as `admissibility.defaults.vm.<path>`. The default is parsed
  once at startup, so a change takes effect on restart.

- **Publication never advertises an offer the policy excludes.** A stated shape
  whose `offer` falls outside its resolved range is not published, and an open
  listing for it closes. Base shapes are read first: a base shape that cannot be
  read, including one whose required field is given a constraint mapping with no
  `offer`, holds the whole pool. Once every base shape reads, a listing whose policy
  cannot be computed — a constraint on a field that is not a quantity, on an
  undefined field, or with an unknown key; bounds that merge to an empty range; or
  one base shape stated twice with different constraints — closes alone, and the
  pool's other listings publish. System status reports the inadmissible offers and
  the uncomputable policies under each site's `publication_derivation` `reports`,
  as `listing_shape_inadmissible` and `shape_constraints_unusable` entries whose
  `findings` name the tier, path, and problem, each tier's conflicting value, or
  each conflicting entry.

- **Writes refuse what they can check.** The provisioning service refuses a pool
  write whose constraint mappings are malformed or that states one base shape twice
  with different constraints, naming each entry; identical entries are accepted, and
  whether a field may carry a constraint is left to the storefront, which never
  judges a pool's shapes against its configured default at write. An override write
  is refused, without a site call and leaving the stored override unchanged, when a
  shape's base shape or constraints cannot be read, its list states one base shape
  with different constraints, or a shape resolves to an empty range against the
  configured default or leaves its `offer` inadmissible.

- **A write needs its site reachable.** It is checked against the site's live
  projection: a pool the site does not project is refused, an unreachable or
  unverifiable site is refused as retryable, and a shape no member is feasible for
  is accepted and reported, because it then publishes nothing.
- **System status reports each override's state:** `applied`, `orphaned` while
  its pool is absent, `unknown` while its site's projection is not loaded, or
  `site_unconfigured`.
- **An override is the only storefront tier.** Each term it states replaces the
  pool's own hint for that term; a term it omits resolves from the hint, then
  from the storefront's configured defaults. The storefront holds no other
  per-pool record.
- **A site whose projection is not loaded holds its listings.** They are neither
  closed nor refreshed until it loads, so a storefront restarting while a site is
  unreachable does not delist that site. Listings derive only from site
  projections; nothing local stands in for one. A site decommissioned without
  closing its listings leaves them advertised until an operator closes them.
- **A candidate with no settlement option yields no listing.** In VM and bare metal
  alike, a candidate whose payload carries no settlement option and no accepted
  escrow is refused and recorded under its site's `publication_derivation`
  `refusals`, with its pool and Physical Resource. Its admissible clauses are its
  pool override's, else the configured ones, after admissibility for its backing
  (an unbacked listing publishes only options its domain does not fulfil through
  capacity). When the candidate's listing is open, each mechanism of those clauses
  is judged by its readiness blockers' `kind` (see "Storefront startup and site
  trust"):
  - every mechanism ruled out by configuration — no clause, a contact-only option
    whose origin has no contact, or any configuration blocker — refuses it as
    `no_settlement_option` and closes the listing through reconciliation; it
    reopens under the same identity on the first cycle whose payload builds again;
  - any mechanism whose every blocker is reachability — its chain or service
    unreachable, or not yet probed since start — holds the listing on its
    last-published terms as `settlement_mechanism_unknown`, a hold, and it
    negotiates as before; with no open listing that is a refusal;
  - any other payload failure is refused as `payload_unbuildable`, its text the
    entry's `error`, and leaves an open listing as it is.

  A mechanism outside the candidate's admissible clauses is not judged, so an
  outage on a mechanism the listing could never publish neither holds nor closes
  it.
- **A clause naming a disabled mechanism is dropped wherever it is stated.** A
  settlement clause is read in full before its mechanism's enablement is judged,
  so a malformed clause — including a stated `mechanism_input` that is not a
  mapping — is a payload failure that leaves its listing as it is. A readable
  clause whose mechanism's section is absent or disabled is dropped and rules that
  mechanism out, whether a pool's hint, an override, or `[pricing].settlements`
  states it, so a listing it alone priced closes as `no_settlement_option`.
  `market-storefront config migrate --scope settlement|publication` validates its result
  through the same reading, so it accepts a configuration whose clause names a
  disabled mechanism, as the storefront starts with one; disabling a mechanism is a
  deliberate operator act.
- **A region is the pool's alone.** A pool stating no `region` is held as
  `pool_region_missing`: it publishes nothing new and leaves its open listings
  unrefreshed.

Constraints are additive: every shape stated without them is valid, and with no
constraint and no configured default publication is unchanged. Sites and storefronts
are upgraded together. A constraint written before a storefront can read constraints
makes that pool's hint unreadable to it, which holds the pool. To roll back to a
release without constraints, first remove every constraint mapping from pool hints
and stored overrides: a constraint left
in place makes the older storefront hold the pool, and the older provisioning service
refuse any write that keeps it.

The compute provisioning contract is at major 3, and every party accepts major 3
alone: a provisioning service, the storefronts that call it, and the family and
domain clients they use upgrade together and roll back together. A mismatched pair
does not half-work; each request is refused by its contract version, naming the
supported major (see
[`compute-provisioning-contract`](../../openspec/specs/compute-provisioning-contract/spec.md)).

Upgrading to listing shapes is fail-forward. Every VM listing's identity now
includes its shape, so the first publication cycle after upgrade closes each
listing and publishes its successor once; a seller's close and pause carry to the
successor, and system status reports the carry-over.

A bare-metal storefront serves the same administrator operations, through
`bare-metal-storefront pool-override` (`set --file`, `get`, `list`, `delete`,
with `--mode` never defaulted). The command calls the administrator API, never
the database. It signs as the storefront itself, as `[Identity.principal]` from
the configuration files the server reads with `ARKHAI_IDENTITY_CREDENTIAL`, so
that principal must be one of `[Identity.administrators]`. It connects to
`--storefront-url` (`-a`), else the configured `base_url`. `bare-metal-storefront
publish` signs and connects the same way, running one publication cycle, or with
`--dry-run` previewing one, and printing the cycle's report as JSON; with
`--abort-all` it closes every open listing as its seller, refused beside
`--dry-run`. A storefront refusal exits 1 with its message, and a request no
storefront answers exits 1 naming the origin it was sent to and the transport
error's type.

- **A bare-metal override states no shapes.** It states settlement clauses, which
  replace `[pricing].settlements` for that pool whole; asking rates; and the terms
  `min_duration_seconds` and `max_duration_seconds`.
- **Each lease bound replaces its configured counterpart on its own.** The pair a
  listing would publish must still be ordered: a minimum above the effective
  maximum (the override's, else `[pricing].default_max_duration_seconds`) is
  refused at the write. If configuration later falls below an accepted minimum,
  the next publication cycle holds that pool as `pool_override_terms_conflict`
  rather than publishing; raise the maximum or correct the override. A pool for
  which neither the override nor configuration states a positive maximum is held
  as `pool_lease_bound_missing`. A pool resolving no settlement clause is not
  held: its candidates have no settlement option, as "A candidate with no
  settlement option yields no listing" above describes.
- **A machine the site builds no view for is reported, and its listing held.** The
  site projects a declaration from which it cannot build a bare-metal view — a
  backed one naming no host, no access methods, or no `physical_host_id`, a missing
  or invalid `allocation_mode`, a private-looking capacity or capability key —
  without the view, and with the reason in its `publication_view_problems`. The
  storefront reports it as `publication_view_unbuildable` with those problems and
  refuses openings against it; an open listing of it is held, neither closed nor
  refreshed, until the declaration is corrected, while a disabled declaration or a
  pool that stops admitting bare metal still closes it.
- **A write takes effect at once.** An accepted write refreshes the site's held
  projections and wakes the publication loop.
- **Status is judged against the held projection.** An override's status reads
  the resource-pool projection the storefront holds for its site; until the
  storefront holds one, including just after a restart, its overrides read
  `unknown`.

## Settlement consumer configuration and cutover

Marketplace roles resolve one strict `[Settlement]` root. `schema_version`
selects the configuration contract, `priority` orders mechanism IDs, and peer
`[Settlement.alkahest]`, `[Settlement.arkhai_payments]`, and `[Settlement.contact]` tables contain only
mechanism-owned consumer settings. Arkhai payments resolves trusted service origin, Ed25519 receipt identity, fee policy, an optional `ca_bundle_path`, and the API key through the shared kit's `settlement_config.py`. The key is stated in exactly one form: a storefront states it as `api_key`, a secret setting in its Secret overlay (`storefront.secrets.toml`, or the API-credit storefront's secret layer), never in public configuration; a buyer states `api_key_env`, naming the variable its own provider holds the key in. One resolution — `api_key`, otherwise the variable `api_key_env` names — serves the client builder, readiness and the payments check alike. `ca_bundle_path` names a PEM bundle the payments client alone verifies the service under, leaving the process's trust store as it is; a bundle that cannot be loaded fails when the client is built. The owner-scoped WorkOS credential reaches only its consuming process; HTTPS is required outside loopback. Buyer `payer_account` is separate domain input (`[vms].payer_account` or `[apicredits].payer_account`), carried in selection params and the accepted Agreement, not inferred from marketplace identity. API-credit sellers supply `payee_account` and `asset` in each payment publication clause; the accepted option determines the seller client's owner. Local development may use `development_auth = true` with a loopback service origin instead of a key; it is mutually exclusive with `api_key` and `api_key_env`, which are mutually exclusive with each other. A Compose or cluster service name is not loopback, so a stack's payments double is reached with a bearer key and a configured CA, as a deployment's service is. Buyer marketplace identity comes only from
the selected durable profile referenced by `[BuyerProfile]`; storefront and
service-role principals retain their own public identity configuration.
EVM credentials and networks remain in `[Wallet]` and `[Chains]`.
Generated TOML, ConfigMaps, status output, and run logs contain only public
configuration projections.

**The storefront payments check.** Payments readiness checks configuration only
and never contacts the service, so a storefront proves its payments access with an
authenticated read from its own process: `market-storefront check-payments
--account <id>`, `bare-metal-storefront check-payments --account <id>`, or
`apicredits-storefront check-payments --account <id>`. Each loads the storefront's
configuration exactly as `serve` does, takes its `[Settlement.arkhai_payments]`
section, builds the client the storefront would build, and reads the account's
balance (`GET /balances/{account}`). It starts no server, opens no database, and
contacts nothing but the payments service. The account is explicit because the
storefront's payments configuration does not name the seller's payee account, and
the service answers only for the key's own account. The command prints one JSON
line with no credential in it, and exits 0 on `ok`, 1 on a failed step, and 2 on a
malformed `--account`:

```console
$ bare-metal-storefront check-payments --account 00000000-0000-4000-8000-0000000000b2
{"check": "payments", "outcome": "ok", "service_url": "https://payments-double:8443", "account": "00000000-0000-4000-8000-0000000000b2", "assets": [], "held": 0}
```

A failure names its `step` and a fixed-text `detail`: `configuration` (no section,
an invalid or disabled one, no `service_url`, neither `api_key` nor `api_key_env`,
a configuration the storefront cannot read, or a `ca_bundle_path` that cannot be
loaded), `credential` (the variable `api_key_env` names is unset, empty, or not a
single-line key), `transport` (the service could not be reached over a trusted
connection, a certificate verification failure among them, or answered outside its
published contract), or `refused`, with the service's error `code` beside it. The
end-to-end lanes run it in each payment storefront's container after the stack is
up, and a storefront chart runs it as a Helm test pod ("Storefront agents:
pass-through configuration"); the operator handbook's
["Payments access"](../operator-handbook.md#payments-access) gives the
deployment's procedure.

`livemode` in a buyer's or storefront's Arkhai payments settings — `[Settlement.arkhai_payments]`,
or `[bare_metal.arkhai_payments]` in the bare-metal buyer's configuration file — is
the service mode whose receipts that process accepts. Receipts sign `livemode`, true only from a live payments service, and a
receipt verifies only when its signed mode equals the process's setting. The default,
`false`, accepts only test-mode receipts, so a process against a live service refuses
every receipt until it sets `livemode = true`; set it on both buyer and storefront
in the same release that points them at a live service. Mode, service origin, and
receipt identity change together, and changing them is a cutover: each receipt
check, including the revalidation of a stored receipt at restart, compares with the
current setting, so a payment deal accepted under the old mode never reaches
delivery or issuance afterwards. Drain open payment deals, or refund them, before
the change.

For signing-key rotation, `receipt_identities` in `[Settlement.arkhai_payments]`
may list current and retiring identity pins. Each entry has `identity`,
`valid_from` (inclusive Unix seconds, default zero), optional `valid_until`
(exclusive), and `retiring` (default false). A nonempty list must include the
current `service_identity` as a non-retiring entry. With no list, that identity
alone remains trusted. Receipt signatures are checked at `approvedAt`; snapshot
signatures at `observedAt`. A valid current-key snapshot may attest an embedded
receipt from a configured retiring identity valid at its approval, without
rewriting the receipt or its proof. Callers pass their durable minimum event
sequence to the shared snapshot verifier; wrong mode, deal or regressing state
is refused before authority state is consumed.

Agreement attachment is set on each side. A buyer's `attach_agreement` (default `false`)
attaches the exact Agreement when it approves a payment; setting it in a seller
configuration is a publication blocker. A seller that wants the Agreement on file sets
`deposit_agreement` on its payment option, and attaches the Agreement itself after
verifying the receipt and before delivering, whenever the buyer did not. The Agreement
discloses both principals, the listing, amount, timing, and provision terms, so enable
either only where that disclosure to the payments service is intended.

Stripe consumer settings are rejected with removal diagnostics; they are not migrated to Arkhai accounts, credentials, or transactions. Role CLIs reject legacy settlement keys and expose the same explicit migration contract. The storefront additionally rejects legacy publication pricing that would synthesize options from `min_price`, `token`, or raw `accepted_escrows`. A check is read-only and reports paths and actions with values redacted. A write requires `--backup`, validates the complete candidate before mutation, creates a restrictive same-directory `.bak`, fsyncs, and atomically replaces the source. Conflicting old and new values fail rather than choosing one. Repeating a completed migration is a no-op.

An Alkahest address book — one deployment's contract addresses, overriding the
SDK's built-in addresses for a chain such as Anvil — is named per chain in
`[Settlement.alkahest.address_books]`, a table from chain name to path; a chain not
listed uses the built-in addresses, and a key naming no configured chain makes
Alkahest unready (`alkahest.address_book_chain_unknown`). `[Chains]` holds only
chain resources. Every role — storefront and buyer, seller and payer — resolves a
chain's book through `kit/alkahest` and uses it for client construction,
publication, release conditions, escrow verification, refunds, and claim
servicing alike. The two retired keys, `[Chains.<name>].alkahest_address_config_path`
and `[Settlement.alkahest].address_config_path`, are refused before the settlement
section is resolved, with a diagnostic naming the table. The settlement migration
commands, `market-storefront config migrate --scope settlement` and the buyer's
`market config migrate --scope settlement`, move them into it. Bare-metal sellers use
`bare-metal-storefront config migrate --config /path/storefront.toml --scope settlement`
with the same `--check` or `--write --backup` modes. The API-credit storefront has no
migration command; its operators move the key by hand. A chain's own key moves to that chain's entry, and the
section key to the one configured chain, or else to the chains whose own keys name
the same book. Where it cannot tell which chains the section key served, or a chain
would be given two different books, it refuses and names the keys; an empty key is
removed. The section key named the book claims were serviced against on every
chain, so on any other configured chain a seller's claims move to that chain's own entry, or to the
built-in addresses where it has none; a seller's migration report names each such
chain before anything is written. A release that predates the table refuses it,
since `[Settlement]` is strict.

A seller's `[Wallet].address` is the recipient its release conditions name, and its
`[Wallet].private_key` signs every chain transaction, so the two name one account.
The address is optional: absent, it is derived from the key. An address that names
another account than the key's makes Alkahest unready
(`alkahest.wallet_address_mismatch`) and leaves the storefront running. A buyer's
address names nothing an escrow pays, and is not compared with its key.

### Alkahest release models

`[Settlement.alkahest].release_models` is the ordered, nonempty, duplicate-free list
of release models offered by the seller: `recipient` (the default), `oracle_gated`,
and `interruptible`. Every published escrow shape gets one option per model.
Each option's `settlement.accepted_escrow.demand` pins its own chain, arbiter and
demand data; it has no `lifecycle` terms, since Alkahest has no lifecycle adapter.
Interruptibility is not a listing-resource attribute: choosing the splitter option
chooses that release condition, without changing the other options on the listing.

```toml
[Settlement.alkahest]
enabled = true
release_models = ["recipient", "interruptible"]
# Configure interruptible_oracle_addresses with a trusted third-party oracle.
```

`trusted_oracle_addresses` is valid only when `oracle_gated` is listed, and
`interruptible_oracle_addresses` only when `interruptible` is listed. Those models
need their respective oracle list before Alkahest is ready; the first address is
the release oracle, and it must not be the seller's wallet or signing account.
Wallet, address-book and chain readiness still apply to every offered model.
A domain refuses startup if any listed model is not one it can deliver, whether or not
the section is enabled: bare metal
accepts recipient and oracle-gated release, never interruptible; the API-credit
storefront accepts recipient release only. VM supports all three models.

The old `oracle_gated` and `interruptible` boolean settings are rejected. The
settlement migration maps `oracle_gated = true` to `["oracle_gated"]`,
`interruptible = true` to `["interruptible"]`, and neither true (including both
absent) to `["recipient"]`, removing the flags. Both true is contradictory and
refused. A conflicting existing `release_models` list is refused without modifying
the file or backup. Dry-run lists redacted key changes; write validates the whole
candidate and preserves the existing atomic replacement and restrictive backup
contract. Repeating it is a no-op. Legacy boolean environment overrides must be
replaced with the corresponding `SETTLEMENT__ALKAHEST__RELEASE_MODELS` list override,
not copied as boolean values.

Publication config migrates separately from the `[Settlement]` hierarchy. The migration converts an unambiguous single-mechanism legacy price into one complete typed clause. It refuses a dual-mechanism source whose one scalar price has no authoritative asset scale, and refuses per-model legacy pricing, which needs manual clauses.

The VM storefront's retired inventory settings — `resources_csv_path`, `resources_csv_inline`, `[escrow_templates]`, and `capacity.use_site_projection_for_listings`, with the chart's `secret.resourcesCsvInline` value — are refused the same way as retired settlement settings: the chart's values schemas refuse them in any spelling, and `market-storefront config set` refuses to write them, naming the seller quickstart's "Upgrading from CSV inventory". No command migrates them, because inventory moves to provisioning by operator action, and startup does not refuse them.

The API-credit storefront and the credits service each own their own state: the
credits service owns keys, request-digested grants, balances, quota, credentials,
and its migration history. Restart either against its own volume. Never
source-share a sibling package or mount one service's database into the other.

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

   Preview and migrate storefront publication defaults:

   ```console
   market-storefront --config /path/storefront.toml config migrate \
     --scope publication --check
   market-storefront --config /path/storefront.toml config migrate \
     --scope publication --write --backup
   ```

4. Repeat `--check` for every file and render the Helm or Compose deployment.
   Do not proceed if a migration, typed configuration validation, generated
   schema check or image/config schema check fails.
   `config migrate` reads: rendering applies the values schema, and at startup
   the storefront applies its typed validation — refusing, for example, a
   settlement schema version other than its own. Untyped settings are not
   checked key by key.
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

### Seller servicing budget diagnostics

`kit/deal-servicing` exposes `ServicingBudget` and `SellerBudgetDiagnostics` for
seller-side loop composition. All polling/watchdog/teardown inputs are finite,
nonnegative seconds. The diagnostic compares reserve-ahead and priced payer
notice, when supplied, with polling + max(configured watchdog, observed cycle)
+ teardown. A shortfall logs a recommendation and possible unpaid-delivery
exposure; it neither stops a loop nor changes an accepted term. The wrapper
measures the injected step, not a second timer or a buyer watchdog.

These are library composition inputs, not new `[Settlement]` configuration keys
or a buyer guarantee. Current compute role roots do not expose a budget table.
Use [the deterministic budget example](../../kit/deal-servicing/examples/budget_first_use.py)
for a runnable warning-and-continue check. During storefront downtime, physical
service can continue until the lease maximum. A rate buyer's protection requires
its own authority stop/case, not a seller-advertised processing budget; rate
execution remains outside the once-only adapter. See
[lifecycle authority limits](../../openspec/specs/deal-lifecycle/architecture.md#current-limits).

### Dispute authority preferences

Dispute preferences are role-owned root configuration, independent of
`[Settlement.arkhai_payments]`. VM and API-credit buyers and storefronts read
these entries from their normal public TOML overlays. The bare-metal buyer reads
them at the root of its file selected by `BARE_METAL_BUYER_CONFIG`, beside
`[bare_metal]`; its storefront reads them through the normal storefront loader.

`use_registry_dispute_authorities` defaults to `true` for a storefront and
`false` for a buyer. Shipped buyer profiles and development fixtures state their
consent explicitly. Put this scalar before any TOML table header:

```toml
use_registry_dispute_authorities = true
```

With the setting enabled, each role resolves its ordered local `[[Dispute]]`
entries first, followed by the recommendations from the registry it works
through. Descriptors are fetched through the signed, pinned registry client at
buyer bootstrap and storefront startup. Multiple registries keep independent
lists: a recommendation from one is not a default for another, and work with no
source registry uses local entries only. A failed descriptor read contributes
no recommendations; local preferences remain usable. Disabling recommendations
does not disable local entries or resolve any authority credential.

A local entry names one authority by all four of `interface`, `origin`,
`account`, and `record_key`. `params` belongs to that interface. The
`advertisement` copy states the supported payment mechanisms and minimum
dispute/case-hold windows; extra interface-owned advertisement fields are
retained. For example, this uses reserved example data, not a live authority or
a shipped role template:

```toml
[[Dispute]]
interface = "example.dispute.v1"
origin = "https://dispute.example"
account = "example-authority-account"
record_key = "example-public-record-key"
params = {}
not_offered = false
not_accepted = false

[Dispute.advertisement]
mechanisms = ["example.payment.v1"]
minimum_dispute_window_seconds = 60
minimum_case_hold_seconds = 3600
```

An omitted `minimum_case_hold_seconds` means the authority requires an unbounded
case hold; JSON descriptors may express that as `null`. TOML has no null literal.
An entry marked `not_offered` is excluded from the seller's offered list; one
marked `not_accepted` is excluded from the buyer's accepted list. Deduplication
uses full identity **before** those marks: a local veto cannot be undone by the
registry repeating that authority, and a registry copy cannot replace locally
accepted parameters. A different origin or record key is a different authority,
even when its payment account matches.

A role with an empty resolved list logs **No dispute authority is available**,
naming both remedies: configure `[[Dispute]]`, or enable
`use_registry_dispute_authorities` and arrange a registry recommendation. Merely
configuring a payments service chooses no dispute authority. The selected
option names its authority under `lifecycle.adjudication.dispute`; mandate
derivation reads that accepted authority, not a service-wide default.
`[Settlement.arkhai_payments].dispute_authority` is rejected, including when its
value is null in a JSON overlay. Remove it and configure preferences instead;
the bare-metal buyer's `[bare_metal.arkhai_payments]` uses the same validation.
No template supplies an authority's account, origin or record key.

Credentials are separate entries, each bound to an authority's whole identity and
stating its token in exactly one form: `api_key`, the token itself, a secret
setting stated in a secret overlay, or `api_key_env`, naming the environment
variable that holds it. A storefront states its entries whole in its Secret
overlay, `storefront.secrets.toml`, with `api_key`; its chart's values schema
refuses any `[[DisputeCredential]]` in public `config`. A buyer may name a variable
its own provider holds:

```toml
# A storefront's storefront.secrets.toml
[[DisputeCredential]]
interface = "example.dispute.v1"
origin = "https://dispute.example"
account = "example-authority-account"
record_key = "example-public-record-key"
api_key = "<the token>"

# A buyer's public TOML
[[DisputeCredential]]
interface = "example.dispute.v1"
origin = "https://dispute.example"
account = "example-authority-account"
record_key = "example-public-record-key"
api_key_env = "EXAMPLE_DISPUTE_API_KEY"
```

The binding must match all four identity fields. An entry stating both forms, or
neither, or an empty or multi-line `api_key`, is refused when the configuration is
validated. Credential resolution happens only when the authority is used: it
returns `api_key`, or reads the named variable, whose absence or empty value fails
with the variable's name, never its value; a storefront holding no usable
credential for a deal's authority reports the deal `repair_required`. The
mediation client receives the resolved token, never a variable name:
`MediationCredential(identity, *, token)` takes a `SecretStr` and refuses an empty
token, one with surrounding whitespace, or one containing a line break, at
construction. Duplicate bindings for an
identity are refused at lookup. The Agreement pins origin/record key for the
deal's potentially unbounded case life: preference edits affect only new deals,
and credentials must still serve accepted identities. Dispute adapters follow no
mid-deal origin redirect or record-key rotation. Payment receipt identity overlap
does not solve that separate limitation. A resolved credential is a secret wrapper and
is not stored in the preference model. Public authority projections contain
neither credential references nor secret values; neither belongs in options,
Agreements, status or run logs. See the runnable
[configuration example](../../kit/deal-lifecycle/examples/dispute_configuration.py)
for ordered resolution, local vetoes, per-registry isolation and secret handling.

### Contact-exchange contacts

A storefront composing `contact-exchange.v1` (bare metal and VM) configures it in
the peer `[Settlement.contact]` table: its `profiles`, the public terms an
introduction option advertises, and the seller's contact in exactly one of two
forms.

```toml
# One storefront, one origin site: the single form.
[Settlement.contact]
enabled = true
contact_payload = { email = "sales@bob.example" }

# One storefront, several seller sites: a contact per origin.
[Settlement.contact.origins.dc-west]
contact_payload = { email = "ops@west-seller.example" }

[Settlement.contact.origins.dc-east]
contact_payload = { email = "sales@east-seller.example" }
```

An origin is the site a listing's durable binding records; the storefront reads
its configured sites (`[capacity.sites]`, on VM and bare metal alike) as the
known origins. The storefront refuses to start when both forms
are set, when the single form is set while more than one site is configured, or
when an `origins` key names no configured site. A site without an entry is legal:
its listings publish no introduction option, and a reveal for an accepted deal whose
origin has lost its entry is refused with `seller_contact_unavailable` before
anything is stored. The contact is never substituted from another origin.

Contacts are ordinary configuration, marked `never_published` rather than secret:
they may sit in the public configuration (the Helm ConfigMap included) and still
never appear in a listing, an option, readiness, or an obligation. Readiness stays
storefront-wide: the mechanism is unready only with no profiles or no contact in
either form.

### Introduction delivery

`[Delivery]` sends each revealed introduction to destinations the side's own
operator configured; the seller's side carries the buyer's contact, the buyer's
side the seller's. `enabled` names sink instances; an instance's table names the
installed sink it uses with `sink`, and a table naming none uses the sink of its own
name, so `[Delivery.file]` keeps its meaning.

```toml
[Delivery]
enabled = ["west-hook", "east-mail", "audit"]

[Delivery.west-hook]
sink = "webhook"
sign = true                         # signed with the storefront's marketplace signer

[Delivery.east-mail]
sink = "smtp"
host = "mail.east-seller.example"
sender = "storefront@example.com"
recipients = ["sales@east-seller.example"]

[Delivery.audit]
sink = "file"
path = "/var/log/introductions.jsonl"

[Delivery.origins]                  # seller side only
dc-west = ["west-hook", "audit"]
dc-east = ["east-mail", "audit"]
```

A storefront with more than one origin must route: with sinks enabled and no
`[Delivery.origins]`, it refuses to start, since broadcasting every reveal to every
destination would hand one seller's buyers' contacts to another. Every routed name
must be enabled, every enabled instance routed, and every origin the table names
must be one of the storefront's sites; a site the table does not name receives no
seller-side delivery. A buyer may not route. With
`sign = true` a webhook request carries a v2 marketplace signature its receiver
verifies against the storefront principal. The installable `apprise` sink
(`arkhai-kit-delivery-apprise`, in both storefront images) reaches any service an
Apprise URL names. Credentials — a webhook's `url` and `headers`, an SMTP
`password`, Apprise `urls` — are secret settings: they belong in the secrets overlay,
and the Helm values schema refuses them in an agent's `config`.

Operators re-deliver a revealed introduction to its origin's instances with
`market-storefront settlement contact redeliver --obligation-ref …` on VM and the
bare-metal storefront's `redeliver-introduction` command. Delivery and re-delivery
are specified in [introduction delivery](../../openspec/specs/introduction-delivery/spec.md).

The VM and bare-metal end-to-end lanes each run a Mailpit as the seller's mail sink.
Each lane's storefront configuration (`domains/vms/storefront/storefront.bob.lane.toml`,
`domains/bare_metal/storefront/storefront.dev.toml`) enables one SMTP instance,
`[Delivery.seller-mail]`, sending to the `mailpit` host on port 1025 and addressed
to the seller contact its `[Settlement.contact]` reveals; the bare-metal lane adds
the service in `compose.bare-metal-local.yml`, which its storefront waits on until
healthy. The introduction scenarios read the mail back through the lane's
`MAILPIT.API_URL` (`e2e-tests/config/config-docker.yml`). Every address in them is a
development value on a reserved domain.

### Contact-exchange retention

Two seller-only settings in `[Settlement.contact]` bound how long revealed contacts
are kept:

| Setting | Default | Meaning |
|---|---|---|
| `retention_seconds` | `2592000` (30 days) | How long both contact payloads of a revealed introduction are kept, counted from the reveal. A positive integer, or `"indefinite"` for no deletion. Zero and negative values are refused, so a typo cannot delete introductions moments after reveal. |
| `retention_sweep_interval_seconds` | `3600` | How often the retention sweep runs. Positive. |

The window is current policy, not a term of any deal: a storefront restarted with a
shorter window deletes, on its next sweep, every introduction already past the new
window, including those revealed under the longer one. The window is published to
buyers; deletion and disclosure behaviour are specified in
[contact-exchange settlement](../../openspec/specs/contact-exchange-settlement/spec.md).

### Bare-metal role configuration

`arkhai-bare-metal-buyer` is an installed core buyer-domain wheel. Its TOML contains registry URLs, authority trust pins, and bounded public defaults; the XDG buyer profile service resolves the fresh or run-recorded signer. The `bare-metal` commands use authenticated discovery and the shared storefront transport.

The bare-metal storefront reads its configuration as every storefront does: `$XDG_CONFIG_HOME/arkhai/storefront.toml` (an operator's own file), `storefront.json` (the document a chart renders), and the Secret overlay `storefront.secrets.toml`, a later file winning on a conflicting key, over the packaged `settings.toml`, which states every default once. Its keys are VM's for the same concepts — `[Identity]`, `[Settlement]`, `[registry]`, `[capacity]`, `[pricing]`, `[negotiation]`, `[Delivery]`, `[Wallet]`, `[Chains]`, `base_url`, `port`, `db_path`, and the interval and timeout keys — and its loader's override layer is VM's, `STOREFRONT_` with `__` between levels, an operator's escape hatch only. Section and key names read in any case; a key the storefront does not read is ignored, so an older release starts on a newer configuration, and the chart's values schema, not startup, refuses a misspelling. A setting that cannot be read refuses startup by its key, never echoing a value. The signer credential, `ARKHAI_IDENTITY_CREDENTIAL`, is the only value the storefront reads from its environment besides the configuration directory, and it never enters settings. The image sets no application setting: its database is the packaged relative `db_path`, under the image's working directory, the data volume, and its command is `bare-metal-storefront serve`, which binds the configured `port` (8000 by default) unless `--port` overrides it.

A registry that gates writes behind a bearer token is given its token in the Secret overlay's `[registry.auth]`, a map from each configured `[registry].urls` entry to its token, matched by normalized URL. The storefront sends it beside its signed request, never in its place, on publication and on its status read alike. The chart's values schema refuses the table in public configuration, and an empty token is no token.

`[capacity.sites]` maps each site to its authority URL, and each site is bound to exactly one `[Identity.service_peers.<peer>]`, seeded at the server's start and rotated through the identity routes (see "Storefront startup and site trust"). Health and status report each site by its ID, its service peer, and the peer's active principals, primary first, never its URL; a site's error text in status may name the URL, which is public configuration refused at startup when it carries credentials. `[capacity].poll_interval` (5 s), `[capacity].publication_interval_seconds` (30 s), and `[capacity].source_confirmation_seconds` (three poll intervals unless stated) time the projection poller, the publication loop, and the opening recheck's confirmation window. `[pricing].settlements` compile when the storefront starts, so a clause that cannot be read refuses startup naming the key; an empty list is not a refusal. `[negotiation].policies` names the seller chain.

`[Settlement]` is the strict shared settlement root. A configured Alkahest section, enabled or disabled, settles with at least one chain (`[Chains.<name>]` and its `rpc_url`, with an optional address book under `[Settlement.alkahest.address_books]`) and the wallet key (`[Wallet].private_key`, in the Secret overlay only), whose account is the seller's address; `[Wallet].address` may state it, and one naming another account is a blocker (see "Settlement consumer configuration and cutover"). A section missing any input starts, and Alkahest readiness names each missing input as a blocker, since disabled sections still service accepted obligations. Those inputs supplied with no Alkahest section are refused at startup. Payments-only configuration supplies none of them and constructs no Alkahest wallet, chain, or RPC client; its payment credentials remain behind the secret boundary. The storefront delivers the `recipient` and `oracle_gated` release models; a section listing `interruptible`, enabled or not, refuses startup (see "Alkahest release models"). Publication additionally requires authenticated registry trust, exact typed clauses, freshly confirmed site projections for its source checks, and a maximum lease duration per pool.

Under Compose, `compose.bare-metal.yml` holds topology only; a deployment's overlay mounts its `storefront.toml` and Secret overlay at `/etc/arkhai/` and gives the identity credential through an environment file, as `compose.bare-metal-local.yml` does for the lane, and nothing gives either a fallback (see "Per-domain stack composition"). The Helm chart, `helm/charts/bare-metal-storefront`, is the storefront chart's agent shape with one agent's keys at its top level: `config` rendered into `storefront.json` in a ConfigMap with null-valued keys removed (see "Storefront agents: pass-through configuration"); `secret` naming an existing Secret whose key is mounted as `storefront.secrets.toml`; `identity.credentialSecret`; `alkahestAddressBook` mounting an existing ConfigMap read-only; `caBundle`, mounting the payments CA bundle and deriving `[Settlement.arkhai_payments].ca_bundle_path` as the storefront chart's option does; `tests.paymentsAccount`, the account its payments check test pod reads; `port`, which the container, probes, and Service share; persistence; and scheduling. The pod's environment carries only `XDG_CONFIG_HOME` and the credential, and service links are off. The chart derives only what the release knows, and only where `config` states none: `port` always (a different stated value refused), `base_url` as the Service's URL, `db_path` under `persistence.mountPath`, `ca_bundle_path` whenever `caBundle` names a source (a different stated value refused), and, in an umbrella release, the internal registry's URL with the chart-level `internalRegistryTrust` under it and `[capacity.sites]` as `{default: <provisioning URL>}`. A site bound to the release's provisioning service must have a role-`service` peer naming `global.provisioningIdentity`, which the chart checks and never adds. Installed alone, with no umbrella globals, it derives all but the last two and refuses `internalRegistryTrust`. Its values schema is closed: the top level refuses every value it does not know, retired ones by name, and `config` is typed by a definition generated from the storefront's settings models, each section closed, so a misspelled or secret key is refused at render. A key stated in two spellings is refused at render too, since the loader would merge them silently. The chart validates no service semantics; the storefront's startup refusal does.

The selected-site authority owns inventory, executor routing, provisioning credentials, and teardown. The payments authority owns financial state. Buyer, storefront, site, and payment credentials retain their separate authority boundaries.

## Current limits

This document describes the pattern as implemented for services with
their own Deployment and profile-resolved settings. A service without a
Kubernetes deployment topology (no Helm chart), such as the API-credit
storefront and service, runs only under Compose: it migrates through the same
command before its application (see "Migrations at startup"), but has no
equivalent of a chart's configuration delivery.

### Artifact publishing destination

Root publishing targets require explicit `AR_PROJECT` and `AR_LOCATION`, supplied
on the make command line or in the environment. `AR_PREFIX` defaults to
`AR_PROJECT`; it selects the repository-name prefix. For example,
`make push-images AR_PROJECT=<project> AR_LOCATION=<region>`.
