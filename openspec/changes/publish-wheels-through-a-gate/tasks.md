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
  - Not reflected on `dev` as of 2026-10-09: `publish-pypi.yml` still builds its
    matrix from its own `PACKAGES` table. `bare-metal-mock-provisioned-deal`
    added its newly published packages to both that table and the manifest, and
    `scripts/tests/test_publish_matrix.py` now checks each list is closed under
    repository dependencies; nothing keeps the two lists equal until this task's
    workflow change is restored.
  - Superseded by 7.1 (2026-11-13): the workflow is deleted (D1), so it reads nothing.
- [x] 1.4 Update `scripts/tests/test_publish_matrix.py`. It currently parses the
  heredoc by regex and asserts the workflow states its table that way; that
  assertion is about to be false. Keep what it actually protects — that a
  distribution with a `force-include` escaping its own directory cannot be built
  as an sdist — and point it at the manifest.
  - Superseded by 7.4 (2026-11-13): no project force-includes outside its own
    directory any more, and PyPI receives wheels only, so `wheel_only` and its test go
    (D6).
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

- [ ] 1.1e `arkhai-vms-provisioning-iac` is the tenth and is **not** built by
  `make dist`, so it cannot be published and is not in the manifest. Whether
  that is deliberate — an Ansible-role package that nobody installs from an
  index — or an omission in the dist graph is a question for whoever owns it.
  Recorded rather than answered: adding it to the build is a separate decision
  from enumerating what the build already produces.
  - Planning note (2026-11-13): the declaration lists what a release ships (D6), which
    this question does not change. Closeout part 6 (13.6) records it as unowned work in
    the campaign's index section, and then checks this task.

- [x] 1.1c `packages.json` carried a `wheel_only` flag on three distributions
  whose wheels force-include files from outside their own directory, which an
  sdist cannot carry. The first manifest dropped it and two tests caught the
  regression. Every field of the original table is preserved.
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
  - Correction (2026-11-13): no such check is in the tree (design, D7). 7.5 builds it.

## 2. Stop automated public publication

- [x] 2.1 Remove the publishing job from `.github/workflows/publish-pypi.yml`.
  Keep `detect-changes` if a later section needs it; delete it if not, rather
  than leaving a job whose only consumer is gone.
- [x] 2.2 Rename the workflow if it no longer publishes to PyPI. A file
  named for what it used to do is the same defect as a stale comment.
- [ ] 2.3 Record in `docs/development/RELEASING.md` that merging no longer
  publishes, and what to do instead. This is a contributor-workflow break and
  the first person it surprises should find the answer where they look.
  - Planning note (2026-11-13): discharged by closeout's rewrite of RELEASING.md
    (13.9), which checks this task.
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

- [ ] 2.7 **Finding (2026-09-21, from `capacity-resource-administration`'s
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
  - Planning note (2026-11-13): closed by 7.1, which deletes the workflow (D1), and by
    7.4, which removes the workflow assertions from `test_publish_matrix.py`. 7.1
    checks this task.

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
- [x] 3.3 Withdrawn with 3.1.

## 4. Promotion

- [x] 4.1–4.8 Withdrawn: promotion and public publication are the deployment's
  (`design.md` D1, D8). The all-or-nothing refusal and the wheels-only answer to the
  sdist question carry forward as requirements on that publisher (D8).
  - Correction (2026-11-13): those decisions are now `design.md` D1 and D13. Under D13
    the publisher's obligations are described in RELEASING.md as the deployment's part,
    not stated as requirements here.

## 5. Repair the published graph

- [x] 5.1 Withdrawn: `settle-through-arkhai-payments` removed hosted settlement on 2026-10-08, including
  `arkhai-kit-hosted-settlement`, so there is no package to bump. (It was to
  replace 0.1.4 on PyPI, which declares a dependency PyPI does not carry.)
- [x] 5.2 Withdrawn: there is no package left to repair.
- [x] 5.3 Withdrawn: reconciliation with `configure-pypi-trusted-publishing` moves to
  13.6 under the redesign.
  - Correction (2026-11-13): it is 13.6 of the replanned closeout too.

## 6. Inventory substitution

- [x] 6.1–6.3 Withdrawn: the component declaration (section 8) is the enumeration, and the
  release's bill of materials (`design.md` D5) binds component versions to a product
  version. Comment hygiene and import placement move to 13.1 and 13.2.
  - Correction (2026-11-13): the declaration is section 7 of the replanned plan, and the
    bill of materials is `design.md` D10 (with D16 for the product version). Comment
    hygiene and import placement are still 13.1 and 13.2.

## 7. CI publishes nothing, one declaration, and the checks that hold both

Delivers D1, D6, D7 and D19's absence of an npm entry. Implements the requirements
"Continuous integration publishes nothing" and "One declaration of release components".
Touches:
- `.github/workflows/`;
- `manifests/`;
- `scripts/` and `scripts/tests/`;
- the root `Makefile`'s publish targets and comments;
- `install.sh`, `scripts/install-remote.sh`, `scripts/build-installer.sh`;
- `README.md`'s tree.

- [ ] 7.1 Delete `.github/workflows/publish-pypi.yml`, `publish-npm.yml`, `release.yml`
  and `release-cli.yml` (D1). Check 2.7, which this closes.
  - Verify: no file under `.github/workflows/` names PyPI, npm, ghcr or a release upload.
- [ ] 7.2 Delete `scripts/verify-marketplace-release.py` and
  `scripts/tests/test_verify_marketplace_release.py` (D1). Delete the curl installer:
  `install.sh`, `scripts/install-remote.sh`, `scripts/build-installer.sh`,
  `scripts/tests/test_install_remote_urls.py` and
  `scripts/tests/test_install_sh_dependencies.py`. Remove `install.sh` from
  `README.md`'s tree (D18).
  - Verify: a search of the tree outside `openspec/` finds no reference to the deleted
    files or to `arkhai.marketplace-release.v2`.
- [ ] 7.3 Set `.github/workflows/validate-model-release.yml` to `permissions: contents:
  read`, and remove the step that appends a validation line to the release's notes
  (D7). Downloading the release's assets still works with the read token.
  - Verify: the workflow's remaining steps reference only `secrets.GITHUB_TOKEN`.
- [ ] 7.4 Rename `manifests/published-distributions.json` to
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

  Point `scripts/push-distributions.py` and `scripts/tests/test_publish_matrix.py` at
  the reader. In the test:
  - delete the assertions about the deleted workflow (path filters, push triggers) and
    about `wheel_only`;
  - keep closure under repository dependencies, dependency order, name-at-path, and the
    RELEASING.md table's equality with the declared distributions (D21).

  - Verify: unit tests for the reader's refusals, one case per rule, in
    `scripts/tests/test_release_components.py`; `make test-release-tooling` passes.
- [ ] 7.5 Add the single-enumeration and workflow-credential check,
  `scripts/check_release_components.py`, as `make check-release-components`, run by
  `make check-packaging` (D7). It refuses, naming the file and what it found:
  - a list of declared distributions, images, development images, the chart or the
    binary in any workflow, publish target or lane target;
  - a workflow with no top-level `permissions:`;
  - a workflow granting `id-token: write`, `packages: write`, `attestations: write` or
    `contents: write` anywhere;
  - a reference to a secret other than `GITHUB_TOKEN`;
  - a named publishing step (`pypa/gh-action-pypi-publish`, `npm publish`,
    `docker push`, `docker/build-push-action` with `push: true`,
    `softprops/action-gh-release`, `gh release create`).

  It has no exception list.
  - Verify: unit tests in `scripts/tests/test_check_release_components.py` over
    synthetic workflow and Makefile text, one case per rule plus a clean case; the
    check passes on the tree; `make check-packaging` passes.
- [ ] 7.6 CI resolves every declared distribution against the wheelhouse it builds
  (D1). A test in `scripts/tests/` asserts every declared wheel is in `.dist`, run by
  `make test-release-tooling` inside `test-deployment-packaging`, after `tests.yml`'s
  `make dist-ci`. If `dist-ci` does not build every declared wheel, `test-deployment-
  packaging`'s job builds what is missing through the existing dist targets, and that
  is recorded in the task note.
  - Verify: passes locally after `make dist`.
- [ ] 7.7 Correct the comments that cite the deleted workflows: the root `Makefile`'s
  `dist-release` and Artifact Registry comments, and any comment
  `make check-comment-hygiene` or a search for the workflow names finds.
  - Verify: `make check-comment-hygiene` passes.
- [ ] 7.8 Section verification.
  - Unit and integration:
    - `make test-release-tooling` (unit: the reader and the check);
    - `make check-packaging`;
    - `make check-comment-hygiene`;
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`, whose
      functional checks pass.
  - End-to-end: no scenario exercises this section; it changes no runtime behaviour, and
    none is owed.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — after
    `make dist-ci`, the declared-wheel resolution test of 7.6 passes, and the new script
    tests run and pass.

### Section 7 notes: returned to planning (2026-11-13, first implementation session)

**Why the section stopped.** 7.5's verification ("the check passes on the tree;
`make check-packaging` passes") cannot hold within section 7. Implemented as D7 states
it, the single-enumeration rule refuses five root `Makefile` publish targets that no
section 7 task touches. Run on this commit, `make check-release-components` reports:
- `push-images`: names the release images `registry`, `storefront`, `provisioning` and
  `frp-grant-admission` (and omits `bare-metal-storefront`, the drift D7 exists to
  stop). 10.3 replaces it.
- `push-dev-images`: names `dev-env` and `e2e-tests`. 10.3 replaces it.
- `clobber-wheels`: names three distributions. 10.3 retires it, and says 7.5 refuses
  it, so the plan saw the refusal but ordered its fix after the check.
- `push-cli`: names the binary's path, `domains/vms/buyer/dist/market`. 9.3 and 11 touch
  the binary and `push-cli`; no task says `push-cli` reads the declaration.
- `push-charts`: names the chart by its package, `arkhai-node-operator-*.tgz`. No task
  touches it, and 10.3 keeps it as a developer push.

Every workflow already passes the credential rule, and no lane target names a component.
If the enumeration rule joined `check-packaging` in section 7, the packaging check would
fail for sections 8 and 9 and for every validation until section 11. Pulling the fixes
forward is not small. `push-images` read from the declaration pushes
`bare-metal-storefront`, whose build writes no revision tag until 10.2, and
`test_image_publication_contract.py` reads `push-images`' literal arguments, which 10.2
rewrites. That would move most of section 10's push half into section 7. Choosing
between these is planning's decision, so the section returns.

**Options for planning.**
- **(a)** Move into section 7: 10.2's bare-metal revision tag and contract-test rewrite,
  10.3's declaration-driven `push-images` and `push-dev-images` and its retirement of
  `clobber-wheels`, and declaration-driven `push-cli` and `push-charts`.
- **(b), recommended.** Split 7.5.
  - The workflow-credential rule joins `check-packaging` in section 7; it passes on the
    tree now.
  - The single-enumeration rule is built and unit-tested in section 7, and joins
    `check-packaging` in the section that makes the last publish target comply.
  - Give `push-charts` and `push-cli` a task that makes them read the declaration;
    none has one now.

  This keeps each section's scope. From section 7 onward, it also holds the half of the
  rule that stops a workflow publishing.
- **(c)** Move all of 7.5 after section 11.

**A second finding, for the round.** The round recorded as `[[1, 2, 7], …]` can never
reach its join as planned. Two tasks of sections 1 and 2 are checked only at closeout:
1.1e at 13.6 and 2.3 at 13.9. `scripts/change-workflow next` reads the session as
incomplete until every task of 1, 2 and 7 is checked. Planning should decide where
1.1e and 2.3 sit so that the round can join, for example as closeout tasks that keep
their history.

**What this commit holds (no task checked).**
- 7.1: the four workflows are deleted, and `.github/workflows/` names no PyPI, npm, ghcr
  or release upload.
- 7.2: the verifier, the curl installer and their tests are deleted, and `install.sh` is
  removed from `README.md`'s tree. Outside `openspec/`, a search finds the deleted files
  and the release contract named only in `docs/buyer-quickstart.md` (the curl
  installer's URL), which 13.9 rewrites. That task has the same `docs/` exclusion 9.3
  states.
- 7.3: `validate-model-release.yml` has `permissions: contents: read`, and its note
  step is removed. Its remaining steps reference only `secrets.GITHUB_TOKEN`.
- 7.4: `manifests/release-components.json` follows D6's shape:
  - fifty-nine distributions, with `arkhai-apicredits-sample-app` and `wheel_only` gone;
  - five images;
  - the chart;
  - `market`, which names `build-buyer` and `domains/vms/buyer/dist/market` until 9.3;
  - two development images;
  - no `npm` key, and no `_comment`, since the reader refuses unknown keys.

  `scripts/release_components.py` is the reader. It collects every refusal before
  raising one `DeclarationError`. A name or local name may appear once across images
  and development images, since both are tagged and pushed side by side. It also gives
  `project_version`, `wheel_file_name` and `declared_wheels`, which sections 8 and 11
  can reuse for the wheelhouse digest. `scripts/push-distributions.py` reads through it,
  and its migration-narrative docstring is rewritten. `test_publish_matrix.py`:
  - reads through it;
  - loses the workflow, path-filter and `wheel_only` assertions;
  - keeps closure, dependency order, name-at-path, the find-links rule and the
    RELEASING.md table checks.

  The RELEASING.md table already equalled the fifty-nine declared distributions, so it
  needed no edit.
- 7.5: `scripts/check_release_components.py` and `make check-release-components` exist,
  but are not in `check-packaging` (above). Some choices go beyond D7's wording, so
  review should look at them:
  - Make variables a rule references are read as part of the rule.
  - A publish target is one named `push-*`, `publish-*`, `clobber-*` or
    `load-candidate`, or one whose recipe runs an uploader.
  - A lane target is one named `test-e2e*`, `build-e2e*` or `pull-release-images`.
  - The chart is found by its declared path (`helm/`) or by its `Chart.yaml` name, and
    the binary by its declared path.
  - `permissions: write-all` and `secrets: inherit` are refused as credential grants.
- 7.6: `scripts/tests/test_release_wheelhouse.py` fails, naming each missing wheel and
  `make dist`, when `.dist` lacks a declared wheel. It passes locally against this
  checkout's `.dist`. `dist-ci` builds a superset of `dist-release-set`, since `kit`'s
  `dist` is its `dist-ci`, so `tests.yml` needs no extra build step.
- 7.7: the comments citing the deleted workflows are corrected:
  - the root `Makefile`'s `dist-release` comment and its stale Artifact Registry
    "upgrade path";
  - `test-release-tooling`'s description, which named the deleted verifier;
  - `check_uv_version.py`'s docstring;
  - `test_init_targets.py`'s docstring.

  `test_ci_evidence.py` and `test_validate_slice.py` keep `publish-pypi.yml` as a
  synthetic name of a workflow validation may not dispatch. It names no file.

**Evidence so far.**
- Unit: `make test-release-tooling` passed, 2788 tests. Among them are the reader's
  cases (`test_release_components.py`) and the check's cases over synthetic workflow and
  Makefile text, one per rule plus clean cases (`test_check_release_components.py`).
- `make check-comment-hygiene` passed.
- `make check-release-components` on the tree fails as listed above.
- Not run, since a return commit owes no checks: `make check-packaging`, `scripts/change-workflow run
  pre-commit`, and the fresh-context review. They belong to the session that finishes
  this section.

## 8. The release record: the layout-1 reader, the version check and the record check

Delivers D10's reader, D11, D12, D14 and D16. Implements the requirements "A version
changes when its contents change", "A marketplace release is recorded by a tagged commit
on its release branch" and "The release bill of materials holds content identities only".
Touches `scripts/`, `scripts/tests/`, the root `Makefile` and `.helm-version`; it reads
`.github/workflows/tests.yml`'s Helm version without changing it.

- [ ] 8.1 Add `scripts/release_bom.py`, the layout-1 reader (D10). It provides:
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
- [ ] 8.2 Pin Helm for the chart digest. Add a root `.helm-version` holding the version
  `tests.yml`'s `azure/setup-helm` installs (v4.3.0). The digest refuses to run under
  any other `helm version --short`. A test holds `tests.yml`'s setup-helm version equal to
  `.helm-version` (D14).
  - Verify: the equality test passes; a unit test with a stubbed `helm version` refuses a
    mismatch.
- [ ] 8.3 Add `scripts/check_release_versions.py` and `make check-release-versions`
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
- [ ] 8.4 Add `scripts/check_release_record.py` and
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
- [ ] 8.5 Section verification.
  - Unit and integration: `make test-release-tooling` (unit: the reader and the digest;
    integration: the two checks against real git); `make check-packaging`;
    `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`.
  - End-to-end: no scenario exercises the release record. It is read only at a load and
    at the cut, and none is owed.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
    `azure/setup-helm` installs the version `.helm-version` names, and the chart-digest
    tests run rather than skip and pass.

## 9. The release binary is PyPI's CLI

Delivers D18. Implements the requirement "The release binary is the buyer CLI with every
declared buyer domain". Touches:
- `core/buyer/market-binary.Dockerfile`;
- `scripts/buyer_domain_wheels.py`;
- the root `Makefile`'s `build`, `build-buyer` and `build-market-binary`;
- `domains/vms/buyer/` (its `pyproject.toml`, `Makefile`, lock and `main.py`);
- `manifests/release-components.json`'s `binaries` entry.

- [ ] 9.1 Add `scripts/buyer_domain_wheels.py`. It derives, from the declaration, the
  declared distributions whose `pyproject.toml` registers a `market.buyer_domains` entry
  point, and prints their wheel file names in `.dist` (D18). No Dockerfile or Makefile
  lists them.
  - Verify: a unit test over a synthetic declaration and projects. On the tree, it names
    `arkhai-vms-buyer`, `arkhai-bare-metal-buyer` and `arkhai-apicredits-buyer`.
- [ ] 9.2 Add `core/buyer/market-binary.Dockerfile` and `make build-market-binary`.
  - The build image is pinned by digest: Debian bookworm, with the Python version
    `.python-version` declares, as `check-python-version` requires.
  - It installs `arkhai-core-buyer` and 9.1's wheels from `.dist`, and freezes
    `core_buyer.cli:main` with PyInstaller, passing `--copy-metadata` for each bundled
    distribution.
  - It runs `market plugins` inside the image as the smoke test, and copies the binary to
    `.dist/bin/market`.
  - PyInstaller is installed in the build image only.
  - Verify: `make build-market-binary` succeeds locally, and its smoke test lists the VM,
    bare-metal and API-credit domains. If the session cannot run Docker, it records that
    as unrun.
- [ ] 9.3 Point the declaration's `market` entry at `build-market-binary` and
  `.dist/bin/market`. `build` builds it in place of `build-buyer`.
  - Retire `build-buyer`, the PyInstaller recipe in `domains/vms/buyer/Makefile`, and
    `domains/vms/buyer/src/arkhai_vms_buyer/main.py`, whose only user is that recipe.
  - Update any target, test or comment that names them; the search includes
    `scripts/tests/test_init_targets.py` and the e2e-tests comments.
  - Verify: a search outside `openspec/` and `docs/` finds no `build-buyer` and no
    `arkhai_vms_buyer/main.py`. `make test-release-tooling` passes. `docs/` is rewritten
    at closeout (13.9).
- [ ] 9.4 Remove `pyinstaller` from `arkhai-vms-buyer`'s runtime dependencies, and bump
  it a minor version (0.11.0 → 0.12.0) per RELEASING.md's versioning policy. Move any
  exact pin on it with the bump, and refresh every lock that installs it with
  `make lock`.
  - Verify:
    - `make check-version-bumps` passes;
    - `make check-packaging` passes, with locks current;
    - `make test-domains` passes for the VM buyer;
    - the built wheel's metadata requires no PyInstaller.
- [ ] 9.5 Section verification.
  - Unit: 9.1's test.
  - System-level build evidence: 9.2's smoke test.
  - Packaging: `make check-packaging`.
  - Functional checks: `scripts/change-workflow run pre-commit
    publish-wheels-through-a-gate`.
  - End-to-end: no scenario runs the binary (D18), and none is owed. The pipeline's lanes
    install `market` from the wheels, so they exercise the buyer CLI 9.4 repackages.

## 10. Build pins, revision tags, and a chart that names no release

Delivers D4, D8, D9 and D15, and declares the development images' pushes (D6, D8).
Implements the requirements:
- "Every declared image's build writes its revision tag";
- "The chart names no release";
- "Wheels build with a pinned backend".

Touches:
- every Makefile computing `GIT_SUFFIX`;
- the root `Makefile`'s build and push targets;
- `scripts/publish_artifacts.py`;
- `build-constraints.txt`;
- `scripts/check_build_requirements.py`;
- `helm/` and its nine subcharts.

- [ ] 10.1 Compute `GIT_SUFFIX` with `git rev-parse --short=9` in the root, `e2e-tests`,
  `dev-env`, `core/registry`, `provisioning/compute/service` and `domains/vms/storefront`
  Makefiles (D4). Extend 7.5's check to refuse a `git rev-parse --short` without `=9` in
  any Makefile.
  - Verify: a unit case for the refusal; the check passes on the tree.
- [ ] 10.2 Every declared image's and development image's build writes
  `arkhai:<local>-<rev9>` when `IMAGE_SUFFIX` is empty. `build-bare-metal-storefront`
  gains its tag (D8).
  - Extend `scripts/tests/test_image_publication_contract.py` from provisioning to every
    declared image and development image, read from the declaration.
  - Verify: the extended test passes.
- [ ] 10.3 `push-images` and `push-dev-images` push the declared images and development
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
- [ ] 10.4 Pin the build requirements (D15).
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
- [ ] 10.5 Remove `appVersion` from `helm/Chart.yaml` and the nine subcharts' `Chart.yaml`
  (D9).
  - Remove the `app.kubernetes.io/version` block from the umbrella's helpers
    (`helm/templates/_helpers.tpl`, and its copy `helm/_helpers.tpl`) and from the seven
    subcharts that carry one.
  - Bump each changed chart's version per RELEASING.md's versioning policy, and update
    the umbrella's ten dependency entries to match.
  - Verify: a search finds no `appVersion` or `.Chart.AppVersion` under `helm/`.
- [ ] 10.6 Chart tests (D9), run by `helm/scripts/test-render.sh`:
  - `helm/tests/test_subchart_pins.py` holds each umbrella dependency entry's `version`
    equal to its subchart's `Chart.yaml` version, naming a mismatch;
  - a render assertion that the chart's default values name no semver-shaped image tag,
    no revision-suffixed tag and no digest.
  - Verify: `make -C helm test-render` passes; a deliberately mismatched pin fails the
    pin test, checked once and reverted.
- [ ] 10.7 Section verification.
  - Unit and integration: `make test-release-tooling`; `make test-deployment-packaging`
    (render tests); `make check-packaging`.
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

## 11. The load operation

Delivers D3 and D5. Implements the requirement "A release candidate is stored under its
revision". Touches:
- the root `Makefile`'s `load-candidate` and `push-cli`;
- `scripts/load_candidate.py`;
- `scripts/publish_artifacts.py`;
- the image builds that install wheels from `.dist`:
  - `core/registry`;
  - `domains/vms/storefront`;
  - `provisioning/compute/service`;
  - the bare-metal storefront's `Dockerfile`;
  - `e2e-tests/Dockerfile`.

- [ ] 11.1 Every image whose build installs wheels from `.dist` takes the wheelhouse
  digest as a build argument and records it as the label
  `org.arkhai.wheelhouse-digest` (D3). Those images are the registry, storefront,
  provisioning and bare-metal storefront images, and the e2e-tests image. This replaces
  the `cksum` `DIST_FINGERPRINT` in `domains/vms/storefront` and
  `provisioning/compute/service`, their Makefiles and Dockerfiles.
  - Verify: after `make build`, `docker image inspect` shows each of the five images
    labelled with 11.2's digest of the `.dist` they were built from.
- [ ] 11.2 Add `scripts/load_candidate.py` and `make load-candidate`. In one invocation
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
- [ ] 11.3 Section verification.
  - Integration: `make test-release-tooling`; `make check-packaging`.
  - Local build: `make build` with 11.1's label check.
  - Functional checks: `scripts/change-workflow run pre-commit
    publish-wheels-through-a-gate`.
  - A real load against the candidate store is the operator's and needs the externally
    provisioned repository. It is not evidence this section owes; if one is made, record
    its revision.
  - End-to-end: the pipeline's three lanes build the labelled images through the changed
    Dockerfiles and must pass unchanged; no scenario runs the load.

## 12. The local lanes run a release candidate's images

Delivers D17. Implements the requirement "A local lane can run a release candidate's
images". Touches:
- `e2e-tests/Makefile`;
- the root `Makefile`'s `build-e2e-*` targets;
- `scripts/release_images.py`;
- the compose files naming release images: `domains/vms/compose.yml`,
  `domains/bare_metal/compose.yml`, `domains/apicredits/compose.yml` and
  `compose.apicredits-lane.yml`.

- [ ] 12.1 Name each release image in the compose files as
  `arkhai:<local>${IMAGE_SUFFIX:-}`. The bare-metal storefront's
  `BARE_METAL_STOREFRONT_IMAGE` default follows the same form. Non-release images keep
  their names (D17).
  - Verify: `docker compose config` for each lane, with `IMAGE_SUFFIX` unset, names the
    bare tags as before.
- [ ] 12.2 Add `scripts/release_images.py`, which reads the declaration and has three
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
- [ ] 12.3 Give `test-e2e-vm`, `test-e2e-bare-metal` and `test-e2e-apicredits` the
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
- [ ] 12.4 Section verification.
  - Unit: `make test-release-tooling`.
  - Packaging: `make check-packaging`, where 7.5's check covers the lane targets.
  - Local lane run: 12.3's.
  - Functional checks: `scripts/change-workflow run pre-commit
    publish-wheels-through-a-gate`.
  - End-to-end: the pipeline's three lanes, run by `e2e.yml` in build mode, exercise the
    compose image lines with an empty suffix and must pass unchanged. The release-image
    mode is exercised only by 12.3's local run and by the deployment's release
    validation.

## 13. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in order. Closeout changes
documentation only. A part that needs a code edit returns the change to implementation.

- [ ] 13.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`. Read the
  comments sections 7–12 added for any that narrate this change or the redesign, or that
  call a mechanism temporary. That includes the docstring of `scripts/push-distributions.py`
  if that file survives. Anything to rewrite returns the change to implementation.
- [ ] 13.2 **Import placement — confirm.** Check the imports sections 7–12 added in:
  - `scripts/release_components.py`;
  - `scripts/release_bom.py`;
  - `scripts/check_release_components.py`;
  - `scripts/check_release_versions.py`;
  - `scripts/check_release_record.py`;
  - `scripts/check_build_requirements.py`;
  - `scripts/load_candidate.py`;
  - `scripts/release_images.py`;
  - `scripts/buyer_domain_wheels.py`;
  - their tests.

  Look for any import still local without a recorded reason.
- [ ] 13.3 **Documentation compliance.**
  - Re-check D1–D21 against `openspec/README.md`'s placement table.
  - Check that no permanent document still describes:
    - a publishing workflow;
    - the release contract;
    - the curl installer or `market-cli-v*` tags;
    - `build-buyer`;
    - `push-wheels` or `clobber-wheels`;
    - an npm publication.
- [ ] 13.4 **Narrative compression.** Compress the completed notes of sections 1–12 to
  final behaviour, material evidence, deferred work and destinations. Sections 3–6 stay
  withdrawn with their history. The rejected and deferred alternatives stay in
  `design.md`.
- [ ] 13.5 **Roadmap currency.** Expected disposition: `docs/development/ROADMAP.md` owes
  nothing, since no market capability changes. Its unowned row on the relay role taking
  the admission-plugin wheel on the operator's word is unaffected: this change releases
  the plugin's image, not a wheel the relay pins. Record the disposition in the
  promotion record.
- [ ] 13.6 **Campaign index currency.**
  - Update this change's row in `openspec/changes/README.md`, and the Package and
    release readiness campaign's prose and graph.
  - Reconcile with `configure-pypi-trusted-publishing`: CI publishes nothing, so its
    trusted-publisher half has no consumer. Record in both rows which of the
    distribution-graph and PyPI-only installation acceptance it still owns.
  - Record 1.1e's question (`arkhai-vms-provisioning-iac` is not built by `make dist`) as
    unowned work in the campaign's section, then check 1.1e.
  - Run `make check-change-index`.
- [ ] 13.7 **Packaging.** Run `make check-packaging`, now including
  `check-release-components` and `check-build-requirements`, and resolve every failure.
  Run `make check-architecture-change CHANGE=publish-wheels-through-a-gate`. No
  `.agents/`, `.claude/` or `.codex/` file changes, so `make check-agent-skills` is not
  owed.
- [ ] 13.8 **End-to-end pipeline.** Record:
  - the passing E2E run the latest validation names, with its three lanes'
    (`test-e2e-vm`, `test-e2e-bare-metal`, `test-e2e-apicredits`) results;
  - the Helm validation's result for the chart without `appVersion`;
  - 12.3's local release-image lane run.

  Or record an explicit blocker naming its cause. The first marketplace release cut under
  this procedure happens only after the change lands on `main`, so it is not closeout
  evidence.
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
    - `make check-release-versions` and its offline scope (D14);
    - under "Versioning policy": the pin-move rule (D15);
    - the npm package not being a component until it can be loaded (D19);
    - no patch releases;
    - how a new PyPI project comes to be owned by the organization;
    - the published-packages table.

    Check 2.3.
  - `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization": nothing
    reaches a public channel except bytes a deployment validated (D1); every identity in
    a release record is a content identity, and development tags, revisions and
    registry contents guarantee nothing (D3); one program per name (D18).
  - `AGENTS.md`, "Public repository discipline", "Never enters this repository": admit a
    marketplace release's bill of materials holding content identities only, enforced by
    `make check-release-record` (D10).
  - `docs/development/BUILD_AND_PACKAGING.md`, "Checks": `check-release-components` (D7,
    D4's `--short=9` rule) and `check-build-requirements` with `build-constraints.txt`
    (D15).
  - `docs/development/TESTING.md`, "Locally verifiable and external-topology scenarios":
    the lanes' release-image mode and record (D17).
  - `docs/buyer-quickstart.md`, "1. Install": PyPI, pinned to a release's versions; the
    release's linux/amd64 `market` binary checked against its bill of materials; and the
    from-the-repository path, without `build-buyer` (D18).

  `openspec/specs/deployment-state/spec.md` is written by the archive (13.11).
  `deployment-state` has no `index.md`, and no capability is new, so
  `openspec/specs/README.md` is unchanged. Complete the promotion record below.
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
| D1 Continuous integration publishes nothing | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization"; `docs/development/RELEASING.md` | Pending (13.9, 13.11) |
| D2 Release candidate, marketplace release, release component, candidate store | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md` | Pending |
| D3 Every component of a release candidate is stored under its revision by one load | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization"; `docs/development/RELEASING.md` | Pending |
| D4 A candidate's revision is nine characters | `openspec/specs/deployment-state/spec.md`; `docs/development/BUILD_AND_PACKAGING.md`, "Checks" | Pending |
| D5 Loading does not refuse an edited tree | `docs/development/RELEASING.md` | Pending |
| D6 One declaration of release components | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md` | Pending |
| D7 The single-enumeration and workflow-credential checks | `openspec/specs/deployment-state/spec.md`; `docs/development/BUILD_AND_PACKAGING.md`, "Checks" | Pending |
| D8 Every declared image's build writes its revision tag | `openspec/specs/deployment-state/spec.md` | Pending (13.11) |
| D9 The chart names no release | `openspec/specs/deployment-state/spec.md` | Pending (13.11) |
| D10 The deployment builds the bill of materials, in layout 1 | `AGENTS.md`, "Public repository discipline"; `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md` | Pending |
| D11 A marketplace release is recorded last by a tagged commit on its release branch | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md`, "Cutting a release" | Pending |
| D12 The release record is checked at the cut | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md`, "Cutting a release" | Pending |
| D13 This repository's specification states only its own behaviour | `docs/development/RELEASING.md` (the deployment's part) | Pending |
| D14 A version changes when its contents change | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md` | Pending |
| D15 The build backend is pinned; a pin move is a release-wide bump | `openspec/specs/deployment-state/spec.md`; `docs/development/BUILD_AND_PACKAGING.md`, "Checks"; `docs/development/RELEASING.md`, "Versioning policy" | Pending |
| D16 A product version is distinct from a distribution version | `openspec/specs/deployment-state/spec.md` (the bill-of-materials requirement) | Pending (13.11) |
| D17 The local lanes can run a release candidate's images | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md`; `docs/development/TESTING.md`, "Locally verifiable and external-topology scenarios" | Pending |
| D18 The release's `market` binary is PyPI's CLI | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization"; `docs/buyer-quickstart.md`, "1. Install" | Pending |
| D19 The npm package is not a release component until it can be loaded | `openspec/specs/deployment-state/spec.md` (the declaration requirement); `docs/development/RELEASING.md` | Pending |
| D20 The orphaned release-verification requirement is removed | `openspec/specs/deployment-state/spec.md` (removed by the archive) | Pending (13.11) |
| D21 RELEASING.md keeps the anchors other documents cite | `docs/development/RELEASING.md` | Pending |
| D22 The change keeps its name | No permanent destination — the change's own directory name | — |
| Roadmap currency | `docs/development/ROADMAP.md`: expected no change | Pending (13.5) |
| Campaign index currency | `openspec/changes/README.md`: this row, the campaign, `configure-pypi-trusted-publishing`'s row, 1.1e's unowned item | Pending (13.6) |
