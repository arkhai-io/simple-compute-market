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
values alone, with no hand-written chart or schema change. The service is the only
source of its configuration's defaults and semantics. The chart keeps what only the
Kubernetes layer knows. No secret-marked setting can reach a ConfigMap.

**Non-Goals.**

- No move to the profile-based loader (decision 10).
- No change to what the Secret overlay carries, to the service's configuration
  defaults, or to what its configuration accepts. The storefront gains typed
  declarations for the secrets it reads untyped (decision 8), which change no
  accepted value.
- No validation of the storefront's untyped configuration sections beyond what
  Dynaconf does today (decision 9).
- No pre-deploy validation of chart values beyond the values schema (decision 9).
- No change to other charts.

## Decisions

### 1. The whole agent configuration passes through, not only settlement

Settlement is where the problem blocks work, but the same hand rendering covers every
section, and fixing one section would leave the chart enumerating the rest. Each
agent's `config` value becomes the service's configuration in the service's own key
names: `Settlement`, `Delivery`, `pricing`, `capacity`, `negotiation`, `registry`,
`provisioning`, `gateway`, `Identity`, `Wallet`, `Chains`, `storefront_domains`,
top-level scalars such as `agent_id` and `log_file_path`, and anything a storefront
later reads.

`Identity` passes through like everything else: principals, administrators, and
service peers are public configuration. The agent's `identity` value keeps only what
is Kubernetes-shaped, the credential Secret reference.

### 2. The document renders as JSON into `storefront.json`

Helm offers three encoders without hand-writing one — `toToml`, `toYaml`, and
`toJson` — and the rendered file must reach the storefront with every type intact. A
verification gate compared them, and implementation found a defect the gate missed.

**Gate evidence.** The same values rendered through each encoder with `helm template`
(Helm 3.10.1, an unverified npm redistribution, so local evidence only; the render
tests re-assert the JSON column under whichever Helm CI runs), then read back with the
storefront's pinned Dynaconf:

| Value | `toToml` | `toYaml` | `toPrettyJson` |
|---|---|---|---|
| `port: 8000` | `8000.0` | `8000` | `8000` |
| `schema_version: 1` | `1.0` | `1` | `1` |
| `retention_seconds: 2592000` | `2592000.0` | `2592000` | `2592000` |
| `request_timeout_seconds: 10.0` | `10.0` | `10` | `10` |
| `frac: 2.5` | `2.5` | `2.5` | `2.5` |
| `9007199254740993` | `9007199254740992.0` | `9007199254740992` | `9007199254740992` |
| `1000000000000000000000` | `…0.0` | `1e+21` | `1e+21` |
| `"0x0000000000000000000000000000000000000001"` | string | quoted string | string |
| `"0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"` | string | **bare; read back as `int`** | string |
| booleans, nested tables, arrays of tables | preserved | preserved | preserved |

Helm decodes every number in a values file as `float64`. The TOML encoder writes a
whole `float64` with a fraction, and the storefront's settlement models are strict:
pydantic 2 in strict mode refuses `1.0` for an `int` field (checked), so `toToml`
fails. YAML and JSON both write whole numbers as integers; a whole float becomes an
integer, which strict `float` fields accept (checked).

YAML fails on strings. Helm's YAML encoder quotes a string only when it would read
back as a number Go can represent, so the 64-bit-sized address above was quoted and
the gate passed; a 160-bit EVM address is not representable, is emitted bare, and the
storefront's Dynaconf YAML loader reads it as an integer
(`344073830386746567427978432078835137280280269756`). Every EIP-191 principal, wallet
address, oracle address, and token asset would be corrupted. JSON quotes every string,
and Dynaconf reads a `.json` include with Python's `json` module, with no type
inference.

CI installs Helm with `azure/setup-helm@v4` and no pinned version, so the number
decoding of whichever Helm runs is not a contract this change can rely on. JSON renders
correctly whether a Helm version decodes whole numbers as integers or floats.

**Consequence: large integers are strings.** Every number in a values file passes
through `float64`, so an integer above 2^53 loses precision with any encoder, and one
of 1e21 or more renders in exponent form. A value that large must be written as a
string. Storefront amounts are already decimal text.

**Decision: JSON.** The ConfigMap carries `storefront.json`, rendered with
`toPrettyJson` and mounted at `/etc/arkhai/storefront.json`. A side benefit: chart
render tests read the rendered document with the standard library's `json`, so they
assert on structure rather than on text.

**Loader.** `kit/config`'s storefront discovery reads `storefront.toml`, then
`storefront.json`, then `storefront.secrets.toml`, so the Secret overlay still has the
final word. The same three-place discovery under `XDG_CONFIG_HOME`; no profiles, no
`ACTIVE_PROFILES`. The server loads the list through Dynaconf `includes`, which reads
JSON already.

**The reporting commands merge as Dynaconf does.** `load_storefront_config()` backs
`config show`, `config get`, and the CLI's `base_url` and `db_path` lookups. It reads
each file with `tomllib` and merges with a case-sensitive dictionary merge. Dynaconf
merges case-insensitively at every level: tested with Dynaconf 3, `[Settlement.Stripe]`
and `[settlement.stripe]` in two files become one table, and one file holding both
`[chains.anvil]` and `[chains.Anvil]` loses a key. A dictionary merge cannot reproduce
that, so the reporting view is built by Dynaconf over the same file list, without the
packaged defaults, and returned as plain data with top-level keys in lowercase. The
mismatch exists today between `storefront.toml` and the overlay; this change removes
it rather than adding a third file to it.

**`config show` with no `storefront.toml`.** It refuses to run when `storefront.toml`
is absent, which in the pod it is. It reports the merged layers when any layer exists.
`config show --raw` prints each public layer present — `storefront.toml`, then
`storefront.json` — verbatim under a header naming its path, and never the Secret
overlay. The merged `config show` already includes the overlay's values; that is
unchanged here.

The editing commands — `config set`, `config init-user`, `config migrate` — operate on
`storefront.toml` and stay TOML-only: they edit a user's file, and a rendered
`storefront.json` is regenerated from values, never edited in place.

The API-credits storefront shares this discovery and so also reads a
`storefront.json` if present. Nothing renders one for it; the effect is a file name
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
- a stated `port` must equal the agent's `port`.

Two Kubernetes decisions read the passed-through configuration, which is not
re-validating it:

- the `wait-for-rpc` init container is rendered when `Settlement.alkahest.enabled` is
  true and a `Chains` entry has an `rpc_url`;
- the `wait-for-registry` init container is rendered only when the agent uses the
  internal registry. Today it always waits on the internal registry, so an agent
  pointed at an external registry in a release without one would wait forever.

**The image/configuration schema-version check is removed,** with
`image.settlementConfigSchemaVersion`. Nothing binds that value to the image: no build
or release step reads it from, or writes it into, an image, so the chart compared two
numbers an operator typed into the same values file. The settlement runtime owns the
contract — it defaults an absent `schema_version` to its own version and refuses any
other at startup, before publication or settlement mutation — which already satisfies
"Configuration cutover is atomic and coordinated". The value joins the retired keys.

A check goes when it validates one service's own configuration: `storefront_domains`
being non-empty, a chain's `chain_id` being present, principal lists holding one or
two entries, Stripe's condition profile and resolver references, and every
per-mechanism default and shape. Structural refusals the typed models express —
unknown keys, types, secret fields — come from the generated values schema
(decision 8); cross-field and semantic refusals stay with the storefront at startup.

Trust is checked rather than injected: the chart never adds a principal to a trust
list the operator wrote.

**Key spelling.** The storefront's loader matches keys case-insensitively at every
level: tested with Dynaconf 3, `[Settlement.Stripe]` and `[settlement.stripe]` merge,
and `Port` sets the same value as `port`. The repository also writes top-level
sections both ways — `[Settlement]` and `[settlement]`, `[Identity.…]` and
`[identity.…]`; `config init-user` writes `[identity.principal]`, `[wallet]`, and
`[chains.…]`. So the chart matches every key it reads or writes the same way — root
`port`, `base_url`, and `db_path`; `registry.urls` and `registry.authorities`;
`provisioning.service_url` and `provisioning.identity.principals`;
`capacity.sites`; the `Settlement`, `Chains`, and `Identity` sections and the chain
`rpc_url` it reads for init containers — and writes a derived value under the
spelling the configuration already uses. Otherwise `Port: 9000` would pass the port
check and render beside the `port: 8001` the chart writes. A configuration that
states one key in two spellings, at any depth, is refused: the loader would merge
them in an order nobody chose. Peer and principal fields under `Identity` need no
folding, because the values schema closes that section to their exact names
(decision 8).

The port check compares exactly: a stated port must be a number and equal the
agent's, with no conversion deciding whether two values disagree.

Making one spelling canonical would be a service-wide cutover — settings,
`config init-user`, documentation, CLI paths, loader, tests, and values together —
and is not this change.

### 5. The values schema stops hand-describing service configuration

An agent's `config` is an open object in both `helm/charts/storefront/values.schema.json`
and `helm/values.schema.json`, constrained only by the generated fragment of
decision 8. The hand-written `settlement`, `stripeSettlement`, `alkahestSettlement`,
`pricing`, `wallet`, `chains`, and `storefrontDomains` definitions are removed from
both, together with their conditional rules (a priority entry requiring an enabled
section, Alkahest requiring a wallet), which are service semantics.
`helm/scripts/check-settlement-schema-drift.py`, which only compared the two
hand-written copies, is removed. `registryAuthority` remains as the definition of the
chart-level `internalRegistryTrust`.

The schema refuses the values shape this change retires, naming the key, so an
un-migrated values file fails at render instead of passing through as keys the
service ignores: `agentId`, `autoRegister`, and `rootPath` on an agent;
`image.settlementConfigSchemaVersion`; `identity.principal`, `identity.servicePeers`,
`identity.administrators`, and `identity.authority`; and under `config`: `seller`,
`registryAuthority`, `registryUrl`, `storefrontDomains`, and `configMapName`. The
existing refusals of `config.hostedSettlement`, `config.chain`, and private keys under
`secret` stay.

`configMapName` moves from `config` to the agent: inside `config` it would pass
through into the service's document.

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
| `image.settlementConfigSchemaVersion` | none; the storefront owns the contract (decision 4) |
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
| `config.settlement`, `config.wallet`, `config.chains`, `config.pricing` | unchanged; the storefront already reads these names |

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

### 8. The secret boundary is enforced by a schema generated from the typed models

The closed hand-written schemas are what currently keep secrets and hosted payer data
out of a ConfigMap: `wallet` admits only `address` and `ssh_public_key`, and the Stripe
section admits only its public fields. An open `config` would lose that, and not only
as exposure. The storefront reads `wallet.private_key` from its merged configuration
whichever file supplied it, and delivery sink credentials are valid typed settings, so
a secret placed in `config` would be rendered into the ConfigMap and then used. The
`secret: True` marker on a typed field says where a value belongs; nothing in the
storefront's runtime refuses a marked value for arriving through a public file.

The boundary is kept without hand-maintaining it. The typed models are already the
source of truth: each is strict, so its JSON Schema is closed, and pydantic carries
field metadata, including `"secret": true` and `"roles"`, into the schema it emits
(checked against `ContactSettlementConfig`). A generator in the VM storefront:

1. builds the storefront's own settlement registry and takes each seller
   registration's `config_model`, plus the declarations below;
2. emits each model's JSON Schema with references inlined, so the fragment uses no
   draft-specific `$defs` keyword;
3. replaces every property marked `"secret": true`, or whose `"roles"` exclude
   `seller`, with `false`, a schema nothing satisfies;
4. nests each fragment at its section's path under an agent's `config` — top-level
   sections under both spellings (decision 4) — closes `Settlement` to the root keys
   and the mechanisms the storefront registers, as the settlement runtime does, and
   leaves `config` and every untyped section open;
5. writes the result into one generated definition in each of the two values schemas,
   replacing that definition whole and touching nothing else.

Helm validates values against the schema on every `template`, `install`, `upgrade`,
and `lint`, before anything renders. A demonstration chart built this way with Helm
3.10.1 rendered public contact settings and an unknown `Delivery` section unchanged,
refused `config.Settlement.contact.contact_payload` naming it, and refused a misspelled
`retention_secnds` naming it.

**Coverage.** Each typed section gets refusal of secret-marked and role-inapplicable
fields, of fields its model does not have — which is what keeps hosted payer and
instrument data out before render — and of wrong types and bounds the model states.
Cross-field and semantic rules stay with the storefront at startup. Untyped sections
stay open. A mechanism or sink installed from outside this repository is not known at
generation and passes through open; settlement mechanisms are registered explicitly in
the storefront's composition root, so today that is none. A typed section the
storefront gains reaches the schema by regeneration, with no template or hand-written
schema edit. Delivery sinks, whose settings depend on each sink's `kind`, are not
composed into the VM storefront yet; `compose-contact-exchange-across-compute`, which
composes them, owns extending the generator to express that dependency for the
built-in sinks.

**Identity is declared closed.** `[Identity]` holds only public material — its
`principal`, `administrators.<subject>.principals`, and
`service_peers.<id>.{role, site_id, principals}` — because the marketplace signing
credential arrives only through `ARKHAI_IDENTITY_CREDENTIAL`, from the chart's
credential Secret reference. A credential-like key placed under `Identity` would not
be refused at startup, only ignored, after it had reached the ConfigMap. So the
storefront declares the section's public surface in `IdentityConfigDeclaration`,
beside the parsers and built from the same identity models they use for each
principal, and the generated schema closes it at every level: any key the
declaration does not name is refused, whatever it is called. That is an allowlist,
not a list of forbidden names, so it needs no update when a new credential name
appears; a public key the parsers gain must be added to the declaration, and a unit
test proves the declaration accepts every operator-written `[Identity]` table the
repository ships.

**Untyped secrets are declared by the storefront.** `wallet.private_key` and the
`registry.auth` tokens are read from Dynaconf with no model to carry the marker. The
storefront declares each with the same marker in a small typed model beside its
reader — `[Wallet]` (`address`, `ssh_public_key`, `private_key`) and `[registry]`'s
`auth` — so the declaration lives with the service. `[Wallet]`'s model is closed, as
the hand-written schema was; `[registry]`'s declaration leaves the section's other
keys open. Neither changes what the storefront accepts at runtime.

**Drift.** A make target regenerates both schema files. The VM storefront's unit
suite regenerates the fragment in memory and fails if either committed schema
differs, so a model or registration change that is not regenerated fails CI in the
`vms-storefront` job. The check cannot join `make check-packaging`: the generator
imports the storefront's models and their third-party dependencies, while every
packaging check reads only the committed tree and the built wheelhouse and resolves
nothing (`openspec/specs/deployment-state/spec.md`, "Packaging conventions are checked
mechanically").

`openspec/specs/deployment-state/spec.md`'s "Generated configuration has one source of
truth" names Helm schema fragments as generated output, but none were: the Helm
schemas were hand-written and the drift script compared two hand-written copies. The
requirement is narrowed to what this change makes true — the generated Helm fragment
enforces the public/secret and role boundaries and closes typed sections, and carries
no defaults and nothing for untyped settings.

### 9. Validation boundaries

The values schema refuses what decision 8 covers before render. The storefront
validates its typed sections at startup: `Settlement` through the settlement runtime,
identity and trust through their parsers. Its untyped sections — `provisioning`,
`registry`, `negotiation`, `pricing`, timing and logging settings — are read directly
from Dynaconf, as they are today: a misspelled key there loads, is ignored, and leaves
the setting at its default. The hand-written schema caught such typos inside
`pricing`, `wallet`, and `chains`, and only there; `wallet` regains it through its
declaration, `pricing` and `chains` do not. That loss is accepted and recorded.
Validating the whole storefront document needs a root model and an allowed-key set the
storefront does not have; it is not this change.

A chart deployment learns of a semantic refusal when the pod starts. The Deployment's
`Recreate` strategy means the old pod is gone by then; recovery is `helm rollback`.
This matches the provisioning chart. `config migrate --check` is not a pre-deploy
check for chart values: it reads one TOML file, and a chart operator has values.

### 10. The storefront does not move to the profile-based loader here

Moving the storefront to `CONFIG_DIRECTORY` and `ACTIVE_PROFILES` would make
`DEPLOYMENT_AND_CONFIG.md`'s "every service uses the same configuration shape" true
and share `market_config.dynaconf_bootstrap`. It would not simplify this change: the
chart's work — copy, derive, check, `toPrettyJson` — is the same either way, and differs
only in the ConfigMap key and mount name. It would cost a format change to every
operator-managed `storefront.secrets.toml` Secret, a redesign of the CLI's
single-file editing commands and the tomlkit-based migration engine shared with the
buyer, the API-credits storefront's discovery, and about 190 references across
Compose stacks, the e2e harness, workflows, scripts, and user documentation.

A rendered `storefront.json` carries exactly what a future `config-<profile>.yml`
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
- **[Schema dialect]** → Helm's values-schema validator has changed between Helm
  releases and CI does not pin Helm. The generated fragment inlines references and
  uses only keywords common to draft-07 and later; render tests exercise it under
  CI's Helm.
- **[Stale generated schema]** → The storefront's unit suite fails on drift.
- **[Untyped-section typos]** → Accepted (decision 9).
- **[Invalid configuration takes the storefront down]** → Accepted (decision 9).
- **[Intended effective-configuration differences]** → The umbrella values state
  `db_path = "./agent.db"`, outside the persistence mount, so state is lost on
  restart; the migrated values omit it and it derives to the mount. An absent
  `seller.dbPath` rendered `db_path = ""`; it now derives. `auto_register` is no
  longer rendered. These and planning's default comparison are the expected
  differences in the before/after comparison.

## Findings outside this change

Found while implementing; recorded for review, not fixed here unless noted.

1. **The provisioning chart's pass-through had decision 2's YAML defect.** It rendered
   `.Values.config` with `toYaml`, and its `config-production.yml` carried bare
   EIP-191 identifiers. Deployed verification showed the provisioning service
   rejected `identity.identifier` as invalid. The chart now writes JSON syntax
   into the YAML profile, which Dynaconf reads with the identifiers intact.
2. **The umbrella's smoke-test configuration had the same defect.**
   `helm/templates/tests/test-config.yaml` rendered its generated profile with
   `toYaml`, leaving the registry trust principal `0x90f79bf6…` bare. It now renders
   JSON syntax into the YAML profile, as the provisioning chart does, and a render
   assertion checks the identifier stays a quoted string.
3. **The committed fixtures named invalid agent IDs.** `eip191-evm-values.yaml` and
   `fiat-ed25519-values.yaml` set `agent_id` to `evm-bob` and `fiat-bob`, which the
   storefront refuses at startup (identifiers may not contain `-`); the old chart
   rendered the same values. Found by the render test that loads a rendered document
   with the storefront's loader, and fixed here (`evm_bob`, `fiat_bob`).
4. **A render assertion was stale.** `helm/scripts/test-render.sh` expected
   `core/registry/filter-spec.yaml` to declare `id: vms.compute`; it declares
   `id: compute.market`. Deployed validation corrected the assertion.
5. **A packaged comment is stale.** `domains/vms/storefront/src/market_storefront/settings.toml`
   says that with no `[capacity.sites]` table the storefront uses a single `default`
   site; the capacity client refuses to start without the table.
6. **The storefront subchart does not render on its own.** Its templates read
   `global.registry` and `global.provisioning`, which only the umbrella supplies. This
   predates the change; the chart's render tests render through the umbrella.
7. **The chart-generated Secret overlay is unreachable.** Both values schemas fix
   `secret.createSecret` to `false`, so `storefront.agentSecretsToml` never renders
   under schema validation. It was updated for the new shape (decision 7) but cannot
   be exercised by a render test.
8. **The deal scenario used a profile-name test to choose its registry URL.** The
   Kubernetes hook's `helm` profile fell through to `localhost:8080`, although
   its generated profile supplied the in-cluster URL. The scenario now reads
   `settings.REGISTRY.API_URL`; the clean Helm run passed all 32 stages.

9. **No CI job runs the chart-to-loader check.** `helm/charts/storefront/tests/test_render.py`
   loads one rendered `storefront.json` with the storefront's own loader when the
   storefront environment exists, and reports a skip otherwise. CI's
   `release-deployment` job has Helm but not that environment, and `tests.yml` runs
   only for pushes and pull requests to `staging` and `dev`. A job that runs
   `make test`, `make build-dev`, and Helm validation together — with make targets to
   drive it — would protect this boundary; it is a CI-design change and out of scope
   here. Until then the check is local evidence, run by `make -C helm test-render`.

## Open questions

None.

## Migration Plan

1. Add `storefront.json` to the storefront discovery and build the reporting view with
   Dynaconf.
2. Add the storefront's secret declarations, the schema generator, its make target,
   and its drift test; generate the fragment into both values schemas.
3. Replace `storefront.agentConfigToml` with the pass-through, derivation, and checks;
   render `storefront.json`; update the overlay helper, init containers, and the
   umbrella's smoke-test configuration.
4. Move `helm/values.yaml`, the subchart's `values.yaml`, and every fixture to the new
   shape; replace the schemas' hand-written service definitions with the open object,
   the generated definition, and the retired-key refusal; remove the drift script.
5. Update the render tests to assert pass-through, derivation, the retained checks,
   the generated refusals, and refusal of the old shape.
6. Operators migrate their values by decision 6's mapping before upgrading the chart;
   the storefront image and its database are unaffected.
