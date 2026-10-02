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

## Goals / Non-Goals

**Goals.** A storefront setting, including a whole settlement mechanism, deploys by
values alone. The service is the only validator of its own configuration. The chart
keeps what only the Kubernetes layer knows.

**Non-Goals.** No move to the profile-based loader. No change to the Secret overlay,
the service's configuration models, or other charts.

## Decisions

### 1. The whole agent configuration passes through, not only settlement

Settlement is where the problem blocks work, but the same hand rendering covers every
section, and fixing one section would leave the chart enumerating the rest. Each
agent's `config` value becomes the service's configuration in the service's own key
names: `[Settlement]`, `[Delivery]`, `[pricing]`, `[capacity]`, `[negotiation]`,
`[registry]`, `[provisioning]`, `[Identity]`, `[Wallet]`, `[Chains]`, top-level
scalars such as `agent_id` and `log_file_path`, and anything a storefront later reads.

`[Identity]` passes through like everything else: principals, administrators, and
service peers are public configuration. The agent's `identity` value keeps only what
is Kubernetes-shaped, the credential Secret reference.

### 2. The document renders through Helm's own encoder, as YAML unless TOML proves safe

Two encoders are available without hand-writing one:

- **`toToml` into the existing `storefront.toml`.** No loader change. The risk is
  numbers: Helm's values decoding is understood to yield `float64` for every number,
  and the TOML encoder renders a whole `float64` with a fraction, `3600.0`. The
  storefront's settlement models are strict, and a strict integer field refuses a
  float, so `schema_version = 1.0` or `retention_seconds = 2592000.0` would stop the
  service starting.
- **`toYaml` into a `storefront.yaml` the loader also reads.** YAML encoding renders
  a whole number as an integer, which is why the provisioning chart's `toYaml`
  pass-through works. It costs one file name in `kit/config`'s storefront discovery,
  read between `storefront.toml` and `storefront.secrets.toml`, so the Secret overlay
  still has the final word. The loader is otherwise unchanged: the same three-place
  discovery under `XDG_CONFIG_HOME`, no profiles, no `ACTIVE_PROFILES`. This is not
  the profile-based loader the non-goals exclude.

**Decision: YAML, behind a verification gate.** The first implementation task renders
integer, large-integer, float, boolean, nested-table, and array-of-tables values
through `toToml` with `helm template` and inspects the output. If `toToml` preserves
integers, the chart keeps `storefront.toml` and the loader is not touched; otherwise
the chart renders `storefront.yaml` and the loader gains that name. Either way the
service sees the same merged settings.

Rejected: keeping a hand-written recursive TOML encoder in the templates. The chart
already has `storefront.tomlLiteral`, which formats numbers with the template
default, and the template default prints `2592000` as `2.592e+06`. A hand-written
encoder is one more thing to keep correct, and it is exactly the kind of chart-side
reimplementation this change removes.

### 3. The chart derives only what the release knows, and only where absent

Following the provisioning chart, the chart deep-copies the agent's `config` and sets
a derived value only when the configuration does not state it:

| Setting | Derived from |
|---|---|
| `base_url` | the agent's own Service and port (`storefront.agentBaseUrl`) |
| `port` | the agent's `port`, which also names the container and Service port |
| `[gateway].root_path` | the agent's `rootPath` |
| `[registry].urls` and its authority entry | the umbrella's internal registry Service and `global.registryIdentity`, when the agent names no external registry |
| `[provisioning].service_url` | the provisioning subchart's Service |
| `[capacity.sites]` | one entry, the configured provisioning site id to that Service, when the agent configures no sites |
| `db_path` | the persistence mount path, when unset |

Everything else the chart renders today with a default — Stripe's API and schema
versions, currency, country, timeouts; Alkahest's flags; negotiation policy mode; the
provisioning poll interval — is the service's default, and the chart stops supplying
it.

### 4. The chart keeps the checks that relate the release, and drops the service's

A check stays when it relates this chart to something else in the release, which the
service cannot see:

- when the agent uses the internal registry, its registry authority id and principals
  must include `global.registryIdentity`;
- its provisioning trust and its provisioning service peer must include
  `global.provisioningIdentity`;
- the image's `settlementConfigSchemaVersion` must equal the configuration's
  `[Settlement].schema_version`, so an image is never deployed with configuration
  written for another;
- the `wait-for-rpc` init container is rendered when Alkahest is enabled and a chain
  is configured, because waiting for a dependency is the Kubernetes layer's concern.
  The chart reads those two values from the passed-through block; reading
  configuration to make a Kubernetes decision is not re-validating it.

A check goes when it validates one service's own configuration: `storefrontDomains`
being non-empty, a chain's `chain_id` being present, Stripe's condition profile and
resolver references, and every per-mechanism default and shape. The service already
refuses each of these at startup, and `market-storefront config migrate --check`
refuses them before a deploy.

Trust is checked rather than injected. The release's own principals are not silently
added to an agent's trust: trust is a security statement the operator makes, and
injecting it would trust whatever the globals say.

### 5. The values schema stops describing service configuration

An agent's `config` is an open object in both `helm/charts/storefront/values.schema.json`
and `helm/values.schema.json`. The hand-written `settlement`, `stripeSettlement`,
`alkahestSettlement`, `pricing`, `wallet`, and `chains` definitions are removed from
both, and `helm/scripts/check-settlement-schema-drift.py`, which only compared the two
copies, is removed with them.

The schema keeps refusing the values shape this change retires — `seller`,
`registryAuthority`, `registryUrl`, `storefrontDomains`, and a `settlement` written
under its old camelCase siblings — so an un-migrated values file fails at render
instead of passing through as keys the service ignores.

`openspec/specs/deployment-state/spec.md`'s "Generated configuration has one source
of truth" requires typed metadata to generate Helm schema fragments. That part of the
requirement is withdrawn: a chart that passes configuration through has no fragment
to keep in step. Generated templates, dotted-path editing validation, and reference
tables stay, so `config migrate --check` and `config show` remain the operator's
pre-deploy validation.

### 6. The values shape changes, with a mapping and a refusal

Operators' values files move from the camelCase shape to the service's key names. The
change ships a mapping from every retired key to its new location, recorded here at
planning and summarized in the release notes, and decision 5's refusal stops an
un-migrated file. The storefront chart's version takes a minor bump, and the umbrella
chart's with it.

### 7. The Secret overlay and other charts are unchanged

`storefront.secrets.toml` stays as it is: the registry write token, integration keys,
and anything an operator places there. A pre-existing Secret an operator manages
needs no change.

The bare-metal storefront chart passes its settlement configuration through already —
as one JSON value from an existing Secret into `BARE_METAL_STOREFRONT_SETTLEMENT` —
and enumerates no mechanism. Its environment-variable carrier differs from
`DEPLOYMENT_AND_CONFIG.md`'s mounted-file pattern, but changing it is a different
problem and this change leaves it alone.

## Risks / Trade-offs

- **[Default drift on removal]** → Where the chart's default differs from the
  service's, an operator who relied on the chart's value sees a different effective
  configuration. Planning compares every removed default with the typed model's and
  records each difference with its disposition before anything is removed.
- **[Un-migrated values]** → Mitigated by decision 5's refusal of retired keys, so the
  failure is a render error naming the key rather than a silently ignored section.
- **[External values producers]** → Workflows, scripts, and the operator's own
  repository may generate storefront values. Planning inventories every producer in
  this repository; producers outside it are covered by the mapping.
- **[Number typing]** → Decision 2's gate settles the encoder on evidence, and the
  render tests keep integer, large-integer, and float values under test.

## Open questions

None. Decision 2 is settled by a verification gate whose outcome selects between two
specified results.

## Migration Plan

1. Render the gate's values through `toToml` and choose the encoder.
2. Replace `storefront.agentConfigToml` with the pass-through and derivation; add the
   loader file name if YAML was chosen.
3. Move `helm/values.yaml`, the subchart's `values.yaml`, and every fixture to the new
   shape; replace the schemas' settlement definitions with the open object and the
   retired-key refusal; remove the drift check.
4. Update the render tests to assert pass-through, derivation, the retained checks,
   and refusal of the old shape.
5. Operators migrate their values by the mapping before upgrading the chart; the
   storefront image and its database are unaffected.
