# Tasks — pass storefront configuration through the chart

Design settled in review; see `design.md` decisions 1–7. These tasks are section-level;
the planning pass names every file and suite.

## 1. Encoder gate and inventory

- [ ] 1.1 **Decision gate.** Render integer, large-integer (`2592000` and above), float,
      boolean, nested-table, and array-of-tables values through `toToml` with
      `helm template` and record the output in `design.md`. If whole numbers render as
      integers, keep `storefront.toml`; otherwise render `storefront.yaml` with
      `toYaml` and add that name to `kit/config`'s storefront discovery between
      `storefront.toml` and `storefront.secrets.toml` (`design.md` decision 2).
- [ ] 1.2 Compare every default `storefront.agentConfigToml` supplies with the typed
      model's default for the same setting, and record each difference and its
      disposition in `design.md` before removing any.
- [ ] 1.3 Inventory every producer of storefront chart values in this repository —
      `helm/values.yaml`, the subchart's `values.yaml`, `helm/fixtures/`, workflows,
      and scripts — and write the retired-key mapping into `design.md`.

## 2. Chart

- [ ] 2.1 Replace `storefront.agentConfigToml` with a pass-through of the agent's
      `config` plus decision 3's derived values, set only where absent.
- [ ] 2.2 Keep decision 4's release checks; remove every single-service check and
      every service default.
- [ ] 2.3 Reduce the agent's `identity` value to the credential Secret reference; its
      public principals move into `config.Identity`.
- [ ] 2.4 Leave `storefront.secrets.toml` and the `wait-for-rpc` init container
      unchanged.

## 3. Schema and values

- [ ] 3.1 Make an agent's `config` an open object in both schemas, remove the
      settlement, Stripe, Alkahest, pricing, wallet, and chains definitions, and add
      the retired-key refusal (`design.md` decision 5).
- [ ] 3.2 Remove `helm/scripts/check-settlement-schema-drift.py` and its call from
      `helm/scripts/test-render.sh`.
- [ ] 3.3 Move `helm/values.yaml`, `helm/charts/storefront/values.yaml`, and every
      fixture to the new shape. Fixtures that exist only to show the chart refusing an
      invalid service configuration are removed; the service's own tests own those
      refusals.
- [ ] 3.4 Bump the storefront chart's and the umbrella chart's versions.

## 4. Validation

- [ ] 4.1 **Render tests.** A section the chart has never heard of renders intact;
      integer, large-integer, and float values survive; each derived value appears
      when absent and yields to a stated one; each retained release check refuses its
      disagreement; a retired key is refused; the ConfigMap still carries no secret
      value.
- [ ] 4.2 **Service tests.** If the loader gained a file name: the storefront merges
      `storefront.toml`, `storefront.yaml`, and `storefront.secrets.toml` in that order.
- [ ] 4.3 **Deployed.** A release rendered from `helm/values.yaml` starts the storefront
      with the same effective configuration as before, compared through
      `market-storefront config show`.

## 5. Documentation

- [ ] 5.1 Add the pass-through requirement and modify "Generated configuration has
      one source of truth" in `openspec/specs/deployment-state/spec.md`.
- [ ] 5.2 Update `docs/development/DEPLOYMENT_AND_CONFIG.md`'s Kubernetes section with
      how the storefront chart applies the pattern and what it derives, and its
      combined-storefront section for the new values shape.
- [ ] 5.3 Remove the Helm-fragment claim from `docs/development/ARCHITECTURE.md`'s
      settlement-configuration paragraph and from
      `openspec/specs/settlement-configuration/architecture.md`.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match.
- [ ] 6.2 **Import placement.** Review imports this change added or touched, if the
      loader changed, and migrate function-level ones to module level where no genuine
      circular import or documented lazy-load reason exists.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final behaviour;
      the gate's evidence and the defaults comparison stay in `design.md`.
- [ ] 6.5 **Roadmap currency.** No roadmap goal owns this change; record that
      disposition. The roadmap is unaffected.
- [ ] 6.6 **Campaign index currency.** Update this change's row and the Goal 6
      campaign graph in `openspec/changes/README.md`, and
      `compose-contact-exchange-across-compute`'s blocker.
- [ ] 6.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=pass-through-storefront-config` and resolve every
      match.
- [ ] 6.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record
      the run. Record separately the Helm deployment verification from 4.3, since the
      pipeline lanes run on Compose.
- [ ] 6.9 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports.
- [ ] 6.10 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A storefront chart passes service configuration through and derives only release-known values where absent | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Chart checks relate release parts; service configuration is validated only by the service | `openspec/specs/deployment-state/spec.md` |
| Helm values schemas carry no service-configuration fragments | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`; `openspec/specs/settlement-configuration/architecture.md` |
| Roadmap currency | None owed |
| Campaign index currency | `openspec/changes/README.md` |
