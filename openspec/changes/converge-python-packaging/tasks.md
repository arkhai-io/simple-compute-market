# Tasks — converge Python packaging

Design: `design.md` (D1–D16). Two slices, each ending in its own closeout. Slice 1 makes
every environment, image, and lock go through one script and adds the packaging checks;
slice 2 moves the six nested-import projects to the flat `src/` layout and publishes them
under new versions.

**Validation that cannot run in the implementation sandbox.** Docker image builds, the
end-to-end pipeline, and any relock or `reinit` of a project that declares the PyTorch
index (`kit/policy`, `domains/vms/buyer`, `domains/vms/storefront`) need a Docker daemon
or `download.pytorch.org`. Where either is unavailable, the step is handed off with the
exact command to run, and every validation it gates is recorded as unrun rather than
passed.

## Slice 1 — one way to build an environment

### 1. Converge the outlier images (D5)

Each image moves to the convention the other lock-based images already follow: copy
`pyproject.toml` and `uv.lock`, sync dependencies from the lock with
`--no-dev --no-install-project`, then install the image's own wheel from `.dist` with
`--no-deps`. The interim sync uses the prevailing refresh-list and registry-rewrite form;
section 3 replaces it in all images at once.

- [x] 1.1 `domains/bare_metal/storefront/Dockerfile`: replace the unlocked
      `uv pip install arkhai-bare-metal-storefront==0.6.0` with lock sync plus own-wheel
      install under a uv cache mount.
- [x] 1.2 `domains/apicredits/sample-app/Dockerfile`: replace the wheel install of the
      application and middleware with lock sync plus own-wheel install.
- [x] 1.3 `provisioning/compute/service/Dockerfile`: lock sync with `--extra adapters`,
      then the service's own wheel; the two adapter wheel installs are dropped.
      `provisioning/compute/service/Dockerfile.dockerignore` admits the project's
      `pyproject.toml` and `uv.lock`.
- [ ] 1.4 Validate: build the three images (`Makefile` targets building
      `domains/bare_metal/storefront/Dockerfile` and
      `domains/apicredits/sample-app/Dockerfile`; `make -C provisioning/compute/service
      build-image`), run each image's existing import smoke check, and compare
      `uv pip freeze` inside each image before and after. Only the bare-metal storefront's
      third-party versions may differ, now matching its lock.

### 2. One Python version (D8)

      Note: 2.6 complete: `core/buyer`, `kit/storefront`, and `core/registry` (whose
      `test-unit` has no `reinit`) each created a fresh 3.13 environment and passed (125, 8,
      104). 2.5 also covers `publish-pypi.yml` (`publish`) and `validate-model-release.yml`
      (`validate`), which run `uv build` and were found by `check-python-version`. 2.6 so far:
      every Makefile resolves `UV_PYTHON` to 3.13, and the suites in 3.7 ran on 3.13.
- [x] 2.1 Add `.python-version` holding `3.13`.
- [x] 2.2 Dockerfiles declare `ARG PYTHON_VERSION=3.13` and use it in every `FROM`:
      `domains/vms/storefront/Dockerfile` (two stages), `domains/apicredits/storefront/
      Dockerfile` (two stages), `domains/bare_metal/storefront/Dockerfile`,
      `provisioning/compute/service/Dockerfile` (default 3.12 → 3.13). The four already
      on `ARG PYTHON_VERSION=3.13` are unchanged.
- [x] 2.3 Every Makefile in Appendix D exports `UV_PYTHON` read from the root
      `.python-version` by relative path, and loses every `--python` flag and every
      `PYTHON_VERSION` variable used only to choose a sync or run interpreter — today in
      `core/buyer`, `core/registry`, `core/storefront`, `domains/apicredits/buyer`,
      `domains/apicredits/sample-app`, `domains/vms/buyer`,
      `domains/vms/provisioning/adapter`, `e2e-tests`, `kit/capability-shape`,
      `kit/config`, `kit/contact-exchange`, `kit/delivery`, `kit/fulfillment`,
      `kit/hosted-settlement`, `kit/negotiation-runtime`, `kit/settlement-runtime`,
      `kit/site-client`, and `kit/storefront`.
- [x] 2.4 `REVIEW_PYTHON` defaults to the declaration in the root `Makefile` and
      `scripts/package-review-wheelhouse.sh`; `tools/issue-discovery/config/phases/
      local.yaml` (`buyer_sync`) and `docs/development/VALIDATION_RUNBOOK.md` stop naming
      3.12.
- [x] 2.5 CI jobs that run uv in a project set `UV_PYTHON` from `.python-version`:
      `.github/workflows/tests.yml`, `.github/workflows/release.yml`,
      `.github/workflows/hosted-stripe-test.yml`.
- [x] 2.6 Validate: `make reinit` then `make test` in `core/buyer`, `kit/storefront`, and
      `domains/vms/provisioning/adapter` (all formerly 3.12) creates a 3.13 environment
      and passes; deleting `.venv` in `core/registry` and running `make test-unit` (no
      `reinit` dependency) creates a 3.13 environment.

### 3. The shared script and its callers (D1–D4, D6, D7, D9)

      Notes: images keep the project at its repository depth below an image root (`/repo/<path>`;
      `e2e-tests` at `/app` with `/.dist`), because uv will not normalise a path above `/`.
      `--no-sources` is dropped from image syncs; it contradicts `--locked`. Relocking the ten
      projects that declared `find-links` removed duplicated wheel entries and nothing else.
      `lock` also upgrades every repository distribution a lock names (D7), which returned
      `arkhai-kit-config` 0.1.2 to `domains/bare_metal` and `domains/vms/domain` (they had
      installed 0.1.0 from PyPI, with the `web3` stack it pulled in) and `arkhai-kit-identity`
      to `domains/apicredits/middleware/python`, which gained a `reinit`; all three suites pass.
      Also changed: `e2e-tests/tests/unit/test_domain_stack_configuration.py` (the image pin
      test removed; the storefront test asserts `install-wheel`), `docs/development/TESTING.md`
      (review-lock reference), and compute-service `serve`/`worker`/`migrate` now pass
      `--find-links`.
- [x] 3.1 `scripts/uv_project.py` with `reinit`, `image -- <uv sync options>`,
      `install-wheel`, and `lock [--project DIR …]`, a `--project` option defaulting to
      the working directory, and `scripts/tests/test_uv_project.py` covering:
      derivation from canonical-wheelhouse, other-local-path (error), index, editable,
      and directory sources; name normalisation and de-duplication; each command's exact
      argument list, including `--python` from the declaration, the relative wheelhouse
      path, `--locked` for `image`, and `--no-index` for `install-wheel`; name and
      version from `pyproject.toml`; and a missing or unparseable lock or
      `pyproject.toml` exiting non-zero before any uv command runs.
- [x] 3.2 Makefiles: each `reinit` in Appendix C becomes one call to the script. `init`
      and `install` targets that run their own `uv sync` depend on `reinit` instead —
      `core/buyer`, `core/registry`, `core/storefront`, `domains/apicredits/buyer`,
      `domains/apicredits/sample-app`, `domains/apicredits/service` (`install`),
      `domains/apicredits/storefront`, `domains/bare_metal/storefront`,
      `domains/vms/buyer`, `domains/vms/storefront`, `e2e-tests`,
      `kit/capability-shape` (which gains a `reinit`), `kit/capacity-publication`,
      `kit/config`, `kit/contact-exchange`, `kit/delivery`, `kit/fulfillment`,
      `kit/hosted-settlement`, `kit/negotiation-runtime`, `kit/pool-overrides`,
      `kit/settlement-runtime`, `kit/site-client`, `kit/storefront`, and
      `provisioning/compute/service` (`install`). The syncs in the root `Makefile`,
      `domains/Makefile` (`test-storefront`), and the non-`init` syncs in
      `core/registry/Makefile`, `domains/vms/storefront/Makefile`, and
      `e2e-tests/Makefile` call the script with `--project`.
- [x] 3.3 Remove `[tool.uv] find-links` from `domains/apicredits/service`,
      `domains/bare_metal`, `domains/compute`, `domains/vms/domain`,
      `domains/vms/provisioning/adapter`, `kit/fulfillment`, `kit/resource-pools`,
      `kit/site`, `provisioning/compute`, and `provisioning/compute/service`
      `pyproject.toml`.
- [x] 3.4 Every Dockerfile that copies `.dist` installs through the script from a
      mirrored layout (`/repo/<project>` and `/repo/.dist`, `UV_PROJECT_ENVIRONMENT` at the
      runtime venv path), with `image -- …` for dependencies and `install-wheel` for the
      image's own distribution in the builder stage: `core/registry/Dockerfile`,
      `domains/apicredits/sample-app/Dockerfile`, `domains/apicredits/service/Dockerfile`,
      `domains/apicredits/storefront/Dockerfile` (its `--reinstall` step becomes
      `install-wheel`), `domains/bare_metal/storefront/Dockerfile`,
      `domains/vms/storefront/Dockerfile` (the runtime stage stops copying `.dist`, drops
      its second wheel install and unused cache mount, and keeps its smoke check),
      `e2e-tests/Dockerfile`, `provisioning/compute/service/Dockerfile`. Every `sed` lock
      rewrite, refresh list, and version literal goes. `domains/vms/storefront/
      Dockerfile.dockerignore` and `provisioning/compute/service/Dockerfile.dockerignore`
      admit `scripts/uv_project.py`. Tombstone `test_storefront_image_pins.py`.
- [x] 3.5 Root `Makefile`: a `lock` target depending on `dist`, relocking `$(PROJECTS)` or
      every project; `review-locks` delegates to it. Tombstone
      `refresh-review-locks.py` and repoint any caller (`scripts/
      package-review-wheelhouse.sh`, `scripts/tests/test_package_review_wheelhouse.py`).
- [x] 3.6 Validate derivation: for every project in Appendix C, compare the derived set
      with the list it replaced. The only differences are those `design.md` records:
      `domains/apicredits/service` gains `arkhai-kit-capability-shape`;
      `domains/vms/provisioning/adapter` gains `arkhai-compute` and
      `arkhai-kit-capability-shape`; `arkhai-hosted-settlement-client` leaves five
      targets; the project's own name leaves ten.
- [x] 3.7 Validate behavior (PyTorch-index projects handed off): rebuild `arkhai-kit-identity` at its current version with an
      added dependency, run `make reinit` in `kit/site`, which consumes it and declares no
      PyTorch index, and confirm the dependency is installed and recorded in the lock; restore
      the wheel. Run `make reinit` and the default suite in `core/registry-client`,
      `kit/site`, `domains/apicredits/service`, `domains/bare_metal/storefront`, and
      `e2e-tests` (unit tier). `make lock` relocks every project and, run twice, changes
      nothing the second time.
- [ ] 3.8 Validate images (handoff where Docker is unavailable): build all eight images,
      run their smoke checks, and run the end-to-end pipeline.

### 4. Checks (D12, D13)

- [x] 4.1 `scripts/check_uv_setup.py` with `scripts/tests/test_check_uv_setup.py`,
      replacing `check_reinit.py` and `test_check_reinit.py`
      (both tombstoned). Cases: the continued-help-comment rule line; a literal package
      flag anywhere in a `reinit` chain; a hand-written `uv sync` in `init`; a project
      with tests and wheelhouse packages but no `reinit`; a Dockerfile `sed` rewrite,
      refresh list, version literal, direct wheelhouse install, and a runtime stage
      copying `.dist`; the current tree passing.
- [x] 4.2 `scripts/check_locks.py` with `scripts/tests/test_check_locks.py`, replacing
      `check_internal_locks.py` (tombstoned). Cases: a lock failing
      `uv lock --check`; a superseded internal version; a same-version wheel that gained,
      and one that lost, an unconditional requirement; the same under an extra; a locked
      dependency version the wheel's specifier no longer admits; a repository distribution
      resolved from an index and from another local path; a non-canonical wheelhouse
      registry; a lock produced by uv for a wheel with platform-marked and extra-scoped
      requirements passing; no network access during any case.
- [x] 4.3 `scripts/check_python_version.py` with
      `scripts/tests/test_check_python_version.py`, covering each condition in D12's
      table and the current tree passing.
- [x] 4.4 Root `Makefile`: `check-uv-setup`, `check-locks`, `check-python-version`, and
      `check-packaging` (depending on `dist`, then running each); `check-reinit` and
      `check-internal-locks` removed from targets, `.PHONY`, and help.
- [x] 4.5 Closeout wiring: `openspec/README.md#plan-closeout-requirements` gains a
      packaging part (`make check-packaging`) after documentation citations, making ten
      parts; `AGENTS.md` names `make check-packaging` in its completion checklist, its
      package-discipline rule, and its diagnostics rule; `docs/prompts/implementation.md`
      step 3c; `openspec/changes/inject-site-pool-authority/proposal.md` (which names
      `make check-reinit`); and the closeout task of every change in Appendix B gains the
      packaging step.
- [x] 4.6 Validate (so far: `make check-packaging` passes; the script suite passes apart from
      two failures present at the checkpoint — a `.git`-dependent image-tag test and
      `test_alkahest_profiles_keep_policy_outside_chains`): `make check-packaging` passes; `make test-release-tooling` passes;
      with the wheelhouse built, each check passes with networking disabled
      (`UV_OFFLINE=1`).

      4.5: 55 numbered closeouts gained a packaging item, and two unnumbered ones a packaging
      line; `unbacked-bare-metal-listings` has a placeholder closeout that will be written from
      the README. `openspec validate --all --strict` fails for the same twelve changes as at the
      checkpoint.
### 5. Documentation and promotion for slice 1 (D14, D15)

- [x] 5.1 `docs/development/BUILD_AND_PACKAGING.md`: wheelhouse consumption; project
      environments and `reinit`; `make lock`; images; the Python declaration; and a table
      mapping each rule to its check.
- [x] 5.2 `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` shortened
      to the architecture and a link; `AGENTS.md` "Package and dependency discipline"
      links the guide; `openspec/README.md`'s placement table gains its row;
      `docs/development/RELEASING.md` corrected wherever it describes `reinit`,
      `find-links`, or image versions.
- [x] 5.3 Promote slice 1's requirements to `openspec/specs/deployment-state/spec.md`
      (wheelhouse consumption, `reinit`, images, locks, Python version, packaging checks,
      aggregate kit tests, and the modified provider-separation requirement), delete its
      stray "Internal wheel development contract" section, and add the rationale to
      `openspec/specs/deployment-state/architecture.md#artifact-and-package-boundary`.
      Promote the closeout requirement to `openspec/specs/planning-governance/spec.md`.

### 6. Slice 1 closeout

Per `openspec/README.md#plan-closeout-requirements`, including the packaging part 4.5
adds.

- [x] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the
      comments and docstrings slice 1 touches for provenance narration the target cannot
      catch — the new scripts' docstrings and the rewritten Makefile and Dockerfile
      comments especially.
- [x] 6.2 **Import placement.** Review every import slice 1 adds or touches; the new
      scripts import at module level unless a documented reason applies.
- [x] 6.3 **Documentation compliance.** Re-check D1–D9 and D12–D15 against
      `openspec/README.md`'s placement rules: normative rules in
      `deployment-state/spec.md`, rationale in its `architecture.md`, contributor guidance
      in `BUILD_AND_PACKAGING.md`.
- [x] 6.4 **Narrative compression.** Compress completed slice 1 notes to final behavior,
      validation evidence, handed-off validations, and documentation destinations.
- [x] 6.5 **Roadmap currency.** The change sits under the lesser goal "Package and
      release readiness", which has no roadmap goal behind it; confirm
      `docs/development/ROADMAP.md` is owed nothing and record that disposition.
- [x] 6.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md` to slice 1 complete, or record the disposition.
- [x] 6.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=converge-python-packaging` and resolve every match.
- [x] 6.8 **Packaging.** Run `make check-packaging` and resolve every failure.
- [ ] 6.9 **End-to-end pipeline.** *Blocked in the implementation sandbox: no Docker daemon; 3.8 and this item are unrun and handed off.* Confirm the pipeline passes with the converged images
      and record the run, its result, and the scenarios that build each image; if it
      cannot run, record the blocker and treat 3.8 as unrun.
- [x] 6.10 **Promotion.** Add the design-promotion record for slice 1's decisions, mapping
      each to its exact permanent heading, and verify no production source references
      `openspec/changes/converge-python-packaging`.

      Evidence: `make check-packaging` passes. Script suite: 259 pass; two failures are
      present at the checkpoint (an image-tag test that needs `.git`, and
      `test_alkahest_profiles_keep_policy_outside_chains`). `make check-comment-hygiene` passes.
      `check-doc-citations` for this change leaves only the two slice 2 files. Roadmap: none
      owed (lesser goal "Package and release readiness" has no roadmap goal). Handed off and
      unrun: relock and `reinit` of `kit/policy`, `domains/vms/buyer`, `domains/vms/storefront`
      (PyTorch index blocked); every image build (3.8); the end-to-end pipeline (6.9).
## Slice 2 — one project layout

### 7. Flat import packages under `src/` (D10)

- [ ] 7.1 Move each project's modules to `src/<package>/` with `git mv`, keeping data files
      beside the modules that load them, and point its wheel target at `src/<package>`:
      `domains/vms/buyer` → `arkhai_vms_buyer`, `domains/vms/listings` →
      `arkhai_vms_listings`, `domains/vms/negotiation` → `arkhai_vms_negotiation` (with
      `rl/models/*.pt`), `domains/vms/settlement` → `arkhai_vms_settlement`,
      `domains/apicredits/buyer` → `arkhai_apicredits_buyer`, `domains/apicredits` →
      `arkhai_apicredits` (its `listings/`, `negotiation/`, `settlement/`, `schema.py`,
      `domain_runtime.py`, and `__init__.py`; the sibling subprojects stay where they are).
- [ ] 7.2 Re-run the Appendix A scan, reconcile it, and rename every import, entry point,
      `monkeypatch` target string, `filterwarnings` entry, and prose reference it lists,
      except the three exclusions it names. `domains/vms/storefront/Dockerfile`'s smoke
      import follows; `domains/vms/compose.yml`'s `PYTHONPATH` note is corrected, and the
      variable removed if nothing then needs it.
- [ ] 7.3 Remove editable-install workarounds: `UV_NO_EDITABLE` from
      `domains/vms/buyer/Makefile`, `domains/apicredits/Makefile`, and
      `domains/apicredits/buyer/Makefile`; the `no_editable` matrix fields and
      `UV_NO_EDITABLE` environment line from `.github/workflows/tests.yml`; `cache-keys`
      from `domains/vms/buyer`, `domains/apicredits/buyer`, and `domains/apicredits`
      `pyproject.toml`.
- [ ] 7.4 `docs/configuration.md` hook examples use `arkhai_vms_buyer.aggregation`.
- [ ] 7.5 Validate: each renamed project's default suite; the suites of
      `domains/vms/storefront`, `domains/apicredits/storefront`,
      `domains/apicredits/service`, `kit/fulfillment`, and `e2e-tests` (unit tier); each
      renamed wheel contains exactly `src/<package>` plus metadata; the Appendix A scan
      finds only its exclusions.

### 8. Versions and publication (D16)

- [ ] 8.1 Bump every distribution whose wheel contents change. Enumerated from Appendix A
      ownership, keeping projects whose changed files ship in the wheel:

      | Distribution | From | To |
      |---|---|---|
      | `arkhai-vms-buyer` | 0.3.4 | 0.4.0 |
      | `arkhai-vms-listings` | 0.3.0 | 0.4.0 |
      | `arkhai-vms-negotiation` | 0.1.0 | 0.2.0 |
      | `arkhai-vms-settlement` | 0.1.0 | 0.2.0 |
      | `arkhai-apicredits-buyer` | 0.3.1 | 0.4.0 |
      | `arkhai-apicredits-domain` | 0.3.0 | 0.4.0 |
      | `arkhai-apicredits-storefront` | 0.4.1 | 0.5.0 |
      | `arkhai-vms-storefront` | 0.7.1 | 0.8.0 |

      `arkhai-apicredits-service` changes only tests; `arkhai-core-buyer`,
      `arkhai-kit-alkahest`, and `arkhai-kit-policy` hold only Appendix A exclusions.
- [ ] 8.2 Move every requirement on a bumped distribution to its new lower bound:
      `domains/apicredits/buyer`, `domains/apicredits/storefront`, `domains/vms/buyer`
      (three), `domains/vms/negotiation`, `domains/vms/settlement`,
      `domains/vms/storefront` (three), and `e2e-tests` (three) `pyproject.toml`.
- [ ] 8.3 Rebuild the wheelhouse and run `make lock` for every project whose lock names a
      bumped distribution (handoff for PyTorch-index projects), then `make check-locks`.
- [ ] 8.4 `.github/workflows/publish-pypi.yml` path filters for the six moved projects,
      including `apicredits-domain`; `scripts/tests/test_publish_matrix.py` if it asserts
      them; `docs/development/RELEASING.md` records the import migration for the bumped
      releases.
- [ ] 8.5 Validate: build every published distribution's wheel before and after slice 2
      and compare contents; every distribution whose contents changed is in 8.1.

### 9. Relative sources (D11)

- [ ] 9.1 `domains/bare_metal/provisioning/adapter/pyproject.toml` drops its
      `[tool.uv.sources]` block; relock with `make lock PROJECTS=
      domains/bare_metal/provisioning/adapter`; its suite passes against `.dist` wheels.
- [x] 9.2 Record the transfer in `openspec/changes/remove-relative-uv-sources/tasks.md`:
      its open sections 1–3 now belong to this change. Done at planning, 2026-09-27.

### 10. Layout check and documentation

- [ ] 10.1 `scripts/check_project_layout.py` with
      `scripts/tests/test_check_project_layout.py`, covering each condition in D12's table
      and the current tree passing; `check-project-layout` joins `check-packaging`.
- [ ] 10.2 `BUILD_AND_PACKAGING.md` gains the layout rule; promote the layout requirement
      and the wheelhouse-source rule to `openspec/specs/deployment-state/spec.md`.

### 11. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 11.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the
      comments and docstrings slice 2 touches, including module docstrings in moved files
      that describe their former location.
- [ ] 11.2 **Import placement.** Review every import slice 2 rewrites; renaming must not
      move an import between module and function level.
- [ ] 11.3 **Documentation compliance.** Re-check D10, D11, and D16 against
      `openspec/README.md`'s placement rules, and confirm every delta requirement of this
      change landed in its owning spec.
- [ ] 11.4 **Narrative compression.** Compress completed notes across both slices,
      moving any remaining rationale into `design.md` first.
- [ ] 11.5 **Roadmap currency.** Confirm and record that `docs/development/ROADMAP.md` is
      owed nothing.
- [ ] 11.6 **Campaign index currency.** Update this change's row and the "Package and
      release readiness" dependency graph in `openspec/changes/README.md` to complete, and
      reconcile `remove-relative-uv-sources`' row with its transferred work.
- [ ] 11.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=converge-python-packaging` and resolve every match,
      including citations to moved files.
- [ ] 11.8 **Packaging.** Run `make check-packaging`, now including
      `check-project-layout`, and resolve every failure.
- [ ] 11.9 **End-to-end pipeline.** Confirm the pipeline passes on the renamed packages
      and record the run, its result, and the VM and API-credit scenarios exercising them;
      if it cannot run, record the blocker and treat the validations it gates as unrun.
- [ ] 11.10 **Promotion.** Complete the design-promotion record for every decision, and
      verify no production source references `openspec/changes/converge-python-packaging`.

## Appendix A — slice 2 rename sites

Every file outside `openspec/` and generated locks that names `domains.vms.buyer`,
`domains.vms.listings`, `domains.vms.negotiation`, `domains.vms.settlement`, or
`domains.apicredits`, grouped by owning project. Re-inventoried 2026-09-28 against the
rebased tree, unchanged from planning; 7.2 re-runs the scan before editing and
reconciles any difference.
Three hits are deliberately not rename sites: the legacy entry-point group
`domains.vms.buyer.aggregation_policies` in `core/buyer/src/core_buyer/aggregation.py`
(a compatibility contract for installed plugin packages, not an import path), and the
"extracted from" history in `kit/alkahest/src/market_alkahest/proposals.py` and
`kit/policy/src/market_policy/scalar_policies.py` / `seller_round.py`, which remain
accurate as history.

**Outside any project** — 2 files

- `docs/configuration.md`
- `domains/vms/compose.yml`

**`core/buyer`** (`arkhai-core-buyer`, published) — 1 file

- `core/buyer/src/core_buyer/aggregation.py`

**`domains/apicredits`** (`arkhai-apicredits-domain`, published) — 16 files

- `domains/apicredits/domain_runtime.py`
- `domains/apicredits/listings/__init__.py`
- `domains/apicredits/listings/pricing.py`
- `domains/apicredits/listings/reconciler.py`
- `domains/apicredits/negotiation/__init__.py`
- `domains/apicredits/negotiation/policies.py`
- `domains/apicredits/negotiation/storefront_round.py`
- `domains/apicredits/pyproject.toml`
- `domains/apicredits/schema.py`
- `domains/apicredits/settlement/__init__.py`
- `domains/apicredits/settlement/fulfillment.py`
- `domains/apicredits/tests/test_credits_client.py`
- `domains/apicredits/tests/test_credits_client_http.py`
- `domains/apicredits/tests/test_distribution_install.py`
- `domains/apicredits/tests/test_hosted_settlement_contract.py`
- `domains/apicredits/tests/test_issuance_evidence.py`

**`domains/apicredits/buyer`** (`arkhai-apicredits-buyer`, published) — 11 files

- `domains/apicredits/buyer/buy_cli.py`
- `domains/apicredits/buyer/buyer_client.py`
- `domains/apicredits/buyer/cli.py`
- `domains/apicredits/buyer/listing_cli.py`
- `domains/apicredits/buyer/negotiate_cli.py`
- `domains/apicredits/buyer/pyproject.toml`
- `domains/apicredits/buyer/tests/test_listing_helpers.py`
- `domains/apicredits/buyer/tests/test_negotiation_flow.py`
- `domains/apicredits/buyer/tests/test_plugin_export.py`
- `domains/apicredits/buyer/tests/test_settle_credentials.py`
- `domains/apicredits/buyer/tests/test_settlement_composition.py`

**`domains/apicredits/service`** (`arkhai-apicredits-service`, published) — 3 files

- `domains/apicredits/service/tests/integration/test_credits_route_parity.py`
- `domains/apicredits/service/tests/integration/test_credits_signed_roundtrip.py`
- `domains/apicredits/service/tests/integration/test_signed_authority.py`

**`domains/apicredits/storefront`** (`arkhai-apicredits-storefront`, published) — 13 files

- `domains/apicredits/storefront/src/apicredits_storefront/controllers/issuance_evidence_controller.py`
- `domains/apicredits/storefront/src/apicredits_storefront/domain_runtime.py`
- `domains/apicredits/storefront/src/apicredits_storefront/negotiation_runtime.py`
- `domains/apicredits/storefront/src/apicredits_storefront/services/credits_service_client.py`
- `domains/apicredits/storefront/src/apicredits_storefront/services/fulfillment_service.py`
- `domains/apicredits/storefront/src/apicredits_storefront/services/issuance_evidence.py`
- `domains/apicredits/storefront/src/apicredits_storefront/services/publication_service.py`
- `domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py`
- `domains/apicredits/storefront/tests/unit/test_concept_modules.py`
- `domains/apicredits/storefront/tests/unit/test_domain_runtime.py`
- `domains/apicredits/storefront/tests/unit/test_issuance_evidence_repository.py`
- `domains/apicredits/storefront/tests/unit/test_keys_lookup.py`
- `domains/apicredits/storefront/tests/unit/test_settlement_fulfillment.py`

**`domains/vms/buyer`** (`arkhai-vms-buyer`, published) — 31 files

- `domains/vms/buyer/buy_cli.py`
- `domains/vms/buyer/buyer_client.py`
- `domains/vms/buyer/config_cli.py`
- `domains/vms/buyer/listing_cli.py`
- `domains/vms/buyer/logs_cli.py`
- `domains/vms/buyer/main.py`
- `domains/vms/buyer/negotiate_cli.py`
- `domains/vms/buyer/pyproject.toml`
- `domains/vms/buyer/tests/conftest.py`
- `domains/vms/buyer/tests/test_aggregation.py`
- `domains/vms/buyer/tests/test_aggregation_policy.py`
- `domains/vms/buyer/tests/test_buy_orchestrator.py`
- `domains/vms/buyer/tests/test_buy_pricing_and_filters.py`
- `domains/vms/buyer/tests/test_buy_resume_cli.py`
- `domains/vms/buyer/tests/test_buyer_client.py`
- `domains/vms/buyer/tests/test_buyer_client_resume.py`
- `domains/vms/buyer/tests/test_config_migration_cli.py`
- `domains/vms/buyer/tests/test_escrow_client_dispatch.py`
- `domains/vms/buyer/tests/test_escrow_selection.py`
- `domains/vms/buyer/tests/test_explain_cli.py`
- `domains/vms/buyer/tests/test_hosted_authorization.py`
- `domains/vms/buyer/tests/test_negotiation_config.py`
- `domains/vms/buyer/tests/test_no_resource_pools_dependency.py`
- `domains/vms/buyer/tests/test_plugin_export.py`
- `domains/vms/buyer/tests/test_policy_cli_injection.py`
- `domains/vms/buyer/tests/test_policy_surface.py`
- `domains/vms/buyer/tests/test_resume_helpers.py`
- `domains/vms/buyer/tests/test_service_cli.py`
- `domains/vms/buyer/tests/test_settlement_config_template.py`
- `domains/vms/buyer/tests/test_vm_listing_helpers.py`
- `domains/vms/buyer/tests/test_vm_settlement_helpers.py`

**`domains/vms/listings`** (`arkhai-vms-listings`, published) — 9 files

- `domains/vms/listings/__init__.py`
- `domains/vms/listings/listing_cardinality_mode.py`
- `domains/vms/listings/pool_descriptors.py`
- `domains/vms/listings/pricing.py`
- `domains/vms/listings/pricing_resolution.py`
- `domains/vms/listings/reconciler.py`
- `domains/vms/listings/resource_csv_importer.py`
- `domains/vms/listings/resources.py`
- `domains/vms/listings/strategy.py`

**`domains/vms/negotiation`** (`arkhai-vms-negotiation`, published) — 4 files

- `domains/vms/negotiation/__init__.py`
- `domains/vms/negotiation/rl/arkhai_common.py`
- `domains/vms/negotiation/rl/torch_arkhai_strategy.py`
- `domains/vms/negotiation/storefront_round.py`

**`domains/vms/settlement`** (`arkhai-vms-settlement`, published) — 2 files

- `domains/vms/settlement/__init__.py`
- `domains/vms/settlement/compute_lease.py`

**`domains/vms/storefront`** (`arkhai-vms-storefront`, published) — 52 files

- `domains/vms/storefront/Dockerfile`
- `domains/vms/storefront/Makefile`
- `domains/vms/storefront/src/market_storefront/__init__.py`
- `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`
- `domains/vms/storefront/src/market_storefront/controllers/deals_controller.py`
- `domains/vms/storefront/src/market_storefront/controllers/listings_controller.py`
- `domains/vms/storefront/src/market_storefront/domain_runtime.py`
- `domains/vms/storefront/src/market_storefront/failure_actions.py`
- `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`
- `domains/vms/storefront/src/market_storefront/publication_binding.py`
- `domains/vms/storefront/src/market_storefront/services/capacity_client.py`
- `domains/vms/storefront/src/market_storefront/services/fulfillment_resume_runtime.py`
- `domains/vms/storefront/src/market_storefront/services/listing_identity_carryover.py`
- `domains/vms/storefront/src/market_storefront/services/listing_service.py`
- `domains/vms/storefront/src/market_storefront/services/listing_source_check.py`
- `domains/vms/storefront/src/market_storefront/services/publication_loop.py`
- `domains/vms/storefront/src/market_storefront/services/publication_service.py`
- `domains/vms/storefront/src/market_storefront/services/publication_terms.py`
- `domains/vms/storefront/src/market_storefront/services/site_projection_cache.py`
- `domains/vms/storefront/src/market_storefront/services/system_service.py`
- `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_planner.py`
- `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_service.py`
- `domains/vms/storefront/src/market_storefront/services/vm_job_spec_service.py`
- `domains/vms/storefront/src/market_storefront/services/vm_pool_override_contribution.py`
- `domains/vms/storefront/src/market_storefront/settings.toml`
- `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`
- `domains/vms/storefront/tests/integration/test_listings_api.py`
- `domains/vms/storefront/tests/integration/test_reconciler_projection.py`
- `domains/vms/storefront/tests/unit/test_accepted_escrows_csv_dsl.py`
- `domains/vms/storefront/tests/unit/test_architecture_imports.py`
- `domains/vms/storefront/tests/unit/test_compute_allocations.py`
- `domains/vms/storefront/tests/unit/test_escrow_fields_policy.py`
- `domains/vms/storefront/tests/unit/test_extract_initial_price.py`
- `domains/vms/storefront/tests/unit/test_file_policy_discovery.py`
- `domains/vms/storefront/tests/unit/test_fulfillment_reconciliation.py`
- `domains/vms/storefront/tests/unit/test_heartbeat_gated_listings.py`
- `domains/vms/storefront/tests/unit/test_hosts.py`
- `domains/vms/storefront/tests/unit/test_listing_cardinality_mode.py`
- `domains/vms/storefront/tests/unit/test_listing_comparison.py`
- `domains/vms/storefront/tests/unit/test_listing_model_capacity_identity.py`
- `domains/vms/storefront/tests/unit/test_pool_descriptors.py`
- `domains/vms/storefront/tests/unit/test_pricing_resolution.py`
- `domains/vms/storefront/tests/unit/test_publications_wiring.py`
- `domains/vms/storefront/tests/unit/test_reconciler.py`
- `domains/vms/storefront/tests/unit/test_resources.py`
- `domains/vms/storefront/tests/unit/test_rl_middleware.py`
- `domains/vms/storefront/tests/unit/test_sync_negotiation_escrow_normalization.py`
- `domains/vms/storefront/tests/unit/test_sync_negotiation_seller_round_hook.py`
- `domains/vms/storefront/tests/unit/test_token_integration.py`
- `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`
- `domains/vms/storefront/tests/unit/test_vm_job_spec_service.py`
- `domains/vms/storefront/tests/unit/test_vm_negotiation_strategy.py`

**`e2e-tests`** (`arkhai-e2e-tests`) — 4 files

- `e2e-tests/tests/conftest.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/hosted/network.py`
- `e2e-tests/tests/smoke/test_storefront_smoke.py`
- `e2e-tests/tests/unit/test_hosted_public_boundary.py`

**`kit/alkahest`** (`arkhai-kit-alkahest`, published) — 1 file

- `kit/alkahest/src/market_alkahest/proposals.py`

**`kit/fulfillment`** (`arkhai-kit-fulfillment`) — 1 file

- `kit/fulfillment/tests/unit/test_import_boundaries.py`

**`kit/policy`** (`arkhai-kit-policy`, published) — 2 files

- `kit/policy/src/market_policy/scalar_policies.py`
- `kit/policy/src/market_policy/seller_round.py`

## Appendix B — closeout tasks gaining the packaging step

Active changes whose closeout section had an unchecked task, re-inventoried 2026-09-28
against the rebased tree. 4.5 re-derives the list at implementation; a change archived
since is skipped, and one added since is included.

- `openspec/changes/add-alkahest-attestation-reference-query/tasks.md`
- `openspec/changes/add-api-credits-hosted-settlement/tasks.md`
- `openspec/changes/add-bare-metal-hosted-settlement/tasks.md`
- `openspec/changes/add-database-migration-commands/tasks.md`
- `openspec/changes/add-deterministic-regression-contract/tasks.md`
- `openspec/changes/add-future-domain-shape-validation/tasks.md`
- `openspec/changes/add-harness-buyer-action-slice/tasks.md`
- `openspec/changes/add-harness-findings-projection/tasks.md`
- `openspec/changes/add-harness-scenario-contract/tasks.md`
- `openspec/changes/add-persistent-buyer-profiles/tasks.md`
- `openspec/changes/automate-seller-spot/tasks.md`
- `openspec/changes/bare-metal-and-credits-domain-stacks/tasks.md`
- `openspec/changes/bare-metal-mock-provisioned-deal/tasks.md`
- `openspec/changes/billable-capacity-reservations/tasks.md`
- `openspec/changes/capacity-reservation-lifecycle-hardening/tasks.md`
- `openspec/changes/capacity-shape-envelope/tasks.md`
- `openspec/changes/capacity-shape-pricing/tasks.md`
- `openspec/changes/compose-contact-exchange-across-compute/tasks.md`
- `openspec/changes/consume-expanded-stripe-funding/tasks.md`
- `openspec/changes/contact-payload-retention/tasks.md`
- `openspec/changes/contain-embedded-host-key-material/tasks.md`
- `openspec/changes/deduplicate-dynaconf-bootstrap/tasks.md`
- `openspec/changes/default-no-pre-settlement-capacity-hold/tasks.md`
- `openspec/changes/disburse-a-settlement-disposition/tasks.md`
- `openspec/changes/fix-golden-image-config/tasks.md`
- `openspec/changes/fix-resource-pool-provider-at-creation/tasks.md`
- `openspec/changes/kit-owned-capacity-and-publication/tasks.md`
- `openspec/changes/kit-owned-negotiation-runtime/tasks.md`
- `openspec/changes/kit-storefront-composition-seam/tasks.md`
- `openspec/changes/market-platform-compute-40-multi-domain-proof/tasks.md`
- `openspec/changes/multi-domain-storefront-composition/tasks.md`
- `openspec/changes/name-unverifiable-responses/tasks.md`
- `openspec/changes/negotiation-capacity-feasibility-probe/tasks.md`
- `openspec/changes/negotiation-driven-capacity-resize/tasks.md`
- `openspec/changes/negotiation-time-capacity-hold/tasks.md`
- `openspec/changes/never-strand-the-host-on-passthrough/tasks.md`
- `openspec/changes/pools-6-fair-scheduling-policy/tasks.md`
- `openspec/changes/pools-7-storefront-fulfillment-cutover/tasks.md`
- `openspec/changes/pools-8-capacity-projection-and-listing-hints/tasks.md`
- `openspec/changes/pools-9-retire-local-physical-authority/tasks.md`
- `openspec/changes/project-an-authoritative-funding-loss/tasks.md`
- `openspec/changes/publish-indicative-listing-rates/tasks.md`
- `openspec/changes/publish-wheels-through-a-gate/tasks.md`
- `openspec/changes/refactor-e2e-fulfillment-lifecycle/tasks.md`
- `openspec/changes/relay-vm-access-without-a-dashboard/tasks.md`
- `openspec/changes/remove-dead-storefront-physical-surfaces/tasks.md`
- `openspec/changes/repair-multi-storefront-scenario/tasks.md`
- `openspec/changes/repair-storefront-alkahest-configuration/tasks.md`
- `openspec/changes/replace-polling-with-authenticated-push/tasks.md`
- `openspec/changes/restore-issue-discovery-thin-runner/tasks.md`
- `openspec/changes/retain-authenticated-request-outcomes/tasks.md`
- `openspec/changes/separate-marketplace-registry/tasks.md`
- `openspec/changes/service-identity-signing/tasks.md`
- `openspec/changes/settle-capacity-claim-vocabulary/tasks.md`
- `openspec/changes/sign-multi-language-credits-middleware/tasks.md`
- `openspec/changes/storefront-domain-parameterization/tasks.md`
- `openspec/changes/type-core-packages/tasks.md`
- `openspec/changes/unbacked-bare-metal-listings/tasks.md`

## Appendix C — `reinit` targets

- `core/buyer/Makefile`
- `core/registry-client/Makefile`
- `core/registry/Makefile`
- `core/storefront-client/Makefile`
- `core/storefront/Makefile`
- `domains/apicredits/Makefile`
- `domains/apicredits/buyer/Makefile`
- `domains/apicredits/sample-app/Makefile`
- `domains/apicredits/service/Makefile`
- `domains/apicredits/storefront/Makefile`
- `domains/bare_metal/Makefile`
- `domains/bare_metal/buyer/Makefile`
- `domains/bare_metal/provisioning/adapter/Makefile`
- `domains/bare_metal/storefront/Makefile`
- `domains/compute/Makefile`
- `domains/vms/buyer/Makefile`
- `domains/vms/domain/Makefile`
- `domains/vms/provisioning/adapter/Makefile`
- `domains/vms/storefront/Makefile`
- `e2e-tests/Makefile`
- `kit/alkahest/Makefile`
- `kit/capacity-publication/Makefile`
- `kit/config/Makefile`
- `kit/contact-exchange/Makefile`
- `kit/delivery/Makefile`
- `kit/fulfillment/Makefile`
- `kit/hosted-settlement/Makefile`
- `kit/negotiation-runtime/Makefile`
- `kit/policy/Makefile`
- `kit/pool-overrides/Makefile`
- `kit/resource-pools/Makefile`
- `kit/settlement-runtime/Makefile`
- `kit/site-client/Makefile`
- `kit/site/Makefile`
- `kit/storefront/Makefile`
- `provisioning/compute/Makefile`
- `provisioning/compute/service/Makefile`

## Appendix D — Makefiles that run uv

- `Makefile` (root)
- `core/Makefile`
- `core/buyer/Makefile`
- `core/registry-client/Makefile`
- `core/registry/Makefile`
- `core/storefront-client/Makefile`
- `core/storefront/Makefile`
- `domains/Makefile`
- `domains/apicredits/Makefile`
- `domains/apicredits/buyer/Makefile`
- `domains/apicredits/middleware/python/Makefile`
- `domains/apicredits/sample-app/Makefile`
- `domains/apicredits/service/Makefile`
- `domains/apicredits/storefront/Makefile`
- `domains/bare_metal/Makefile`
- `domains/bare_metal/buyer/Makefile`
- `domains/bare_metal/provisioning/adapter/Makefile`
- `domains/bare_metal/storefront/Makefile`
- `domains/compute/Makefile`
- `domains/vms/buyer/Makefile`
- `domains/vms/domain/Makefile`
- `domains/vms/provisioning/adapter/Makefile`
- `domains/vms/provisioning/iac/Makefile`
- `domains/vms/storefront/Makefile`
- `e2e-tests/Makefile`
- `kit/alkahest/Makefile`
- `kit/capability-shape/Makefile`
- `kit/capacity-publication/Makefile`
- `kit/config/Makefile`
- `kit/contact-exchange/Makefile`
- `kit/delivery/Makefile`
- `kit/fulfillment/Makefile`
- `kit/hosted-settlement/Makefile`
- `kit/identity/Makefile`
- `kit/negotiation-runtime/Makefile`
- `kit/policy/Makefile`
- `kit/pool-overrides/Makefile`
- `kit/resource-pools/Makefile`
- `kit/settlement-runtime/Makefile`
- `kit/site-client/Makefile`
- `kit/site/Makefile`
- `kit/storefront/Makefile`
- `provisioning/compute/Makefile`
- `provisioning/compute/service/Makefile`
