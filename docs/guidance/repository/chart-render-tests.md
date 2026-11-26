---
tags: [repository, testing, helm]
---

# Chart render tests

Where this repository's chart render tests live, how they run, and how one is written
here. What a chart render test is, what it covers, and how to write one are
[`helm-render-tests.md`](../engineering/helm-render-tests.md). It is a
[static configuration test](static-configuration-tests.md): it needs Helm, not a
cluster. What every chart renders is [`helm-charts.md`](helm-charts.md).

## The supported Helm

The supported Helm is the release pinned in
[`.github/workflows/tests.yml`](../../../.github/workflows/tests.yml).
`helm/scripts/test-render.sh` prints `helm version --short` before its first
render, so each render log names the Helm it ran. The script does not enforce
the pin; a render step's result is recorded for the version it reports. The
chart's content digest does enforce it: `.helm-version` names the Helm the digest is
computed with, the digest refuses any other
([`package-versions.md`, "A version changes when its contents change"](package-versions.md#a-version-changes-when-its-contents-change)),
and a test holds `.helm-version` equal to `tests.yml`'s pin, so a Helm bump edits both.
A Helm binary taken from a redistribution, where `get.helm.sh` is unreachable, is
kept out of the repository
([the validation runbook's "Optional Environment-Dependent Local Tests"](../../development/VALIDATION_RUNBOOK.md#5-optional-environment-dependent-local-tests)
gives obtaining one).

## Where they live and how they run

- Umbrella-chart assertions are in `helm/scripts/test-render.sh`, run by
  `make -C helm test-render` and by the top-level `make test-deployment-packaging`.
  The umbrella's own Python render tests, such as the two-release topology's
  `helm/tests/test_release_topology.py`, live in `helm/tests/`, and
  `test-render.sh` runs them beside each chart's. Among them,
  `helm/tests/test_default_images.py` holds that the chart's default values name no
  release — no semver-shaped or revision-suffixed image tag and no digest — and
  `helm/tests/test_subchart_pins.py` that each of the umbrella's dependency entries
  names its subchart's own version.
- A chart's own render tests are `helm/charts/<chart>/tests/test_render.py`. Call
  each from `test-render.sh` so that one target runs every render check; a test
  reachable only through its chart's own Makefile is easily never run.
- `make test` runs all of it, through `make test-deployment-packaging`, and all of it
  needs `helm` on `PATH`.
- `helm/charts/storefront/tests/test_render.py` also loads one rendered
  `storefront.json` with the storefront's own configuration loader, through the
  interpreter `STOREFRONT_PYTHON` names, runs the storefront's startup refusal over
  it, and derives the local release's Alkahest release conditions over its render;
  over the chart defaults' render the refusal names the missing settlement
  mechanism. Over the chart rendered alone with its production example,
  `helm/charts/storefront/examples/production-values.yaml`, it runs the startup
  refusal, which accepts the render, and derives the example's recurring clauses
  against a representative dispute authority advertisement under the example's own
  listing horizon, publishing an on-demand and a spot option with the clause's
  delivery deadline and `charged` and `returned`, and none once an overlay removes
  the rate servicing declaration. `test-render.sh` sets it when the VM storefront environment exists
  (`make init-storefront`). `helm/charts/bare-metal-storefront/tests/test_render.py`
  does the same through `BARE_METAL_STOREFRONT_PYTHON`, which `test-render.sh` sets
  when `domains/bare_metal/storefront/.venv` exists (`make
  init-bare-metal-storefront`; both targets build the wheelhouse first, and `make
  init` runs both): bare metal's loader, startup
  refusal, clause compilation, and site binding over the example's rendered
  document, and the refusal over the defaults'. That shows a rendered configuration
  is publishable, not that the storefront starts on it, since the runtime also needs
  the credential, the overlay's wallet key, a writable database, and chain clients.
  Without its interpreter each check reports a skip. No CI job has both Helm and
  those environments, so in CI these checks do not run; run them locally before a
  change to a chart or a loader is reviewed.
- `helm/charts/storefront/tests/test_render.py` also asserts, over the defaults,
  the local release, every rendering fixture, and a second agent, that each VM
  storefront Deployment renders exactly one init container — `migrate`, running
  `market-storefront-migrate` alone from the application's image and environment
  over the data volume, without `entrypoint.sh` or ZeroTier — and no `wait-for-`
  container, and that each carries a `startupProbe` on `/health`, as the
  bare-metal chart's test asserts of `bare-metal-storefront-migrate`: the
  storefront migrates its own database first, then starts with its dependencies
  unreachable and reports them degraded.
- `helm/charts/registry/tests/test_render.py` asserts, over the defaults, with
  persistence disabled, with another mount path, and with a secret profile, that
  the registry Deployment renders exactly one init container running
  `registry-migrate` from the application's image, with its environment and
  profile mounts but not its signer credential, over the application's data
  volume, and that the application container states its own command; in the
  umbrella with the `api-credits-registry` alias enabled both instances render the
  same, and with it disabled nothing of the alias renders.
  `helm/charts/provisioning/tests/test_render.py` asserts the same of
  `compute-provisioning-migrate`, and that the application container mounts the
  SSH key from the Secret `sshKey.secretName` names only without `mockMode`,
  where an empty or absent name is refused naming it, while under `mockMode` no
  key mounts and no name is needed.
- `helm/tests/test_release_topology.py` asserts, over both topology releases,
  that no Pod annotated `helm.sh/hook: test` carries all of any Deployment's
  `matchLabels` or any Service's selector — every test pod carries
  `app.kubernetes.io/component: test` and its release's instance label and lacks
  `app.kubernetes.io/name`, which every selector requires — and that each release
  renders exactly its expected test templates, so a test pod that stops rendering
  fails rather than leaving nothing to check.
- Both storefront charts' render tests assert the payments interface: the CA
  bundle option (`caBundle`) mounted from a ConfigMap or a Secret together with
  the `ca_bundle_path` it derives into the rendered configuration, neither
  rendered without it, and the option refused without a payments section; the
  values schema refusing in public `config` the payments `api_key`, its
  `api_key_env`, and every `[[DisputeCredential]]` entry; a payments-only
  storefront rendering with nothing for its removed settings; and the
  payments-check test pod running the storefront's own command with the
  Deployment's image, environment, and configuration mounts but no data volume,
  probes, or ZeroTier device, rendered only with payments and an account. The
  VM storefront chart's render test asserts the same of the mediation-check test
  pod, which runs `market-storefront check-mediation --origin` with the CA mount
  and the Secret overlay present and renders only when `tests.mediationOrigin`
  names an origin; in the local release Bob's names the mediation double's.
  `helm/charts/payments-lane-double/tests/test_render.py` and
  `helm/charts/mediation-lane-double/tests/test_render.py` assert each double is
  off by default, runs once behind its Service (`payments-double`,
  `mediation-double`) in the local release and not at all in the bare-metal
  release, and serves a named TLS Secret over the image's files.
- `helm/tests/test_release_topology.py` also holds the local release's payments
  values to the double's committed fixtures, and asserts the registry chart
  renders its settings as the profile `config-production.env`, sets only
  `CONFIG_DIRECTORY` and `ACTIVE_PROFILES` in the pod environment, layers a
  `secretProfile` after it, and refuses the retired `auth.*KeySecret` values
  naming `secretProfile`. Through the interpreter `REGISTRY_PYTHON` names, which
  `test-render.sh` sets when `core/registry/.venv` exists, it loads the rendered
  profile with the registry's own loader; without it that check reports a skip.
- Release tooling (`make test-release-tooling`) reads back the secret overlays
  `topology-secrets` writes: the seller payments key in each storefront's
  runtime overlay, and Bob's `[[DisputeCredential]]` equal to his Compose
  secret overlay's but for its `ca_bundle_path`, which names the storefront
  chart's CA file (`storefront.caBundleFile`) rather than the Compose mount
  (`scripts/tests/test_change_build_and_helm_targets.py`).

## Writing one here

Use the standard library only. `test-render.sh` runs a plain
`python3`, which has no YAML parser, so a render test passes values as a JSON file
and asserts on the rendered text; the storefront's `storefront.json` is read back
with `json`.

## A chart's values schema types the chart's own values

**A chart's values schema types the chart's own values**
([`helm.md`](../engineering/helm.md#a-charts-values-schema-types-the-charts-own-values)).
The provisioning chart passes its `config` through to the service's profile: its
schema types the chart's own values and refuses under `config` only the keys the
chart derives itself or delivers from a Secret, and retired ones, so a section the
service adds, such as `[Events]`, deploys with no chart change. No chart gains a
schema generated from a service's configuration models.

The two storefront charts do not yet meet the rule, which is deferred work: each
storefront chart's values schema carries a definition generated from that
storefront's typed configuration models (`make helm-values-schema`, which runs each
storefront's generator in its own environment), because the storefront's loader does
not refuse a secret in its public file, an unknown key, or a doubled spelling
itself. Moving those refusals into the loader and removing the definitions is a row
of [`openspec/changes/README.md`](../../../openspec/changes/README.md). The generator
is `kit/config`'s, with its own unit tests over small
model sets; each storefront supplies only its sections, settlement registrations,
and discovered delivery sinks, and writes only its own chart's schema. Both
storefronts opt into the generator's `accepting_null` form: the definition accepts
`null` wherever it accepts a key, at every depth, including keys inside list
elements, so the chart can remove it before rendering. A refused key stays
refused as `null`; the transformation does not widen array item schemas to
accept null elements. Each storefront's drift test is its own unit test —
`domains/vms/storefront/tests/unit/test_values_schema.py` and
`domains/bare_metal/storefront/tests/test_values_schema.py` — so `make test` fails
when a model or settlement registration changes without regenerating. The render
tests then assert what the schema refuses and accepts.
