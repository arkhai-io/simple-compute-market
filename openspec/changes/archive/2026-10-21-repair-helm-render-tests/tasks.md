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

- [x] 1.1 **Decision gate.** On the branch as planned, with both loader environments
      present (`make init-storefront`; `make -C domains/bare_metal/storefront init`) and
      Helm v4.3.0 on `PATH`, run `make -C helm test-render` and record in `design.md`,
      under a new `## Implementation findings`, every failing test by file and name and
      its cause: a `null` surviving into a values schema (`got null`) or a template, or
      any other. The eight tests that set a `null` are named in "Corrections" 3. If any
      failure has another cause, stop and ask the owner whether it belongs to this change
      before Section 2 starts; do not fix it here. Evidence: the record.
      — Thirteen failures established: ten surviving-null refusals and three Helm refusal-wording assertions. The owner included the wording fixes in 4.5. All earlier make
      test suites passed. Diagnosis and corrected counts are in design.md,
      Implementation findings.

## 2. `kit/config`: the generator accepts `null` wherever it accepts a key

Delivers the generator form of D2: a definition in which a key's value may be `null`
wherever the key is accepted, a refused key staying refused. Touches `kit/config` only;
no storefront uses it yet.

- [x] 2.1 `kit/config/src/market_config/values_schema.py`: add one public function that
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
      — Implemented accepting_null(definition), preserving refused keys, the root and array item
      types while widening keys at every depth. It copies its input. Detailed schema
      handling is retained in design.md.
- [x] 2.2 `kit/config/tests/unit/test_values_schema.py` (unit): over a definition built
      from the module's existing test models, the function accepts `null` for a typed
      field, a typed section, a key of an open section, a delivery instance, and a key
      under `additionalProperties`; a secret field, a role-inapplicable field, a retired
      key, and a misspelled sink key stay `false`; a field already accepting `null` is
      unchanged; array item schemas are unchanged; the input definition is not mutated.
      Break the function once (leave refused keys out of its skip) and confirm a test
      fails, then restore it.
      — Unit coverage proves accepted/removable keys, refused secret and retired keys,
      combinators, list-element keys, references, and independent copies. Removing the
      refused-key skip made two tests fail; restored.
- [x] 2.3 Verification: `make dist`, then `make -C kit/config test` (unit), and
      `make test-kits`. No dependency or lock changes; if one proves necessary, run
      `make lock PROJECTS="kit/config"` and `make check-packaging` here.
      End-to-end: none; the generator runs only when a storefront writes its schemas.
      — After make dist, kit/config unit tests: 256 passed; make test-kits: 22 suites passed. No
      dependency or lock change. The not-yet-fixed render suite was the sole make test
      failure; no end-to-end scenario owed.

## 3. Both storefronts accept `null` in the definitions they write

Delivers D2's regenerated schemas: the VM storefront's definition in the storefront
chart and the umbrella, and the bare-metal storefront's in its chart, each accepting
`null` where it accepts a key. Touches the two storefronts' `values_schema.py`, their
drift tests, and the three schema files the generators write.

- [x] 3.1 `domains/vms/storefront/src/market_storefront/values_schema.py` and
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/values_schema.py`:
      apply Section 2's function to the definition each builds, as the last step of
      `storefront_config_definition` (D2). Reinit both environments against the rebuilt
      `kit/config` wheel (`make -C domains/vms/storefront reinit`;
      `make -C domains/bare_metal/storefront reinit`), then `make helm-values-schema`,
      which rewrites `storefrontServiceConfig` in `helm/charts/storefront/values.schema.json`,
      `helm/values.schema.json`, and `helm/charts/bare-metal-storefront/values.schema.json`.
      Commit the regenerated files.
      — Both generators apply accepting_null last; all three schemas regenerated. Storefront
      test targets refreshed their environments; the owner ran make helm-values-schema.
- [x] 3.2 `domains/vms/storefront/tests/unit/test_values_schema.py` and
      `domains/bare_metal/storefront/tests/test_values_schema.py` (unit): with
      `Draft7Validator`, as the VM test already uses it, a `config` setting a typed
      section, a typed field, and a delivery instance to `null` validates; a wallet's
      private key and a retired key stated as `null` are refused. Adjust any existing
      structural assertion the new form moves without weakening what it asserts. The drift
      tests pass against the committed schemas.
      — Both storefronts validate accepted nulls and refused secret/retired keys with
      Draft7Validator; drift checks pass. Bare metal adds jsonschema>=4.0 to dev
      dependencies and its lock is regenerated.
- [x] 3.3 Record in `design.md` "Implementation findings" every typed field of either
      storefront's configuration models that the definition now accepts as `null` and
      whose default is not `None` — the fields an operator cannot set to `None` through
      chart values (D2) — or that there is none. A finding, not a decision: the design
      settled that a `null` means removal.
      — No typed field with an effective non-None default has a different accepted None outcome.
      Model/default details and untyped-field limits are retained in design.md,
      Implementation findings.
- [x] 3.4 Verification: `make test-storefront` and `make test-bare-metal` (unit and
      library integration), with `make helm-values-schema` leaving no diff.
      End-to-end: none; a schema file is read only by Helm at render.
      — VM: 1103 unit and 448 integration tests passed; make test-bare-metal passed, including
      440 storefront tests. Generated-schema drift checks and check-packaging passed
      after the relock. The pending chart fixes still blocked make test at render; no
      end-to-end scenario owed.

## 4. The charts absorb a `null`

Delivers D2 and D5 at render: a values-file `null` removes an agent, an agent's value, or
a configuration key at any depth, whatever Helm's merge did; an agent renders as it would
had the removed key never been stated; an agent map naming no agent once its nulls are
removed is refused; a refused key stays refused as `null` (`deployment-state` "A
storefront chart passes service configuration through", its four removal scenarios and
the scenarios "An overlay removes a defaulted setting", "… a value the release knows",
"… a required setting", and "… internal-registry trust"). Touches `helm/` only.

- [x] 4.1 `helm/charts/storefront/templates/_helpers.tpl`: one recursive helper that
      returns the chart's agents with every `null` removed — a `null` agent dropped, and
      `null` values dropped at every depth of each agent, `config` included — and fails,
      naming `agents`, when no agent remains (D2, 09 F2). Every reader of an agent reads
      through it: `configmap.yaml`, `deployment.yaml`, `service.yaml`, `secrets.yaml`,
      `pvc.yaml`, and `tests/storefront-environment-test.yaml`, so
      `storefront.agentConfigDocument` and the other per-agent helpers receive agents
      with no `null` in them. A removed key a helper adds when absent is added, as for a
      key never stated (09 F1).
      — storefront.dropNulls normalizes copies, including keys inside list elements;
      storefront.agents fills the caller map and refuses no remaining agent. All six
      readers use it. Null list elements retain their schema meaning.
- [x] 4.2 `helm/templates/_helpers.tpl` and `helm/templates/tests/test-config.yaml`: the
      umbrella reads `storefront.agents` and the bare-metal agent's `config` through its
      own normalization with the same rules, failing naming `agents` when the VM
      storefront is enabled and no agent remains (D2). The umbrella does not include the
      storefront chart's helper, since a disabled subchart's templates are not rendered.
      — arkhai.dropNulls and arkhai.storefrontAgents apply the same rules. The umbrella
      normalizes both storefront configs and refuses an empty storefront.agents map
      independently of subchart helpers.
- [x] 4.3 `helm/charts/bare-metal-storefront/templates/_helpers.tpl`: the bare-metal
      chart reads its `config` and `internalRegistryTrust` with every `null` removed, at
      every depth, before `bare-metal-storefront.configDocument` and the other templates
      read them (D2). A removed `internalRegistryTrust` reaches the existing refusal
      "requires internalRegistryTrust".
      — bare-metal-storefront.configDocument normalizes copies of config and
      internalRegistryTrust, the only reader of either. Removed trust reaches the
      existing missing-trust refusal.
- [x] 4.4 The hand-written schemas accept `null` where an overlay removes something (D2):
      in `helm/charts/storefront/values.schema.json` and `helm/values.schema.json`, an
      entry of the agent map, an agent's `internalRegistryTrust`, and its `config`; in
      `helm/charts/bare-metal-storefront/values.schema.json`, `internalRegistryTrust` and
      `config`. The list form of `agents`, a `name` inside an entry, and the retired
      values shape stay refused, `null` or not. `minProperties: 1` stays.
      — Hand-written schemas accept removal of agent entries, config and internalRegistryTrust.
      Implementation triage 22 F1 also covered every agent value and its nested keys;
      missing port or identity is refused by name. Refused keys and identity subkeys
      keep their constraints.
- [x] 4.5 Render tests (chart render tests, `docs/development/TESTING.md` "Chart Render
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
      Amended after 1.1: ten existing tests set a `null` — six in the storefront chart's
      tests, two in the bare-metal chart's, two in the topology's — and each passes
      unchanged. The three tests 1.1 recorded as failing on Helm 4's wording of a
      schema refusal (bare-metal `test_a_stated_port_must_be_a_number_equal_to_the_charts`
      and `test_the_retired_values_shape_is_refused_naming_each_key`; storefront
      `test_an_agent_is_named_by_its_key_alone`) assert the key their refusal names
      rather than a whole message, still asserting a non-zero exit (owner's decision at
      1.1).
      — Render checks cover agent removal, empty maps, defaulted/derived/required settings,
      list-element keys, trust, refused keys and topology. Triage 22 added all chart-level removals and full-manifest comparison against an agent never stated. Four
      tests failed with null-agent removal broken; restored. Detailed assertions and
      review rationale are retained in design.md.
- [x] 4.6 Verification: `make -C helm test-render` with both loader interpreters set
      (chart render tests and the chart-to-loader checks), every test Section 1 recorded
      as failing now passing; `make test`. End-to-end: `make validate-helm`'s Helm
      scenarios `contracts` and `e2e_alkahest_escrow_codecs` deploy the local release,
      which states no `null`, so they show the helpers leave a release without removals
      deploying as before; they do not exercise removal, which is a render-time
      behaviour the render tests prove, and no scenario is owed for it. The
      docker-compose pipeline deploys no chart.
      — Every shell assertion and all 83 Python render tests passed on Helm v4.3.0 with both
      loader interpreters and no skips; make test passed. After test-only fixes, render
      checks passed again. Validation supplies contracts and e2e_alkahest_escrow_codecs;
      neither tests null removal, which belongs to render checks.

## 5. CI pins Helm, and every render run names its Helm

Delivers D3 and D4's mechanism. Touches `.github/workflows/tests.yml` and
`helm/scripts/test-render.sh`.

- [x] 5.1 `.github/workflows/tests.yml`: pass `version: "v4.3.0"` to
      `azure/setup-helm@v4`, as the same job pins uv (D3).
      — Pinned in the release-deployment job beside setup-uv.
- [x] 5.2 `helm/scripts/test-render.sh`: print `helm version --short` before the first
      render, so every render log, `make validate-helm`'s included, names the Helm it ran
      (D4).
      — Prints helm <version> after dependency update and before the first render.
- [x] 5.3 Verification: `make -C helm test-render` prints the version first and passes;
      `make test-release-tooling`. CI's run of the pushed branch shows Helm v4.3.0 in
      its setup step and passes `make -C helm test-render`; record the run.
      End-to-end: none; the pin and the printed version change no deployment.
      — Render and make test passed with helm v4.3.0+gbec5b06; release-tooling: 1090 passed.
      Dispatched tests.yml run 39625394342 at ca8f5f309 passed release deployment
      contracts with the pin installed. Its five loader/startup skips were covered
      locally without skips. Four unrelated CI-only storefront failures also reproduce
      on dev and remain in the index; exact tests and counts are retained in design.md.
      The comment fix f6f091a83 subsequently passed render, make test, packaging, check-change and make validate-helm. Further validation is waived by the owner at
      closeout.

## 6. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [x] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`. Confirm the template
      and Python comments this change added describe current behaviour, citing
      `openspec/specs/deployment-state/spec.md`, "A storefront chart passes service
      configuration through", where they point anywhere. A finding returns the change
      to implementation.
      — Confirmed against the implementation diff, including the 43 F1 comment fix. make check-comment-hygiene passed at closeout; comments explain current invariants and use
      the permanent contract. No code edit needed.
- [x] 6.2 **Import placement.** Confirm every import Sections 2 and 3 added is at module
      level. One that should move returns the change to implementation.
      — Inspected added/changed Python imports against dev: accepting_null in both generators
      and Draft7Validator in the bare-metal tests are all at module level. No local
      import added.
- [x] 6.3 **Documentation compliance.** Check each decision's destination below against
      the placement table in `openspec/README.md`: the normative removal rule in the
      `deployment-state` spec, the operator idiom and the supported Helm in
      `DEPLOYMENT_AND_CONFIG.md`, the pin, the printed version, and the generator's form
      in `TESTING.md`; nothing in `ARCHITECTURE.md`.
      — D1 remains diagnosis/history. D2/D5 go to the deployment-state contract and operator
      guide; D3/D4 and generator conventions go to TESTING.md. The deployment-state
      architecture companion is aligned where it previously claimed unchanged pass-through. No repository-wide architecture decision or capability-index addition.
- [x] 6.4 **Narrative compression.** Shorten completed-task notes to results, validation
      evidence, and destinations; the Section 1 record and the Section 3.3 finding stay
      in `design.md` "Implementation findings".
      — Completed task instructions and checkboxes preserved; completion notes shortened to
      final behavior and material evidence. Detailed implementation evidence, fresh-context findings and review rationale moved into design.md, Implementation detail
      retained at closeout. The failing-set and typed-field findings remain in their
      existing design headings.
- [x] 6.5 **Roadmap currency.** No `docs/development/ROADMAP.md` goal owns this change; it
      sits under "Unblocking work — the local end-to-end stack" in the index. Record that
      nothing is owed.
      — No roadmap goal or gap is owned by this repair; ROADMAP.md stays unchanged. The owning
      campaign is Unblocking work — the local end-to-end stack.
- [x] 6.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md` under "Unblocking work — the local end-to-end stack"
      to its closeout state; the campaign's graph does not include this change and stays
      as it is. Record the disposition.
      — Continued the previous session's sole uncommitted edit, the in-closeout index row;
      rewrote its notes with evidence and waiver. No graph node exists for this repair;
      no dependency/status on another row changes. The index check passed in 6.10 and is repeated after archival.
- [x] 6.7 **Packaging.** `make check-packaging` passes, and
      `make check-architecture-change CHANGE=repair-helm-render-tests` reports no
      exception or override row this change owns.
      — Owner waived further validation on 2026-10-21. Packaging is not rerun; its latest
      recorded pass precedes the comment-only f6f091a83 commit (43-pre-closeout.triage.md; workflow record 66). No architecture exception/override in
      ARCHITECTURE.toml names this change; check-architecture-change is not rerun.
      Agent-skill consistency is checked by the archival document checks. Waived runs
      are not claimed as passes.
- [x] 6.8 **End-to-end pipeline.** Record the run of the end-to-end pipeline on the final
      commit and its result, and `make validate-helm`'s record: `test-render` passing,
      the Helm version its log names, and the Helm scenarios `contracts` and
      `e2e_alkahest_escrow_codecs` (Section 4.6). The docker-compose lanes deploy no
      chart and exercise none of this change; say so. If either cannot run for a reason
      unrelated to this change, record the blocker and its owning change and treat what
      it gates as unrun.
      — Last complete passing validation: ca8f5f309, pipeline 39623742125 (30-validation.md),
      all three lanes passed. Latest pipeline: 39634190724 at 2d3fb01f2
      (40-validation.md), VM failed; other lanes passed. Triage 40 identifies duplicate
      root settlement registration, owned by unbacked-bare-metal-listings. Final
      comment-fix commit f6f091a83 passed make validate-helm (existing helm/1 summary:
      test-render on v4.3.0+gbec5b06, deploy-local, contracts and
      e2e_alkahest_escrow_codecs). That run has no separate NN-validation.md; its
      summary and workflow record 66 are the evidence. Eleven compose-only scenarios
      remain unrun against Helm. Compose deploys no chart; null removal is covered by
      render tests. The owner explicitly waived all further validation for closeout; no
      pipeline run at the final code commit or closeout commit is claimed.
- [x] 6.9 **Promotion.** Write the permanent documents below and complete the design
      promotion record:
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through
        configuration": a `null` always means removal, at any depth of an agent, whatever
        the Helm release's merge does; a removed key the chart derives takes the
        release's value; removing every agent is refused, and `storefront.enabled: false`
        runs none; a key the schema refuses stays refused as `null`; the supported Helm is
        the release `.github/workflows/tests.yml` pins, without repeating its number.
        Correct the section's "Helm cannot remove a subchart's default from a parent's
        values": Helm removes a parent's `null` only for a key the subchart's own
        defaults define, so the storefront subchart still ships no agent, and the
        chart removes the rest itself.
      - `docs/development/TESTING.md`, "Chart Render Tests": replace "rely on the pinned
        Helm of the release environment" with the release `tests.yml` pins, which is the
        supported one, and say `test-render.sh` prints the Helm it runs, without claiming
        a render result is evidence only on that release (D4); in its "A values schema
        generated from typed models" paragraph, that the generated definition accepts
        `null` wherever it accepts a key and a refused key stays refused.
      - `openspec/specs/deployment-state/spec.md`: written by the archive in 6.11, from
        this change's delta.
      — Promoted D2–D5 to DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration
      and TESTING.md#chart-render-tests. Aligned deployment-state/architecture.md#settlement-configuration-cutover and the operator guide's
      bare-metal paragraph with null removal. The existing permanent requirement lacks
      the removal text, so archival merges the delta once. Permanent destinations and
      waiver are recorded in design.md and below.
- [x] 6.10 **Documentation citations.** `make check-doc-citations
      CHANGE=repair-helm-render-tests` passes, then
      `openspec validate repair-helm-render-tests --strict`.
      — make check-change CHANGE=repair-helm-render-tests passed all six static checks:
      comment hygiene, agent skills, documentation citations, task list, change index,
      and the pinned OpenSpec 1.14.0 strict validator, both before and after archival.
      Post-archive validation covered all permanent specs. New citations and Markdown
      links in the promoted permanent documents were also checked and resolve.
- [x] 6.11 **Archival.** `openspec archive repair-helm-render-tests -y`, which merges the
      `deployment-state` delta into `openspec/specs/deployment-state/spec.md`; the row in
      `openspec/changes/README.md` then links the archive directory. Commit.
      — Archived 2026-10-21 with OpenSpec 1.14.0 from the installed pinned package.
      One modified deployment-state requirement merged; it exactly matches the delta,
      occurs once, and no other requirement changed. The incomplete-task warning was
      this archival task itself. Reviews moved with the change and remain local.
      The index links the archive and stays in closeout for the closeout review.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1: under Helm 4.3.0 a parent's `null` survives for a key the subchart does not define | Not promoted; change history in `design.md` |
| D2, D5: agents keyed by name; a values-file `null` removes an agent, an agent's value, or a configuration key whatever the Helm release's merge did; an empty agent map is refused; a refused key stays refused as `null` | `openspec/specs/deployment-state/spec.md#requirement-a-storefront-chart-passes-service-configuration-through`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration`; `openspec/specs/deployment-state/architecture.md#settlement-configuration-cutover` |
| D2: the generator accepts `null` wherever it accepts a key | `docs/development/TESTING.md`, "Chart Render Tests" ("A values schema generated from typed models") |
| D3: CI pins Helm v4.3.0 | `docs/development/TESTING.md`, "Chart Render Tests"; `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through configuration" |
| D4: the supported Helm is the release CI pins, and every render run names its Helm | `docs/development/TESTING.md`, "Chart Render Tests" |
| Roadmap currency | No goal/gap impact; `docs/development/ROADMAP.md` unchanged (6.5) |
| Campaign index currency | `openspec/changes/README.md#unblocking-work--the-local-end-to-end-stack`; row stays `in closeout` pending closeout review and archive cleanup; graph unchanged (6.6) |
