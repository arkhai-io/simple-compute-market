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
  storefront unchanged: values carry the service's own keys (`[Settlement]`,
  `[Delivery]`, `[pricing]`, `[capacity]`, and so on), and the chart serializes the
  block rather than enumerating it.
- The chart adds only what the Kubernetes layer knows and the service cannot — the
  service URLs of sibling subcharts, the public URL of the agent's own Service, the
  gateway root path, and trust pins drawn from the umbrella's identity globals —
  and only where the agent's configuration does not already state them.
- The chart stops re-implementing service defaults and service validation. It
  keeps the checks that relate this chart to the rest of the release: that the
  agent's registry and provisioning trust include the release's own registry and
  provisioning principals, that the image's settlement configuration schema version
  matches the configuration's, and the RPC wait init container keyed off a
  configured Alkahest chain.
- The values schema stops describing service configuration: an agent's `config` is
  an open object, the hand-written settlement definitions are removed from both
  schemas, and the drift check that compared them is removed.
- The storefront discovers the rendered document through its existing loader. The
  rendering format, and whether the loader gains a file name to read it, is decided
  in `design.md`.
- Every committed values file and fixture moves to the new shape, and render tests
  assert that a section the chart has never heard of reaches the storefront intact.

## Capabilities

### Modified Capabilities

- `deployment-state`: a storefront chart passes service configuration through and
  derives only Kubernetes-layer values; Helm values schemas no longer carry
  generated service-configuration fragments.

### New Capabilities

None.

## Non-Goals

- Do not move the storefront onto the profile-based (`ACTIVE_PROFILES` /
  `config-<profile>.yml`) loader provisioning uses. That is unprioritized until a
  need arises.
- Do not change the storefront Secret overlay (`storefront.secrets.toml`) or what
  belongs in it.
- Do not change the service's own configuration models, defaults, or validation.
- Do not change the bare-metal storefront chart, which receives its settlement
  configuration as JSON from an existing Secret; see `design.md`.
- Do not change the provisioning, registry, dev-env, or e2e charts.

## Impact

- `helm/charts/storefront/templates/_helpers.tpl` (`storefront.agentConfigToml` and
  the helpers only it uses), `templates/configmap.yaml`, `templates/deployment.yaml`
  (mount paths only, if the format changes), `values.yaml`, `values.schema.json`.
- `helm/values.yaml`, `helm/values.schema.json`, `helm/fixtures/*-values.yaml`,
  `helm/scripts/test-render.sh`, `helm/scripts/check-settlement-schema-drift.py`
  (removed).
- Possibly `kit/config`'s storefront file discovery, if the rendered format is not
  TOML (`design.md` decision 2).
- Operators' own values files: the agent `config` block changes shape. A mapping
  from the old keys to the new is part of the change.

## Dependencies and Related Changes

- **Blocks `compose-contact-exchange-across-compute`**, which composes contact
  exchange and delivery into the VM storefront and must be deployable by Helm. On
  this change's baseline its `[Settlement.contact]` and `[Delivery]` sections need no
  chart work.
- Independent of `deduplicate-dynaconf-bootstrap`, which explicitly excludes the
  storefront loader.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the settlement-configuration paragraph
      says typed metadata generates Helm schema fragments; it no longer does.
- [x] Existing subsystem specification — `openspec/specs/deployment-state/spec.md`;
      the `openspec/specs/settlement-configuration/architecture.md` companion, which
      makes the same Helm-fragment claim.
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/development/DEPLOYMENT_AND_CONFIG.md` also changes: its Kubernetes section
gains how the storefront chart applies the pass-through pattern and what it
derives, and the combined storefront section points at the new values shape.

### Knowledge to promote

- A storefront chart passes service configuration through and derives only
  Kubernetes-layer values; chart checks relate the release's subcharts and images,
  never one service's own configuration —
  `openspec/specs/deployment-state/spec.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Helm values schemas carry no service-configuration fragments; the service's typed
  configuration is the only validation of its own keys —
  `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`;
  `openspec/specs/settlement-configuration/architecture.md`.
