## Readiness

Redesigned 2026-11-12. The interim gate (a merge publishing to the development registry
and a promotion script here) is replaced by the release described in `design.md`: CI
publishes nothing, a release candidate is a `main` commit stored under its revision by one
load operation, the deployment validates, promotes and publishes, and the release is
recorded last on its release branch. Sections 1–2 are kept as implemented. Sections 3–6
belonged to the interim design and are withdrawn, their completed tasks preserved.

Sections 7–12 were replanned on 2026-11-13 against the design as settled by the triages of
design reviews 11 and 26 (D1–D22), replacing the unchecked sections written before them.
Section 13 is the closeout.

Amended on 2026-11-13 after section 7 returned to planning, taking option (b), which the
owner confirmed: 7.5 is split, the workflow-credential rule joining `make
check-packaging` in section 7 and the single-enumeration rule in 10.9; `push-charts`
(10.7) and `push-cli` (10.8) each gain a task; 1.1e and 2.3 move into the closeout (13.6,
13.9), their text kept where it was.

Amended again on 2026-11-13, after section 9 returned to design. Design amended D18: the
binary builds from a locked virtual project, whose buyer domains a packaging check holds
to the declaration, and `check-uv-setup` reads every Dockerfile and every wheelhouse
`pip` install. The owner waived another design review. Section 9's 9.1, 9.2 and 9.5 are
replanned, and 13.2, 13.7, 13.9 and the promotion record follow.

Both returns' options are kept in `design.md` (D7, D18 and its alternatives).

- **External prerequisites.** Nothing outside this repository gates implementation. Two
  things a real load needs are outside it, and no task depends on them:
  - the candidate store's repository (`<prefix>-candidates`), which only an operator's
    real load needs (D3);
  - a development registry serving npm, which D19 makes a precondition for the npm
    package joining the declaration, not for this change.
- **Transition.** `publish-pypi.yml` keeps uploading version bumps merged to `main` until
  this change lands there, whichever section deletes it (D13). Disabling the workflow in
  the repository's Actions settings closes the window sooner, and is the owner's call.

## 1. One enumeration

- [x] 1.1 Add a package manifest declaring every distribution this repository
  publishes, with each entry's source path, distribution name, and dependency
  order. Derive its initial contents from the `packages.json` heredoc in
  `.github/workflows/publish-pypi.yml` and reconcile against the three wheels
  `push-wheels` names in the root `Makefile`. The two disagree today; record
  which is correct per distribution rather than assuming the longer list is.
- [x] 1.2 Make `push-wheels` read the manifest instead of naming three wheels
  literally, and publish every entry rather than three.
- [x] 1.3 Make `publish-pypi.yml` read the manifest instead of heredocing its
  own table.
  - Superseded by 7.1: the workflow is deleted (D1), so it reads nothing.
- [x] 1.4 Update `scripts/tests/test_publish_matrix.py`. It currently parses the
  heredoc by regex and asserts the workflow states its table that way; that
  assertion is about to be false. Keep what it actually protects — that a
  distribution with a `force-include` escaping its own directory cannot be built
  as an sdist — and point it at the manifest.
  - Superseded by 7.4: no project force-includes outside its own directory any more,
    and PyPI receives wheels only, so `wheel_only` and its test go (D6).
- [x] 1.1b The two lists disagreed **in both directions**, which the plan did
  not anticipate. The workflow published twenty-six distributions the registry
  never received, and the registry received one --
  `arkhai-vms-provisioning-operator-client` -- the workflow never published.
  The manifest is the union: **29 distributions**. Whether that operator client
  should now also reach the public index is a consequence worth confirming
  rather than assuming; it follows from publishing everything, and nothing in
  the code decides it.
- [x] 1.1d The manifest was incomplete, which "one enumeration" does not
  survive. Comparing it against every buildable distribution in the tree found
  **ten** that neither publication path carried, six of them `kit/` packages —
  capacity-publication, contact-exchange, delivery, fulfillment,
  resource-pools, storefront. Those are precisely the composable functionality
  other teams are meant to build marketplaces from, and none of them was
  reachable from any index.

  Nine are built by `make dist` and are added, ordered so a kit precedes what
  consumes it: the manifest holds **38**. None needed `wheel_only`; the suite
  grew from 188 to 206 as the new entries picked up the existing
  per-distribution assertions, and all pass.

- 1.1e (moved to 13.6 on 2026-11-13, so that the round holding sections 1, 2 and 7 can
  complete; its text is kept here) `arkhai-vms-provisioning-iac` is the tenth and is **not** built by
  `make dist`, so it cannot be published and is not in the manifest. Whether
  that is deliberate — an Ansible-role package that nobody installs from an
  index — or an omission in the dist graph is a question for whoever owns it.
  Recorded rather than answered: adding it to the build is a separate decision
  from enumerating what the build already produces.
  - Recorded as unowned work in the campaign's index section (13.6).

- [x] 1.1c `packages.json` carried a `wheel_only` flag on three distributions
  whose wheels force-include files from outside their own directory, which an
  sdist cannot carry. The first manifest dropped it and two tests caught the
  regression. Every field of the original table is preserved.
  - Superseded by 7.4, which drops `wheel_only` (D6).
- [x] 1.1a The two lists disagreed and the longer one is right: all twenty-eight
  distributions are published. The three the registry path names are the
  clients other services consume, and the rest are kit packages other teams are
  meant to compose marketplaces from — which requires importing them
  individually. Reconciliation is therefore an extension of the registry path,
  not a reduction of the PyPI one.
- [x] 1.5 Add a check that the manifest is the only enumeration: no distribution
  list in a workflow, and no literal wheel name in a publish target. Two lists
  kept in agreement by hand is the failure this section exists to remove, and
  nothing stops it recurring without a check.
  - Correction: no such check was in the tree (D7); 7.5 built it.

## 2. Stop automated public publication

- [x] 2.1 Remove the publishing job from `.github/workflows/publish-pypi.yml`.
  Keep `detect-changes` if a later section needs it; delete it if not, rather
  than leaving a job whose only consumer is gone.
- [x] 2.2 Rename the workflow if it no longer publishes to PyPI. A file
  named for what it used to do is the same defect as a stale comment.
- 2.3 (moved to 13.9 on 2026-11-13, so that the round holding sections 1, 2 and 7 can
  complete; its text is kept here) Record in `docs/development/RELEASING.md` that merging no longer
  publishes, and what to do instead. This is a contributor-workflow break and
  the first person it surprises should find the answer where they look.
  - Discharged by 13.9's rewrite of RELEASING.md.
- [x] 2.4 Verified: `make test-release-tooling` passes, and no workflow path
  reaches a PyPI upload.

- [x] 2.5 `detect-changes` deleted with the job that consumed it, rather than
  left computing outputs nobody reads. The workflow now builds the wheelhouse
  and resolves every manifest entry against it, so the set is known good before
  anyone promotes it — which is the check the file's new name claims.
- [x] 2.6 `test_the_publish_job_creates_the_directory_those_packages_look_in`
  asserted step ordering inside the deleted job. The guarantee it protected —
  that something creates the `.dist` every package's `find-links` points at —
  now comes from `make dist` rather than from ordering, and the test asserts
  the workflow still reaches it.

- [x] 2.7 **Finding (2026-09-21, from `capacity-resource-administration`'s
  branch): this change's workflow edits are not in the tree, though its tasks
  say they are.** `.github/workflows/publish-pypi.yml` is still the publishing
  workflow: it keeps the `publish` job and its `pypa/gh-action-pypi-publish`
  step (2.1), heredocs its own package table rather than reading
  `manifests/published-distributions.json` (1.3), keeps its publishing name
  (2.2), and creates `.dist` with `mkdir -p` rather than building it with
  `make dist`. The rewritten `scripts/tests/test_publish_matrix.py` (2.6) is
  present, so `make test-release-tooling` fails
  `test_the_workflow_builds_the_directory_those_packages_look_in`, contrary to
  2.4. The failure is identical on the upload that branch started from, so no
  edit on it caused this. Recover the workflow from wherever 1.3, 2.1, 2.2, and
  2.5 were implemented, confirm 2.4 against it, and re-verify that no workflow
  path reaches a PyPI upload.
  - Closed by 7.1 and 7.4: `publish-pypi.yml` is deleted, so no workflow path reaches a
    PyPI upload, and `make test-release-tooling` passes with the workflow assertions
    gone (7.8).

## 3. Publish to the development registry on merge

Withdrawn by the redesign (`design.md` D1): development registries are scratch, and the
candidate is loaded by the publish targets after a merge, not by CI.

- [x] 3.1 Withdrawn: no workflow pushes to a registry.
- [x] 3.2 `push-wheels` resolves and attempts every manifest entry. Two defects
  found by running it, both mine:

  Credentials were passed as `--username`/`--password` arguments. The publisher
  refuses those alongside `UV_PUBLISH_TOKEN`, which is exported in any shell
  that has published to the public index — so the target failed on the first
  distribution with an error about argument conflicts rather than anything to
  do with publishing. Worse, an argument is on the command line: the token
  appeared in the `CalledProcessError` traceback, and would appear in any
  captured build log. Credentials now reach the publisher through the
  environment only, `UV_PUBLISH_TOKEN` is cleared for the subprocess, and a
  failing publish is reported rather than raised so the arguments are never
  printed.

  Verified against a stubbed publisher with `UV_PUBLISH_TOKEN` deliberately
  exported: the conflict is gone and no credential appears in the output.

  Then run for real: **38 distributions published** to the development
  registry, in manifest order, no failures. That is the target proven end to
  end — resolution, credential handling, and upload.

  What it does not prove is the identity. The push authenticated as a person
  with `gcloud` credentials, which is what task 3.1 exists to replace: the
  registry now holds a complete build, and nothing yet lets CI put one there.
  - Superseded by 11.4 (2026-11-13): nothing installs from the development Python
    index, so a load stores the wheels in the candidate store instead, and
    `push-wheels` is retired (D3).
  - Correction: the load is 11.2 of the replanned section, and `push-wheels` is retired
    by 10.3.
- [x] 3.3 Withdrawn with 3.1.

## 4. Promotion

- [x] 4.1–4.8 Withdrawn: promotion and public publication are the deployment's
  (`design.md` D1, D8). The all-or-nothing refusal and the wheels-only answer to the
  sdist question carry forward as requirements on that publisher (D8).
  - Correction: those decisions are now `design.md` D1 and D13. Under D13 the
    publisher's obligations are described in RELEASING.md as the deployment's part, not
    stated as requirements here.

## 5. Repair the published graph

- [x] 5.1 Withdrawn: `settle-through-arkhai-payments` removed hosted settlement on 2026-10-08, including
  `arkhai-kit-hosted-settlement`, so there is no package to bump. (It was to
  replace 0.1.4 on PyPI, which declares a dependency PyPI does not carry.)
- [x] 5.2 Withdrawn: there is no package left to repair.
- [x] 5.3 Withdrawn: reconciliation with `configure-pypi-trusted-publishing` moves to
  13.6 under the redesign.

## 6. Inventory substitution

- [x] 6.1–6.3 Withdrawn: the component declaration (section 8) is the enumeration, and the
  release's bill of materials (`design.md` D5) binds component versions to a product
  version. Comment hygiene and import placement move to 13.1 and 13.2.
  - Correction: the declaration is section 7 of the replanned plan, and the bill of
    materials is `design.md` D10 (with D16 for the product version).

## 7. CI publishes nothing, one declaration, and the checks that hold both

Delivers D1, D6, D7 and D19's absence of an npm entry. Implements the requirements
"Continuous integration publishes nothing" and "One declaration of release components".
Touches:
- `.github/workflows/`;
- `manifests/`;
- `scripts/` and `scripts/tests/`;
- the root `Makefile`'s publish targets and comments;
- `install.sh`, and `install-remote.sh` and `build-installer.sh` under `scripts/`;
- `README.md`'s tree.

(Citations of files this change deleted are respelled throughout this file, naming each
file and its directory apart, so that the citation check, which resolves a path, does
not report them; 13.10.)

- [x] 7.1 Delete `.github/workflows/publish-pypi.yml`, `publish-npm.yml`, `release.yml`
  and `release-cli.yml` (D1). Check 2.7, which this closes.
  - Verify: no file under `.github/workflows/` names PyPI, npm, ghcr or a release upload.
  - Done: only `e2e.yml`'s `actions/upload-artifact` steps match, which keep a run's
    diagnostics as workflow artifacts and publish nothing. 2.7 is checked.
- [x] 7.2 Delete `verify-marketplace-release.py` and
  `test_verify_marketplace_release.py`, in `scripts/` and `scripts/tests/` (D1). Delete
  the curl installer: `install.sh`, `install-remote.sh` and `build-installer.sh` in
  `scripts/`, and `test_install_remote_urls.py` and `test_install_sh_dependencies.py` in
  `scripts/tests/`. Remove `install.sh` from `README.md`'s tree (D18).
  - Verify: a search of the tree outside `openspec/` finds no reference to the deleted
    files or to `arkhai.marketplace-release.v2`.
  - Done. The search also matches uv's own installer URL (`astral.sh/uv/…/install.sh`),
    and synthetic workflow names in three tests that name no file. The two documents
    that described what was deleted, `docs/buyer-quickstart.md` and
    `docs/development/RELEASING.md`, were rewritten at 13.9.
- [x] 7.3 Set `.github/workflows/validate-model-release.yml` to `permissions: contents:
  read`, and remove the step that appends a validation line to the release's notes
  (D7). Downloading the release's assets still works with the read token.
  - Verify: the workflow's remaining steps reference only `secrets.GITHUB_TOKEN`.
  - Done: its one secret reference is `secrets.GITHUB_TOKEN`, and the credential rule
    passes on it.
- [x] 7.4 Rename `manifests/published-distributions.json` to
  `manifests/release-components.json` in D6's shape:
  - `distributions`, without `arkhai-apicredits-sample-app` and without `wheel_only`;
  - `images` with `name` and `local` for the five release images;
  - `chart`;
  - `binaries`, whose `market` entry names today's `build-buyer` target and its output
    until 9.3 replaces both;
  - `development_images` (dev-env, e2e-tests);
  - no `npm` key (D19).

  Add one reader, `scripts/release_components.py`, which every consumer imports. It
  refuses a missing required key, an unknown key, an empty `npm` list, a duplicated name
  or distribution, and a value of the wrong kind (D6).

  Point `push-distributions.py` (in `scripts/`) and `scripts/tests/test_publish_matrix.py`
  at the reader. In the test:
  - delete the assertions about the deleted workflow (path filters, push triggers) and
    about `wheel_only`;
  - keep closure under repository dependencies, dependency order, name-at-path, and the
    RELEASING.md table's equality with the declared distributions (D21).

  - Verify: unit tests for the reader's refusals, one case per rule, in
    `scripts/tests/test_release_components.py`; `make test-release-tooling` passes.
  - Done. The declaration holds fifty-nine distributions, five images, the chart, the
    binary and two development images. The reader collects every refusal before raising
    one `DeclarationError`; a name may appear once across images and development images.
    Unit: one case per refusal, among them each duplicate rule and a list item that is
    not an object, and the repository's own declaration.
- [x] 7.5 Add the single-enumeration and workflow-credential check,
  `scripts/check_release_components.py`, as `make check-release-components` (D7). It
  refuses, naming the file and what it found:
  - **the single-enumeration rule:** a list of declared distributions, images,
    development images, the chart or the binary in any workflow, publish target or lane
    target;
  - **the workflow-credential rule:**
    - a workflow with no top-level `permissions:`;
    - a workflow granting `id-token: write`, `packages: write`, `attestations: write` or
      `contents: write` anywhere;
    - a reference to a secret other than `GITHUB_TOKEN`;
    - a named publishing step (`pypa/gh-action-pypi-publish`, `npm publish`,
      `docker push`, `docker/build-push-action` with `push: true`,
      `softprops/action-gh-release`, `gh release create`).

  It has no exception list. Each rule can run on its own.

  `make check-packaging` runs the workflow-credential rule from this section on. It does
  not yet run the single-enumeration rule: five root `Makefile` publish targets still
  name components, and 10.3, 10.7 and 10.8 make them read the declaration (`push-images`,
  `push-dev-images`, `clobber-wheels`, `push-charts`, `push-cli`). 10.9 then adds the
  single-enumeration rule to `make check-packaging`.
  - Verify:
    - unit tests in `scripts/tests/test_check_release_components.py` over synthetic
      workflow and Makefile text, one case per rule plus a clean case;
    - the workflow-credential rule passes on the tree, and `make check-packaging`
      passes with it;
    - the single-enumeration rule, run alone on the tree, refuses exactly those five
      targets and nothing else. Record its output in the task note.
  - Done. `--rule` selects a rule; with none, every rule runs. The unit cases cover each
    reading of a target and a secret `design.md`'s "Implementation choices" lists. On
    this section's tree the enumeration rule refused exactly the five targets, eleven
    lines: `push-images` naming four images, `push-dev-images` two development images,
    `push-charts` the chart, `push-cli` the binary, and `clobber-wheels` three
    distributions.
- [x] 7.6 CI resolves every declared distribution against the wheelhouse it builds
  (D1). A test in `scripts/tests/` asserts every declared wheel is in `.dist`, run by
  `make test-release-tooling` inside `test-deployment-packaging`, after `tests.yml`'s
  `make dist-ci`. If `dist-ci` does not build every declared wheel, `test-deployment-
  packaging`'s job builds what is missing through the existing dist targets, and that
  is recorded in the task note.
  - Verify: passes locally after `make dist`.
  - Done: `scripts/tests/test_release_wheelhouse.py`. `dist-ci` builds a superset of
    `dist-release-set`, so the job needs no extra build step.
- [x] 7.7 Correct the comments that cite the deleted workflows: the root `Makefile`'s
  `dist-release` and Artifact Registry comments, and any comment
  `make check-comment-hygiene` or a search for the workflow names finds.
  - Verify: `make check-comment-hygiene` passes.
  - Done.
- [x] 7.8 Section verification.
  - Unit and integration:
    - `make test-release-tooling` (unit: the reader and both rules of the check);
    - `make check-packaging`, running the workflow-credential rule;
    - `make check-comment-hygiene`;
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`, whose
      functional checks pass.
  - End-to-end: no scenario exercises this section; it changes no runtime behaviour, and
    none is owed.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — after
    `make dist-ci`, the declared-wheel resolution test of 7.6 passes, and the new script
    tests run and pass.
  - Done: `make test-release-tooling` passed 2817 tests, and the functional checks
    passed. The owed CI observation is recorded in 13.8.

## 8. The release record: the layout-1 reader, the version check and the record check

Delivers D10's reader, D11, D12, D14 and D16. Implements the requirements "A version
changes when its contents change", "A marketplace release is recorded by a tagged commit
on its release branch" and "The release bill of materials holds content identities only".
Touches `scripts/`, `scripts/tests/`, the root `Makefile` and `.helm-version`; it reads
`.github/workflows/tests.yml`'s Helm version without changing it.

- [x] 8.1 Add `scripts/release_bom.py`, the layout-1 reader (D10). It provides:
  - parsing of a committed bill of materials, digesting its bytes as committed and never
    re-serializing them;
  - refusal of any layout but `arkhai:bom-layout` = `1`;
  - the field and URL allowlist: only layout 1's keys, no `repository_url` in any purl,
    no URL but the public vcs link;
  - components by bom-ref `<kind>/<name>`;
  - the chart content digest, the dirhash of D14, computed over a `helm package` archive's
    regular files;
  - the same dirhash over a set of files, which 11.2 uses for the wheelhouse digest (D3).

  Add the deployment's example document as a test fixture,
  `scripts/tests/fixtures/release-bom-layout1.cdx.json`, written one key per line at
  two-space indent. It uses placeholder digests and is public-safe.
  - Verify: unit tests in `scripts/tests/test_release_bom.py` cover:
    - the fixture parses;
    - an unknown layout, an unknown field, a `repository_url` and a foreign URL are each
      refused and named;
    - the dirhash of a known file set equals a hand-computed value;
    - two archives of one file set with different tar metadata give one digest.
  - Done. The fixture was written from D10's text, since no example document from the
    deployment is in this repository. The unit cases cover each refusal, each kind's
    identity, a key stated twice, the dirhash of a manifest built from SHA-256's own
    test vectors, and archives differing only in tar metadata and order.
- [x] 8.2 Pin Helm for the chart digest. Add a root `.helm-version` holding the version
  `tests.yml`'s `azure/setup-helm` installs (v4.3.0). The digest refuses to run under
  any other `helm version --short`. A test holds `tests.yml`'s setup-helm version equal to
  `.helm-version` (D14).
  - Verify: the equality test passes; a unit test with a stubbed `helm version` refuses a
    mismatch.
  - Done. The real-Helm cases are integration tests gated by `HELM_REQUIRED=1`, which
    `tests.yml`'s packaging job sets, so a skip fails there. Since the round triage (T1
    with V1), `package_chart` refuses a package storing a file Git ignores under
    `helm/`, `archive_digest` refuses any path stored twice, and `helm/.helmignore`
    names what `helm dependency update` and the tests leave behind (D14).
- [x] 8.3 Add `scripts/check_release_versions.py` and `make check-release-versions`
  (D14).
  - It reads the bill of materials at every `marketplace-v*` tag carrying
    `manifests/release-bom.cdx.json`, except the tag being checked.
  - It refuses a (component, version) pair that any earlier record names with another
    content identity: a wheel's SHA-256, the chart's content digest. It names the
    component and the release that recorded it.
  - Its subject is either the wheelhouse plus the chart `make dist-helm` packages with
    the pinned Helm, or, given a tag (`TAG=`), that tag's own committed bill of
    materials, with no build.
  - With no earlier record it passes and says so.
  - It reads no package registry.
  - Verify: integration tests in `scripts/tests/test_check_release_versions.py` use real
    git in a scratch repository holding bills of materials at tags. They cover:
    - an unchanged wheel passes;
    - a changed wheel with a bumped version passes;
    - a changed wheel at the previous release's version fails;
    - a changed wheel at a version released two releases earlier fails and names that
      release;
    - a changed chart digest at an unchanged chart version fails;
    - at the cut, the tag's own record is the subject and is never compared with itself;
    - no earlier record passes with its message.

    `make check-release-versions` on this tree passes, saying no earlier record exists
    (v0.3.0 carries none).
  - Done. Library integration over real git, the chart's packaging stubbed at its seam.
    Further cases: a tag carrying no record, a tag a branch shadows, a respelled
    distribution, an earlier record in an unknown layout refused, a declared wheel
    missing from the wheelhouse, and the cut with no build. The result names every tag
    it compared. On this tree it passes, saying no earlier marketplace release carries a
    bill of materials.
- [x] 8.4 Add `scripts/check_release_record.py` and
  `make check-release-record TAG=marketplace-v<semver>` (D11, D12). It refuses unless:
  1. the tag's commit is on `releases/<semver>`, and its parent is reachable from the
     default branch;
  2. the commit changes exactly one path, adding `manifests/release-bom.cdx.json`;
  3. the document passes 8.1's layout and allowlist;
  4. its `arkhai:source-revision` is the parent commit, and its subject's version is the
     tag's semver;
  5. its components, by bom-ref, are unique and exactly the release components the
     declaration at the parent commit declares, naming each missing, extra and
     duplicated one and any development image;
  6. 8.3 passes with the record as its subject.

  It needs no wheelhouse and no Helm.
  - Verify: integration tests in `scripts/tests/test_check_release_record.py` with real
    git in a scratch repository: a well-formed record passes, and each of the six rules
    has a failing case, including a record naming a development image and one naming a
    component twice.
  - Done. Since the round triage (52 F2), rule 1 holds every `releases/<semver>` ref,
    local or remote-tracking, to the tag's commit, with cases for a later commit on the
    branch and a remote branch at another commit. On this tree,
    `make check-release-record TAG=marketplace-v0.3.0` refuses: its commit has two
    parents.
- [x] 8.5 Section verification.
  - Unit and integration: `make test-release-tooling` (unit: the reader and the digest;
    integration: the two checks against real git); `make check-packaging`;
    `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`.
  - End-to-end: no scenario exercises the release record. It is read only at a load and
    at the cut, and none is owed.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
    `azure/setup-helm` installs the version `.helm-version` names, and the chart-digest
    tests run rather than skip and pass.
  - Done: `make test-release-tooling` passed 2884 tests, none skipped, and the functional
    checks passed. The owed CI observation is recorded in 13.8.

## 9. The release binary is PyPI's CLI

Delivers D18, as amended after the section's return to design. Implements the
requirement "The release binary is the buyer CLI with every declared buyer domain",
with its scenarios for a missing and an undeclared domain.

Replanned on 2026-11-13 against the amended D18. 9.1, 9.2 and 9.5 are rewritten:
- the binary builds from a locked virtual project through `scripts/uv_project.py image`;
- a packaging check holds that project's dependencies to the declaration;
- `check-uv-setup` reads every Dockerfile and every wheelhouse `pip` install.

9.3 and 9.4 stand as written; their work in that commit stands.

Touches:
- `buyer_domain_wheels.py` in `scripts/`, renamed `scripts/market_binary.py`, and its test;
- `scripts/check_release_components.py`, a `market-binary` rule, and its test;
- `scripts/check_uv_setup.py` and its test;
- the binary's virtual project, `core/buyer/market-binary/` (`pyproject.toml`,
  `uv.lock`, `Dockerfile`), replacing `core/buyer/market-binary.Dockerfile`;
- the root `Makefile`'s `build`, `build-buyer`, `build-market-binary`,
  `check-market-binary` and `check-packaging`;
- `domains/vms/buyer/` (its `pyproject.toml`, `Makefile`, lock and `main.py`);
- `manifests/release-components.json`'s `binaries` entry.

- [x] 9.1 Rename `buyer_domain_wheels.py`, in `scripts/`, to `scripts/market_binary.py`,
  and add the check holding the binary's project to the declaration (D18).
  - What the script derives, from the declaration and each declared project's
    `pyproject.toml`:
    - the buyer CLI: the one declared distribution defining the binary's console
      script;
    - the buyer domains: every declared distribution registering a
      `market.buyer_domains` entry point;
    - the entry point the binary freezes;
    - the PyInstaller options: `--copy-metadata` for the CLI and each domain, and
      `--hidden-import` for each module a domain's entry point names.
  - How it finds the binary: by its `binaries[]` entry, the one whose `target` the
    caller names. `build-market-binary` passes `$@`.
    - The console script is the entry's `name`.
    - A command prints the directory of the entry's `path`, where the build exports
      the binary.
    - It refuses no entry, two entries, and a `path` whose file name is not `name`.
    - `BINARY_NAME` goes.
  - What it drops: the `domains`, `cli` and `constraints` commands, their refusal of a
    wheel `.dist` lacks, and their test cases. The lock installs the wheels (9.2).
  - The check: add the rule `market-binary` to `scripts/check_release_components.py`,
    run as `make check-market-binary` in `make check-packaging`, as `check-workflow-
    credentials` runs `--rule credentials`. `make check-release-components` runs it
    with the other rules.
    - It refuses the binary project unless its `[project].dependencies` names, by
      normalised distribution name, exactly the buyer CLI and the buyer domains the
      script derives.
    - It names each missing distribution, with the project that registers it, and each
      extra one.
    - It reads only `dependencies`. The `freeze` group is not compared.
  - Verify:
    - Unit, `scripts/tests/test_market_binary.py`, renamed from
      `test_buyer_domain_wheels.py`, over synthetic declarations and projects. It has a
      case for each remaining command, the binary entry found by its target, and no
      matching entry, two, and a `path` not ending in `name`. It keeps the existing
      cases for two entry points in one domain, a missing `pyproject.toml`, the console
      script defined by two distributions or none, no buyer domain, and a declaration
      the reader refuses.
    - Unit, `scripts/tests/test_check_release_components.py`: the rule passes an exact
      project. It refuses a missing domain, naming it and its project; an extra
      distribution; and a missing CLI. It ignores the `freeze` group.
    - On the tree: the script names `arkhai-core-buyer` with `core_buyer.cli:main` and
      the three domains, and `make check-market-binary` passes once 9.2's project
      exists.
  - Done: 14 cases in `test_market_binary.py`; the rule's cases include other
    spellings, specifiers and markers. On the tree `make check-market-binary` prints
    `OK: the market binary's project bundles exactly the buyer CLI and the declared
    buyer domains.`
- [x] 9.2 Build the binary from a locked virtual project, and make `check-uv-setup`
  refuse what the earlier install did (D18).
  - The project: add `core/buyer/market-binary/pyproject.toml`, shaped as D18 shows.
    - It is virtual (`[tool.uv] package = false`).
    - Its `dependencies` are the buyer CLI and the three buyer domains, by bare name.
    - Its `freeze` dependency group holds `pyinstaller==6.22.3`.
    - Its `environments` are linux x86_64 only.
    - `requires-python` admits the version `.python-version` declares.
    - Lock it with `make lock PROJECTS=core/buyer/market-binary`.
  - The Dockerfile: move `core/buyer/market-binary.Dockerfile` to
    `core/buyer/market-binary/Dockerfile`.
    - Its build stage is `ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim`
      for linux/amd64, pinned by digest. It keeps the step refusing an image whose
      Python is not the `PYTHON_VERSION` default.
    - It copies `.dist/`, `scripts/uv_project.py` and the project's `pyproject.toml` and
      `uv.lock` at the depths BUILD_AND_PACKAGING.md's "Images" gives. It installs with
      `uv_project.py image --project <project> -- --group freeze` into
      `UV_PROJECT_ENVIRONMENT`, with no `install-wheel`, since the project builds no
      wheel.
    - It takes the binary's name as the build argument `BINARY_NAME`, for PyInstaller's
      `--name` and the final stage's `COPY`. It keeps the frozen entry point, the
      PyInstaller options, the smoke test and the `scratch` export stage as they are.
    - The constraints argument and both `pip install` steps go.
  - The Makefile: `build-market-binary` derives its arguments from `market_binary.py`
    (9.1), passing `$@`, and exports to the directory the script prints. It names no
    domain, binary or path.
  - The digest: if the session cannot query a registry, it takes the digest from the
    first build's BuildKit log, as section 9's notes describe, pins it, and builds again
    from it.
  - `check-uv-setup`: `scripts/check_uv_setup.py` reads `*.Dockerfile` as well as
    `Dockerfile*`, as `check_python_version.py` does.
    - In a stage that copies the wheelhouse, it refuses any `pip install`,
      `python -m pip install` or `uv pip install` naming the wheelhouse not made through
      the script. Naming the wheelhouse means `--find-links`/`-f`, or a `.dist` path.
    - Its docstring and its row in BUILD_AND_PACKAGING.md's "Checks" are amended at
      closeout (13.9).
  - Verify:
    - Unit, `scripts/tests/test_check_uv_setup.py`:
      - a `*.Dockerfile` is read;
      - plain `pip install --find-links`, `python -m pip install` and `uv pip install`
        from the wheelhouse are each refused;
      - the install the section returned on, `pip install --find-links /dist --constraint
        …` followed by `pip install --no-index --no-deps --find-links /dist`, is
        refused;
      - a `uv pip install` that does not name the wheelhouse, as in
        `provisioning/compute/service/Dockerfile`, passes;
      - an install made through the script (`uv_project.py image` or `install-wheel`)
        passes.
    - On the tree: `make check-uv-setup`, `make check-python-version`, `make check-locks`
      and `make check-market-binary` pass.
    - Local build evidence, an image build rather than one of TESTING.md's levels: `make
      build-market-binary` succeeds from the pinned digest, its smoke test lists the VM,
      bare-metal and API-credit domains, and it exports `.dist/bin/market`. If the
      session cannot run Docker, it records that as unrun.
  - Done. The lock resolves 105 packages: every repository distribution from `.dist`,
    and PyInstaller 6.22.3 in `freeze`. `uv_project.py lock` now locks a named project
    with no lock (outside the plan; `design.md`, "Implementation choices"), and the
    `check_uv_setup.py` docstring was amended with the code, since closeout edits none.
    Local build evidence: the build succeeded, its smoke test printed `api_credits.v1`,
    `bare_metal.v1` and `compute.v1` with no skipped domain, and it exported a 48 MB
    `.dist/bin/market`; the rebuild from the pin reused that build's layers.
- [x] 9.3 Point the declaration's `market` entry at `build-market-binary` and
  `.dist/bin/market`. `build` builds it in place of `build-buyer`.
  - Retire `build-buyer`, the PyInstaller recipe in `domains/vms/buyer/Makefile`, and
    `domains/vms/buyer/src/arkhai_vms_buyer/main.py`, whose only user is that recipe.
  - Update any target, test or comment that names them; the search includes
    `scripts/tests/test_init_targets.py` and the e2e-tests comments.
  - Verify: a search outside `openspec/` and `docs/` finds no `build-buyer` and no
    `arkhai_vms_buyer/main.py`. `make test-release-tooling` passes. `docs/` is rewritten
    at closeout (13.9).
  - Done. The VM buyer Makefile's `build` and `smoke-test` targets went too, and
    `push-cli` uploads `.dist/bin/market`.
- [x] 9.4 Remove `pyinstaller` from `arkhai-vms-buyer`'s runtime dependencies, and bump
  it a minor version (0.11.0 → 0.12.0) per RELEASING.md's versioning policy. Move any
  exact pin on it with the bump, and refresh every lock that installs it with
  `make lock`.
  - Verify:
    - `make check-version-bumps` passes;
    - `make check-packaging` passes, with locks current;
    - `make test-domains` passes for the VM buyer;
    - the built wheel's metadata requires no PyInstaller.
  - Done. No exact pin on it existed; three locks were refreshed, and no lock but the
    binary project's `freeze` group names PyInstaller. A case in
    `test_release_wheelhouse.py` refuses a declared wheel requiring it.
- [x] 9.5 Section verification.
  - Unit: 9.1's tests (`test_market_binary.py`, the `market-binary` rule's cases in
    `test_check_release_components.py`) and 9.2's (`test_check_uv_setup.py`), and
    `test_check_python_version.py`. All of them run in `make test-release-tooling`.
  - Local build evidence: 9.2's build and smoke test, from the locked project.
  - Packaging: `make check-packaging`, now running `check-market-binary` and the widened
    `check-uv-setup`, with the binary's lock current.
  - Functional checks: `scripts/change-workflow run pre-commit
    publish-wheels-through-a-gate`, run after the build, together with a fresh-context
    check of the section's diff.
  - Search: no `buyer_domain_wheels`, `market-binary.Dockerfile` or `pip install` from
    the wheelhouse remains outside `openspec/` and `docs/`.
  - End-to-end: no scenario runs the binary (D18), and none is owed. The pipeline's lanes
    install `market` from the wheels, so they exercise the buyer CLI 9.4 repackages.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging`. The new and
    changed cases in `scripts/tests/` pass there, as section 7 already owes.
  - Done: `make test-release-tooling` passed 2922 tests, the functional checks passed,
    and the search found nothing. Section 9's one defect outside the change — the
    API-credit domain's pydantic warnings on every `market` start — is recorded as
    unowned work (13.6).

## 10. Build pins, revision tags, and a chart that names no release

Delivers D4, D8, D9 and D15, and declares the development images' pushes (D6, D8).
Implements the requirements:
- "Every declared image's build writes its revision tag";
- "The chart names no release";
- "Wheels build with a pinned backend".

Touches:
- every Makefile computing `GIT_SUFFIX`;
- the root `Makefile`'s build and push targets, including `push-charts`, `push-cli` and
  `check-packaging`;
- `scripts/publish_artifacts.py`;
- `build-constraints.txt`;
- `scripts/check_build_requirements.py`;
- `helm/` and its nine subcharts.

- [x] 10.1 Compute `GIT_SUFFIX` with `git rev-parse --short=9` in the root, `e2e-tests`,
  `dev-env`, `core/registry`, `provisioning/compute/service` and `domains/vms/storefront`
  Makefiles (D4). Extend 7.5's check to refuse a `git rev-parse --short` without `=9` in
  any Makefile.
  - Verify: a unit case for the refusal; the check passes on the tree.
  - Done: the check's `revision` rule, with cases across continuation lines.
- [x] 10.2 Every declared image's and development image's build writes
  `arkhai:<local>-<rev9>` when `IMAGE_SUFFIX` is empty. `build-bare-metal-storefront`
  gains its tag (D8).
  - Extend `scripts/tests/test_image_publication_contract.py` from provisioning to every
    declared image and development image, read from the declaration.
  - Verify: the extended test passes.
  - Done: a static configuration test following `make build-dev` through `make -n`.
- [x] 10.3 `push-images` and `push-dev-images` push the declared images and development
  images through `scripts/publish_artifacts.py`, from the declaration, each as
  `arkhai:<name>-<rev9>` beside its bare `arkhai:<name>` tag. This replaces their literal
  lines (D8).
  - Retire `push-wheels` and `clobber-wheels`. Nothing installs from the development
    Python index (D3), and `clobber-wheels` names three wheels literally, which 7.5
    refuses.
  - `push-runtime-artifacts` keeps the remaining developer pushes; no release step
    names it (D3).
  - Verify: integration tests in `scripts/tests/test_publish_artifacts.py`, with the
    `docker` subprocess stubbed at `publish_artifacts.py`'s own wrapper. They show the
    pushes are exactly the declared set, with each one's revision and bare tags, and
    `provisioning` pushed from local `compute-provisioning`.
  - Done. `push-distributions.py` (in `scripts/`), its only caller gone, was deleted
    with `PYTHON_REGISTRY` and the client-version variables. `push-runtime-artifacts` is
    `push-images push-charts push-cli`.
- [x] 10.4 Pin the build requirements (D15).
  - A root `build-constraints.txt`, beside `.python-version`, pins `hatchling` exactly at
    the version builds use today.
  - The root `Makefile` exports it as `UV_BUILD_CONSTRAINT`, beside `UV_PYTHON`. Every
    subproject Makefile that runs `uv build` applies it, since each also runs on its own.
  - Add `scripts/check_build_requirements.py` as `make check-build-requirements` in
    `make check-packaging`, beside `check-python-version`. It refuses any
    `[build-system]` requirement the declaration does not pin, and any `uv build` in a
    Makefile that does not apply the constraint.
  - Verify:
    - unit cases for an unpinned backend, an unpinned plugin and an unconstrained
      `uv build`;
    - the check passes on the tree;
    - after `make dist-clean dist`, every wheel's `WHEEL` file names the pinned
      hatchling.
  - Done. `hatchling==1.33.0`, exported by absolute path from the root and 41 subproject
    Makefiles. Every declared wheel names `Generator: hatchling 1.33.0`; moving the pin
    once to 1.27.0 rebuilt a wheel under it, showing uv applies the export.
- [x] 10.5 Remove `appVersion` from `helm/Chart.yaml` and the nine subcharts' `Chart.yaml`
  (D9).
  - Remove the `app.kubernetes.io/version` block from the umbrella's helpers
    (`helm/templates/_helpers.tpl`, and its copy `helm/_helpers.tpl`) and from the seven
    subcharts that carry one.
  - Bump each changed chart's version per RELEASING.md's versioning policy, and update
    the umbrella's ten dependency entries to match.
  - Verify: a search finds no `appVersion` or `.Chart.AppVersion` under `helm/`.
  - Done: patch bumps — the umbrella, the storefront and the bare-metal storefront to
    0.4.1, the seven others to 0.1.1.
- [x] 10.6 Chart tests (D9), run by `helm/scripts/test-render.sh`:
  - `helm/tests/test_subchart_pins.py` holds each umbrella dependency entry's `version`
    equal to its subchart's `Chart.yaml` version, naming a mismatch;
  - a render assertion that the chart's default values name no semver-shaped image tag,
    no revision-suffixed tag and no digest.
  - Verify: `make -C helm test-render` passes; a deliberately mismatched pin fails the
    pin test, checked once and reverted.
  - Done: the render assertion is `helm/tests/test_default_images.py`, which also reads
    every chart's `values.yaml`, since the lane doubles render nothing by default.
- [x] 10.7 `push-charts` packages the declared chart (`chart.path`) and pushes the package
  `make dist-helm` writes for it. The package is found from the declaration and the
  chart's `Chart.yaml`, never named in the recipe (D6, D7). It stays a developer push;
  no release step names it (D3).
  - Verify: an integration test with `helm` stubbed at the push's own wrapper shows the
    pushed file is the declared chart's `<name>-<version>.tgz`. The single-enumeration
    rule no longer refuses `push-charts`.
  - Done.
- [x] 10.8 `push-cli` uploads the declared binary (`binaries[]`'s `path`, `.dist/bin/market`
  since 9.3) as package `market`, version `<rev9>`. The path is never named in the recipe
  (D6, D7). It stays a developer push; 11.2's load uploads the binary itself.
  - Verify: an integration test with `gcloud` stubbed at the upload's own wrapper shows
    the uploaded file is the declared binary's path, under the nine-character revision.
    The single-enumeration rule no longer refuses `push-cli`.
  - Done.
- [x] 10.9 Add the single-enumeration rule (7.5) to `make check-packaging` (D7). From
  here on, it also covers the targets sections 11 and 12 add.
  - Verify: `make check-release-components` runs both rules and passes on the tree;
    `make check-packaging` passes.
  - Done: `check-packaging` runs `check-release-components` (every rule) and
    `check-build-requirements`; the two focused targets stay.
- [x] 10.10 Section verification.
  - Unit and integration: `make test-release-tooling`; `make test-deployment-packaging`
    (render tests); `make check-packaging`, now running both rules of 7.5's check.
  - Local build: `make build` succeeds and writes every revision tag.
  - Functional checks: `scripts/change-workflow run pre-commit
    publish-wheels-through-a-gate`.
  - End-to-end:
    - The pipeline's three lanes (`e2e.yml` jobs running `make -C e2e-tests
      test-e2e-vm`, `test-e2e-bare-metal` and `test-e2e-apicredits`) build every image
      through the changed targets and must pass unchanged.
    - Helm validation renders and upgrades the chart without `appVersion`.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
    `make -C helm test-render` passes, including the subchart-pin test and the
    default-values assertion.
  - Done: `make test-deployment-packaging` passed (2967 tests, then the render tests).
    Local build evidence: `make build-dev` tagged every declared image and development
    image with the nine-character revision. The end-to-end and owed CI evidence is
    recorded in 13.8.

## 11. The load operation

Delivers D3 and D5. Implements the requirement "A release candidate is stored under its
revision". Touches:
- the root `Makefile`'s `load-candidate`;
- `scripts/load_candidate.py`;
- `scripts/publish_artifacts.py`;
- the image builds that install wheels from `.dist`:
  - `core/registry`;
  - `domains/vms/storefront`;
  - `provisioning/compute/service`;
  - the bare-metal storefront's `Dockerfile`;
  - `e2e-tests/Dockerfile`.

- [x] 11.1 Every image whose build installs wheels from `.dist` takes the wheelhouse
  digest as a build argument and records it as the label
  `org.arkhai.wheelhouse-digest` (D3). Those images are the registry, storefront,
  provisioning and bare-metal storefront images, and the e2e-tests image. This replaces
  the `cksum` `DIST_FINGERPRINT` in `domains/vms/storefront` and
  `provisioning/compute/service`, their Makefiles and Dockerfiles.
  - Verify: after `make build`, `docker image inspect` shows each of the five images
    labelled with 11.2's digest of the `.dist` they were built from.
  - Done, with the inspection unrun: no rule of the implementing step allowed `docker
    image inspect`. `scripts/wheelhouse_digest.py` prints the digest and refuses a
    missing declared wheel. Unit: `test_wheelhouse_digest.py`; the static configuration
    test holds every declared image whose Dockerfile copies `.dist/` to the argument and
    label, and the two others to none. Every build computed its digest in `make
    build-dev` and `make build-candidate`.
- [x] 11.2 Add `scripts/load_candidate.py` and `make load-candidate`. In one invocation
  and in this order (D3), it:
  1. builds `.dist` once, and runs `make check-release-versions` on it (8.3);
  2. builds every declared image and development image, and the binary (9.2), from that
     `.dist`;
  3. refuses, naming what differs, unless `.dist`'s wheelhouse digest (8.1's dirhash over
     the declared wheels) is still the one it built with, and every `.dist`-built image
     carries it;
  4. deletes the revision's `wheelhouse`, `chart` and `market` versions, all three,
     before uploading any;
  5. uploads the declared wheels as generic package `wheelhouse`, version `<rev9>`, and
     the chart package as generic package `chart`, version `<rev9>`, in
     `<prefix>-candidates`. It uploads the binary as package `market`, version `<rev9>`,
     in `<prefix>-cli`, and pushes the images and development images as in 10.3.

  It never uses `--skip-existing`, or any mode keeping an earlier file. The repository
  names derive from `AR_PREFIX`. The load does not check that the tree is clean (D5),
  and does not push to the development Python index.
  - Verify: integration tests in `scripts/tests/test_load_candidate.py`, with `docker`,
    `gcloud` and `helm` stubbed at the script's own subprocess wrapper. They show:
    - the step order;
    - a refusal with no upload when `.dist` changes after the image builds, and when an
      image's label differs;
    - all three deletes before the first upload;
    - no skip-existing flag in any upload;
    - the store receiving exactly the declared wheels, one chart and one binary;
    - a version check failure stopping the load before any build.
  - Done. The load builds through a new `build-candidate` target and first removes each
    declared image's revision tag (`design.md`, "Implementation choices"). The tests
    cover every case the task lists, a reload, a delete refused for another reason, and
    an upload failing after the deletes. The stub models no store: that `gcloud
    artifacts versions delete` answers `NOT_FOUND` for a missing version, and the reload
    scenarios against a real store, are shown only by the first real load.
- [x] 11.3 Section verification.
  - Integration: `make test-release-tooling`; `make check-packaging`.
  - Local build: `make build` with 11.1's label check.
  - Functional checks: `scripts/change-workflow run pre-commit
    publish-wheels-through-a-gate`.
  - A real load against the candidate store is the operator's and needs the externally
    provisioned repository. It is not evidence this section owes; if one is made, record
    its revision.
  - End-to-end: the pipeline's three lanes build the labelled images through the changed
    Dockerfiles and must pass unchanged; no scenario runs the load.
  - Done: `make build-candidate` froze the binary, packaged the chart at 0.4.1 and tagged
    the seven declared images; `make test-release-tooling` passed 2981 tests after the
    fresh-context fixes. 11.1's label inspection is unrun, and no real load was made.

## 12. The local lanes run a release candidate's images

Delivers D17. Implements the requirement "A local lane can run a release candidate's
images". Touches:
- `e2e-tests/Makefile`;
- the root `Makefile`'s `build-e2e-*` targets;
- `scripts/release_images.py`;
- the compose files naming release images: `domains/vms/compose.yml`,
  `domains/bare_metal/compose.yml`, `domains/apicredits/compose.yml` and
  `compose.apicredits-lane.yml`.

- [x] 12.1 Name each release image in the compose files as
  `arkhai:<local>${IMAGE_SUFFIX:-}`. The bare-metal storefront's
  `BARE_METAL_STOREFRONT_IMAGE` default follows the same form. Non-release images keep
  their names (D17).
  - Verify: `docker compose config` for each lane, with `IMAGE_SUFFIX` unset, names the
    bare tags as before.
  - Done. `test_release_images.py` renders each lane's Compose files unset and with a
    suffix: unset, the release images run bare; set, exactly those gain the suffix. The
    renders are gated by `COMPOSE_REQUIRED=1`, which `tests.yml`'s packaging job sets.
- [x] 12.2 Add `scripts/release_images.py`, which reads the declaration and has three
  commands:
  - `pull DOCKER_REGISTRY= IMAGE_SUFFIX=` pulls `<registry>/arkhai:<name><suffix>` for
    each declared release image and tags it `arkhai:<local><suffix>`;
  - `check` fails naming every declared release image a lane's compose files reference
    that is missing locally, and refuses an empty suffix;
  - `record` writes `.snapshot/e2e-release-images-<lane>.json` from the lane's running
    containers, as `{"lane", "image_suffix", "images": {<published name>: "sha256:<hex>"}}`.
    The value is the manifest digest from the image's single repo digest, with no
    registry name. A release image with no repo digest, or with two different ones,
    fails. The record is also printed.

  Expose `pull` as `make -C e2e-tests pull-release-images`.
  - Verify: unit tests in `scripts/tests/test_release_images.py`, with stubbed `docker`
    output, cover:
    - a missing image named;
    - an empty suffix refused;
    - the record's shape;
    - no repo digest and two repo digests each refused;
    - the registry stripped from the value;
    - `provisioning` pulled and tagged as `compute-provisioning`.
  - Done; the tests drive `main` against a stubbed `docker`, so they are integration
    tests. Beyond the task's wording, and stated in D17 and the delta since the round
    triage: `check` refuses a release image run bare; `record` counts only a repo digest
    from a registry, and refuses a release image with no running container and a lane
    running no candidate image. A suffix begins with `-`, so every call passes
    `--suffix=<value>`.
- [x] 12.3 Give `test-e2e-vm`, `test-e2e-bare-metal` and `test-e2e-apicredits` the
  `RELEASE_IMAGES=1` mode. In it, the root `build-e2e-*` targets build the wheels,
  dev-env, the test image and the non-release images the lane runs, and no declared
  release image. The lane runs 12.2's `check` before starting its stack and `record`
  after `up --wait`. Without the switch the lanes behave as today.
  - Verify: run locally once with a registry container on `localhost`:
    1. build the release images;
    2. push them to the local registry as `arkhai:<name>-<rev9>`;
    3. run `pull-release-images DOCKER_REGISTRY=localhost:<port> IMAGE_SUFFIX=-<rev9>`;
    4. run `test-e2e-bare-metal RELEASE_IMAGES=1 IMAGE_SUFFIX=-<rev9>`.

    The lane passes, builds no release image, and its record's digests equal the
    pushed manifests'. A run with one image removed fails before the stack starts. If
    the session cannot run the lanes, it records that as unrun.
  - Done. Dry-run tests hold, for each lane, that release-image mode writes no release
    image tag and runs check, down, build, up, record and the scenarios in order; a
    Compose test holds the dropped builds to the declaration.
  - The registry round trip, run for the round's triage (implementation review 52 F3)
    at `033dd0250` on Docker 29.8.0 with the containerd image store and a disposable
    local `registry:2`: the five release images were pushed with the code `push-images`
    runs, every local tag removed, and `pull-release-images` pulled and retagged them,
    keeping the registry's repo digest. `test-e2e-bare-metal RELEASE_IMAGES=1` then built
    only dev-env, the test image and the two lane doubles, passed 98 scenarios, and
    recorded `registry`, `provisioning` and `bare-metal-storefront` with the pushed
    manifest digests. With one image removed, the lane failed at its first command,
    naming it. Not covered: the VM and API-credit lanes in this mode, and a hosted
    registry.
  - On the containerd store a locally built image has a repo digest in the local
    `arkhai` repository, and a push gives it the registry's: hence `record`'s rule and
    what it proves (D17).
- [x] 12.4 Section verification.
  - Unit: `make test-release-tooling`.
  - Packaging: `make check-packaging`, where 7.5's check covers the lane targets.
  - Local lane run: 12.3's.
  - Functional checks: `scripts/change-workflow run pre-commit
    publish-wheels-through-a-gate`.
  - End-to-end: the pipeline's three lanes, run by `e2e.yml` in build mode, exercise the
    compose image lines with an empty suffix and must pass unchanged. The release-image
    mode is exercised only by 12.3's local run and by the deployment's release
    validation.
  - Done: `make test-release-tooling` passed 3013 tests, and the functional checks
    passed. The pre-commit run's documentation citations check reported only citations
    of files the change deleted or renamed, resolved at 13.10. The pipeline evidence is
    recorded in 13.8.

### Round triage fixes (2026-11-14)

The triage of the round at `033dd0250` (implementation review 52, validation 53, the
owner's notes 54) accepted, and fixed against `033dd0250`:
- **52 F1:** `build-candidate` held to the declaration by a dry-run test; D6 and the
  delta's "A component is added" scenario say so.
- **52 F2:** the record check holds the release branch's tip (8.4).
- **52 F3:** the registry round trip (12.3).
- **§12 Q1–Q3:** D17 and the delta say "repo digest from a registry" and what it proves,
  name `check`'s and `record`'s further refusals, and modify "A stack's configuration
  lives in committed files" for the release-image suffix.
- **§12 Q4:** TESTING.md's "Static Configuration Tests".
- **T1 with V1:** the chart's content digest no longer reads local state (8.2, D14).
- **54 O1:** no change, by the owner's word.

After the fixes, `make test-release-tooling` passed 3027 tests with none skipped, and the
pre-commit run's functional checks passed.

### Pre-closeout triage edits (2026-11-14)

The triage of pre-closeout review 70 at `a9560056a` (validation 69 passed) made
documentation edits only: the delta and D14 say the version check compares the release
tags the checkout holds and names every tag it compared, with the preflight in 13.9's
RELEASING.md bullet (70 F1); D3's clause on the version check's comparison was corrected
(70 F2).

## 13. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in order. Closeout changes
documentation only. A part that needs a code edit returns the change to implementation.

- [x] 13.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`. Read the
  comments sections 7–12 added for any that narrate this change or the redesign, or that
  call a mechanism temporary. That includes the docstring of `push-distributions.py` (in
  `scripts/`) if that file survives. Anything to rewrite returns the change to
  implementation.
  - Done (2026-11-14): `make check-comment-hygiene` passed both scans. A search of the
    comments and docstrings the change added (outside `openspec/`, locks, `docs/` and
    JSON) for narrating words — previous, formerly, no longer, replaced, retired,
    migration, review, temporary, interim, legacy, transition — found none narrating the
    change; the nearest, the binary Dockerfile's "would still build with the old
    Python", states an invariant. The wheel pusher was deleted at 10.3.
- [x] 13.2 **Import placement — confirm.** Check the imports sections 7–12 added in:
  - `scripts/release_components.py`;
  - `scripts/release_bom.py`;
  - `scripts/check_release_components.py`;
  - `scripts/check_release_versions.py`;
  - `scripts/check_release_record.py`;
  - `scripts/check_build_requirements.py`;
  - `scripts/load_candidate.py`;
  - `scripts/release_images.py`;
  - `scripts/market_binary.py`;
  - `scripts/check_uv_setup.py`;
  - their tests.

  Look for any import still local without a recorded reason.
  - Done: none of those files, `wheelhouse_digest.py`, `publish_artifacts.py`,
    `check_python_version.py`, their tests, `release_bom_fixtures.py` or the two new
    `helm/tests/` modules holds an indented import. The one in `scripts/uv_project.py`
    predates the change and records its reason (image builds copy the script alone).
- [x] 13.3 **Documentation compliance.**
  - Re-check D1–D21 against `openspec/README.md`'s placement table.
  - Check that no permanent document still describes:
    - a publishing workflow;
    - the release contract;
    - the curl installer or `market-cli-v*` tags;
    - `build-buyer`;
    - `push-wheels` or `clobber-wheels`;
    - an npm publication.
  - Done. Placement: the normative rules of D1–D4, D6–D12 and D14–D20 are in the delta;
    the release procedure, the deployment's part (D13) and the rationale of D5 and D21
    are in RELEASING.md, which holds release procedure beside the build conventions
    `BUILD_AND_PACKAGING.md` holds; the repository-wide principles of D1, D3 and D18 are
    in `ARCHITECTURE.md`; the check rows and build conventions (D3's label, D4, D7, D15,
    D18) in `BUILD_AND_PACKAGING.md`; the lanes' test mode (D17) in `TESTING.md`; the
    admitted artifact (D10) in `AGENTS.md`. No decision is a subsystem conceptual model
    that would belong in `deployment-state`'s companion.
  - Search of `docs/`, `openspec/specs/`, `AGENTS.md` and `README.md`: before promotion,
    only `docs/buyer-quickstart.md` (the curl installer, `market-cli-v*`, `build-buyer`)
    and `docs/development/RELEASING.md` (the publishing workflows, the release
    wheelhouse archive, trusted publishing) described them; both were rewritten at 13.9.
    `openspec/specs/market-change-workflow/spec.md` names `publish-pypi.yml` only as a
    synthetic example of a workflow validation may not dispatch. Found and corrected
    beyond 13.9's list: `docs/development/DEPLOYMENT_AND_CONFIG.md` said every lane
    keeps bare tags and that a bare build writes `arkhai:<tag>-<sha>`, and its "Artifact
    publishing destination" named no load.
- [x] 13.4 **Narrative compression.** Compress the completed notes of sections 1–12 to
  final behaviour, material evidence, deferred work and destinations. Sections 3–6 stay
  withdrawn with their history. The rejected and deferred alternatives stay in
  `design.md`.
  - Done. Every task's text is kept; its notes are compressed. The section notes'
    choices that review accepted and no decision recorded — the checks' reading of a
    target and a secret, this repository's reading of layout 1, the record and version
    checks' details, the load's, the lanes' and the binary's — moved first to
    `design.md`'s new "Implementation choices". The two returns' notes are summarized
    under "Readiness", their options in `design.md` (D7, D18's alternatives).
    Per-session histories, intermediate test counts and fixes superseded by later ones
    were removed; each section keeps its final behaviour, its last evidence and what
    stayed unrun.
- [x] 13.5 **Roadmap currency.** Expected disposition: `docs/development/ROADMAP.md` owes
  nothing, since no market capability changes. Its unowned row on the relay role taking
  the admission-plugin wheel on the operator's word is unaffected: this change releases
  the plugin's image, not a wheel the relay pins. Record the disposition in the
  promotion record.
  - Done: confirmed. No roadmap goal names publication or releases, and the
    admission-plugin row is unaffected as stated. Recorded below.
- [x] 13.6 **Campaign index currency.**
  - Update this change's row in `openspec/changes/README.md`, and the Package and
    release readiness campaign's prose and graph.
  - Reconcile with `configure-pypi-trusted-publishing`: CI publishes nothing, so its
    trusted-publisher half has no consumer. Record in both rows which of the
    distribution-graph and PyPI-only installation acceptance it still owns.
  - Record the question 1.1e kept in section 1 (`arkhai-vms-provisioning-iac` is not
    built by `make dist`) as unowned work in the campaign's section.
  - Run `make check-change-index`.
  - Done. The row is `in closeout`, its notes naming validation 75; the campaign's
    summary and graph say CI publication is retired once this change lands. The
    reconciliation is recorded in `configure-pypi-trusted-publishing`'s row and the
    campaign prose: this change owns the release inventory and the retirement of CI
    publication; that change keeps the PyPI-only installation proof and PyPI project
    ownership. Two items are recorded as unowned work from this change: 1.1e's question,
    and the API-credit domain's pydantic warnings on every `market` start, which section
    9 found. `scripts/change-workflow check index` passed.
- [x] 13.7 **Packaging.** Run `make check-packaging`, now including
  `check-release-components`, `check-market-binary` and `check-build-requirements`, and
  resolve every failure.
  Run `make check-architecture-change CHANGE=publish-wheels-through-a-gate`. No
  `.agents/`, `.claude/` or `.codex/` file changes, so `make check-agent-skills` is not
  owed.
  - Done (2026-11-14, at `a25c2b077`): `scripts/change-workflow run pre-archive
    publish-wheels-through-a-gate` passed, exit 0. `make check-packaging` rebuilt the
    wheelhouse and every check printed `OK`, among them the build requirements and the
    release components' four rules; `make check-architecture-change` printed
    `publish-wheels-through-a-gate owns no architecture row`.
- [x] 13.8 **End-to-end pipeline.** Record:
  - the passing E2E run the latest validation names, with its three lanes'
    (`test-e2e-vm`, `test-e2e-bare-metal`, `test-e2e-apicredits`) results;
  - the Helm validation's result for the chart without `appVersion`;
  - 12.3's local release-image lane run.

  Or record an explicit blocker naming its cause. The first marketplace release cut under
  this procedure happens only after the change lands on `main`, so it is not closeout
  evidence.
  - Done. Validation 75 at `a25c2b077`, the pre-closeout commit after the merge of `dev`
    at `3acfdbf03`, passed every part. Closeout changes no code, so these runs describe
    the code the closeout commit carries.
    - **Pipeline:** `e2e.yml` run 43598059019, success: `e2e-vm`, `e2e-bare-metal`,
      `e2e-apicredits` and `native-ansible-gate` passed. The lanes run in build mode,
      where the Compose files resolve to the bare tags, so they are regression evidence
      for the changed builds, revision tags, wheelhouse labels and Compose image lines.
    - **Helm:** the chart without `appVersion` built, rendered (`test-render`), deployed
      and passed its served scenarios pod and its payments and mediation checks in the
      change's namespace.
    - **CI owed by sections 7, 8, 9, 10 and 12:** `tests.yml` run 43598062499, job `test
      · test-deployment-packaging`, passed with `HELM_REQUIRED=1` and
      `COMPOSE_REQUIRED=1` set, `3027 passed` with no skips, and the chart render checks
      passing; no other job failed. Baseline: `dev`'s `tests.yml` run 43230450813 at
      `07af25d57`, all 20 jobs green.
    - **Release-image mode:** 12.3's local registry round trip, on the bare-metal lane.
- [ ] 13.9 **Promotion.** Write:
  - `docs/development/RELEASING.md`, rewritten from this repository's side, naming no
    private repository, project, registry or host:
    - the release's five steps;
    - the terms of D2;
    - the declaration;
    - `make load-candidate` and the candidate store, including retention and the reload
      (D3), and the source revision as the operator's word (D5);
    - the deployment's part (D13): validation and the bill of materials, its PyPI read,
      every lane run with `RELEASE_IMAGES=1` with `frp-grant-admission` covered only
      live, image aliasing, cutting after production, and publishing all or nothing,
      wheels only;
    - under "Cutting a release": the cut, `make check-release-record`,
      `make audit-secrets` and the migration-floor judgement (D11, D12, D21);
    - `make check-release-versions` and its offline scope (D14), with its preflight:
      fetch the release tags before `make load-candidate` and before the cut, and
      confirm the check's summary names the newest marketplace release, since it
      compares only the tags the checkout holds (pre-closeout review 70 F1);
    - under "Versioning policy": the pin-move rule (D15);
    - the npm package not being a component until it can be loaded (D19);
    - no patch releases;
    - how a new PyPI project comes to be owned by the organization;
    - the published-packages table.

    The rewrite records that merging publishes nothing, and what a contributor does
    instead, discharging the obligation 2.3 kept in section 2.
  - `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization": nothing
    reaches a public channel except bytes a deployment validated (D1); every identity in
    a release record is a content identity, and development tags, revisions and
    registry contents guarantee nothing (D3); one program per name (D18).
  - `AGENTS.md`, "Public repository discipline", "Never enters this repository": admit a
    marketplace release's bill of materials holding content identities only, enforced by
    `make check-release-record` (D10).
  - `docs/development/BUILD_AND_PACKAGING.md`:
    - "Checks": `check-release-components` (D7, D4's `--short=9` rule),
      `check-build-requirements` with `build-constraints.txt` (D15), and
      `check-market-binary` (D18).
    - "Checks" also gains two row amendments. `check-uv-setup` reads `*.Dockerfile` and
      refuses any wheelhouse `pip` install not made through the script.
      `check-python-version` reads `*.Dockerfile` (D18).
    - "Images": the binary's locked virtual project and its digest-pinned build image.
      A Python bump pins a new digest, and the build refuses a stale one (D18).
  - `docs/development/TESTING.md`, "Locally verifiable and external-topology scenarios":
    the lanes' release-image mode and record (D17).
  - `docs/buyer-quickstart.md`, "1. Install": PyPI, pinned to a release's versions; the
    release's linux/amd64 `market` binary checked against its bill of materials; and the
    from-the-repository path, without `build-buyer` (D18).

  `openspec/specs/deployment-state/spec.md` is written by the archive (13.11).
  `deployment-state` has no `index.md`, and no capability is new, so
  `openspec/specs/README.md` is unchanged. Complete the promotion record below.
  - Done. Each document is written as listed. RELEASING.md keeps the "Published
    packages", "Cutting a release" and "Versioning policy" headings other documents and
    `test_publish_matrix.py` read, and adds "The bill of materials" and "Running the
    lanes on a release candidate's images". Written beyond the list, from the sections'
    closeout notes:
    - `BUILD_AND_PACKAGING.md`: the wheelhouse digest argument and label in "Images"
      (D3); `build-constraints.txt` and `.helm-version` beside `.python-version`; a
      first lock by `make lock PROJECTS=`; the focused `check-workflow-credentials` and
      `check-market-binary` targets;
    - `TESTING.md`: a lane target's release-image suffix, the Helm pin the chart digest
      enforces, and the two new chart tests in "Chart Render Tests";
    - `DEPLOYMENT_AND_CONFIG.md`: 13.3's corrections.

    `openspec/specs/README.md` is unchanged.
  - **Returned to implementation for the `AGENTS.md` amendment (2026-11-14).** Every
    document above is written and committed but `AGENTS.md`. `AGENTS.md` lies outside
    the repository's inert paths (`.agents/workflow.toml`), and the change-workflow
    tests read it, so committing it runs `after-functional-change` and
    `pre-commit-functional`, which closeout may not run: `run pre-commit` refused with
    "the closeout step may not run after-functional-change". The owner chose a
    documentation-only fix round in implementation, which runs those hooks. That round
    adds this paragraph to `AGENTS.md`, "Public repository discipline", "Never enters
    this repository", after the paragraph ending "is not an exception.", verbatim:

    ```markdown
    One run artifact is admitted: a marketplace release's bill of materials, committed
    at the cut as `manifests/release-bom.cdx.json` on its release branch. It holds
    content identities only — versions, digests, the source revision and the public
    repository link — and names no registry host, project or path.
    `make check-release-record` refuses any field or URL its layout does not admit, so
    the admission is enforced rather than promised
    ([`docs/development/RELEASING.md`, "The bill of materials"](docs/development/RELEASING.md#the-bill-of-materials)).
    ```

    Until it lands, `docs/development/RELEASING.md`'s "The bill of materials" says the
    discipline admits the record before `AGENTS.md` does. Closeout then resumes at 13.9,
    checks it, and runs 13.10 and 13.11. Already run at this commit: the scoped citation
    check passed, and `openspec validate --strict` passed for the change.
- [ ] 13.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=publish-wheels-through-a-gate` and resolve every
  match. Then run `scripts/change-workflow openspec validate publish-wheels-through-a-gate
  --strict`.
- [ ] 13.11 **Archival.** Last: `scripts/change-workflow openspec archive
  publish-wheels-through-a-gate -y`. It merges the deltas: eleven added requirements, and
  the removal of "Release verification is a publication-time activity". Point the index
  row at the archived directory, then run `scripts/change-workflow openspec validate
  --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| D1 Continuous integration publishes nothing | `openspec/specs/deployment-state/spec.md`, "Continuous integration publishes nothing"; `docs/development/ARCHITECTURE.md#build-packaging-and-initialization`; `docs/development/RELEASING.md#the-release` | Promoted |
| D2 Release candidate, marketplace release, release component, candidate store | `openspec/specs/deployment-state/spec.md`, "A release candidate is stored under its revision"; `docs/development/RELEASING.md#terms` | Promoted |
| D3 Every component of a release candidate is stored under its revision by one load | `openspec/specs/deployment-state/spec.md`, "A release candidate is stored under its revision"; `docs/development/ARCHITECTURE.md#build-packaging-and-initialization`; `docs/development/RELEASING.md#loading-a-release-candidate`; `docs/development/BUILD_AND_PACKAGING.md#images` (the `WHEELHOUSE_DIGEST` argument and `org.arkhai.wheelhouse-digest` label) | Promoted |
| D4 A candidate's revision is nine characters | `openspec/specs/deployment-state/spec.md`, "Every declared image's build writes its revision tag"; `docs/development/BUILD_AND_PACKAGING.md#checks` (`check-release-components`, its revision rule) | Promoted |
| D5 Loading does not refuse an edited tree | `docs/development/RELEASING.md#loading-a-release-candidate` | Promoted |
| D6 One declaration of release components | `openspec/specs/deployment-state/spec.md`, "One declaration of release components"; `docs/development/RELEASING.md#what-a-release-comprises` | Promoted |
| D7 The single-enumeration and workflow-credential checks | `openspec/specs/deployment-state/spec.md`, "Continuous integration publishes nothing" and "One declaration of release components"; `docs/development/BUILD_AND_PACKAGING.md#checks` | Promoted |
| D8 Every declared image's build writes its revision tag | `openspec/specs/deployment-state/spec.md`, "Every declared image's build writes its revision tag" | Promoted (13.11) |
| D9 The chart names no release | `openspec/specs/deployment-state/spec.md`, "The chart names no release"; `docs/development/TESTING.md#chart-render-tests` (its tests) | Promoted (13.11) |
| D10 The deployment builds the bill of materials, in layout 1 | `AGENTS.md#public-repository-discipline`; `openspec/specs/deployment-state/spec.md`, "The release bill of materials holds content identities only"; `docs/development/RELEASING.md#the-bill-of-materials` | Promoted |
| D11 A marketplace release is recorded last by a tagged commit on its release branch | `openspec/specs/deployment-state/spec.md`, "A marketplace release is recorded by a tagged commit on its release branch"; `docs/development/RELEASING.md#cutting-a-release` | Promoted |
| D12 The release record is checked at the cut | `openspec/specs/deployment-state/spec.md`, "A marketplace release is recorded by a tagged commit on its release branch"; `docs/development/RELEASING.md#cutting-a-release` | Promoted |
| D13 This repository's specification states only its own behaviour | `docs/development/RELEASING.md#the-deployments-part` | Promoted |
| D14 A version changes when its contents change | `openspec/specs/deployment-state/spec.md`, "A version changes when its contents change"; `docs/development/RELEASING.md#the-version-check` | Promoted |
| D15 The build backend is pinned; a pin move is a release-wide bump | `openspec/specs/deployment-state/spec.md`, "Wheels build with a pinned backend"; `docs/development/BUILD_AND_PACKAGING.md#one-python-version` and `#checks`; `docs/development/RELEASING.md#versioning-policy` | Promoted |
| D16 A product version is distinct from a distribution version | `openspec/specs/deployment-state/spec.md`, "The release bill of materials holds content identities only"; `docs/development/RELEASING.md#the-bill-of-materials` | Promoted (13.11) |
| D17 The local lanes can run a release candidate's images | `openspec/specs/deployment-state/spec.md`, "A local lane can run a release candidate's images" and the modified "A stack's configuration lives in committed files"; `docs/development/RELEASING.md#running-the-lanes-on-a-release-candidates-images`; `docs/development/TESTING.md#locally-verifiable-and-external-topology-scenarios` | Promoted |
| D18 The release's `market` binary is PyPI's CLI | `openspec/specs/deployment-state/spec.md`, "The release binary is the buyer CLI with every declared buyer domain"; `docs/development/ARCHITECTURE.md#build-packaging-and-initialization`; `docs/development/BUILD_AND_PACKAGING.md#images` and `#checks`; `docs/buyer-quickstart.md#1-install` | Promoted |
| D19 The npm package is not a release component until it can be loaded | `openspec/specs/deployment-state/spec.md`, "One declaration of release components"; `docs/development/RELEASING.md#what-a-release-comprises` | Promoted |
| D20 The orphaned release-verification requirement is removed | `openspec/specs/deployment-state/spec.md` (removed by the archive) | Promoted (13.11) |
| D21 RELEASING.md keeps the anchors other documents cite | `docs/development/RELEASING.md` ("Published packages", "Cutting a release", "Versioning policy") | Promoted |
| D22 The change keeps its name | No permanent destination — the change's own directory name | — |
| Implementation choices | `design.md`, "Implementation choices", as change history; the behaviour they describe is the code's, and the documents above describe it | — |
| Roadmap currency | `docs/development/ROADMAP.md`: no change, recorded at 13.5 | Done |
| Campaign index currency | `openspec/changes/README.md`: this row, the campaign's summary and graph, `configure-pypi-trusted-publishing`'s row, the unowned work from this change | Done |
