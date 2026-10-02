# Tasks — pass storefront configuration through the chart

Design settled in review; see `design.md` decisions 1–10. These tasks are section-level;
the planning pass names every file and suite.

## 1. Encoder gate and inventory

- [x] 1.1 **Decision gate.** Rendered integer, large-integer, float, boolean,
      nested-table, array-of-tables, and address values through `toToml`, `toYaml`,
      and `toPrettyJson`. `toToml` writes whole numbers as floats; `toYaml` leaves a
      160-bit address bare, which the storefront's YAML loader reads as an integer.
      The chart renders `storefront.json` with `toPrettyJson`. Evidence in `design.md`
      decision 2.
- [x] 1.2 Chart defaults compared with the typed models. Every removed default equals
      the model's, except Stripe's `expected_api_version` (`"0.2.1"`) and
      `expected_schema_version` (`5`), which the models leave unset and the old schema
      required whenever Stripe was enabled; no valid configuration changes.
- [x] 1.3 Producers and consumers of storefront chart values: both `values.yaml` files,
      `helm/fixtures/`, `helm/templates/tests/test-config.yaml`,
      `helm/scripts/test-render.sh`, `helm/Makefile`, and
      `docs/development/VALIDATION_RUNBOOK.md`. No workflow or script sets storefront
      agent values. Decision 6's mapping covers every key they use.

## 2. Loader

- [x] 2.1 `kit/config/src/market_config/config_loader.py`: discovery reads
      `storefront.toml`, `storefront.json`, `storefront.secrets.toml`;
      `storefront_public_config_files()` names the public layers.
- [x] 2.2 `load_storefront_config()` merges with Dynaconf over the same files, with no
      environment loader and no packaged defaults, top-level keys in lowercase.
- [x] 2.3 `domains/vms/storefront/src/market_storefront/groups/config.py`: `config show`
      reports the merged layers when any exists; `--raw` prints each public layer under
      its path and never the overlay.

## 3. Generated values schema

- [x] 3.1 `domains/vms/storefront/src/market_storefront/utils/config.py`:
      `WalletConfigDeclaration` (`private_key` secret, section closed),
      `RegistryConfigDeclaration` (`auth` secret, section open), and
      `IdentityConfigDeclaration` (public keys only, closed at every level) beside
      their readers.
- [x] 3.2 `domains/vms/storefront/src/market_storefront/values_schema.py`: the
      generator. Every field is keyed by an any-case name pattern — secret-marked and
      non-seller fields as `false`, the rest with their schema; `required` is dropped;
      case-only name collisions are refused; references are inlined, a recursive one
      becoming `{}`; `Settlement` is closed to the registered mechanisms. Both values
      schemas refuse the retired `config` keys in any spelling.
- [x] 3.3 `Makefile`: `make helm-values-schema` regenerates both schemas in the
      storefront environment.
- [x] 3.4 `domains/vms/storefront/tests/unit/test_values_schema.py`: drift against both
      committed schemas, the generator's refusals, `Identity`'s closure, and the
      declaration accepting every operator-written `[Identity]` table shipped (nine).

## 4. Chart

- [x] 4.1 `helm/charts/storefront/templates/_helpers.tpl`:
      `storefront.agentConfigDocument` replaces `storefront.agentConfigToml`,
      `storefront.principalsToml`, and `storefront.tomlLiteral`;
      `templates/configmap.yaml` carries `storefront.json`; `templates/deployment.yaml`
      mounts it.
- [x] 4.2 `internalRegistryTrust` is written under the derived internal registry URL.
- [x] 4.3 Every key the chart reads or writes is matched in any spelling, and one key
      in two spellings is refused at any depth (`storefront.foldedKey`,
      `storefront.foldedMap`, `storefront.refuseFoldedDuplicates`); a stated port
      must be a number equal to the agent's. The schema-version check, single-service
      checks, and service defaults are gone. The umbrella smoke-test configuration
      reads keys the same way (`arkhai.storefrontConfigKey`).
- [x] 4.4 The agent's `identity` carries only `credentialSecret`; `configMapName` is
      read from the agent.
- [x] 4.5 `templates/deployment.yaml`: `wait-for-rpc` reads `Settlement` and `Chains`;
      `wait-for-registry` renders only for the internal registry.
- [x] 4.6 `storefront.agentSecretsToml` keys `[registry.auth]` by the effective first
      registry URL and renders no `[integrations]`.
- [x] 4.7 `helm/templates/tests/test-config.yaml` reads the new shape through
      `arkhai.storefrontConfigSection` (`helm/templates/_helpers.tpl`), follows the
      agent's registry, and renders its generated profile as JSON syntax so EIP-191
      principals stay strings (`design.md` finding 2).

## 5. Schema and values

- [x] 5.1 Both `values.schema.json` files: `config` is open, constrained by the
      generated `storefrontServiceConfig` and the retired-key refusal; a
      `storefrontIdentity` definition; the hand-written service definitions and their
      conditional rules removed.
- [x] 5.2 `helm/scripts/check-settlement-schema-drift.py` tombstoned and its call removed.
- [x] 5.3 Both `values.yaml` files and `helm/fixtures/{eip191-evm,fiat-ed25519,
      invalid-missing-identity-secret}-values.yaml` moved to the new shape; the fiat and
      EVM fixtures' `agent_id` corrected (`design.md` finding 3);
      `invalid-hosted-identity-v1-values.yaml` and
      `invalid-missing-hosted-capability-values.yaml` tombstoned.
- [x] 5.4 Storefront chart 0.2.0; umbrella chart 0.2.0 and its dependency pin.

## 6. Validation

- [x] 6.1 **Render tests** (static, not integration).
      `helm/charts/storefront/tests/test_render.py`, 19 tests, each seen to fail
      against a broken template line it guards, and `helm/scripts/test-render.sh`,
      now passing in full (`design.md` findings 2 and 4). The loader-backed test runs
      only where the storefront environment exists; no CI job runs it (finding 9,
      out of scope).
- [x] 6.2 **Service tests.** kit/config 140; VM storefront unit 1079 (1 skipped),
      including `_build_settings()` over a rendered `storefront.json` and the
      overlay; VM storefront integration 338 (CI's two deselections); API-credits
      storefront 96, unit and integration together.
- [x] 6.3 **Deployed.** Local Docker Desktop Kubernetes, default release via
      `make -C helm deploy`: the deployed `market-storefront config show` agreed with
      the mounted `storefront.json` (agent ID, port, base URL, registry, identity,
      settlement, chains). With an Alkahest local overlay,
      `make -C helm test-module MODULE=e2e-tests` passed 32, 377 deselected (bundle
      `helm-local-20261002-183115`). That run exposed findings 1 and 8, both fixed. It
      predates the `Identity` closure, key folding, and finding 2's fix; re-verify
      with 8.8. Offline before/after comparison of rendered documents: only
      `auto_register` (dropped), `db_path` (now under the persistence mount), and the
      fixtures' corrected `agent_id` differ.

## 7. Documentation

- [x] 7.1 `openspec/specs/deployment-state/spec.md`: "A storefront chart passes service
      configuration through" and "A storefront reads chart-rendered configuration
      between its file and its overlay" added; "Generated configuration has one
      source of truth" narrowed to the generated values-schema definition.
- [x] 7.2 `docs/development/DEPLOYMENT_AND_CONFIG.md`: a "Storefront agents:
      pass-through configuration" subsection of the Kubernetes section (layers,
      derived settings, release checks, the generated schema's refusals, retired
      keys, JSON rendering, large integers as strings); the combined-storefront
      section points at it; the cutover sequence drops the image/configuration
      schema check; the provisioning and smoke-test JSON encoding is stated.
- [x] 7.3 `docs/development/ARCHITECTURE.md`'s settlement-configuration paragraph,
      `openspec/specs/deployment-state/architecture.md`, and
      `openspec/specs/settlement-configuration/architecture.md` describe the
      generated definition instead of Helm schema fragments.
- [x] 7.4 `docs/development/TESTING.md`'s chart render test section names the
      drift test, the loader-backed check and its environment, and that no CI job
      runs that check.
- [x] 7.5 `docs/development/VALIDATION_RUNBOOK.md`: the real-provisioning upgrade
      sets `config.provisioning.mode`; the storefront overlay step writes
      `storefront.secrets.toml` directly, replacing a step that rendered the
      chart's Secret with keys the schema already refused.

## 8. Closeout

- [x] 8.1 **Comment hygiene.** `make check-comment-hygiene` passes; the two
      production comments citing `openspec/specs/deployment-state/spec.md` headings
      resolve after promotion.
- [x] 8.2 **Import placement.** Every import this change added is at module level.
- [x] 8.3 **Documentation compliance.** Change history, alternatives, gate evidence,
      and findings live in `design.md`; current-state behaviour is pending promotion
      to the destinations in the record below; production comments cite only
      permanent documents. Codex's provisioning-encoding sentence is already in
      `docs/development/DEPLOYMENT_AND_CONFIG.md` as current state.
- [x] 8.4 **Narrative compression.** Section 6 states results; the encoder gate,
      defaults comparison, and findings stay in `design.md`.
- [x] 8.5 **Roadmap currency.** No roadmap goal owns this change, and
      `docs/development/ROADMAP.md` does not describe the chart; nothing is owed.
- [x] 8.6 **Campaign index currency.** This change's row reads "complete …
      closeout review pending, not archived"; `compose-contact-exchange-across-compute`'s
      row, tasks, and proposal no longer call it blocked on this change; the Goal 6
      graph is unchanged.
      `compose-contact-exchange-across-compute`'s design and proposal now say what
      this baseline gives it: `[Delivery]` by values alone, `[Settlement.contact]`
      once the mechanism is registered and the values schema regenerated, with the
      generator extended for `kind`-dependent sinks. `add-full-stack-ci-job` is
      indexed as the owner of finding 9.
- [x] 8.7 **Documentation citations.**
      `make check-doc-citations CHANGE=pass-through-storefront-config` passes.
- [x] 8.8 **End-to-end pipeline.** Actions run 37040193730 on
      `feat/pass-through-storefront-config` at `d8a6c8d2`: Compose VM lane 129
      passed, bare-metal lane 16 passed; both lanes run the storefront's new
      configuration discovery. Earlier: run 37015527919 (129 and 16), and the Helm
      E2E module, 32 (6.3). The Compose lanes do not render the chart; the Helm
      module run predates the `Identity` closure, key folding, and the any-case
      schema, which the render tests cover.
- [x] 8.9 **Packaging.** `make check-packaging` passes.
- [x] 8.10 **Promotion.** Record below; the two production comments that cite
      `openspec/specs/deployment-state/spec.md` headings resolve.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A storefront chart passes service configuration through and derives only release-known values where absent | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| A value keyed by a release-created name is chart-level and checked against the release | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Chart checks relate release parts; service semantics are validated by the service at startup | `openspec/specs/deployment-state/spec.md` |
| A pass-through values schema is generated from typed models and keeps secrets and payer data out of ConfigMaps | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`; `openspec/specs/deployment-state/architecture.md`; `openspec/specs/settlement-configuration/architecture.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Generated-schema drift is a storefront unit test | `docs/development/TESTING.md` |
| The storefront reads `storefront.toml`, `storefront.json`, then `storefront.secrets.toml`, and reports what it loads | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| The storefront stays on its own loader | Not promoted; change history in `design.md` decision 10 |
| Keys match in any spelling, as the loader reads them, in chart reads and the generated schema; one key in two spellings is refused | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| `Identity` is declared closed to its public keys, so private identity material is refused before render | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/ARCHITECTURE.md` |
| The retired values shape is refused at render, naming the key | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Provisioning's YAML profile and the umbrella's generated smoke-test profile preserve EIP-191 principal strings through JSON syntax | `docs/development/DEPLOYMENT_AND_CONFIG.md#kubernetes-configmap-and-secret-mounting` |
| No CI job runs the chart-to-loader check (finding 9) | `docs/development/TESTING.md`; owned by `add-full-stack-ci-job`, indexed in `openspec/changes/README.md` |
| Roadmap currency | None owed |
| Campaign index currency | `openspec/changes/README.md` |
