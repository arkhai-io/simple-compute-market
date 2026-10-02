## Why

`docs/development/DEPLOYMENT_AND_CONFIG.md`'s Kubernetes pattern says non-secret
configuration renders from the chart's values into a ConfigMap, and that adding a
new non-secret key requires only a values change — no template change. The VM
storefront chart (`helm/charts/storefront`) does not follow it. Its
`storefront.agentConfigToml` helper writes `storefront.toml` key by key, and for
settlement it:

- re-implements each mechanism's defaults — Stripe's `enabled`, `expected_api_version`
  `"0.2.1"`, `expected_schema_version` `5`, `currency` `"usd"`, `country` `"US"`,
  timeouts; Alkahest's `oracle_gated` and oracle address lists — which already belong
  to the mechanisms' typed configuration models;
- re-implements the mechanisms' validation, such as refusing an enabled Stripe
  section whose `condition_profile` names no configured profile or whose evaluator
  names no configured resolver;
- closes the values schema around the mechanisms it knows: `settlement` sets
  `additionalProperties: false`, `priority` is an enum of `fiat.stripe.v1` and
  `alkahest.v1`, each mechanism has a hand-written definition, and
  `helm/scripts/check-settlement-schema-drift.py` only checks that the umbrella and
  subchart copies agree with each other.

The rest of the document is rendered the same way: camelCase values translated to
service keys one at a time, with single-service checks such as "`chain_id` is
required" repeated in templates.

Configuration validation is the service's concern. The chart duplicating it means
every mechanism or setting a storefront gains needs chart edits, the chart's
defaults can disagree with the service's silently, and an operator reads two
validation surfaces that are allowed to drift. Composing a further settlement
mechanism into the VM storefront — `compose-contact-exchange-across-compute` — is
blocked on exactly this.

## What Changes

- The storefront chart passes each agent's service configuration through to the
  storefront unchanged: values carry the service's own keys (`Settlement`,
  `Delivery`, `pricing`, `capacity`, `Identity`, and so on), and the chart serializes
  the block with `toYaml` into a `storefront.yaml` ConfigMap entry rather than
  enumerating it.
- The chart adds only what the Kubernetes layer knows and the service cannot — the
  agent's port and its Service's public URL, the internal registry's and
  provisioning service's URLs, a default capacity site, the database path under the
  persistence mount, and the internal registry's trust entry keyed by its derived
  URL — and, except for the port, only where the agent's configuration does not
  already state them.
- The chart stops re-implementing service defaults and service validation. It keeps
  the checks that relate this chart to the rest of the release: that the agent's
  registry and provisioning trust include the release's own registry and
  provisioning principals, and that the configured port is the agent's port. It
  reads the passed-through configuration only to decide which init containers to
  run. The image/configuration settlement schema-version check, which compared two
  values-file numbers, is removed; the storefront owns that contract.
- The hand-written service definitions in both values schemas, and the drift check
  that compared them, are replaced by a fragment generated from the storefront's
  typed configuration models. It refuses secret-marked and role-inapplicable fields
  and closes typed sections, so secrets and hosted payer data still cannot reach a
  ConfigMap, while carrying no defaults and leaving untyped sections open. The
  storefront declares the secrets it reads untyped. A storefront test fails when the
  committed fragment is stale. The schema refuses the retired values shape, naming
  the key.
- The storefront's file discovery reads `storefront.yaml` between `storefront.toml`
  and `storefront.secrets.toml`, and its configuration commands report what the
  server loads, merged as Dynaconf merges, when only the rendered files are present.
- Every committed values file, fixture, and the umbrella's smoke-test configuration
  moves to the new shape, and render tests assert that a section the chart has never
  heard of reaches the storefront intact.

## Capabilities

### Modified Capabilities

- `deployment-state`: a storefront chart passes service configuration through and
  derives only Kubernetes-layer values; the generated-configuration requirement
  gains a values-schema fragment generated from typed models that keeps secrets and
  payer data out of pass-through configuration.

### New Capabilities

None.

## Non-Goals

- Do not move the storefront onto the profile-based (`ACTIVE_PROFILES` /
  `config-<profile>.yml`) loader provisioning uses; see `design.md` decision 10.
- Do not change what the storefront Secret overlay (`storefront.secrets.toml`)
  carries; an operator-managed Secret needs no change.
- Do not change the service's configuration defaults or what its configuration
  accepts. The storefront gains typed declarations for secrets it reads untyped,
  which change no accepted value.
- Do not validate the storefront's untyped configuration sections, and do not add
  pre-deploy validation of chart values beyond the values schema; see `design.md`
  decision 9.
- Do not make one section spelling canonical; that is a service-wide cutover.
- Do not change the bare-metal storefront chart, which receives its settlement
  configuration as JSON from an existing Secret; see `design.md`.
- Do not change the provisioning, registry, dev-env, or e2e charts.

## Impact

- `helm/charts/storefront/templates/_helpers.tpl` (`storefront.agentConfigToml`, the
  helpers only it uses, and `storefront.agentSecretsToml`),
  `templates/configmap.yaml`, `templates/deployment.yaml` (mount, init containers),
  `values.yaml`, `values.schema.json`, `Chart.yaml`.
- `helm/values.yaml`, `helm/values.schema.json`, `helm/Chart.yaml`,
  `helm/templates/tests/test-config.yaml`, `helm/fixtures/*-values.yaml`,
  `helm/scripts/test-render.sh`, `helm/scripts/check-settlement-schema-drift.py`
  (removed).
- The VM storefront: a values-schema generator, its make target and drift test, typed
  declarations for `[Wallet]` and `[registry]`'s `auth`, and its `config show` and
  `config get` commands.
- `kit/config`'s storefront file discovery and reporting view. The API-credits
  storefront shares the discovery.
- `docs/development/VALIDATION_RUNBOOK.md`, which sets storefront values in the old
  shape, and `docs/development/DEPLOYMENT_AND_CONFIG.md`'s cutover sequence, which
  names an image/configuration schema check.
- Operators' own values files: the agent `config` block changes shape. `design.md`
  decision 6 maps every retired key to its new location.

## Dependencies and Related Changes

- **Blocks `compose-contact-exchange-across-compute`**, which composes contact
  exchange and delivery into the VM storefront and must be deployable by Helm. On
  this change's baseline its `[Settlement.contact]` and `[Delivery]` sections need no
  chart work beyond regenerating the values-schema fragment, which it extends for
  `kind`-dependent delivery sinks.
- Independent of `deduplicate-dynaconf-bootstrap`, which explicitly excludes the
  storefront loader.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the settlement-configuration paragraph
      says typed metadata generates Helm schema fragments; it now says what the
      generated fragment covers.
- [x] Existing subsystem specification — `openspec/specs/deployment-state/spec.md`
      (a new pass-through requirement, a new configuration-layer requirement, and
      "Generated configuration has one source of truth" narrowed); the
      `openspec/specs/deployment-state/architecture.md` and
      `openspec/specs/settlement-configuration/architecture.md` companions, which
      describe generated Helm schema fragments.
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/development/DEPLOYMENT_AND_CONFIG.md` also changes: its Kubernetes section
gains how the storefront chart applies the pass-through pattern, what it derives, the
`storefront.yaml` layer, that large integers are written as strings, and that the
generated schema refuses secret-marked settings, which belong in the Secret overlay;
its combined-storefront section points at the new values shape; its cutover sequence
loses the image/configuration schema check. `docs/development/VALIDATION_RUNBOOK.md`
moves to the new values shape. `docs/development/TESTING.md`'s chart render test
section names the generated-schema drift test.

### Knowledge to promote

- A storefront chart passes service configuration through and derives only
  Kubernetes-layer values; chart checks relate the release's subcharts, never one
  service's own configuration — `openspec/specs/deployment-state/spec.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- A value keyed by something only Kubernetes names, such as trust for the internal
  registry, is chart-level and checked against the release —
  `openspec/specs/deployment-state/spec.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- A pass-through chart's values schema is generated from the service's typed models
  to keep secret-marked, role-inapplicable, and unknown typed fields out of
  ConfigMaps; untyped secrets are declared by the service —
  `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`;
  `openspec/specs/deployment-state/architecture.md`;
  `openspec/specs/settlement-configuration/architecture.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- The storefront reads `storefront.toml`, `storefront.yaml`, then
  `storefront.secrets.toml`, and its reporting commands merge as the server does —
  `openspec/specs/deployment-state/spec.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- The generated-schema drift test — `docs/development/TESTING.md`.
