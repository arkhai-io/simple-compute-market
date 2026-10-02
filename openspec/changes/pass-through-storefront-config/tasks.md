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
      `storefront.toml` and `storefront.secrets.toml` (`design.md` decision 2).
- [ ] 2.2 Build the reporting view behind `config show` and `config get` with Dynaconf
      over the same files, without packaged defaults, top-level keys in lowercase.
- [ ] 2.3 Make `config show` report the merged layers when any layer exists, and
      `config show --raw` print each public layer present under its path, never the
      Secret overlay.

## 3. Generated values schema

- [ ] 3.1 Declare `[Wallet]` (`address`, `ssh_public_key`, `private_key` secret) and
      `[registry]`'s `auth` (secret) with the secret marker in typed models beside
      their readers, changing no accepted value (`design.md` decision 8).
- [ ] 3.2 Add the generator to the VM storefront: emit the JSON Schema of each seller
      settlement registration's model, `Identity.principal`, and the declarations;
      inline references; replace secret-marked and non-seller fields with `false`;
      nest each at its path under both top-level spellings; close `Settlement` to the
      registered mechanisms; write one generated definition into each values schema.
- [ ] 3.3 Add a make target that regenerates both values schemas.
- [ ] 3.4 Add the VM storefront unit test that regenerates the fragment in memory and
      fails when either committed schema differs.

## 4. Chart

- [ ] 4.1 Replace `storefront.agentConfigToml` with a pass-through of the agent's
      `config` rendered as `storefront.yaml`, plus decision 3's derived values, and
      mount it at `/etc/arkhai/storefront.yaml`.
- [ ] 4.2 Add the agent-level `internalRegistryTrust`, written under the derived
      internal registry URL (decision 3).
- [ ] 4.3 Keep decision 4's release checks, reading top-level sections in either
      spelling and refusing both; remove the image/configuration schema-version check,
      every single-service check, and every service default.
- [ ] 4.4 Reduce the agent's `identity` value to the credential Secret reference; its
      public principals move into `config.Identity`. Move `configMapName` from
      `config` to the agent.
- [ ] 4.5 Read `Settlement` and `Chains` for `wait-for-rpc`; render `wait-for-registry`
      only when the agent uses the internal registry.
- [ ] 4.6 Key the overlay helper's `[registry.auth]` by the effective first registry
      URL and stop rendering `[integrations]` (decision 7).
- [ ] 4.7 Move `helm/templates/tests/test-config.yaml` to the new values shape.

## 5. Schema and values

- [ ] 5.1 Make an agent's `config` an open object in both schemas constrained by the
      generated definition, remove the hand-written settlement, Stripe, Alkahest,
      pricing, wallet, chains, and storefront-domains definitions and their
      conditional rules, and add the retired-key refusal (`design.md` decision 5).
- [ ] 5.2 Remove `helm/scripts/check-settlement-schema-drift.py` and its call from
      `helm/scripts/test-render.sh`.
- [ ] 5.3 Move `helm/values.yaml`, `helm/charts/storefront/values.yaml`, and every
      fixture to the new shape; the umbrella values omit `db_path` and
      `image.settlementConfigSchemaVersion`. Fixtures and assertions that exist only
      to show the chart refusing a semantically invalid service configuration are
      removed; the service's own tests own those refusals.
- [ ] 5.4 Bump the storefront chart's and the umbrella chart's versions.

## 6. Validation

- [ ] 6.1 **Render tests.** A section the chart has never heard of renders intact;
      integer, large-integer, and float values survive; each derived value appears
      when absent and yields to a stated one; the port is always the agent's; each
      retained release check refuses its disagreement; both spellings of a section are
      refused; a retired key is refused; a secret-marked field, a hosted payer field,
      and an unknown field in a typed section are each refused naming the field; the
      init containers follow the configuration; one rendered `storefront.yaml` is
      parsed with the storefront's own loader.
- [ ] 6.2 **Service tests.** The storefront merges `storefront.toml`,
      `storefront.yaml`, and `storefront.secrets.toml` in that order; `config show`
      reports the merged layers with no `storefront.toml` and merges differently
      spelled sections as the server does; `config show --raw` omits the overlay; the
      `[Wallet]` and `[registry]` declarations accept every value accepted before.
- [ ] 6.3 **Deployed.** A release rendered from `helm/values.yaml` starts the storefront
      with the same effective configuration as before, compared through
      `market-storefront config show`, apart from the intended differences in
      `design.md`'s risks and task 1.2's record.

## 7. Documentation

- [ ] 7.1 Add the pass-through and configuration-layer requirements and narrow
      "Generated configuration has one source of truth" in
      `openspec/specs/deployment-state/spec.md`.
- [ ] 7.2 Update `docs/development/DEPLOYMENT_AND_CONFIG.md`'s Kubernetes section with
      how the storefront chart applies the pattern, what it derives, the
      `storefront.yaml` layer, large integers as strings, and the generated schema's
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

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match.
- [ ] 8.2 **Import placement.** Review imports this change added or touched in the
      loader, the declarations, and the generator, and migrate function-level ones to
      module level where no genuine circular import or documented lazy-load reason
      exists.
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
- [ ] 8.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record
      the run. Record separately the Helm deployment verification from 6.3, since the
      pipeline lanes run on Compose.
- [ ] 8.9 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports.
- [ ] 8.10 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A storefront chart passes service configuration through and derives only release-known values where absent | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| A value keyed by a release-created name is chart-level and checked against the release | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Chart checks relate release parts; service semantics are validated by the service at startup | `openspec/specs/deployment-state/spec.md` |
| A pass-through values schema is generated from typed models and keeps secrets and payer data out of ConfigMaps | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`; `openspec/specs/deployment-state/architecture.md`; `openspec/specs/settlement-configuration/architecture.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Generated-schema drift is a storefront unit test | `docs/development/TESTING.md` |
| The storefront reads `storefront.toml`, `storefront.yaml`, then `storefront.secrets.toml`, and reports what it loads | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| The storefront stays on its own loader | Not promoted; change history in `design.md` decision 10 |
| Roadmap currency | None owed |
| Campaign index currency | `openspec/changes/README.md` |
