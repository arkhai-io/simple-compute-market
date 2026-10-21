# Tasks — repair Helm render tests

Planned against the design as reviewed and triaged in `reviews/09-design.triage.md`.
Sections follow the layers and the design's implementation cadence: the failing set is
established before anything changes (1), then `kit/config`'s generator (2), the two
storefronts that compose it and the schemas they write (3), the charts (4), CI and the
render script (5), and closeout (6). Depends on nothing open.

`kit/config` is `arkhai-kit-config` (`market_config`); `domains/vms/storefront` is the VM
storefront (`market_storefront`) and `domains/bare_metal/storefront` the bare-metal
storefront (`arkhai_bare_metal_storefront`). Every render check in this plan runs under
Helm v4.3.0 (`helm version --short`), the release `tests.yml` pins in Section 5.

## 1. The failing set under Helm v4.3.0

Establishes which render tests fail before the fix, and why (design "Corrections" 3;
cadence step 1). Changes no code.

- [ ] 1.1 **Decision gate.** On the branch as planned, with both loader environments
      present (`make init-storefront`; `make -C domains/bare_metal/storefront init`) and
      Helm v4.3.0 on `PATH`, run `make -C helm test-render` and record in `design.md`,
      under a new `## Implementation findings`, every failing test by file and name and
      its cause: a `null` surviving into a values schema (`got null`) or a template, or
      any other. The eight tests that set a `null` are named in "Corrections" 3. If any
      failure has another cause, stop and ask the owner whether it belongs to this change
      before Section 2 starts; do not fix it here. Evidence: the record.

## 2. `kit/config`: the generator accepts `null` wherever it accepts a key

Delivers the generator form of D2: a definition in which a key's value may be `null`
wherever the key is accepted, a refused key staying refused. Touches `kit/config` only;
no storefront uses it yet.

- [ ] 2.1 `kit/config/src/market_config/values_schema.py`: add one public function that
      takes a finished definition and returns a copy in which every schema reached as a
      mapping key's value — under `properties`, `patternProperties`, or
      `additionalProperties`, at every depth, including inside the combinators listed in
      `_COMBINATORS` — also accepts `null`, while every refused key (`false`) and every
      schema of an array's items keep their meaning (D2). The definition's root is left
      as it is: the agent's `config` key is the hand-written schema's (Section 4). Prefer
      a form that keeps each accepted field's existing shape readable — extending a
      `type` where one is stated — over wrapping every field, so a reader of the
      definition finds a field where it was. Describe the function in the module
      docstring's list of what the definition does, as current behaviour.
- [ ] 2.2 `kit/config/tests/unit/test_values_schema.py` (unit): over a definition built
      from the module's existing test models, the function accepts `null` for a typed
      field, a typed section, a key of an open section, a delivery instance, and a key
      under `additionalProperties`; a secret field, a role-inapplicable field, a retired
      key, and a misspelled sink key stay `false`; a field already accepting `null` is
      unchanged; array item schemas are unchanged; the input definition is not mutated.
      Break the function once (leave refused keys out of its skip) and confirm a test
      fails, then restore it.
- [ ] 2.3 Verification: `make dist`, then `make -C kit/config test` (unit), and
      `make test-kits`. No dependency or lock changes; if one proves necessary, run
      `make lock PROJECTS="kit/config"` and `make check-packaging` here.
      End-to-end: none; the generator runs only when a storefront writes its schemas.

## 3. Both storefronts accept `null` in the definitions they write

Delivers D2's regenerated schemas: the VM storefront's definition in the storefront
chart and the umbrella, and the bare-metal storefront's in its chart, each accepting
`null` where it accepts a key. Touches the two storefronts' `values_schema.py`, their
drift tests, and the three schema files the generators write.

- [ ] 3.1 `domains/vms/storefront/src/market_storefront/values_schema.py` and
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/values_schema.py`:
      apply Section 2's function to the definition each builds, as the last step of
      `storefront_config_definition` (D2). Reinit both environments against the rebuilt
      `kit/config` wheel (`make -C domains/vms/storefront reinit`;
      `make -C domains/bare_metal/storefront reinit`), then `make helm-values-schema`,
      which rewrites `storefrontServiceConfig` in `helm/charts/storefront/values.schema.json`,
      `helm/values.schema.json`, and `helm/charts/bare-metal-storefront/values.schema.json`.
      Commit the regenerated files.
- [ ] 3.2 `domains/vms/storefront/tests/unit/test_values_schema.py` and
      `domains/bare_metal/storefront/tests/test_values_schema.py` (unit): with
      `Draft7Validator`, as the VM test already uses it, a `config` setting a typed
      section, a typed field, and a delivery instance to `null` validates; a wallet's
      private key and a retired key stated as `null` are refused. Adjust any existing
      structural assertion the new form moves without weakening what it asserts. The drift
      tests pass against the committed schemas.
- [ ] 3.3 Record in `design.md` "Implementation findings" every typed field of either
      storefront's configuration models that the definition now accepts as `null` and
      whose default is not `None` — the fields an operator cannot set to `None` through
      chart values (D2) — or that there is none. A finding, not a decision: the design
      settled that a `null` means removal.
- [ ] 3.4 Verification: `make test-storefront` and `make test-bare-metal` (unit and
      library integration), with `make helm-values-schema` leaving no diff.
      End-to-end: none; a schema file is read only by Helm at render.

## 4. The charts absorb a `null`

Delivers D2 and D5 at render: a values-file `null` removes an agent, an agent's value, or
a configuration key at any depth, whatever Helm's merge did; an agent renders as it would
had the removed key never been stated; an agent map naming no agent once its nulls are
removed is refused; a refused key stays refused as `null` (`deployment-state` "A
storefront chart passes service configuration through", its four removal scenarios and
the scenarios "An overlay removes a defaulted setting", "… a value the release knows",
"… a required setting", and "… internal-registry trust"). Touches `helm/` only.

- [ ] 4.1 `helm/charts/storefront/templates/_helpers.tpl`: one recursive helper that
      returns the chart's agents with every `null` removed — a `null` agent dropped, and
      `null` values dropped at every depth of each agent, `config` included — and fails,
      naming `agents`, when no agent remains (D2, 09 F2). Every reader of an agent reads
      through it: `configmap.yaml`, `deployment.yaml`, `service.yaml`, `secrets.yaml`,
      `pvc.yaml`, and `tests/storefront-environment-test.yaml`, so
      `storefront.agentConfigDocument` and the other per-agent helpers receive agents
      with no `null` in them. A removed key a helper adds when absent is added, as for a
      key never stated (09 F1).
- [ ] 4.2 `helm/templates/_helpers.tpl` and `helm/templates/tests/test-config.yaml`: the
      umbrella reads `storefront.agents` and the bare-metal agent's `config` through its
      own normalization with the same rules, failing naming `agents` when the VM
      storefront is enabled and no agent remains (D2). The umbrella does not include the
      storefront chart's helper, since a disabled subchart's templates are not rendered.
- [ ] 4.3 `helm/charts/bare-metal-storefront/templates/_helpers.tpl`: the bare-metal
      chart reads its `config` and `internalRegistryTrust` with every `null` removed, at
      every depth, before `bare-metal-storefront.configDocument` and the other templates
      read them (D2). A removed `internalRegistryTrust` reaches the existing refusal
      "requires internalRegistryTrust".
- [ ] 4.4 The hand-written schemas accept `null` where an overlay removes something (D2):
      in `helm/charts/storefront/values.schema.json` and `helm/values.schema.json`, an
      entry of the agent map, an agent's `internalRegistryTrust`, and its `config`; in
      `helm/charts/bare-metal-storefront/values.schema.json`, `internalRegistryTrust` and
      `config`. The list form of `agents`, a `name` inside an entry, and the retired
      values shape stay refused, `null` or not. `minProperties: 1` stays.
- [ ] 4.5 Render tests (chart render tests, `docs/development/TESTING.md` "Chart Render
      Tests"), standard library only, each asserting the rendered artifacts together:
      - `helm/charts/storefront/tests/test_render.py`: an overlay removing Bob beside a
        second agent renders no Deployment, Service, ConfigMap, Secret, or PVC for Bob
        and renders the other agent as it would alone; removing the only agent is refused
        naming `agents`, through the umbrella and through the storefront chart rendered
        alone; a removed defaulted setting at depth is absent from `storefront.json`; a
        removed `db_path`, `registry.urls`, and `port` carry the release's values; a
        removed setting the storefront requires and the chart does not add (Bob's
        `Settlement`) renders absent, and, where `STOREFRONT_PYTHON` is set, the
        storefront's startup refusal over the rendered document names it; a
        removed `internalRegistryTrust` is refused naming the missing trust; a wallet's
        private key stated as `null` is refused naming the key; no rendered
        `storefront.json` contains a JSON `null` the values stated. The four existing
        tests that set a `null` pass unchanged.
      - `helm/charts/bare-metal-storefront/tests/test_render.py`: through the umbrella, a
        removed configuration key at depth is absent from `storefront.json`, and a
        removed `internalRegistryTrust` is refused naming the trust; the two existing
        tests that set a `null` pass unchanged.
      - `helm/tests/test_release_topology.py`: its two existing tests that set a `null`
        pass unchanged.
      Break the helper once (stop it dropping a `null` agent) and confirm a test fails,
      then restore it.
- [ ] 4.6 Verification: `make -C helm test-render` with both loader interpreters set
      (chart render tests and the chart-to-loader checks), every test Section 1 recorded
      as failing now passing; `make test`. End-to-end: `make validate-helm`'s Helm
      scenarios `contracts` and `e2e_alkahest_escrow_codecs` deploy the local release,
      which states no `null`, so they show the helpers leave a release without removals
      deploying as before; they do not exercise removal, which is a render-time
      behaviour the render tests prove, and no scenario is owed for it. The
      docker-compose pipeline deploys no chart.

## 5. CI pins Helm, and every render run names its Helm

Delivers D3 and D4's mechanism. Touches `.github/workflows/tests.yml` and
`helm/scripts/test-render.sh`.

- [ ] 5.1 `.github/workflows/tests.yml`: pass `version: "v4.3.0"` to
      `azure/setup-helm@v4`, as the same job pins uv (D3).
- [ ] 5.2 `helm/scripts/test-render.sh`: print `helm version --short` before the first
      render, so every render log, `make validate-helm`'s included, names the Helm it ran
      (D4).
- [ ] 5.3 Verification: `make -C helm test-render` prints the version first and passes;
      `make test-release-tooling`. CI's run of the pushed branch shows Helm v4.3.0 in
      its setup step and passes `make -C helm test-render`; record the run.
      End-to-end: none; the pin and the printed version change no deployment.

## 6. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`. Confirm the template
      and Python comments this change added describe current behaviour, citing
      `openspec/specs/deployment-state/spec.md`, "A storefront chart passes service
      configuration through", where they point anywhere. A finding returns the change
      to implementation.
- [ ] 6.2 **Import placement.** Confirm every import Sections 2 and 3 added is at module
      level. One that should move returns the change to implementation.
- [ ] 6.3 **Documentation compliance.** Check each decision's destination below against
      the placement table in `openspec/README.md`: the normative removal rule in the
      `deployment-state` spec, the operator idiom and the supported Helm in
      `DEPLOYMENT_AND_CONFIG.md`, the pin, the printed version, and the generator's form
      in `TESTING.md`; nothing in `ARCHITECTURE.md`.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to results, validation
      evidence, and destinations; the Section 1 record and the Section 3.3 finding stay
      in `design.md` "Implementation findings".
- [ ] 6.5 **Roadmap currency.** No `docs/development/ROADMAP.md` goal owns this change; it
      sits under "Unblocking work — the local end-to-end stack" in the index. Record that
      nothing is owed.
- [ ] 6.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md` under "Unblocking work — the local end-to-end stack"
      to its closeout state; the campaign's graph does not include this change and stays
      as it is. Record the disposition.
- [ ] 6.7 **Packaging.** `make check-packaging` passes, and
      `make check-architecture-change CHANGE=repair-helm-render-tests` reports no
      exception or override row this change owns.
- [ ] 6.8 **End-to-end pipeline.** Record the run of the end-to-end pipeline on the final
      commit and its result, and `make validate-helm`'s record: `test-render` passing,
      the Helm version its log names, and the Helm scenarios `contracts` and
      `e2e_alkahest_escrow_codecs` (Section 4.6). The docker-compose lanes deploy no
      chart and exercise none of this change; say so. If either cannot run for a reason
      unrelated to this change, record the blocker and its owning change and treat what
      it gates as unrun.
- [ ] 6.9 **Promotion.** Write the permanent documents below and complete the design
      promotion record:
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through
        configuration": a `null` always means removal, at any depth of an agent, whatever
        the Helm release's merge does; a removed key the chart derives takes the
        release's value; removing every agent is refused, and `storefront.enabled: false`
        runs none; a key the schema refuses stays refused as `null`; the supported Helm is
        the release `.github/workflows/tests.yml` pins, without repeating its number.
      - `docs/development/TESTING.md`, "Chart Render Tests": replace "rely on the pinned
        Helm of the release environment" with the release `tests.yml` pins, which is the
        supported one, and say `test-render.sh` prints the Helm it runs, without claiming
        a render result is evidence only on that release (D4); in its "A values schema
        generated from typed models" paragraph, that the generated definition accepts
        `null` wherever it accepts a key and a refused key stays refused.
      - `openspec/specs/deployment-state/spec.md`: written by the archive in 6.11, from
        this change's delta.
- [ ] 6.10 **Documentation citations.** `make check-doc-citations
      CHANGE=repair-helm-render-tests` passes, then
      `openspec validate repair-helm-render-tests --strict`.
- [ ] 6.11 **Archival.** `openspec archive repair-helm-render-tests -y`, which merges the
      `deployment-state` delta into `openspec/specs/deployment-state/spec.md`; the row in
      `openspec/changes/README.md` then links the archive directory. Commit.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1: under Helm 4.3.0 a parent's `null` survives for a key the subchart does not define | Not promoted; change history in `design.md` |
| D2, D5: agents keyed by name; a values-file `null` removes an agent, an agent's value, or a configuration key whatever the Helm release's merge did; an empty agent map is refused; a refused key stays refused as `null` | `openspec/specs/deployment-state/spec.md`, "A storefront chart passes service configuration through"; `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through configuration" |
| D2: the generator accepts `null` wherever it accepts a key | `docs/development/TESTING.md`, "Chart Render Tests" ("A values schema generated from typed models") |
| D3: CI pins Helm v4.3.0 | `docs/development/TESTING.md`, "Chart Render Tests"; `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through configuration" |
| D4: the supported Helm is the release CI pins, and every render run names its Helm | `docs/development/TESTING.md`, "Chart Render Tests" |
| Roadmap currency | To be recorded at 6.5 |
| Campaign index currency | To be recorded at 6.6 |
