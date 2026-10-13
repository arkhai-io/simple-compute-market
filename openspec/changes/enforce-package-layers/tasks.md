## 1. Audit: rules file, library, and report

Nothing in this section fails a build. It lands first so the changes that own
findings can cite the baseline.

- [x] 1.1 Create `docs/development/ARCHITECTURE.toml`, beside the prose it
      encodes. It lives under `docs/` because `make check-comment-hygiene` exempts
      `docs/` and every exception row names its owning change. Tables:
      - `[layers]`: the order `core` < `kit` < `specialization` < `composition` and
        each layer's permitted scope (design, "What each layer's scope may
        contain").
      - `[[families]]`: `compute`, with its directory `domains/compute` and its
        vocabulary distribution `arkhai-compute`.
      - `[[domains]]`: `vms` and `bare_metal` (family `compute`) and `apicredits`
        (no family), each with its directory and identifying `tokens`, seeded
        from `core/tests/unit/test_domain_boundaries.py`'s `CONCRETE_IDENTITIES`
        (`compute.v1`, `bare_metal.v1`, `api_credits.v1`).
      - `[[mechanisms]]`: `alkahest`, `arkhai-payments`, and `contact-exchange`,
        each with the one kit that holds it in scope and its `tokens`.
      - `[conventions]`: the kind words (`contracts`, `client`); the role words
        (`storefront`, `buyer`, `service`, `app`), which are not read under
        `kit/`; the skipped paths (`e2e-tests`, `tools/`, `scripts`, `dev-env`)
        and virtual projects.
      - `[[plugin_groups]]`: `market.buyer_domains`,
        `market.storefront_contributions`, and `market.delivery_sinks` (owner
        `arkhai-kit-delivery`).
      - `[budgets]`: `contracts` and `client`, as the design states them.
      - Empty `[[overrides]]`, `[[exceptions]]`, `[[declarations]]`, and
        `[external_budgets]`, filled by 1.5 and 2.1.
- [x] 1.2 Add `scripts/architecture.py`, a standard-library module with no
      dependency on any project environment:
      - **Projects.** Every `pyproject.toml` outside the skipped paths, with its
        distribution name, `src/<package>` import root (the layout
        `check_project_layout.py` already enforces), declared internal
        distributions from `dependencies` and every `optional-dependencies` extra,
        entry-point groups, and virtual flag.
      - **Classification.** Layer, kind, and scope from the path and name per the
        design's reading table, then the override row if one exists; the plugin
        property from the plugin groups and their owners. A project that matches
        no reading is a finding, not a default.
      - **Edges.** `ast.walk` over every `Import` and `ImportFrom` under `src/`.
        Relative imports resolve to their package. An import root maps to a
        distribution only through the internal `src/<package>` table, so no
        third-party metadata is needed. Each edge records its file, line, and
        context: module, function, `TYPE_CHECKING`, or `try`. The context is
        reported and never consulted by a rule. Declared dependencies are edges
        too, located at the project's `pyproject.toml`.
      - **Rules.** One `problems()` per rule, each returning findings that name
        the rule, project, target, file, line, context, and message: `layer`,
        `cycle` (strongly connected components within one layer), `scope`,
        `layer_scope`, `undeclared_import` (internal only), `unused_declaration`,
        `kind_allowlist`, `package_allowlist` (import roots against
        `sys.stdlib_module_names` and the allowlist row), `plugin_in_degree`,
        `vocabulary` (string literals against `tokens` outside the project's
        scope), `exception_expiry` (a row excusing no current finding), and
        `override_expiry` (path conforms, or a granted scope element no edge
        uses).
      - **Exceptions.** An exception suppresses only the finding of the rule it
        names; `strict=True` applies none.
- [x] 1.3 Add `scripts/tests/test_architecture.py`. It loads the module the way
      `scripts/tests/test_check_project_layout.py` loads its checker and builds
      synthetic trees under `tmp_path`, with a passing and a failing tree for
      every rule in 1.2. It also covers:
      - every import context, relative imports, and optional extras;
      - a suffix read only for kind and role words (`kit/capability-shape` is a
        library);
      - role words ignored under `kit/` (`kit/storefront` is a library);
      - a scope-root vocabulary project;
      - the nested `domains/apicredits/middleware/python`;
      - a domain with no family;
      - plugin as a property, including a group owner that registers into its own
        group;
      - an exception that suppresses only its named rule;
      - both override-expiry conditions;
      - an exception expiring because its edge is gone, and because a rule
        revision makes its edge legal.

      The suite runs under the existing `make test-release-tooling`, which
      collects `scripts/tests`.
- [x] 1.4 Add `scripts/architecture_report.py` and
      `make architecture-report [OUT=<path>]`. It runs every rule in strict mode
      over the tree and writes a Markdown report to `OUT`, or to standard output.
      Neither the script nor the target names a change directory, which
      `make check-comment-hygiene` would reject in the script and which would go
      stale at archive. Task 1.6 writes the baseline to
      `openspec/changes/enforce-package-layers/baseline.md`. The report has:
      - the classification of every project: layer, kind, scope, plugin, and
        whether it comes from an override;
      - every finding grouped by rule, each with an empty classification column.

      The baseline is a change document, so it leaves with the change at
      archive.
- [x] 1.5 Seed `[[overrides]]` for the projects whose path does not yet say what
      they are, each owned by `align-package-paths-with-layers` and dated:
      - `core/buyer`, `core/storefront`, and `core/registry` as compositions;
      - `core/storefront-client` and `core/registry-client` as kit clients;
      - `provisioning/compute`, `provisioning/compute/ansible`, and
        `provisioning/compute/contracts` as `{compute}` specializations, the
        last of kind `contracts`;
      - `provisioning/compute/client` as a `{compute}` client;
      - `provisioning/compute/service` as a `{compute}` composition.

      Also seed the mechanism grants for `arkhai_vms_settlement` (`alkahest`) and
      `arkhai_apicredits` (`alkahest`, `arkhai-payments`). Any other override the
      report shows is needed is added at the 1.7 gate, not here.
- [x] 1.6 Run
      `make architecture-report OUT=openspec/changes/enforce-package-layers/baseline.md`
      and confirm every project outside the
      skipped paths is classified, with none unread. Reconcile the findings with
      `ARCHITECTURE.md`'s "Where the current tree diverges": every divergence it
      outlines appears in the baseline, or is listed under "What the rules
      deliberately do not catch" in `design.md`.
- [x] 1.7 **Decision gate: classify the baseline with the maintainer.** Classify
      every finding as one of:
      - a **defect**, naming its owning change;
      - **accepted**, with its reason: a `[[declarations]]` row for an
        unimported declaration, or an package-allowlist entry;
      - a **rule error**: revise the rule in `design.md` and in 1.2–1.3, then
        rerun.

      Each defect's owning change must name the finding in its proposal or
      design. A defect no change owns goes to the unowned-work list in
      `openspec/changes/README.md` under this change's campaign; it does not get
      an exception row. Section 2 does not start until the classified baseline is
      accepted.
      *Done.* Classified with the maintainer's rule that a purely declarative
      remedy is fixed here (design, "Audit before gate"). Results:
      - four missing declarations added and eight unexplained ones removed;
      - two declarations kept with a reason;
      - fifteen exception rows: four for
        `kit-owned-storefront-auth-and-persistence`, two for
        `kit-owned-storefront-shell`, eight for `move-escrow-into-alkahest`, one
        for `deduplicate-dynaconf-bootstrap`;
      - eight rule errors revised in `design.md`, "Rule errors the audit found".

      No defect is unowned. The baseline is `baseline.md`.

## 2. Gate

- [x] 2.1 Seed the rules file from the classified baseline:
      - `[[exceptions]]` from the defects, each naming its owning change, the
        rule, the edge or token, and the date;
      - `[[declarations]]` from the accepted unimported declarations, each with
        its reason;
      - `[external_budgets]` for the packages whose per-package tests assert a
        third-party allowlist today: `kit/identity`, `kit/settlement-runtime`,
        `kit/capability-shape`, `kit/capability-pricing`,
        `kit/resource-pools-contracts`, `kit/resource-pools-client`,
        `kit/contact-exchange`, `core`, `domains/compute`,
        `provisioning/compute/contracts`, and `provisioning/compute/client`. Copy
        each test's permitted third-party roots.

      Confirm `exception_expiry` reports nothing, so that no row is seeded for an
      edge the rules do not report.
- [x] 2.2 Add the four check scripts. Each has `check_project_layout.py`'s
      shape: a docstring naming its rules and citing
      `docs/development/ARCHITECTURE.md#package-and-dependency-layers`, a
      `problems(root)` built on `scripts/architecture.py`, and a `main()` that
      prints findings and exits non-zero only on a failing rule.
      - `scripts/check_architecture_layers.py`: `layer`, `cycle`, `layer_scope`,
        and `override_expiry`.
      - `scripts/check_architecture_scope.py`: `scope` and `vocabulary`.
      - `scripts/check_architecture_dependencies.py`: `undeclared_import` and
        `unused_declaration`. The latter warns.
      - `scripts/check_architecture_kinds.py`: `kind_allowlist`, `package_allowlist`,
        and `plugin_in_degree`.

      Each script also evaluates `exception_expiry` for the rows that name its
      rules. Each accepts `--strict`, which applies no exceptions, and
      `--change <name>`.
- [x] 2.3 Set the failure modes the design fixes:
      - `unused_declaration` warns.
      - `vocabulary` warns everywhere and fails in the `core` and `kit` layers.
      - `kind_allowlist` fails only for a kind the baseline showed clean or
        seeded; any other kind warns until it is.

      Record the kinds in each mode in the script's docstring.
- [x] 2.4 Add the Makefile targets and add them to `.PHONY`:
      - `check-architecture`, which runs the four scripts and fails if any fails;
      - `check-architecture-layers`, `check-architecture-scope`,
        `check-architecture-dependencies`, and `check-architecture-kinds`;
      - `check-architecture-change CHANGE=<name>`, which lists the exception rows
        `<name>` owns and fails while any remains.

      Add `check-architecture` to `check-packaging`'s sub-make line.
- [x] 2.5 Add a `make check-architecture` step to the `release-deployment` job in
      `.github/workflows/tests.yml`, before `make test-release-tooling`. It needs
      plain `python3`, no wheelhouse and no uv.
- [x] 2.6 Add `scripts/tests/test_check_architecture.py`. It covers each script's
      exit code on a failing tree, a warning-only tree, and a clean tree, plus
      `--strict` and `--change`. It checks that `check-architecture-change` fails
      while the named change owns a row and passes once none remains.
- [x] 2.7 Run `make check-architecture` on the tree and confirm it passes with
      only the documented warnings; run `make test-release-tooling`.
      *Done.* `make check-architecture` passes with no warnings. The tooling
      suite passes after the release guide's internal-dependency column was
      regenerated for the eight changed projects. The suites of the seven
      relocked projects pass. The VM buyer's and VM storefront's locks are
      stale until `download.pytorch.org` is reachable; see 6.8.

## 3. Retire the per-package boundary tests

A test retires in its own commit, only when all of these hold:
`check-architecture` runs in CI (2.5); `scripts/tests/test_architecture.py` has a
synthetic tree that fails on the same violation; and no exception row excuses an
edge the test forbids. Only a test's import-boundary assertions retire. Its other
assertions stay, and a test that asserts what the check cannot express is kept.

- [x] 3.1 Inventory every per-package boundary assertion. Twenty test modules
      and one function in `kit/config` hold them today, not the eighteen
      `proposal.md` first counted. Record for each the rule or rules that subsume
      it, what is kept, and whether an exception row blocks it. The expected
      dispositions:

      | Test | Subsumed by | Kept |
      |---|---|---|
      | `kit/identity/tests/unit/test_package_boundary.py` | `package_allowlist` | — |
      | `kit/settlement-runtime/tests/unit/test_import_boundaries.py` | `package_allowlist`, `scope`, `vocabulary` | — |
      | `kit/capability-shape/tests/unit/test_import_boundary.py` | `package_allowlist` | — |
      | `kit/capability-pricing/tests/unit/test_import_boundary.py` | `package_allowlist`, `layer` | — |
      | `kit/resource-pools-contracts/tests/unit/test_import_boundaries.py` | `kind_allowlist`, `package_allowlist` | — |
      | `kit/resource-pools-client/tests/unit/test_import_boundaries.py` | `kind_allowlist`, `package_allowlist` | — |
      | `kit/fulfillment/tests/unit/test_import_boundaries.py` | the denylist: `layer`, `scope` | the per-module carrier allowlist |
      | `kit/contact-exchange/tests/unit/test_package_boundary.py` | `package_allowlist`, `scope` | — |
      | `kit/site/tests/unit/test_import_boundaries.py` | the denylist: `layer`, `scope` | any `market_resource_pools` assertion `inject-site-pool-authority` adds |
      | `kit/config/tests/unit/test_resolution.py::test_common_config_has_no_concrete_mechanism_imports` | `market_alkahest`: `scope` | all, as found: it also forbids `stripe` and `web3`, and `kit/config` has no package allowlist |
      | `core/tests/unit/test_carrier_purity.py` | `layer`, `package_allowlist` | — |
      | `core/tests/unit/test_domain_boundaries.py` | imports: `layer`, `scope` | identity branching, as found: it scans the roles too, where `vocabulary` only warns |
      | `core/buyer/tests/unit/test_delivery_boundary.py` | — | all, as found: a composition composes mechanisms by rule, so the buyer role staying mechanism-neutral is not a graph rule |
      | `domains/vms/storefront/tests/unit/test_architecture_imports.py` | the kit scan and core storefront's domain-free scan: `layer`, `scope` | the concept-module scan, which forbids even `market_core`; the construction-site and `pyproject.toml` checks; and the no-bare-metal import test, blocked by `kit-owned-storefront-shell`'s rows |
      | `domains/compute/tests/test_import_boundary.py` | `scope`, `package_allowlist` | — |
      | `domains/bare_metal/tests/test_import_boundary.py` | `scope` | — |
      | `domains/bare_metal/storefront/tests/test_import_boundaries.py` | `layer`, `scope` | the runtime import smoke test |
      | `provisioning/compute/service/tests/unit/test_import_boundaries.py` | adapter isolation and the operator-client rule: `layer`, `scope` | the adapter-entrypoint allowlist, the Ansible module separation, the deployment-config regex, and the Ansible distribution's runtime check |
      | `provisioning/compute/client/tests/unit/test_import_boundaries.py` | `kind_allowlist`, `package_allowlist` | — |
      | `provisioning/compute/contracts/tests/unit/test_import_boundaries.py` | `kind_allowlist`, `package_allowlist` | — |
      | `domains/vms/buyer/tests/test_no_resource_pools_dependency.py` | — | all: it asserts what importing a module loads at runtime |

- [x] 3.2 Retire every unblocked test from 3.1, one package per commit. Before
      each deletion, add its synthetic failing case to
      `scripts/tests/test_architecture.py` and run the package's own suite.
- [x] 3.3 For each test still blocked by an exception row at this change's
      closeout, add a task to the owning change: retire the test once its row is
      gone. Record the hand-off here.
      *Done.*
      - `kit-owned-storefront-shell`'s design now retires
        `test_vm_storefront_imports_no_bare_metal_composition` with its rows.
      - Thirteen modules were deleted, and import-boundary tests were removed
        from five others.
      - `inject-site-pool-authority`'s design now adds, rather than keeps,
        `kit/site`'s planned test.
      - The package allowlists list internal roots as well as third-party ones,
        which is what let the allowlist tests retire (design, "Rule errors the
        audit found").

## 4. Promotion

This runs after code review, to reduce churn.

- [x] 4.1 `docs/development/ARCHITECTURE.md`, "Package and dependency layers":
      - "Where the current tree diverges" points at the exceptions table in
        `ARCHITECTURE.toml` as the authoritative list. It keeps prose only for
        what the check cannot see, the kit-area order.
      - "Kind" states the path-and-name conventions the check reads, the plugin
        groups, and the `contracts` and `client` kind allowlists, replacing the sentence
        that defers them to this change.
      - "Repository layers" gains the per-layer scope bounds table.
- [x] 4.2 `openspec/specs/market-composition/spec.md`: sync the "From-below kit
      dependencies" delta. Add the repository check as evidence in its Evidence
      section. In `openspec/specs/market-composition/architecture.md`, "Package
      ownership" says the check holds the layer and scope rules and that
      ownership remains review's.
- [x] 4.3 `openspec/specs/planning-governance/spec.md`: sync the delta. Add the
      architecture check to the Evidence list. In `openspec/README.md`'s
      plan-closeout part 8, `make check-packaging` covers architecture and
      `make check-architecture-change CHANGE=<name>` gates archive.
- [x] 4.4 `openspec/specs/deployment-state/spec.md`: sync the delta.
      `docs/development/BUILD_AND_PACKAGING.md`'s "Checks" table gains the four
      `check-architecture-*` rows.
- [x] 4.5 `AGENTS.md`, "Package and dependency discipline": the rules are
      enforced by `make check-architecture`, by the per-package tests it keeps,
      and by review for what neither expresses. A known divergence is an
      exception row naming its owning change, never a comment at the import.
- [x] 4.6 `docs/development/TESTING.md`, "Boundary-Change Validation", and
      `openspec/specs/test-compatibility/architecture.md`: dependency direction is
      validated by `make check-architecture`, and a per-package architecture test
      is written only for what it cannot express.

## 5. Review revisions

From the implementation review; the decisions are in `design.md`, "Review
revisions".

- [x] 5.1 Move each package's own constraints into a `[tool.arkhai.architecture]`
      table in its `pyproject.toml`:
      - each package allowlist becomes `allowed-dependencies`, a list of
        distribution names, in the eleven projects with a package allowlist;
      - each declarations row becomes a `runtime-dependencies` entry, mapping
        the dependency to its reason, in `domains/bare_metal/buyer` and
        `domains/vms/storefront`.

      Remove `[external_budgets]` and `[[declarations]]` from
      `docs/development/ARCHITECTURE.toml`. Point `core/pyproject.toml`'s
      comment at its own table. Confirm that no lock changes.
- [x] 5.2 `scripts/architecture.py`:
      - read the package table and reject any key other than
        `allowed-dependencies`, `import-roots`, and `runtime-dependencies`;
      - check every declared dependency, internal or third-party, against
        `allowed-dependencies`;
      - map a third-party import root to the distribution of the same
        normalized name, or through `import-roots`;
      - take `unused_declaration` and `declaration_expiry` from
        `runtime-dependencies`;
      - report a non-virtual project whose wheel target is not exactly one
        package as `unclassified` rather than skipping it.
- [x] 5.3 Add a `configuration` rule, run by `check_architecture_layers.py`. It
      fails on:
      - duplicate exception, override, or plugin-group rows;
      - a family's vocabulary, a domain's family, a mechanism's kit, a
        plugin-group owner, an override's scope element, or a kind-allowlist
        distribution that names nothing;
      - an exception or override owner that is not an unarchived directory
        under `openspec/changes/`.
- [x] 5.4 Tests in `scripts/tests/test_architecture.py` and
      `test_check_architecture.py`, each with a passing and a failing case:
      - a declared third-party dependency outside its allowlist;
      - an aliased import root;
      - an unknown package-table key;
      - a malformed project failing closed;
      - every `configuration` failure.

      The synthetic trees create the change directories their rows name.
- [x] 5.5 Documentation, bringing the promoted text in line with 5.1–5.3:
      - `docs/development/ARCHITECTURE.md`'s "Kind" places package allowlists and runtime
        reasons in a package's `pyproject.toml`;
      - its "Where the current tree diverges" names overrides beside exceptions
        as recorded divergences;
      - `docs/development/BUILD_AND_PACKAGING.md`'s check rows;
      - `AGENTS.md`;
      - `openspec/specs/market-composition/spec.md`'s evidence lines that cite
        the rules file's package allowlists;
      - `baseline.md`'s declarations section.
- [x] 5.6 Run `make check-architecture`, `make test-release-tooling`, comment
      hygiene, scoped citations, and strict validation.
      *Done.* All pass.
      - The tooling suite has 457 tests, including 68 in the two architecture
        modules.
      - Moving the tables changed no lock, because a `[tool.*]` table is not
        wheel metadata. The VM buyer's lock changed later, for the test
        dependency in 5.7.
      - The declaration side of the allowlists added `keyring` to the identity
        kit's list and `pydantic` to the provisioning client's.
      - No project fails closed today; the only one without a single wheel
        package is the virtual IaC project, which is skipped as before.

- [x] 5.7 Declare `arkhai-vms-settlement` in `domains/vms/buyer`'s `dev`
      dependency group. The audit had removed it as a runtime declaration with
      no import, and the CI suite then failed to collect a test that imports it;
      design, "A declaration can serve a project's tests".
- [x] 5.8 Build the wheelhouse for every CI job with an internal dependency:
      `predist: true` on `kit-resource-pools`, which has failed on `dev` since it
      first depended on the shape kit, and on `apicredits-sample-app`, which
      resolved a stale middleware release from the public index instead of this
      repository's code.
- [x] 5.9 Share the wheel-path rule: `scripts/check_project_layout.py` exposes
      `wheel_package`, and `scripts/architecture.py` discovers projects through
      it, so a wheel naming a missing package fails closed. Configuration
      validation refuses an owner that is not a single unarchived change name,
      finds duplicates under the normalized key, and refuses an exception for an
      unknown rule.
- [x] 5.10 A package with an allowlist must declare every third-party
      distribution it imports; the limits are stated in `ARCHITECTURE.md`'s
      "Kind".
- [x] 5.11 Rename budgets to allowlists:
      - the rules `kind_allowlist` and `package_allowlist`;
      - `[kind_allowlists]` in the rules file;
      - the library, scripts, tests, and the eleven package comments;
      - `ARCHITECTURE.md`, with both terms in its Terms table;
      - `BUILD_AND_PACKAGING.md`;
      - the `market-composition` scenario, in the delta and the synced spec;
      - the change documents.
- [x] 5.12 Validate. Passed:
      - `make check-architecture`, `make check-project-layout`, and the
        architecture and project-layout tests (82);
      - comment hygiene, scoped citations, and strict validation.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`, then read the
      docstrings of the new scripts directly for the provenance narration the
      target cannot catch. Exception rows are exempt only because they live under
      `docs/`.
- [ ] 6.2 **Import placement.** Every import in the new scripts and tests is at
      module level; confirm against the suites. The scripts import only the
      standard library and `scripts/architecture.py`.
- [ ] 6.3 **Documentation compliance.** Re-check the accepted decisions against
      `openspec/README.md`'s placement rules:
      - normative behavior in the three specs;
      - the conventions and scope bounds in `ARCHITECTURE.md`;
      - check inventory in `BUILD_AND_PACKAGING.md`;
      - and nothing durable left only in `design.md` or `baseline.md`.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final
      behavior, material evidence, deferred work (the 3.3 hand-offs), and
      destinations, moving rationale into `design.md` first.
- [ ] 6.5 **Roadmap currency.** This change sits under the lesser goal "Package
      and release readiness" and changes no goal's current state, so it most
      likely owes `docs/development/ROADMAP.md` nothing. Confirm that and record
      the no-impact disposition explicitly.
- [ ] 6.6 **Campaign index currency.** Update this change's row and the
      campaign's dependency graph in `openspec/changes/README.md`, including the
      unowned defects 1.7 recorded and the edges to every change that owns an
      exception row.
- [ ] 6.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=enforce-package-layers` and resolve every
      match, including any citation of `docs/development/ARCHITECTURE.toml`.
- [ ] 6.8 **Packaging.** Run `make check-packaging`, which now includes
      `check-architecture`, and resolve every failure. Run
      `make check-architecture-change CHANGE=enforce-package-layers` and confirm
      this change owns no exception row.
- [ ] 6.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the run and its result. This change alters no runtime path, so
      the evidence is that the pipeline is unaffected; the retired tests'
      packages also pass their own suites. If the pipeline cannot run for a
      reason unrelated to this change, record the blocker and its owning change,
      and treat the validations it gates as unrun.
- [ ] 6.10 **Promotion.** Add the design-promotion record to `design.md`, mapping
      every accepted decision to its permanent heading, and confirm no
      production source or script cites `openspec/changes/enforce-package-layers`.
