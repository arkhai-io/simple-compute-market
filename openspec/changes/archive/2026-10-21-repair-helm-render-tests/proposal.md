## Why

`make -C helm test-render` fails its render tests with `values don't meet the
specifications of the schema(s)`, `got null, want object`, at paths such as
`/internalRegistryTrust` and `/agents/bob`. `dev` fails the same step in CI
(`.github/workflows/tests.yml`, the `make -C helm test-render` step), which installs Helm
through `azure/setup-helm@v4` with no version pinned and so takes the latest release.

Under Helm v4.3.0, a `null` a parent chart's values aim at a subchart is removed only when
the subchart's own defaults define the key. Otherwise it survives into both charts' values
schemas, the templates, and the rendered configuration. Every storefront agent, every key
under one, and the bare-metal storefront's `internalRegistryTrust` are supplied from the
umbrella or an overlay, so `null` removal — the operator idiom `DEPLOYMENT_AND_CONFIG.md`
documents, `bob: null` to replace Bob — fails for operators' `helm install` and
`helm upgrade` as well as for the tests.

Until it is fixed:

- `make test` fails its last suite;
- `make validate-helm` stops at `test-render`, so no Helm scenario runs, and no
  change can produce the Helm part of its validation evidence. This blocks the
  Helm evidence `parallel-change-workflows` owes from its sections 5–7.

## What Changes

- Establish the full failing set under Helm v4.3.0 before the fix.
- The storefront charts make a values-file `null` remove what it names — an agent, an
  agent's value, or a key at any depth of its configuration — whatever the Helm
  release's merge did: one helper drops nulls from each agent before any template reads
  it, and the values schemas accept `null` wherever they accept the key. An agent renders
  as it would had a removed key never been stated, and an agent map that names no agent
  once its nulls are removed is refused.
- `kit/config`'s values-schema generator gains that null-accepting form; both storefront
  charts' schemas and the umbrella's storefront definition are regenerated. A key the
  schema refuses stays refused even as `null`.
- CI pins Helm v4.3.0, and `helm/scripts/test-render.sh` prints the Helm version it runs.
- State: **implementation and pre-closeout reviews complete; closeout proceeds on the owner's validation waiver recorded in `design.md`.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: "A storefront chart passes service configuration through" adds
  agents keyed by name and `null` removal that does not depend on the Helm release.

## Non-Goals

- Do not change which scenarios the Helm validation run serves; that is
  `helm-e2e-pipeline-parity`.
- Do not change the values shape or what the charts deploy; a `null` keeps meaning
  removal.
- Do not support a Helm release other than the one CI pins.

## Answered questions

- The cause is how Helm v4.3.0 carries a parent's `null` into a subchart's values
  (`design.md`, D1). Which release, if any, removed these nulls when the tests last
  passed is not known.
- `null` removal stays the supported idiom, made independent of the Helm release (D2).
- An operator's values file that nulls one of these keys fails the same way, so this is
  a deployment defect as well as a test one.

## Dependencies and Related Changes

- Unblocks the Helm validation evidence of `parallel-change-workflows`, and of
  every change whose validation runs `make validate-helm`.
- Related to `helm-e2e-pipeline-parity` and `add-full-stack-ci-job`, which also
  touch the Helm validation path.
- Opened from the unowned item recorded by `parallel-change-workflows`'
  implementation validation.

## Impact

`helm/` charts, their templates, values schemas, render tests, and
`helm/scripts/test-render.sh`; `kit/config`'s values-schema generator and both
storefronts' generated schemas; `.github/workflows/tests.yml`'s Helm setup. No service
code changes, and no change to the storefront's configuration loader.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Agents keyed by name and `null` removal independent of the Helm release (D2, D5) —
  `openspec/specs/deployment-state/spec.md`, "A storefront chart passes service
  configuration through", through this change's delta.
- A values-file `null` always means removal; a key the schema refuses stays refused as
  `null`; the supported Helm is the release CI pins (D2, D4) —
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through
  configuration".
- The supported Helm is the release `tests.yml` pins, and `test-render.sh` names the Helm
  it ran (D3, D4) —
  `docs/development/TESTING.md`, "Chart Render Tests", replacing the citation of a pin
  that did not exist.
- `kit/config`'s generator accepts `null` wherever it accepts a key (D2) —
  `docs/development/TESTING.md`, "A values schema generated from typed models".
