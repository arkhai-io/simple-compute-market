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
      generator. Secret-marked and non-seller fields become `false` under an any-case
      name pattern; references are inlined, a recursive one becoming `{}`; `Settlement`
      is closed to the registered mechanisms.
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
      `arkhai.storefrontConfigSection` (`helm/templates/_helpers.tpl`) and follows the
      agent's registry.

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

- [x] 6.1 **Render tests.** `helm/charts/storefront/tests/test_render.py` (17 tests,
      each seen to fail against a broken template where it guards a template line) and
      the reworked `helm/scripts/test-render.sh`. These are static render checks, not
      integration tests. The stale compute filter ID assertion in `design.md`
      finding 4 was corrected during deployed validation. The loader-backed test runs
      when the storefront environment exists and reports a skip otherwise, so no CI
      job runs it; a CI job that runs `make test`, `make build-dev`, and Helm
      validation together is out of scope (`design.md` finding 9).
- [x] 6.2 **Service tests.** `_build_settings()` reads a rendered `storefront.json`
      under the Secret overlay (`tests/unit/test_config_loader.py`). kit/config 140
      passed; VM storefront unit 1078 passed,
      1 skipped; VM storefront integration 338 passed (CI's two deselections);
      API-credits storefront 96 passed (its unit and integration tests together).
- [x] 6.3 **Deployed.** On a local Docker Desktop Kubernetes cluster,
      `make -C helm deploy` brought up the default release with rebuilt images.
      The deployed `market-storefront config show` agreed with the mounted
      `storefront.json` for agent ID, port, base URL, registry URL, identity,
      settlement, and chain settings. A clean release with an Alkahest local
      values overlay passed `make -C helm test-module MODULE=e2e-tests`:
      32 passed, 377 deselected (evidence bundle `helm-local-20261002-183115`).
      The E2E image was rebuilt with `make -C e2e-tests build`. The default
      deployment exposed bare EIP-191 identifiers in provisioning's YAML profile;
      its ConfigMap now uses JSON syntax to preserve string types (`design.md`
      finding 1). The E2E scenario now reads the active profile's registry URL,
      allowing the same suite to run in Kubernetes (finding 8). Earlier offline
      comparison evidence: the default release and the fiat and EVM fixtures,
      rendered by the original and the new chart and loaded with the storefront's
      Dynaconf settings, differ only in `auto_register` (no longer rendered),
      `db_path` (`./agent.db` → `/var/lib/arkhai/agent.db`), and the fixtures'
      corrected `agent_id`.

## 7. Documentation

- [ ] 7.1 Add the pass-through and configuration-layer requirements and narrow
      "Generated configuration has one source of truth" in
      `openspec/specs/deployment-state/spec.md`.
- [ ] 7.2 Update `docs/development/DEPLOYMENT_AND_CONFIG.md`'s Kubernetes section with
      how the storefront chart applies the pattern, what it derives, the
      `storefront.json` layer, large integers as strings, and the generated schema's
      refusal of secret-marked settings, which belong in the Secret overlay; update its
      combined-storefront section for the new values shape and remove the
      image/configuration schema check from its cutover sequence.
- [ ] 7.3 Replace the Helm-fragment claim in `docs/development/ARCHITECTURE.md`'s
      settlement-configuration paragraph, `openspec/specs/deployment-state/architecture.md`,
      and `openspec/specs/settlement-configuration/architecture.md` with what the
      generated fragment covers.
- [ ] 7.4 Name the generated-schema drift test in `docs/development/TESTING.md`'s chart
      render test section.
- [ ] 7.5 Move `docs/development/VALIDATION_RUNBOOK.md`'s storefront values to the new
      shape.

## 8. Closeout

- [x] 8.1 **Comment hygiene.** `make check-comment-hygiene` passes. Two production
      comments cite `openspec/specs/deployment-state/spec.md` headings that promotion
      (8.10) creates or narrows; they resolve once it lands.
- [x] 8.2 **Import placement.** Every import this change added is at module level.
- [ ] 8.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour;
      the gate's evidence and the defaults comparison stay in `design.md`.
- [ ] 8.5 **Roadmap currency.** No roadmap goal owns this change; record that
      disposition. The roadmap is unaffected.
- [ ] 8.6 **Campaign index currency.** Update this change's row and the Goal 6
      campaign graph in `openspec/changes/README.md`, and
      `compose-contact-exchange-across-compute`'s blocker.
- [ ] 8.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=pass-through-storefront-config` and resolve every
      match.
- [x] 8.8 **End-to-end pipeline.** GitHub Actions run 37015527919 on
      `feat/pass-through-storefront-config`: the Compose VM lane passed 129 and the
      bare-metal lane 16. Recorded separately, the Helm deployment from 6.3 passed the
      E2E module with 32 tests. Re-run the pipeline on the final commit before
      archiving if code changes after these runs.
- [x] 8.9 **Packaging.** `make check-packaging` passes.
- [ ] 8.10 **Promotion.** Complete the design-promotion record below.

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
| Provisioning's YAML profile preserves EIP-191 principal strings through JSON syntax | `docs/development/DEPLOYMENT_AND_CONFIG.md#kubernetes-configmap-and-secret-mounting` |
| Roadmap currency | None owed |
| Campaign index currency | `openspec/changes/README.md` |
