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
  provisioning principals, that the image's settlement configuration schema version
  matches the configuration's, and that the configured port is the agent's port. It
  reads the passed-through configuration only to decide which init containers to
  run.
- The values schema stops describing service configuration: an agent's `config` is
  an open object, the hand-written service definitions are removed from both
  schemas, and the drift check that compared them is removed. The schema refuses the
  retired values shape, naming the key.
- The storefront's file discovery reads `storefront.yaml` between `storefront.toml`
  and `storefront.secrets.toml`, and its configuration commands report what the
  server loads when only the rendered files are present.
- Every committed values file, fixture, and the umbrella's smoke-test configuration
  moves to the new shape, and render tests assert that a section the chart has never
  heard of reaches the storefront intact.
- An agent's `config` is public configuration. The storefront, not the chart,
  validates it, at startup.

## Capabilities

### Modified Capabilities

- `deployment-state`: a storefront chart passes service configuration through and
  derives only Kubernetes-layer values; Helm values schemas no longer carry
  generated service-configuration fragments; pass-through configuration is public
  and validated by the service at startup.

### New Capabilities

None.

## Non-Goals

- Do not move the storefront onto the profile-based (`ACTIVE_PROFILES` /
  `config-<profile>.yml`) loader provisioning uses; see `design.md` decision 10.
- Do not change what the storefront Secret overlay (`storefront.secrets.toml`)
  carries; an operator-managed Secret needs no change.
- Do not change the service's own configuration models, defaults, or validation.
- Do not guard pass-through configuration against secrets placed in it, and do not
  add pre-deploy validation of chart values; see `design.md` decisions 8 and 9.
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
- `kit/config`'s storefront file discovery and file reading; the VM storefront's
  `config show` and `config get`. The API-credits storefront shares the discovery.
- `docs/development/VALIDATION_RUNBOOK.md`, which sets storefront values in the old
  shape.
- Operators' own values files: the agent `config` block changes shape. `design.md`
  decision 6 maps every retired key to its new location.

## Dependencies and Related Changes

- **Blocks `compose-contact-exchange-across-compute`**, which composes contact
  exchange and delivery into the VM storefront and must be deployable by Helm. On
  this change's baseline its `[Settlement.contact]` and `[Delivery]` sections need no
  chart work. A delivery sink credential an operator keeps secret goes in the Secret
  overlay, since an agent's `config` renders into a ConfigMap.
- Independent of `deduplicate-dynaconf-bootstrap`, which explicitly excludes the
  storefront loader.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the settlement-configuration paragraph
      says typed metadata generates Helm schema fragments; it no longer does.
- [x] Existing subsystem specification — `openspec/specs/deployment-state/spec.md`
      (a new pass-through requirement; "Generated configuration has one source of
      truth" and "Identity configuration separates public and secret material"
      modified); the `openspec/specs/deployment-state/architecture.md` and
      `openspec/specs/settlement-configuration/architecture.md` companions, which make
      the same Helm-fragment claim.
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/development/DEPLOYMENT_AND_CONFIG.md` also changes: its Kubernetes section
gains how the storefront chart applies the pass-through pattern, what it derives, the
`storefront.yaml` layer, that large integers are written as strings, and that an
agent's `config` is public with secret-marked settings belonging in the Secret
overlay; the combined storefront section points at the new values shape.
`docs/development/VALIDATION_RUNBOOK.md` moves to the new values shape.

### Knowledge to promote

- A storefront chart passes service configuration through and derives only
  Kubernetes-layer values; chart checks relate the release's subcharts and images,
  never one service's own configuration —
  `openspec/specs/deployment-state/spec.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- A value keyed by something only Kubernetes names, such as trust for the internal
  registry, is chart-level and checked against the release — 
  `openspec/specs/deployment-state/spec.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- An agent's pass-through configuration is public, and the storefront validates it at
  startup — `openspec/specs/deployment-state/spec.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- The storefront reads `storefront.toml`, `storefront.yaml`, then
  `storefront.secrets.toml` — `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Helm values schemas carry no service-configuration fragments; the service's typed
  configuration is the only validation of its own keys —
  `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`;
  `openspec/specs/deployment-state/architecture.md`;
  `openspec/specs/settlement-configuration/architecture.md`.
