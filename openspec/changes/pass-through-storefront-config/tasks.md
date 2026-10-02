# Tasks — pass storefront configuration through the chart

Design settled in review; see `design.md` decisions 1–10. These tasks are section-level;
the planning pass names every file and suite.

## 1. Encoder gate and inventory

- [x] 1.1 **Decision gate.** Rendered integer, large-integer, float, boolean,
      nested-table, and array-of-tables values through `toToml` and `toYaml` with
      `helm template`. `toToml` writes whole numbers as floats, which the strict
      settlement models refuse; the chart renders `storefront.yaml` with `toYaml`.
      Evidence and the loader consequences are in `design.md` decision 2.
- [ ] 1.2 Compare every default `storefront.agentConfigToml` supplies with the typed
      model's default for the same setting, and record each difference and its
      disposition in `design.md` before removing any.
- [ ] 1.3 Inventory every producer and consumer of storefront chart values in this
      repository — `helm/values.yaml`, the subchart's `values.yaml`, `helm/fixtures/`,
      `helm/templates/tests/test-config.yaml`, workflows, scripts, and documentation —
      and verify `design.md` decision 6's mapping against it.

## 2. Loader

- [ ] 2.1 Add `storefront.yaml` to `kit/config`'s storefront discovery between
      `storefront.toml` and `storefront.secrets.toml`, and read each file by its suffix,
      YAML with the parser Dynaconf uses (`design.md` decision 2).
- [ ] 2.2 Make `market-storefront config show` report the merged layers when any
      layer exists, rather than requiring `storefront.toml`.

## 3. Chart

- [ ] 3.1 Replace `storefront.agentConfigToml` with a pass-through of the agent's
      `config` rendered as `storefront.yaml`, plus decision 3's derived values, and
      mount it at `/etc/arkhai/storefront.yaml`.
- [ ] 3.2 Add the agent-level `internalRegistryTrust`, written under the derived
      internal registry URL (decision 3).
- [ ] 3.3 Keep decision 4's release checks; remove every single-service check and
      every service default.
- [ ] 3.4 Reduce the agent's `identity` value to the credential Secret reference; its
      public principals move into `config.Identity`. Move `configMapName` from
      `config` to the agent.
- [ ] 3.5 Read `Settlement` and `Chains` for `wait-for-rpc`; render `wait-for-registry`
      only when the agent uses the internal registry.
- [ ] 3.6 Key the overlay helper's `[registry.auth]` by the effective first registry
      URL and stop rendering `[integrations]` (decision 7).
- [ ] 3.7 Move `helm/templates/tests/test-config.yaml` to the new values shape.

## 4. Schema and values

- [ ] 4.1 Make an agent's `config` an open object in both schemas, remove the
      settlement, Stripe, Alkahest, pricing, wallet, chains, and storefront-domains
      definitions, and add the retired-key refusal (`design.md` decision 5).
- [ ] 4.2 Remove `helm/scripts/check-settlement-schema-drift.py` and its call from
      `helm/scripts/test-render.sh`.
- [ ] 4.3 Move `helm/values.yaml`, `helm/charts/storefront/values.yaml`, and every
      fixture to the new shape; the umbrella values omit `db_path`. Fixtures and
      assertions that exist only to show the chart refusing an invalid or
      secret-bearing service configuration are removed; the service's own tests own
      those refusals.
- [ ] 4.4 Bump the storefront chart's and the umbrella chart's versions.

## 5. Validation

- [ ] 5.1 **Render tests.** A section the chart has never heard of renders intact;
      integer, large-integer, and float values survive; each derived value appears
      when absent and yields to a stated one; the port is always the agent's; each
      retained release check refuses its disagreement; a retired key is refused; the
      init containers follow the configuration; one rendered `storefront.yaml` is
      parsed with the storefront's own loader.
- [ ] 5.2 **Service tests.** The storefront merges `storefront.toml`,
      `storefront.yaml`, and `storefront.secrets.toml` in that order; `config show`
      reports the merged layers with no `storefront.toml`.
- [ ] 5.3 **Deployed.** A release rendered from `helm/values.yaml` starts the storefront
      with the same effective configuration as before, compared through
      `market-storefront config show`, apart from the intended differences in
      `design.md`'s risks and task 1.2's record.

## 6. Documentation

- [ ] 6.1 Add the pass-through and configuration-layer requirements and modify
      "Generated configuration has one source of truth" and "Identity configuration
      separates public and secret material" in
      `openspec/specs/deployment-state/spec.md`.
- [ ] 6.2 Update `docs/development/DEPLOYMENT_AND_CONFIG.md`'s Kubernetes section with
      how the storefront chart applies the pattern, what it derives, the
      `storefront.yaml` layer, large integers as strings, and that an agent's `config`
      is public with secret-marked settings in the Secret overlay; update its
      combined-storefront section for the new values shape.
- [ ] 6.3 Remove the Helm-fragment claim from `docs/development/ARCHITECTURE.md`'s
      settlement-configuration paragraph, from
      `openspec/specs/deployment-state/architecture.md`, and from
      `openspec/specs/settlement-configuration/architecture.md`.
- [ ] 6.4 Move `docs/development/VALIDATION_RUNBOOK.md`'s storefront values to the new
      shape.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match.
- [ ] 7.2 **Import placement.** Review imports this change added or touched in the
      loader, and migrate function-level ones to module level where no genuine
      circular import or documented lazy-load reason exists.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [ ] 7.4 **Narrative compression.** Shorten completed-task notes to final behaviour;
      the gate's evidence and the defaults comparison stay in `design.md`.
- [ ] 7.5 **Roadmap currency.** No roadmap goal owns this change; record that
      disposition. The roadmap is unaffected.
- [ ] 7.6 **Campaign index currency.** Update this change's row and the Goal 6
      campaign graph in `openspec/changes/README.md`, and
      `compose-contact-exchange-across-compute`'s blocker.
- [ ] 7.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=pass-through-storefront-config` and resolve every
      match.
- [ ] 7.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record
      the run. Record separately the Helm deployment verification from 5.3, since the
      pipeline lanes run on Compose.
- [ ] 7.9 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports.
- [ ] 7.10 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A storefront chart passes service configuration through and derives only release-known values where absent | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| A value keyed by a release-created name is chart-level and checked against the release | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Chart checks relate release parts; service configuration is validated only by the service, at startup | `openspec/specs/deployment-state/spec.md` |
| Pass-through configuration is public; secret-marked settings belong in the Secret overlay | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| The storefront reads `storefront.toml`, `storefront.yaml`, then `storefront.secrets.toml` | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Helm values schemas carry no service-configuration fragments | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`; `openspec/specs/deployment-state/architecture.md`; `openspec/specs/settlement-configuration/architecture.md` |
| The storefront stays on its own loader | Not promoted; change history in `design.md` decision 10 |
| Roadmap currency | None owed |
| Campaign index currency | `openspec/changes/README.md` |
