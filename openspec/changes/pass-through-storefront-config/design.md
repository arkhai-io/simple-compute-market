# Design — pass storefront configuration through the chart

## Context

The provisioning chart is the reference for `DEPLOYMENT_AND_CONFIG.md`'s Kubernetes
pattern: it deep-copies `.Values.config`, sets the few values only the release knows
(the storefront URL, identities from globals, definition-document paths) where they
are absent, and renders the whole document with `toYaml`. A key provisioning gains
needs no chart change.

The VM storefront chart does the opposite. `storefront.agentConfigToml` in
`helm/charts/storefront/templates/_helpers.tpl` writes `storefront.toml` one key at a
time from camelCase values (`seller.agentId` → `agent_id`, `seller.provisioning.mode`
→ `[provisioning].mode`, and so on), supplies its own defaults, and repeats
single-service validation. For settlement it renders every Stripe and Alkahest key by
hand with chart-chosen defaults and refuses Stripe configurations the service's own
model already refuses. The values schemas close `settlement` around those two
mechanisms. The storefront loader reads fixed file names — `storefront.toml` and
`storefront.secrets.toml` under `XDG_CONFIG_HOME` — which the Deployment mounts from
the ConfigMap and Secret at `/etc/arkhai/`.

Beyond the helper, the old values shape is read in three more places: the Secret
overlay helper (`storefront.agentSecretsToml` keys `[registry.auth]` by
`config.registryUrl` and renders `[integrations]` from `config.seller.integrations`),
the Deployment's init containers (`config.settlement.alkahest`, `config.chains`), and
the umbrella's smoke-test configuration (`helm/templates/tests/test-config.yaml`
reads `config.registryAuthority`, `config.seller.baseUrl`, `agentId`,
`config.settlement`, and checks `identity.principal` against provisioning's trusted
storefront principals).

## Goals / Non-Goals

**Goals.** A storefront setting, including a whole settlement mechanism, deploys by
values alone. The service is the only validator of its own configuration. The chart
keeps what only the Kubernetes layer knows.

**Non-Goals.**

- No move to the profile-based loader (decision 10).
- No change to what the Secret overlay carries, to the service's configuration
  models, defaults, or validation, or to other charts.
- No chart-side guard against secrets placed in pass-through configuration
  (decision 8).
- No pre-deploy validation of chart values (decision 9).

## Decisions

### 1. The whole agent configuration passes through, not only settlement

Settlement is where the problem blocks work, but the same hand rendering covers every
section, and fixing one section would leave the chart enumerating the rest. Each
agent's `config` value becomes the service's configuration in the service's own key
names: `[Settlement]`, `[Delivery]`, `[pricing]`, `[capacity]`, `[negotiation]`,
`[registry]`, `[provisioning]`, `[gateway]`, `[Identity]`, `[Wallet]`, `[Chains]`,
`storefront_domains`, top-level scalars such as `agent_id` and `log_file_path`, and
anything a storefront later reads.

`[Identity]` passes through like everything else: principals, administrators, and
service peers are public configuration. The agent's `identity` value keeps only what
is Kubernetes-shaped, the credential Secret reference.

**Spelling.** Values use the spelling of the storefront's packaged `settings.toml`:
`Settlement`, `Identity`, `Wallet`, `Chains` capitalized; other sections lowercase.
Dynaconf treats top-level keys case-insensitively, so a lowercase `settlement` would
load, but the chart reads `Settlement`, `Chains`, and `Identity` for its own checks
(decision 4), and two spellings of one section in one document would merge in an
unspecified order. The schema therefore refuses the lowercase spellings the old shape
used (decision 5).

### 2. The document renders as YAML into `storefront.yaml`

Two encoders were available without hand-writing one: `toToml` into the existing
`storefront.toml`, or `toYaml` into a new `storefront.yaml` the loader also reads. A
verification gate chose between them.

**Gate evidence.** One chart rendered the same values through both encoders with
`helm template` (Helm 3.10.1, an unverified npm redistribution, so local evidence
only; the render tests re-assert the YAML column under whichever Helm CI runs):

| Value | `toToml` | `toYaml` |
|---|---|---|
| `port: 8000` | `8000.0` | `8000` |
| `schema_version: 1` | `1.0` | `1` |
| `retention_seconds: 2592000` | `2592000.0` | `2592000` |
| `request_timeout_seconds: 10.0` | `10.0` | `10` |
| `frac: 2.5` | `2.5` | `2.5` |
| `9007199254740993` | `9007199254740992.0` | `9007199254740992` |
| `1000000000000000000000` | `1000000000000000000000.0` | `1e+21` |
| booleans, `"0x…"` and `"on"` strings, nested tables, arrays of tables | preserved | preserved, ambiguous strings quoted |
| any integer set with `--set` | integer | integer |

Helm decodes every number in a values file as `float64`. The TOML encoder writes a
whole `float64` with a fraction, and the storefront's settlement models are strict:
pydantic 2 in strict mode refuses `1.0` for an `int` field (checked), so `toToml`
fails the gate. YAML writes whole numbers as integers; a whole float becomes an
integer, which strict `float` fields accept (checked). Dynaconf 3 merges a YAML
include between the two TOML layers as expected (checked).

CI installs Helm with `azure/setup-helm@v4` and no pinned version, so the number
decoding of whichever Helm runs is not a contract this change can rely on. YAML
renders correctly whether a Helm version decodes whole numbers as integers or floats.

**Consequence: large integers are strings.** Every number in a values file passes
through `float64`, so an integer above 2^53 loses precision with either encoder, and
one of 1e21 or more renders in exponent form. A value that large must be written as a
string. Storefront amounts are already decimal text.

**Decision: YAML.** The ConfigMap carries `storefront.yaml`, mounted at
`/etc/arkhai/storefront.yaml`.

**Loader.** `kit/config`'s storefront discovery reads `storefront.toml`, then
`storefront.yaml`, then `storefront.secrets.toml`, so the Secret overlay still has the
final word. The same three-place discovery under `XDG_CONFIG_HOME`; no profiles, no
`ACTIVE_PROFILES`. Three consumers need more than the name:

- The server loads the list through Dynaconf `includes`, which reads YAML already.
- `load_storefront_config()` reads each file with `tomllib` and backs `config show`,
  `config get`, and the CLI's `base_url` and `db_path` lookups. It reads each file by
  its suffix, and reads YAML with the parser Dynaconf uses, so `config show` reports
  what the server loads.
- `config show` refuses to run when `storefront.toml` is absent, which in the pod it
  is. It reports the merged layers when any layer exists.

The editing commands — `config set`, `config init-user`, `config migrate` — operate on
`storefront.toml` and stay TOML-only: they edit a user's file, and a rendered
`storefront.yaml` is regenerated from values, never edited in place.

The API-credits storefront shares this discovery and so also reads a
`storefront.yaml` if present. Nothing renders one for it; the effect is a file name
it now tolerates.

Rejected: keeping a hand-written recursive TOML encoder in the templates. The chart
already has `storefront.tomlLiteral`, which formats numbers with the template
default, and the template default prints `2592000` as `2.592e+06`. A hand-written
encoder is one more thing to keep correct, and it is exactly the kind of chart-side
reimplementation this change removes.

### 3. The chart derives only what the release knows

Following the provisioning chart, the chart deep-copies the agent's `config` and adds
release-known values:

| Setting | Derived from | When |
|---|---|---|
| `port` | the agent's `port`, which names the container port, probes, and Service port | always; a stated different value is refused (decision 4) |
| `base_url` | the agent's own Service and port (`storefront.agentBaseUrl`) | absent |
| `registry.urls` | the umbrella's internal registry Service | absent |
| `registry.authorities.<internal URL>` | the agent's `internalRegistryTrust` | when `registry.urls` is derived |
| `provisioning.service_url` | the provisioning subchart's Service | absent |
| `capacity.sites` | `{default: <effective provisioning.service_url>}` | absent |
| `db_path` | `<persistence.mountPath>/agent.db` | absent |

`port` cannot be "set where absent": a configuration whose `port` differs from the
agent's leaves the container listening where neither the Service nor the probes look.

**Release-keyed registry trust.** The storefront keys registry trust by URL
(`registry.authorities.<url>`). When the agent uses the internal registry, that URL is
the release's Service name, which a values file should not have to spell. The agent
therefore states the trust once, outside `config`, as `internalRegistryTrust:
{authority, principals}`, and the chart writes it under the derived URL. This is the
same shape of value as the provisioning chart's derived storefront URL: a value whose
position depends on what Kubernetes names. It keeps trust a statement the operator
makes — `global.registryIdentity` describes the release's registry, and the chart
checks the agent's trust against it (decision 4) rather than copying it — and it keeps
key rotation possible, since trust may hold the old and new principals while the
global names the active one.

`internalRegistryTrust` is required when `registry.urls` is derived and refused when
`config` states `registry.urls`; a `config` that states an entry under the derived URL
alongside `internalRegistryTrust` is refused, naming both.

**Site ID.** The site key of the derived `capacity.sites` entry is `default`. It was
`config.seller.provisioning.siteId`, which defaults to `default` and which no values
file in this repository sets. The storefront has no setting naming one site; it has
the `capacity.sites` map, and an operator who needs another site ID states that map,
which then passes through.

`gateway.root_path` is not derived. No template uses the agent's `rootPath` for
anything but this setting and no values file sets it, so it is service configuration
and passes through as `config.gateway.root_path`.

Everything else the chart renders today with a default — Stripe's API and schema
versions, currency, country, timeouts; Alkahest's flags; negotiation policy mode;
`auto_register`, which nothing reads — is the service's default or nothing, and the
chart stops supplying it.

### 4. The chart keeps the checks that relate the release, and drops the service's

A check stays when it relates this chart to something else in the release, which the
service cannot see:

- when the agent uses the internal registry, `internalRegistryTrust.authority` must
  equal `global.registryIdentity.authority` and its principals must include
  `global.registryIdentity.principal`;
- when the effective `provisioning.service_url` is the internal provisioning Service,
  `provisioning.identity.principals` must include `global.provisioningIdentity`, and
  a service peer (`Identity.service_peers.*`, `role = "service"`) whose `site_id` is a
  `capacity.sites` key mapped to that URL must include it too;
- `Settlement.schema_version` must be stated and equal the image's
  `settlementConfigSchemaVersion`, so an image is never deployed with configuration
  written for another. The service would default an absent version; the release check
  needs the configuration to say which contract it was written for;
- a stated `port` must equal the agent's `port`.

Two Kubernetes decisions read the passed-through configuration, which is not
re-validating it:

- the `wait-for-rpc` init container is rendered when `Settlement.alkahest.enabled` is
  true and a `Chains` entry has an `rpc_url`;
- the `wait-for-registry` init container is rendered only when the agent uses the
  internal registry. Today it always waits on the internal registry, so an agent
  pointed at an external registry in a release without one would wait forever.

A check goes when it validates one service's own configuration: `storefront_domains`
being non-empty, a chain's `chain_id` being present, principal lists holding one or
two entries, Stripe's condition profile and resolver references, and every
per-mechanism default and shape. The service refuses each of these at startup
(decision 9).

Trust is checked rather than injected: the chart never adds a principal to a trust
list the operator wrote.

### 5. The values schema stops describing service configuration

An agent's `config` is an open object in both `helm/charts/storefront/values.schema.json`
and `helm/values.schema.json`. The hand-written `settlement`, `stripeSettlement`,
`alkahestSettlement`, `pricing`, `wallet`, `chains`, and `storefrontDomains`
definitions are removed from both, and `helm/scripts/check-settlement-schema-drift.py`,
which only compared the two copies, is removed with them. `registryAuthority` remains
as the definition of the chart-level `internalRegistryTrust`.

The schema refuses the values shape this change retires, naming the key, so an
un-migrated values file fails at render instead of passing through as keys the
service ignores: `agentId`, `autoRegister`, and `rootPath` on an agent;
`identity.principal`, `identity.servicePeers`, `identity.administrators`, and
`identity.authority`; and under `config`: `seller`, `registryAuthority`,
`registryUrl`, `storefrontDomains`, `configMapName`, and the lowercase `settlement`,
`identity`, `wallet`, and `chains`. The existing refusals of `config.hostedSettlement`,
`config.chain`, and private keys under `secret` stay.

`configMapName` moves from `config` to the agent: inside `config` it would pass
through into the service's document.

`openspec/specs/deployment-state/spec.md`'s "Generated configuration has one source
of truth" requires typed metadata to generate Helm schema fragments. That part of the
requirement is withdrawn: a chart that passes configuration through has no fragment
to keep in step. Generated templates, dotted-path editing validation, and reference
tables stay.

### 6. The values shape changes, with a mapping and a refusal

Operators' values files move to the service's key names by the mapping below, and
decision 5's refusal stops an un-migrated file. The storefront chart's version takes a
minor bump, and the umbrella chart's with it. Planning verifies the mapping against
every producer in this repository.

| Retired value | New location |
|---|---|
| `agentId`, `config.seller.agentId` | `config.agent_id` |
| `autoRegister` | none; nothing reads `auto_register` |
| `rootPath` | `config.gateway.root_path` |
| `identity.principal` | `config.Identity.principal` |
| `identity.administrators.<s>.principals` | `config.Identity.administrators.<s>.principals` |
| `identity.servicePeers.<id>.{role, siteId, principals}` | `config.Identity.service_peers.<id>.{role, site_id, principals}` |
| `identity.authority` | none; nothing reads it |
| `config.configMapName` | `configMapName` on the agent |
| `config.storefrontDomains[].{contribution, offeringMode, domainIdentity, contractVersion}` | `config.storefront_domains[].{contribution, offering_mode, domain_identity, contract_version}` |
| `config.registryAuthority` | `internalRegistryTrust` on the agent (internal registry), or `config.registry.authorities.<url>` (external) |
| `config.registryUrl` | `config.registry.urls` with its `config.registry.authorities.<url>` entry |
| `config.seller.baseUrl` | `config.base_url` |
| `config.seller.dbPath` | `config.db_path`, or omit it to use the persistence mount |
| `config.seller.logFilePath` | `config.log_file_path` |
| `config.seller.resourcesCsvPath` | `config.resources_csv_path` |
| `config.seller.enableEventQueue` | none; never rendered |
| `config.seller.provisioning.{mode, pollInterval, serviceUrl}` | `config.provisioning.{mode, poll_interval, service_url}` |
| `config.seller.provisioning.siteId` | `config.capacity.sites` |
| `config.seller.provisioning.identity.principals` | `config.provisioning.identity.principals` |
| `config.seller.negotiation.{policies, policyMode}` | `config.negotiation.{policies, policy_mode}` |
| `config.seller.integrations.geminiApiKey` | none; nothing reads `gemini_api_key`, and it was a secret held under `config` |
| `config.settlement` | `config.Settlement`, contents unchanged |
| `config.wallet`, `config.chains` | `config.Wallet`, `config.Chains`, contents unchanged |
| `config.pricing` | unchanged |

### 7. The Secret overlay's contract and other charts are unchanged

`storefront.secrets.toml` still carries the registry write token, `resources_csv_inline`,
and anything an operator places there, and a pre-existing Secret an operator manages
needs no change. The helper that renders the optional chart-generated overlay stops
reading the retired shape: it keys `[registry.auth]` by the effective first registry
URL — the same value the ConfigMap renders — and no longer renders `[integrations]`,
whose only key has no reader.

The bare-metal storefront chart passes its settlement configuration through already —
as one JSON value from an existing Secret into `BARE_METAL_STOREFRONT_SETTLEMENT` —
and enumerates no mechanism. Its environment-variable carrier differs from
`DEPLOYMENT_AND_CONFIG.md`'s mounted-file pattern, but changing it is a different
problem and this change leaves it alone.

### 8. Pass-through configuration is public, and the chart does not police it

The closed schemas are what currently refuse, for example, a
`settlement.stripe.webhook_secret` value before it reaches a ConfigMap. With an open
`config`, a secret an operator places there renders into the ConfigMap and is refused
by the storefront only at startup. That is the cost of pass-through and is accepted.

No general guard exists without a maintained list. A schema rule on key names needs a
list of credential names. The typed models already mark secret fields with
`json_schema_extra={"secret": True}`, but enforcing that marker against the file layer
a value came from would run after the value is in the ConfigMap, would change the
service's validation, and would break local setups that keep one file.

So an agent's `config` is public by definition: the spec states it, and
`DEPLOYMENT_AND_CONFIG.md` says that secret-marked settings belong in the Secret
overlay. The schema's refusals of private keys in the chart's own values (`secret.*`,
`identity`) stay, because those values are the chart's, not the service's.
`openspec/specs/deployment-state/spec.md`'s "Identity configuration separates public
and secret material" is modified to match: its schema-refusal scenarios now describe
the chart's own values and the storefront's startup refusal.

### 9. Configuration validation is the service's, at startup

The storefront validates its own configuration when it starts, and a chart deployment
learns of an invalid configuration there. The Deployment's `Recreate` strategy means
the old pod is gone by then; recovery is `helm rollback`. This matches the provisioning
chart, which also has no pre-deploy validation.

`config migrate --check` is not a pre-deploy check for chart values: it reads one
TOML file, and a chart operator has values, not that file. The spec makes no
pre-deploy claim. A role-neutral pre-deploy check belongs with a later move to the
profile-based loader, if one is made.

### 10. The storefront does not move to the profile-based loader here

Moving the storefront to `CONFIG_DIRECTORY` and `ACTIVE_PROFILES` would make
`DEPLOYMENT_AND_CONFIG.md`'s "every service uses the same configuration shape" true
and share `market_config.dynaconf_bootstrap`. It would not simplify this change: the
chart's work — copy, derive, check, `toYaml` — is the same either way, and differs
only in the ConfigMap key and mount name. It would cost a format change to every
operator-managed `storefront.secrets.toml` Secret, a redesign of the CLI's
single-file editing commands and the tomlkit-based migration engine shared with the
buyer, the API-credits storefront's discovery, and about 190 references across
Compose stacks, the e2e harness, workflows, scripts, and user documentation.

A rendered `storefront.yaml` carries exactly what a future `config-<profile>.yml`
would, so nothing here is lost if that move is made. Proposing it is deferred until
after this change is implemented.

## Risks / Trade-offs

- **[Default drift on removal]** → Where the chart's default differs from the
  service's, an operator who relied on the chart's value sees a different effective
  configuration. Planning compares every removed default with the typed model's and
  records each difference with its disposition before anything is removed.
- **[Un-migrated values]** → Decision 5's refusal turns an old values file into a
  render error naming the key.
- **[External values producers]** → Producers outside this repository are covered by
  decision 6's mapping.
- **[Number typing]** → Render tests keep integer, large-integer, and float values
  under test; large integers are documented as strings.
- **[Secrets in pass-through configuration]** → Accepted (decision 8).
- **[Invalid configuration takes the storefront down]** → Accepted (decision 9).
- **[Intended effective-configuration differences]** → The umbrella values state
  `db_path = "./agent.db"`, outside the persistence mount, so state is lost on
  restart; the migrated values omit it and it derives to the mount. An absent
  `seller.dbPath` rendered `db_path = ""`; it now derives. `auto_register` is no
  longer rendered. These and planning's default comparison are the expected
  differences in the before/after comparison.

## Open questions

None.

## Migration Plan

1. Add `storefront.yaml` to the storefront discovery and make the read paths
   format-aware.
2. Replace `storefront.agentConfigToml` with the pass-through, derivation, and checks;
   render `storefront.yaml`; update the overlay helper, init containers, and the
   umbrella's smoke-test configuration.
3. Move `helm/values.yaml`, the subchart's `values.yaml`, and every fixture to the new
   shape; replace the schemas' service definitions with the open object and the
   retired-key refusal; remove the drift check.
4. Update the render tests to assert pass-through, derivation, the retained checks,
   and refusal of the old shape.
5. Operators migrate their values by decision 6's mapping before upgrading the chart;
   the storefront image and its database are unaffected.
