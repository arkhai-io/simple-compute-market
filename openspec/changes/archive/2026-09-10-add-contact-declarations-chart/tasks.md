# Tasks

## Implementation and evidence

- [x] Update `helm/charts/bare-metal-storefront/values.yaml` with the default-null hook.
- [x] Update `helm/charts/bare-metal-storefront/values.schema.json` with reused
  reference shape, mode exclusion and existing publication safety conditions.
- [x] Update `helm/charts/bare-metal-storefront/templates/deployment.yaml` to share
  publication selection while preserving historical output bytes.
- [x] Add `scripts/tests/test_contact_declarations_chart.py` for reference, mount,
  mode, privacy, delivery and default-off render checks.
- [x] Add `domains/bare_metal/storefront/tests/test_contact_declarations_chart_startup.py`
  for rendered configuration through installed startup, actual general/v1/v2
  loaders, invalid input and mixed-path refusal with deterministic local fixtures.
- [x] Compare complete historical renders against exact pre-amendment source for
  physical, runtime-only, legacy publication and delivery/storage permutations.
- [x] Run the complete owning chart and contact Secret suites plus contact-only,
  app-composition and delivery publication startup regressions. Record exact commands,
  failed/unrun checks, chart/render hashes and wheel/source/imported-file parity.
- [x] Validate this change with strict OpenSpec and check the complete diff.
- [x] Constrain the general hook's `configMap` and `registry.apiKeySecret` to valid
  Kubernetes object names and data keys, reusing the existing strict reference
  definition without changing historical `contactOffers` or delivery acceptance.
- [x] Extend `scripts/tests/test_contact_declarations_chart.py` with schema and Helm
  render refusal for malformed general names/keys, length and character boundaries,
  valid references reaching the rendered manifest, and the retained historical
  acceptance of the same malformed values under `contactOffers`.
- [x] Exclude the Kubernetes reserved data keys `.` and any `..` prefix from the
  general hook's two references with an overlay on the shared reference definition,
  leaving `contactOffers`, delivery and other references at their existing checks.
- [x] Cover reserved keys in both directions: schema and Helm refusal on the general
  hook, retained acceptance under `contactOffers` and `deliveryConfigSecret`, and
  leading-dot and embedded-double-dot keys still reaching the rendered manifest.

## Local validation

- Combined chart, Secret, installed-startup, contact-only, physical publication,
  package/import and existing contact-publication suites: 158 passed; two upstream
  websocket deprecation warnings, no skips.
- Twenty complete historical render-byte comparisons match pre-amendment source.
- Ninety-four packaged files across the bare-metal domain/storefront, contact kit
  and storefront core match committed source, qualified wheels and installed files.
  All 22 qualified wheel hashes remain unchanged; no wheels were rebuilt.
- Chart render target, Helm lint, comment hygiene, diff whitespace checks and this
  change's strict OpenSpec validation pass. Repository-wide strict OpenSpec reports
  the same 12 unrelated failures as the pre-amendment snapshot.
- Registry-dependent regressions run the candidate registry application from source
  with installed wheel dependencies and disposable signed loopback fixtures.
- Permanent configuration, owning specification and architecture are promoted.
  Post-promotion focused tests, render/packaged-source parity, hygiene and scoped
  validation pass. Full storefront/system suites, static typing and release/deployment
  checks were not rerun; there are no production Python changes or activation claims.

## Closeout after independent review

- [x] Comment hygiene: `make check-comment-hygiene` passes; touched comments describe
  current invariants and deterministic fixtures.
- [x] Import placement: new imports are module-level; actual focused tests pass.
- [x] Documentation compliance: accepted behavior and rationale are promoted to the
  configuration guide and owning specification/architecture after independent review.
- [x] Narrative compression: retained final behavior, evidence, limits and destinations.
- [x] Roadmap currency: no goal or gap mapping changed; the existing general-publication
  state and separate image/deployment gaps remain accurate.
- [x] Campaign index currency: amendment status and archive link are reconciled in
  `openspec/changes/README.md`; historical completed tasks are preserved.
- [x] Promotion: `storefront-publication/spec.md`, companion `architecture.md` and
  `DEPLOYMENT_AND_CONFIG.md` contain the reviewed hook and compatibility contract.
  Owning-spec validation and citation checks passed; the design records destinations.
