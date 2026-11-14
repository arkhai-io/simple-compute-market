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

Amended on 2026-11-13 after section 7 returned to planning ("Section 7 notes"), taking
option (b), which the owner confirmed:
- 7.5 is split. The workflow-credential rule joins `make check-packaging` in section 7.
  The single-enumeration rule is built and unit-tested in section 7, and joins
  `make check-packaging` in 10.9, once 10.3, 10.7 and 10.8 have made the last publish
  target read the declaration.
- `push-charts` (10.7) and `push-cli` (10.8) each gain a task.
- 1.1e and 2.3 had been left unchecked until closeout, inside sections 1 and 2. They are
  moved into the closeout (13.6, 13.9), with their text kept where it was, so that the
  round holding sections 1, 2 and 7 can complete.

Amended again on 2026-11-13, after section 9 returned to design ("Section 9 notes:
returned to design"). Design amended D18: the binary builds from a locked virtual
project, whose buyer domains a packaging check holds to the declaration, and
`check-uv-setup` reads every Dockerfile and every wheelhouse `pip` install. The owner
waived another design review. Section 9's 9.1, 9.2 and 9.5 are replanned, and 13.2,
13.7, 13.9 and the promotion record follow.

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

- 1.1e (moved to 13.6 on 2026-11-13, so that the round holding sections 1, 2 and 7 can
  complete; its text is kept here) `arkhai-vms-provisioning-iac` is the tenth and is **not** built by
  `make dist`, so it cannot be published and is not in the manifest. Whether
  that is deliberate — an Ansible-role package that nobody installs from an
  index — or an omission in the dist graph is a question for whoever owns it.
  Recorded rather than answered: adding it to the build is a separate decision
  from enumerating what the build already produces.
  - Planning note (2026-11-13): the declaration lists what a release ships (D6), which
    this question does not change. Closeout part 6 (13.6) records it as unowned work in
    the campaign's index section.

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
- 2.3 (moved to 13.9 on 2026-11-13, so that the round holding sections 1, 2 and 7 can
  complete; its text is kept here) Record in `docs/development/RELEASING.md` that merging no longer
  publishes, and what to do instead. This is a contributor-workflow break and
  the first person it surprises should find the answer where they look.
  - Planning note (2026-11-13): discharged by closeout's rewrite of RELEASING.md
    (13.9).
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
  - Planning note (2026-11-13): closed by 7.1, which deletes the workflow (D1), and by
    7.4, which removes the workflow assertions from `test_publish_matrix.py`. 7.1
    checks this task.
  - Closed (2026-11-13) by 7.1 and 7.4: `publish-pypi.yml` is deleted, so no workflow
    path reaches a PyPI upload, and `make test-release-tooling` passes with the
    workflow assertions gone (7.8).

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

- [x] 7.1 Delete `.github/workflows/publish-pypi.yml`, `publish-npm.yml`, `release.yml`
  and `release-cli.yml` (D1). Check 2.7, which this closes.
  - Verify: no file under `.github/workflows/` names PyPI, npm, ghcr or a release upload.
  - Done (2026-11-13). A search of `.github/workflows/` for PyPI, npm, ghcr and upload
    finds only `e2e.yml`'s `actions/upload-artifact` steps, which keep a run's
    diagnostics as workflow artifacts and publish nothing. 2.7 is checked.
- [x] 7.2 Delete `scripts/verify-marketplace-release.py` and
  `scripts/tests/test_verify_marketplace_release.py` (D1). Delete the curl installer:
  `install.sh`, `scripts/install-remote.sh`, `scripts/build-installer.sh`,
  `scripts/tests/test_install_remote_urls.py` and
  `scripts/tests/test_install_sh_dependencies.py`. Remove `install.sh` from
  `README.md`'s tree (D18).
  - Verify: a search of the tree outside `openspec/` finds no reference to the deleted
    files or to `arkhai.marketplace-release.v2`.
  - Done (2026-11-13), with one remainder this task's search does not exclude. Outside
    `openspec/` and `docs/`, a search finds no deleted file and no release contract.
    The search also matches uv's own installer URL (`astral.sh/uv/…/install.sh`) in
    the root and registry Makefiles and the host bootstrap script, which is not the
    deleted installer. It also matches synthetic workflow names that name no file:
    `publish-pypi.yml` in `test_ci_evidence.py` and `test_validate_slice.py`, and
    `.github/workflows/release.yml` in `test_check_python_version.py`. Two
    documents under `docs/` still describe what was deleted:
    - `docs/buyer-quickstart.md` gives the curl installer's URL;
    - `docs/development/RELEASING.md` describes `publish-pypi.yml` and `release.yml`.

    13.9 rewrites both documents, and 13.3 checks that no permanent document still
    describes a publishing workflow or the curl installer. Until closeout they describe
    deleted files.
- [x] 7.3 Set `.github/workflows/validate-model-release.yml` to `permissions: contents:
  read`, and remove the step that appends a validation line to the release's notes
  (D7). Downloading the release's assets still works with the read token.
  - Verify: the workflow's remaining steps reference only `secrets.GITHUB_TOKEN`.
  - Done (2026-11-13). Its one secret reference is `secrets.GITHUB_TOKEN`, in the
    download step, and `make check-workflow-credentials` passes on it.
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

  Point `scripts/push-distributions.py` and `scripts/tests/test_publish_matrix.py` at
  the reader. In the test:
  - delete the assertions about the deleted workflow (path filters, push triggers) and
    about `wheel_only`;
  - keep closure under repository dependencies, dependency order, name-at-path, and the
    RELEASING.md table's equality with the declared distributions (D21).

  - Verify: unit tests for the reader's refusals, one case per rule, in
    `scripts/tests/test_release_components.py`; `make test-release-tooling` passes.
  - Done (2026-11-13). Unit: `test_release_components.py` has a case for each
    refusal:
    - a missing required key, one case per key;
    - an unknown key, at the top and in an entry;
    - an empty `npm` list;
    - each duplicate rule: an image's name (across release and development images) and
      local name, a distribution's key, path, and name however it is spelled, a
      binary's name and path, and an npm package's path;
    - values of the wrong kind, including a list item that is not an object.

    It also reads every problem at once and the repository's own declaration.
    `test_publish_matrix.py` reads through the reader and passes. `make
    test-release-tooling` passed, 2817 tests.
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
  - Done (2026-11-13). The script takes `--rule enumeration` and `--rule credentials`,
    and runs both with neither: `check()`'s default is every rule, and so is the
    command line's. `make check-release-components`, which names no rule, printed the
    enumeration refusals below. The credential rule reads no declaration.
    - `make check-release-components` runs both rules.
    - `make check-workflow-credentials` runs the credential rule alone, and
      `check-packaging` runs it after `check-architecture`. 10.9 replaces it there with
      `check-release-components`.
    - Unit: `test_check_release_components.py`, over synthetic workflow and Makefile
      text, with clean cases. The credential rule has a case for:
      - no top-level `permissions:`;
      - each write grant, and `write-all`;
      - a named secret, by `secrets.X`, by `secrets['X']`, in another case, and after a
        `}}` inside a string literal;
      - a secret on a line beginning with `#` inside a block scalar, which is not a
        comment;
      - the secrets context read without a name (`toJSON(secrets)`,
        `secrets[matrix.name]`);
      - `secrets: inherit`;
      - `GITHUB_TOKEN` passing under either spelling and in lower case;
      - each named publishing step, and `docker/build-push-action` with `push: true`,
        with `push:` an expression, and with `push: false`, which passes.

      The enumeration rule has a case for each component kind named by a workflow and
      by a Makefile target: each distribution, image and development image, the chart
      by its path and by its `Chart.yaml` name, the binary, and an npm package once
      declared. It also has a case for an image named by its published name where that
      differs from its local name, and for
      each way a target is a publish target (`push-*`, `publish-*`, `clobber-*`,
      `load-candidate`, an uploader in the recipe) or a lane target (`test-e2e*`,
      `build-e2e*`, `pull-release-images`), a list held in a variable, and a longer
      name that is not a declared one.

      Further cases show each rule run alone on a tree breaking both, the credential
      rule passing with no declaration, `check()` running both rules when none is
      named, and the command passing on this tree with `--rule credentials`.
    - On the tree, `make check-workflow-credentials` prints `OK: no workflow can
      publish.` `make check-packaging` passes with it: it ran inside
      `scripts/change-workflow run pre-commit` (7.8).
    - On the tree, `make check-release-components` fails. The credential rule passes,
      so its output is the enumeration rule's alone, and it names exactly the five
      targets:
      ```text
      Makefile: publish target push-images names image registry
      Makefile: publish target push-images names image storefront
      Makefile: publish target push-images names image provisioning
      Makefile: publish target push-images names image frp-grant-admission
      Makefile: publish target push-dev-images names development image dev-env
      Makefile: publish target push-dev-images names development image e2e-tests
      Makefile: publish target push-charts names chart helm
      Makefile: publish target push-cli names binary market
      Makefile: publish target clobber-wheels names distribution arkhai-core-registry-client
      Makefile: publish target clobber-wheels names distribution arkhai-core-storefront-client
      Makefile: publish target clobber-wheels names distribution arkhai-vms-provisioning-operator-client
      ```
      (Each line ends "; read it from the declaration instead".)
- [x] 7.6 CI resolves every declared distribution against the wheelhouse it builds
  (D1). A test in `scripts/tests/` asserts every declared wheel is in `.dist`, run by
  `make test-release-tooling` inside `test-deployment-packaging`, after `tests.yml`'s
  `make dist-ci`. If `dist-ci` does not build every declared wheel, `test-deployment-
  packaging`'s job builds what is missing through the existing dist targets, and that
  is recorded in the task note.
  - Verify: passes locally after `make dist`.
  - Done (2026-11-13). `scripts/tests/test_release_wheelhouse.py` passes locally
    against this checkout's `.dist`, inside `make test-release-tooling`. In CI,
    `tests.yml` runs `make dist-ci` before `make test-deployment-packaging`, whose
    prerequisite is `test-release-tooling`. `dist-ci` builds a superset of
    `dist-release-set`, so the job needs no extra build step. That CI run is owed by
    validation (7.8).
- [x] 7.7 Correct the comments that cite the deleted workflows: the root `Makefile`'s
  `dist-release` and Artifact Registry comments, and any comment
  `make check-comment-hygiene` or a search for the workflow names finds.
  - Verify: `make check-comment-hygiene` passes.
  - Done (2026-11-13). The comments the section's notes list are corrected, and
    `make check-comment-hygiene` passes.
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
  - Done (2026-11-13, second session). Results:
    - `make test-release-tooling` (unit) passed, 2817 tests.
    - `make check-workflow-credentials` passed.
    - `make check-comment-hygiene` passed.
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`: its
      functional hooks passed, among them the relock, `make check-packaging` (running
      the credential rule) and every suite. Its closing `pre-commit` hook passed every
      check but the documentation citations, which fail on this change's own
      documents ("Section 7 notes: resumed", below).
  - End-to-end: confirmed that no scenario exercises this section. No marker in
    `e2e-tests/` covers a workflow, the declaration or the check, and none was added.
  - Owed by validation: confirmed as written above. `tests.yml` is a workflow
    `scripts/ci_evidence.py` lists, and its `test · test-deployment-packaging` job runs
    `make test-release-tooling` after `make dist-ci`.

### Section 7 notes: resumed (2026-11-13, second session)

**What this session added to the work-in-progress commit.**
- 7.5's split. `scripts/check_release_components.py` takes `--rule enumeration` and
  `--rule credentials`. `make check-workflow-credentials` runs the credential rule, and
  `check-packaging` runs that target. `make check-release-components` still runs both
  rules, and fails on the tree until 10.3, 10.7 and 10.8.
- Fixes from the two fresh-context checks:
  - The credential rule now refuses any read of the secrets context, inside a
    `${{ }}` expression, that does not name `GITHUB_TOKEN`. That includes a read that
    names no secret, such as `toJSON(secrets)` or `secrets[matrix.name]`, which can
    reach every secret. Before the fix it saw only `secrets.X` and `secrets['X']`, and
    it missed three more cases:
    - expressions on lines beginning with `#`, which inside a block scalar are text;
    - other letter cases, since Actions compares context and secret names without
      case;
    - an expression continuing past a `}}` inside a string literal.
  - A secret in a bare `if:` is not looked for. Actions does not allow the secrets
    context there, so the refusal would guard a case Actions already rejects
    (`ARCHITECTURE.md`, "No speculative guard code").
  - `docker/build-push-action` is refused for any `push:` but a literal `false`, such as
    an expression true on some events.
  - Test cases were added for the rules that had none (7.4 and 7.5 list them).
  - The docstrings of `release_components.py` and `check_release_components.py` now
    state the rule rather than claiming the tree already meets it.
  - `push-distributions.py` reports a `DeclarationError` instead of raising a
    traceback.
  - `push-wheels`' help says "declared".

**Choices for review**, beyond those the first session listed:
- The enumeration rule refuses a single mention of a declared component in a workflow,
  publish target or lane target, not only a list of them. D7 says "a list". A target
  naming one component by hand is the same drift D7 exists to stop, since the next
  component added is missed. The spec delta's scenario ("names it") reads the same way.
- `check-workflow-credentials` is a second target over one script. 10.9 should decide
  whether it stays as the credential rule's focused runner once `check-packaging` runs
  `check-release-components`. 13.9's `BUILD_AND_PACKAGING.md` row should name it if it
  stays.

**Declined from the fresh-context check.** The check asked that the declared-wheel
test (7.6) not depend on a wheelhouse a workflow builds, by giving
`test-release-tooling` a `dist-release-set` prerequisite or by moving the test into a
check target. I declined, for two reasons:
- 7.6 places the test in `test-release-tooling`, after `tests.yml`'s `make dist-ci`, by
  design. Every `make test` job runs after `make dist-ci`, as TESTING.md's
  "Boundary-Change Validation" describes, and `make validate-local` runs
  `check-packaging`, which builds `dist`, before `make test`.
- A `dist-release-set` prerequisite would rebuild every wheel inside the CI job that
  has just built them.

The test names the missing wheels and `make dist` when it fails.

The second check also noted that the root `Makefile`'s `dist-release` and
`dist-release-set` comments say nearly the same thing. That is cosmetic, and it is left
as it is.

**For closeout (13.3).** The citation check reads only `openspec/`, `docs/`, `tools/`,
`scripts/`, `e2e-tests/` and `.agents/` paths. It will not report
`docs/development/RELEASING.md`'s citations of the deleted
`.github/workflows/publish-pypi.yml` and `release.yml`, so 13.3 has to find them by
hand. 13.9's rewrite removes them.

**A finding for the round: the change's citations cannot pass before closeout.**
`check-repository`'s citation check, scoped to this change, reports 25 citations in
the change's own documents that do not resolve. They are of two kinds:
- files sections 8–12 create, named by their tasks: `scripts/release_bom.py`, its
  tests and fixture, and others;
- files this section deleted, named where the design (D1, D18), the proposal and 7.2's
  completed text say they are deleted: `scripts/verify-marketplace-release.py`,
  `scripts/install-remote.sh`, `scripts/build-installer.sh` and the deleted tests.

The first kind resolves as sections 8–12 land. The second never resolves, and this
step may not rewrite the design, the proposal or a completed task to remove it.
13.10 runs the same check and must resolve every match. The question is for the round
or closeout to settle: rewrite those citations at closeout, or have the scoped check
accept a path the change itself deletes. It was already failing on the first kind
before this section began: the plan's own `scripts/release_bom.py` did not exist when
it was planned.

**Outside the plan.** None beyond the fixes above, all within section 7's files.

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

**Planning's answer (2026-11-13).** Option (b), confirmed by the owner. 7.5 is amended
to split the two rules. 10.7 and 10.8 make `push-charts` and `push-cli` read the
declaration, and 10.9 adds the single-enumeration rule to `make check-packaging`. 1.1e
and 2.3 move into the closeout (13.6, 13.9). This section resumes from this commit.

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
  - Done (2026-11-13). Unit: `scripts/tests/test_release_bom.py`, passing inside `make
    test-release-tooling`. Its unit cases cover:
    - the fixture parsing into its subject and components by bom-ref;
    - the digest taken of the bytes as committed;
    - each refusal, named:
      - an unknown or absent layout;
      - an unknown field, at the top, in a component, and as an unknown property;
      - a `repository_url`;
      - a foreign URL: the vcs link changed, a second link, and a URL in a value, named
        by its component's bom-ref;
      - a key stated twice, which could otherwise hide a `repository_url` behind a
        clean copy;
    - each kind's identity, including:
      - a wheel's purl naming another file;
      - a bom-ref of an unknown kind or not matching its name;
      - the npm row's group and SHA-512;
    - the header, compared with its JSON type, and the subject, its lifecycles, and a
      repeated property;
    - the dirhash of a hand-written manifest built from SHA-256's own test vectors;
    - two archives of one file set, with different tar metadata and order, giving one
      digest;
    - a path an archive stores twice: counted once with one content, refused with two.

    Its real-Helm cases, under 8.2, are integration tests that start a real external
    process.

    The wheelhouse digest is `files_digest`, the same dirhash over file names. The
    fixture, `scripts/tests/fixtures/release-bom-layout1.cdx.json`, was written here from
    D10. No example document from the deployment is in this repository (see the notes).
- [x] 8.2 Pin Helm for the chart digest. Add a root `.helm-version` holding the version
  `tests.yml`'s `azure/setup-helm` installs (v4.3.0). The digest refuses to run under
  any other `helm version --short`. A test holds `tests.yml`'s setup-helm version equal to
  `.helm-version` (D14).
  - Verify: the equality test passes; a unit test with a stubbed `helm version` refuses a
    mismatch.
  - Done (2026-11-13). `.helm-version` holds `v4.3.0`. `release_bom.package_chart`
    compares `helm version --short`, before its `+`, with it, then runs the same `helm
    package` as `make dist-helm`, into a temporary directory. Unit, in
    `test_release_bom.py`:
    - `tests.yml`'s `azure/setup-helm` version equals `.helm-version`;
    - a stubbed Helm reporting v4.2.1 is refused before anything is packaged;
    - a stubbed Helm reporting the pin packages, and the archive is digested.

    Integration, starting the real pinned Helm, in the same file:
    - `helm/` packaged twice gives one digest;
    - the archive stores every file under `charts/`, and only those, exactly twice.

    Both skip without that Helm on `PATH`, except under `HELM_REQUIRED=1`, where a skip
    fails. Both ran locally under v4.3.0.
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
  - Done (2026-11-13). Library integration: `scripts/tests/test_check_release_versions.py`
    runs the check against real git in a scratch repository whose releases are cut as
    the procedure cuts them. The wheelhouse is a directory of wheel files whose bytes
    each test chooses. The chart's packaging is stubbed at the check's `chart` seam,
    since its digest is the reader's and is tested there. It covers each case the task
    lists, and also:
    - a tag carrying no record is not an earlier record, and cannot be checked with
      `--tag`;
    - a tag that a branch of its name shadows is still read;
    - a distribution respelled (`arkhai_core` for `arkhai-core`) is still the project
      an earlier record named;
    - an earlier record in an unknown layout is refused, not skipped;
    - a declared wheel missing from the wheelhouse is refused, naming `make dist`;
    - the command's pass and refusal output.

    Two cut cases, with the tag's own record as the subject:
    - **no build:** one release, checked with the wheelhouse directory absent and a
      chart seam that raises if called. It passes, saying no earlier record exists, so
      the tag was not compared with itself.
    - **a refusal:** a second release reusing the first one's version with other bytes
      is refused. Its summary lists only the first release.

    On this tree, `make check-release-versions` printed `OK: no earlier marketplace
    release carries a bill of materials, so there is nothing to compare the wheelhouse
    and the packaged chart with.` It still built its subject first: it read every
    declared wheel in `.dist` and packaged `helm/` under the pinned Helm.
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
  - Done (2026-11-13). Library integration: `scripts/tests/test_check_release_record.py`,
    with real git in a scratch repository. A well-formed record passes, with an earlier
    release present. Each rule has a failing case:
    - **rule 1:** the commit on another branch, no release branch, and a branch point
      `main` cannot reach. A remote's `main` reaches the branch point too.
    - **rule 2:** another path changed, and no record added.
    - **rule 3:** a field layout 1 does not admit, and a `repository_url`.
    - **rule 4:** another source revision and another version.
    - **rule 5:** a missing component, an undeclared one, a development image, and a
      component named twice. The declaration is read at the branch point, not from the
      checkout, and a branch point with no declaration or a nameless chart is refused.
    - **rule 6:** an earlier release's version with other bytes.

    It also has cases for:
    - a name that is not a marketplace tag, and a tag that does not exist;
    - a tag on a merge commit;
    - a declared npm package as a component, named without its scope;
    - the command's output with `--default-branch`.

    On this tree, `make check-release-record TAG=marketplace-v0.3.0` refuses with
    `marketplace-v0.3.0's commit has 2 parents; a release commit has exactly one`. It
    stops there, before reading any record. With no `TAG`, the target says to name one.
- [x] 8.5 Section verification.
  - Unit and integration: `make test-release-tooling` (unit: the reader and the digest;
    integration: the two checks against real git); `make check-packaging`;
    `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`.
  - End-to-end: no scenario exercises the release record. It is read only at a load and
    at the cut, and none is owed.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
    `azure/setup-helm` installs the version `.helm-version` names, and the chart-digest
    tests run rather than skip and pass.
  - Done (2026-11-13). Results:
    - `make test-release-tooling` passed, 2884 tests, none skipped. That includes the
      reader's unit cases, both checks' integration cases against real git, and the
      two cases that start the real pinned Helm.
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`: its
      functional hooks passed. They include the relock, which changed no lock, `make
      check-packaging` and every suite.
    - Its closing `pre-commit` hook passed every check but the documentation
      citations. That check reports 18 citations in the change's own documents, of the
      two kinds section 7's notes describe:
      - files sections 9–12 create: `scripts/buyer_domain_wheels.py`,
        `check_build_requirements.py`, `load_candidate.py`, `release_images.py` and
        their tests;
      - files section 7 deleted.

      Section 8's own files resolve seven of the 25 that section 7 found.
    - `make check-comment-hygiene` passed.
    - `make check-release-versions` and `make check-release-record` on the tree behave
      as 8.3 and 8.4 record.
  - End-to-end: confirmed that none is owed. No marker in `e2e-tests/` exercises the
    release record, and none was added.
  - Owed by validation: confirmed as written, now with `HELM_REQUIRED=1` on that job,
    so that a skip fails it ("Section 8 notes").

### Section 8 notes (2026-11-13)

**A finding the deployment must agree with: Helm stores each subchart twice.** Under
Helm v4.3.0, `helm package helm/` writes every file under `charts/` into the archive
twice, at the same path. Every other file is written once, and the copies are
byte-identical. Two real-Helm tests hold this: one asserts the archive's repeated
paths are exactly those under `charts/`, and the other packages `helm/` twice and gets
one digest. The digest would refuse differing copies. D14 lists "the package's regular
files by archive path" and does not say what a path stored twice counts as.
`release_bom.archive_digest` reads a file as its path and contents, so:
- a path stored twice with one content is one file and one line;
- a path stored twice with different contents is refused, since the copy a reader takes
  is then the reader's choice.

The deployment computes the same `arkhai:content-digest` from the stored package. If
its builder writes one line per archive member, the two digests differ for this chart.
`make check-release-versions` would then refuse every load at an unchanged chart
version once the first record exists. The owner should confirm that the deployment's
builder counts a path once. The rule belongs in the digest's description at closeout:
RELEASING.md (13.9), and the D14 requirement's wording if review wants it normative.

**Choices for review, where D10–D14 are silent.** No example document from the
deployment is in this repository. The fixture and the allowlist are therefore written
from D10's text. If the deployment's example differs, both follow it.
- The npm row has no purl, since D10's table gives none.
- An image's purl tag must be `<name>-` followed by the first nine characters of the
  subject's source revision. A wheel's purl must name its own distribution and version
  in its file name.
- The subject's version may carry a semver prerelease suffix.
- The reader checks fields, kinds, digest formats and URLs. It does not check key
  order or the serialization rules, which only fix the bytes the digest is taken of.
- Bom-ref names:
  - a wheel's is its declared `dist`, as spelled, which the record check holds it to;
    the version check compares names as PyPI does;
  - the chart's is its `Chart.yaml` name at the branch point;
  - an npm package's is its `package.json` name without `@arkhai/`.
- `PUBLIC_VCS_URL` is a constant in `release_bom.py`.
- "Every earlier record" is every other tag carrying one. Checking an old tag compares
  it with later releases too, as D14's rule reads.
- The record check finds `releases/<semver>` and the default branch locally or as any
  remote's branch of that name. The default branch is `main`, overridable with
  `--default-branch`. A tag on a merge commit is refused before rule 1.
- The version check always builds its subject, even with no earlier record, so every
  run exercises the Helm pin and the wheelhouse. It packages the chart itself into a
  temporary directory with `dist-helm`'s command, rather than reading `.dist/*.tgz`,
  so a stale package cannot be its subject. `check-release-versions` has no `dist`
  prerequisite: the load (11.2) builds `.dist` once and then runs the check on it.

**Outside the plan.**
- `release_components.chart_field` reads a `Chart.yaml` scalar without a YAML parser.
  `check_release_components._chart_name` now uses it instead of its own pattern, and
  the enumeration rule's refusals on the tree are unchanged.
- `tests.yml` gains `HELM_REQUIRED` beside `GITLEAKS_REQUIRED` on the packaging job's
  test step. The plan said section 8 reads `tests.yml` without changing it, meaning its
  Helm version, which is unchanged. TESTING.md requires a test that starts a real
  external process to run in a gate that fails on a skip. Without the variable, the
  real-Helm tests could skip in CI unnoticed.

**From the fresh-context check.** Fixed:
- a key stated twice, which `json.loads` would have let hide a `repository_url`;
- `%(refname:short)`, which turns a tag that a branch of its name shadows into
  `tags/<name>` and dropped its record;
- the record read as text rather than as committed bytes;
- the header's `version` accepting `true`;
- a URL refusal named by JSON path rather than by the component;
- the Helm skip gate;
- the tests patching the imported `REPO_ROOT`: each `main` now takes `root`;
- tests for the branches it named as untested;
- three task notes that overstated their tests.

Declined from the first check: none.

**From the second fresh-context check.** Fixed:
- The version check matched a wheel by its distribution exactly as spelled. It now
  compares names as PyPI does (PEP 503), so a respelled distribution is still the
  project an earlier record named.
- `root` now reaches the chart seam's pin.
- A version must begin with a digit, so it cannot carry a registry host.
- The declaration's path and the semver pattern are each written once
  (`release_components.DECLARATION_PATH`, `release_bom.SEMVER`).
- Tests were added for some refusal branches it listed: a `--tag` with no record, a
  missing `.helm-version`, and a branch point with no declaration or a nameless chart.

Some refusal branches still have no test. They are each a malformed shape, such as
properties that are not a list, a purl that is not a string, `helm package` writing
no archive, or an unreadable `package.json`. None is a guard nobody could trigger.

Declined from the second check:
- **Moving `git`, `committed_bom` and `recorded_releases` into `release_bom.py`.** Rule
  6 of the record check is the version check run with the record as its subject. The
  record check therefore imports the version check's own functions rather than a copy.
  `release_bom.py` stays the document reader that D12 says the two checks share, and
  it reads no git.
- **Rule 1 accepting any remote's `main`.** This is already listed as a choice for
  review. A fork's remote reaching the branch point would still have to be a commit
  that the record's source revision names.
- **The test-level label.** TESTING.md calls tests that start real external processes
  a third kind of integration test, beside in-process and library tests, run in a gate
  that fails on a skip. The real-Helm cases are that kind, and `HELM_REQUIRED` is their
  gate. The notes above call them integration.

**For closeout (13.9).** `docs/development/TESTING.md`, "Chart Render Tests", says the
supported Helm is `tests.yml`'s and that nothing enforces it. That is still true of the
render tests. The chart digest, however, now refuses any Helm but `.helm-version`'s,
and a test holds `.helm-version` equal to `tests.yml`'s version. 13.9 names no home
for this. Closeout should say in TESTING.md, or in BUILD_AND_PACKAGING.md beside
`.python-version`, that a Helm bump edits both files.

**For section 11.** `release_bom.files_digest(paths)` is the wheelhouse digest (D3).
Pass it `release_components.declared_wheels(...)`. `check_release_versions.check(root,
dist_dir=..., chart=...)` is the load's version check, and its `chart` seam takes the
chart directory and returns a `ChartPackage`.

**End-to-end.** Confirmed: no scenario exercises this section, and none was added.

**Owed by validation.** Confirmed as written in 8.5. In `tests.yml`, the job `test ·
test-deployment-packaging` installs Helm through `azure/setup-helm`, sets
`HELM_REQUIRED=1`, and runs `make test-deployment-packaging`. Its prerequisite
`test-release-tooling` holds the two real-Helm tests in `test_release_bom.py`. Under
`HELM_REQUIRED=1` a skip fails, so the job passing shows they ran and passed.

**From the triage of the round at `033dd0250`** (2026-11-14; implementation review 52,
validation 53). Fixed here, the checks recorded in section 12's last note:
- **V1 and T1: the chart's content digest no longer reads local state.** The real-Helm
  test asserting that `helm package` stores each subchart's files twice failed in CI:
  that happens only when `helm dependency update` (`make -C helm init`) has left an
  archive of each subchart beside its directory, which a clean checkout lacks. The
  same command leaves a `Chart.lock` stamped with its time, which Helm packages, and
  the chart's Python tests leave caches; packaged, a fresh lock alone moved the digest
  of an unchanged chart. Outside the plan:
  - `helm/.helmignore` names `Chart.lock`, `charts/*.tgz`, `__pycache__/`, `*.pyc`,
    `.pytest_cache/` and `.port-forward.pids`; the chart stays 0.4.1, which no release
    records;
  - `release_bom.package_chart` refuses a package storing a file Git ignores under the
    chart's directory (`git_ignored_files`, an injected seam);
  - `archive_digest` refuses any path stored more than once, so two readers of layout
    1 cannot digest one package two ways;
  - `helm/Makefile`'s `test-render` comment no longer says `init` keeps a stale archive
    from being rendered.

  `test_release_bom.py`: the twice-stored test is replaced by one packaging a copy of
  the chart's tracked files clean and after `helm dependency update`, a cache, a pytest
  cache and a pid file, to one content digest; a real-Helm case refusing an ignored file
  the `.helmignore` does not name; unit cases for the refusal, for any repeated path, and
  for `git_ignored_files` in a scratch repository. D14 records the rule.
- **52 F2: the record check holds the release branch's tip.** It refused only a tagged
  commit no `releases/<semver>` ref reached, so a commit added after the record passed.
  Every ref of that name, local or a remote's, must now be at the tag's commit.
  `test_check_release_record.py`: a later commit on the branch, and a remote branch at
  another commit beside one at the tag, each refused. D12's first item, the module
  docstring and the delta (a scenario) say so.

## 9. The release binary is PyPI's CLI

Delivers D18, as amended after the section's return to design. Implements the
requirement "The release binary is the buyer CLI with every declared buyer domain",
with its scenarios for a missing and an undeclared domain.

Replanned on 2026-11-13 against the amended D18. 9.1, 9.2 and 9.5 are rewritten:
- the binary builds from a locked virtual project through `scripts/uv_project.py image`;
- a packaging check holds that project's dependencies to the declaration;
- `check-uv-setup` reads every Dockerfile and every wheelhouse `pip` install.

Their in-progress notes are kept as the history of the commit the section returned
on. 9.3 and 9.4 stand as written; their work in that commit stands.

Touches:
- `scripts/buyer_domain_wheels.py`, renamed `scripts/market_binary.py`, and its test;
- `scripts/check_release_components.py`, a `market-binary` rule, and its test;
- `scripts/check_uv_setup.py` and its test;
- the binary's virtual project, `core/buyer/market-binary/` (`pyproject.toml`,
  `uv.lock`, `Dockerfile`), replacing `core/buyer/market-binary.Dockerfile`;
- the root `Makefile`'s `build`, `build-buyer`, `build-market-binary`,
  `check-market-binary` and `check-packaging`;
- `domains/vms/buyer/` (its `pyproject.toml`, `Makefile`, lock and `main.py`);
- `manifests/release-components.json`'s `binaries` entry.

- [x] 9.1 Rename `scripts/buyer_domain_wheels.py` to `scripts/market_binary.py`, and add
  the check holding the binary's project to the declaration (D18).
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
  - In progress (2026-11-13, before the return to design), unchecked because the section returned to design
    ("Section 9 notes: returned to design"). The script's default command, `domains`, prints the buyer-domain
    wheels. Four more commands derive the rest of the binary's build from the same
    reading ("Section 9 notes"):
    - `cli`: the buyer CLI's wheel;
    - `entry-point`: the console script it freezes;
    - `constraints`: every declared distribution at its declared version;
    - `pyinstaller-options`.

    `domains` and `cli` refuse a wheel `.dist` lacks, naming `make dist`.

    Unit: `scripts/tests/test_buyer_domain_wheels.py`, over synthetic declarations and
    projects, 12 cases, passing. It has a case for:
    - each command's output;
    - two entry points in one domain;
    - a domain wheel and the CLI wheel each missing from `.dist`;
    - a declared project with no `pyproject.toml`;
    - two distributions defining the console script, none, and no buyer domain;
    - a declaration the reader refuses.

    One case reads the tree. It finds `arkhai-core-buyer` with `core_buyer.cli:main`,
    and the three domains the task names. `make build-market-binary` printed the same
    three wheels.
  - Done (2026-11-13, after the replan). `scripts/market_binary.py` takes a required
    `--target` and four commands: `name`, `output-dir`, `entry-point` and
    `pyinstaller-options`. `binary()` refuses no entry with the target, two, and a
    `path` not ending in `name`. `BINARY_NAME`, `domains`, `cli`, `constraints` and the
    wheelhouse refusal are gone. The script also holds `TARGET` and `PROJECT`
    (`core/buyer/market-binary`), which the check uses to find the binary and its
    project.
    - The rule is `check_release_components.check_market_binary`, run as `--rule
      market-binary`. `make check-market-binary` runs it in `check-packaging`, and
      `make check-release-components` runs it with the other two rules.
    - Unit, `scripts/tests/test_market_binary.py`, 14 cases over synthetic declarations
      and projects. They cover each command; the entry found by its target among two;
      no entry, two, and a misnamed path; the CLI and domains in declaration order;
      and every case the task says to keep.
    - Unit, `scripts/tests/test_check_release_components.py`. The rule passes an exact
      project, and one spelled with other normalisations, specifiers and markers. It
      names a missing domain with its project, a missing CLI, and an extra
      distribution. It ignores the `freeze` group and refuses a missing project. It
      also runs alone, and with every rule when none is named. The tree tests now
      build the binary's project, since `check()` runs every rule by default.
    - On the tree: the repository case finds `arkhai-core-buyer`, `core_buyer.cli:main`,
      `market` at `.dist/bin/market`, and the three domains. `make check-market-binary`
      prints `OK: the market binary's project bundles exactly the buyer CLI and the
      declared buyer domains.` `make check-release-components` prints the same eleven
      enumeration refusals 7.5 records, and nothing from the new rule.
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
  - In progress (2026-11-13, before the return to design), unchecked: its install from the wheelhouse is the design
    question the section returned on. The build image is `python:3.13-slim-bookworm`, pinned by its
    index digest, for linux/amd64. Its first step refuses to build if the image's Python
    is not the `PYTHON_VERSION` default, since the digest, not the tag, selects the
    image. `check-python-version` now also reads `*.Dockerfile`, so it holds that default
    to `.python-version` ("Section 9 notes").

    The install, the hidden imports and the smoke test go beyond the task's wording, as
    the notes explain. PyInstaller 6.22.3 is installed in the build image only.

    Build evidence, a local image build rather than one of TESTING.md's levels: `make
    build-market-binary` succeeded locally on Docker with BuildKit, building from the
    pinned digest, and exported a 48 MB `.dist/bin/market`. In the smoke test the frozen
    binary printed `api_credits.v1`, `bare_metal.v1` and `compute.v1`, the same stdout
    as the installed CLI. No skipped domain was reported, and the count was one line per
    bundled domain wheel. Which domains it listed is read from that build's log. Since
    that build, the count is one line per registered entry point, and the Makefile's
    argument handling has changed; neither has been rebuilt.
  - Done (2026-11-13, after the replan).
    - **The project.** `core/buyer/market-binary/pyproject.toml` is as D18 shows, with a
      header comment. `make lock PROJECTS=core/buyer/market-binary` could not lock it at
      first: `uv_project.py lock` read the project's existing lock and refused a project
      with none. It now locks a named project with no lock afresh ("Section 9 notes:
      after the replan", outside the plan). The lock resolves 105 packages: every repository distribution from
      `../../../.dist`, and PyInstaller 6.22.3 in the `freeze` group.
    - **The Dockerfile.** `core/buyer/market-binary/Dockerfile` builds on
      `ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim` for linux/amd64,
      pinned at `sha256:531f855b…44ca`. It keeps the Python check, binutils, the entry
      point, the options, the smoke test and the `scratch` export. It copies `.dist/`,
      the script and the project's two files under `/repo`, and installs with
      `uv_project.py image --project /repo/core/buyer/market-binary -- --group freeze`
      into `UV_PROJECT_ENVIRONMENT=/opt/market`. `BINARY_NAME` names PyInstaller's
      output, the smoke test's two commands and the final `COPY`. The constraints
      argument and both `pip install` steps are gone.
    - **The Makefile.** `build-market-binary` reads `name`, `output-dir`, `entry-point`
      and `pyinstaller-options` from `market_binary.py --target $@`, and exports to the
      directory `output-dir` prints. It names no domain, binary or binary path. It names
      the Dockerfile's path, as every image target does.
    - **The digest.** As before, it was taken from the first build's BuildKit log: that
      build ran on the unpinned tag and resolved `sha256:531f855b…44ca`. The second build
      ran from the pin.
    - **`check-uv-setup`.** It reads `*.Dockerfile` as well as `Dockerfile*`, and skips
      ignore files. In a Dockerfile that copies the wheelhouse, it refuses any `pip
      install`, `pip3 install`, `python -m pip install` or `uv pip install` that may
      read the wheelhouse. As the task defines it, that is one passing `--find-links`
      or `-f` with any value, or naming a path in `.dist`. It also counts a path where
      the file copied `.dist/`, such as the `/dist` of the install this section
      returned on. That rule replaces its narrower `uv pip install --find-links`
      pattern. Like the existing `uv sync` refusal, it applies to every stage of such a
      file, not only the copying stage: a later stage can reach the copy through
      `--from`. Its docstring states the rule and its known limits (the handoff
      below). Closeout edits no code, so the docstring could not wait for 13.9; 13.9
      still amends BUILD_AND_PACKAGING.md's row.
    - Unit, `scripts/tests/test_check_uv_setup.py`, 12 new cases, passing:
      - a `market.Dockerfile` is read;
      - a `Dockerfile.dockerignore`, which `Dockerfile*` matches, is not read, though
        it holds text the check would refuse in a Dockerfile;
      - a wheelhouse install in a later stage, through a mount from the copying stage,
        is refused;
      - seven installs reading the wheelhouse are each refused, among them plain
        `pip install --find-links`, `python3 -m pip install -f`, `pip3 install
        --find-links=`, `uv pip install --find-links`, a wheel by its copied path, and
        a wheel by its `.dist` path;
      - the returned install, constrained and then reinstalled from `/dist`, is refused;
      - a `uv pip install` naming no wheelhouse, as in
        `provisioning/compute/service/Dockerfile`, passes;
      - the installs made through the script (`image` and `install-wheel`) pass, by
        the existing case.
    - Unit, `scripts/tests/test_uv_project.py`: a named project with no lock is locked
      with `uv lock --find-links` and no upgrade flags. A named directory that is
      missing, or that declares no project inside another one, is refused before uv
      runs.
    - On the tree: `make check-uv-setup`, `make check-python-version` and `make
      check-market-binary` passed. `make check-locks` passed inside `make
      check-packaging`, in the pre-commit run (9.5).
    - Local build evidence, an image build rather than one of TESTING.md's levels:
      - The first build, on the unpinned tag, succeeded. Its install step ran `uv sync
        --locked --find-links ../../../.dist --group freeze` with a `--reinstall-package`
        for each internal package, and installed 104 packages.
      - Its smoke test printed `api_credits.v1`, `bare_metal.v1` and `compute.v1`, and
        reported no skipped domain.
      - It exported a 48 MB `.dist/bin/market`.
      - The second build, from the pinned digest, succeeded and exported the binary
        again. BuildKit reused every layer of the first build, since the digest is the
        one that build resolved. Its smoke test result is therefore the first build's.
- [x] 9.3 Point the declaration's `market` entry at `build-market-binary` and
  `.dist/bin/market`. `build` builds it in place of `build-buyer`.
  - Retire `build-buyer`, the PyInstaller recipe in `domains/vms/buyer/Makefile`, and
    `domains/vms/buyer/src/arkhai_vms_buyer/main.py`, whose only user is that recipe.
  - Update any target, test or comment that names them; the search includes
    `scripts/tests/test_init_targets.py` and the e2e-tests comments.
  - Verify: a search outside `openspec/` and `docs/` finds no `build-buyer` and no
    `arkhai_vms_buyer/main.py`. `make test-release-tooling` passes. `docs/` is rewritten
    at closeout (13.9).
  - Done (2026-11-13, after the replan). The work recorded below stands. A search
    outside `openspec/` and `docs/` again finds no `build-buyer`,
    `arkhai_vms_buyer/main.py` or `vms/buyer/dist`, and `make test-release-tooling`
    passed (9.5).
  - In progress (2026-11-13), unchecked with the section. The declaration names `build-market-binary` and `.dist/bin/market`,
    and `build` runs `build-market-binary`. `build-buyer` is retired. So are the VM
    buyer Makefile's `build` and `smoke-test` targets and `main.py`.

    Comments updated:
    - the root `Makefile`'s `build-e2e-base` comment and push prerequisites;
    - `arkhai_vms_buyer.cli`'s comment on `app`, which tests and a docs attachment
      still import;
    - `domains/Makefile`'s `dist-buyer` help, which called the VM buyer the `market`
      CLI.

    `test_init_targets.py` names only `init-buyer`, which stays, and no e2e-tests
    comment named `build-buyer`. `push-cli` now uploads `.dist/bin/market` ("Section 9
    notes"). A search outside `openspec/` and `docs/` for `build-buyer`,
    `arkhai_vms_buyer/main.py` and `vms/buyer/dist` finds nothing. `make
    test-release-tooling` passed, 2895 tests, inside the pre-commit run (9.5).
- [x] 9.4 Remove `pyinstaller` from `arkhai-vms-buyer`'s runtime dependencies, and bump
  it a minor version (0.11.0 → 0.12.0) per RELEASING.md's versioning policy. Move any
  exact pin on it with the bump, and refresh every lock that installs it with
  `make lock`.
  - Verify:
    - `make check-version-bumps` passes;
    - `make check-packaging` passes, with locks current;
    - `make test-domains` passes for the VM buyer;
    - the built wheel's metadata requires no PyInstaller.
  - Done (2026-11-13, after the replan). The work and evidence recorded below stand.
    No lock in the tree names `pyinstaller` but the binary's own, in its `freeze`
    group, which is no published distribution's dependency. `make check-version-bumps`
    and `make check-packaging` passed again in the pre-commit run (9.5).
  - In progress (2026-11-13), unchecked with the section; its own evidence passes, and
    the package's description now calls it the VM buyer domain of the `market` CLI. No exact pin on `arkhai-vms-buyer` exists. The VM storefront and
    `e2e-tests` declare a `>=0.9.0` floor, which is unchanged. `make lock` rewrote the
    three locks that install it: the VM buyer's, the VM storefront's and `e2e-tests`'.
    No lock in the tree now names `pyinstaller`. Results:
    - `make check-version-bumps` passed.
    - `make check-packaging` passed with the locks current, inside the pre-commit run's
      functional hooks (9.5).
    - The VM buyer's part of `make test-domains` (unit, through `make -C domains/vms/buyer
      test`) passed, 256 tests. Its reinit removed PyInstaller and setuptools from the
      environment.
    - A new case in `scripts/tests/test_release_wheelhouse.py`, in the scripts' suite,
      reads the built wheelhouse: every declared wheel's `METADATA` in `.dist`, failing
      on a missing one. It refuses any `Requires-Dist` naming PyInstaller, and it
      passes, `arkhai_vms_buyer-0.12.0` among the wheels it read.
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
  - Done (2026-11-13, after the replan). Results:
    - Unit: `make test-release-tooling` passed, 2922 tests, after the fresh-context
      fixes. It holds 9.1's and 9.2's cases, `test_check_python_version.py` and
      `test_uv_project.py`.
    - Local build evidence: 9.2's build and smoke test, from the locked project (9.2's
      note says what the pinned build reused).
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate` ran twice,
      after the build and again after the fresh-context fixes. Both times its
      functional hooks passed:
      - the relock, which changed no lock;
      - `make check-packaging`, whose output includes `check-uv-setup`, `check-locks`,
        `check-python-version`, `check-project-layout`, `check-architecture`,
        `check-workflow-credentials` and `check-market-binary`, each printing `OK`;
      - every suite.
    - Both times the closing `pre-commit` hook passed every check but the documentation
      citations. That check reports 19 citations in the change's own documents, of the
      two kinds section 7's notes describe:
      - files sections 10–12 create;
      - files the change deleted or renamed: section 7's, and now
        `scripts/buyer_domain_wheels.py` and its test, which this section renamed.
        The plan's own text and the in-progress notes name them.
    - Search: outside `openspec/` and `docs/`, no `buyer_domain_wheels`,
      `market-binary.Dockerfile` or `pip install` from the wheelhouse remains. The one
      Dockerfile `pip install`, in `provisioning/compute/service/Dockerfile`, names no
      wheelhouse.
  - End-to-end: confirmed. No marker in `e2e-tests/` runs the binary, and none was added.
    The lanes install `market` from the wheels through `e2e-tests/uv.lock`.
  - Owed by validation: confirmed as written above. `tests.yml` is a workflow
    `scripts/ci_evidence.py` lists, and its `test · test-deployment-packaging` job runs
    `make test-release-tooling`.
  - Evidence so far (2026-11-13, before the return to design), unchecked with the section:
    - Unit: `test_buyer_domain_wheels.py` passed, 12 cases since the fresh-context fixes.
    - Build evidence: 9.2's smoke test passed, on the build before those fixes.
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`, run
      before the fresh-context fixes: its
      functional hooks passed. They include the relock, which changed no further lock,
      `make check-packaging` and every suite; `make test-release-tooling` passed 2895
      tests. `check-packaging` passing says nothing about the binary's Dockerfile:
      `check-uv-setup` reads only `Dockerfile*` (the return, below).
    - Its closing `pre-commit` hook passed every check but the documentation citations.
      That check reports 17 citations in the change's own documents, of the two kinds
      section 7's notes describe: files sections 10–12 create, and files section 7
      deleted. `scripts/buyer_domain_wheels.py` resolves one of the 18 section 8 found.
  - End-to-end: confirmed. No marker in `e2e-tests/` runs the binary, and none was
    added. The lanes' test image installs `market` from the wheels through
    `e2e-tests/uv.lock`, which 9.4 relocked without PyInstaller, so the lanes exercise
    the repackaged VM buyer.
  - Owed by validation: none. The new cases in `scripts/tests/` run in `tests.yml`'s
    `test · test-deployment-packaging` job, which section 7 already owes.

### Section 9 notes: after the replan (2026-11-13)

**Outside the plan.**
- **`scripts/uv_project.py lock` locks a new project.** It read a named project's
  existing lock to choose its upgrade flags, so it refused a project with none, and
  `make lock PROJECTS=core/buyer/market-binary` failed. A project with no lock now gets
  `uv lock --find-links <wheelhouse>` with no upgrade flags, since a first lock resolves
  everything afresh. A named directory must declare a project, or the command refuses
  before uv runs. Without that, uv would lock an enclosing project instead, such as
  `core/buyer` for `PROJECTS=core/buyer/src`, now that a project sits inside
  `core/buyer`. Neither file is in the section's Touches list.
- **`check_uv_setup.py`'s docstring** is amended here, not at 13.9, since closeout edits
  no code.

**Choices for review.**
- `market_binary.py` holds the binary's build target and project path as `TARGET` and
  `PROJECT`, so that the check can find the binary and its project. The Dockerfile
  spells its own project path in its `COPY`s, and the Makefile spells the Dockerfile's
  path, as every image does. A second binary would need a mapping from target to
  project, and none is speculated now.
- The `market-binary` rule finds the binary as the build does, by `TARGET`. A
  declaration whose binary names another target fails the rule with the script's
  refusal, not a pass.
- The pip refusal counts `--find-links`/`-f` with any value as reading the wheelhouse,
  as 9.2's task defines it. A `pip install -f https://…` in a Dockerfile that copies
  `.dist/` is therefore refused, even with nothing from the wheelhouse.

**Known limits of the pip refusal**, stated in the docstring: an install finding the
wheelhouse only through `PIP_FIND_LINKS`, `UV_FIND_LINKS` or a shell variable holding
its paths, and a Dockerfile that bind-mounts `.dist` without copying it. The last
predates this section: the whole check skips a file that does not copy the wheelhouse.

**Declined from the fresh-context check.**
- **`.dockerignore` hard-codes `.dist/bin`**, the binary's output directory, which the
  Makefile now reads from the declaration. It is the ignore file's own exclusion, and a
  moved `path` would make the old binary part of build contexts again, not part of an
  image, since no image copies `.dist/bin`. It is left as a known second copy rather
  than a test, because nothing else holds an ignore file to the declaration.
- **Amending 13.9 and the Touches list.** A later task and a section's header are
  planning's to edit. They are recorded here and under "For closeout" instead.

**For closeout.**
- **13.9, `docs/development/BUILD_AND_PACKAGING.md`:**
  - "Locks": `make lock PROJECTS=<dir>` locks a project with no lock yet.
  - "Images": the binary's project is the one image-like build that exports a file
    rather than an image, and it installs no project wheel (`install-wheel` is
    skipped, as for a virtual project).
  - "Checks": `check-uv-setup`'s row gains the pip rule and `*.Dockerfile`, and a
    `check-market-binary` row is added.
- **13.9, the binary's digest.** A Python bump re-pins
  `core/buyer/market-binary/Dockerfile`'s digest, and the build's own check refuses a
  stale one. The earlier notes' "For closeout" line already asks BUILD_AND_PACKAGING.md
  to say so; the image is now the uv one.
- The earlier notes' closeout items still stand.

**End-to-end.** None owed, confirmed in 9.5.

### Section 9 notes: returned to design (2026-11-13)

**Why the section stopped.** D18 and the repository's image rule cannot both hold as
written, and choosing between them is a design decision.
- **What D18 asks.** The binary's build image installs the buyer domains from `.dist`,
  "derived from the declaration and never listed in a Dockerfile". No project's lock
  covers `arkhai-core-buyer` with all three domains.
- **What the rule says.** `docs/development/BUILD_AND_PACKAGING.md`, "Images", says "An
  image installs the committed lock exactly as it is", through `scripts/uv_project.py`.
  `check-uv-setup`'s row refuses a Dockerfile that installs from the wheelhouse without
  the script, or that spells a repository distribution's version.
- **What this commit does.** `core/buyer/market-binary.Dockerfile` installs with
  `pip`, with no lock:
  - it pins every declared distribution through a constraints build argument;
  - it then reinstalls each one from `.dist` alone.

  It passes `check-uv-setup` only because that check reads `Dockerfile*` and not
  `*.Dockerfile`. This section widened `check-python-version` to `*.Dockerfile`
  precisely so that the plan's file name would not escape it. Widening `check-uv-setup`
  the same way would refuse this file, and leaving it narrow keeps a private exception,
  which `AGENTS.md`'s "Amend a rule or comply" forbids.
- **The hazard is real, not only formal.** Suppose PyPI serves an internal package at
  the version `.dist` holds, but with other `Requires-Dist`. The first resolve can then
  take PyPI's dependency set, and the reinstall from `.dist` with `--no-deps` keeps it.
  That is the failure BUILD_AND_PACKAGING.md's "Wheels" section describes. Third-party
  versions are also unlocked, which is how an unlocked image build once broke (the
  comment in `e2e-tests/Dockerfile`).

**Options for design.**
- **(a), recommended. A locked project for the binary.** For example
  `core/buyer/market-binary/`, with a `pyproject.toml` depending on `arkhai-core-buyer`
  and the buyer domains, PyInstaller in a group, and a `uv.lock` that `make lock`
  relocks.
  - The image installs it through `uv_project.py image`, as every image does.
  - A test (or `check-release-components`) holds the project's dependencies equal to
    what `buyer_domain_wheels.py` derives from the declaration, naming a missing or
    extra domain. RELEASING.md's table and D21 are the precedent: "a table … held equal
    by a check, is not a second list".
  - D18's "never listed in a Dockerfile" still holds. Its "derived from the
    declaration" becomes "held equal to the declaration by a check".
  - Third-party versions are locked, and `check-uv-setup` widens to `*.Dockerfile` with
    no exception.
  - Cost: a lock-only project to classify in `docs/development/ARCHITECTURE.toml`, and
    the check.
- **(b) Amend the image rule for the binary's build.** BUILD_AND_PACKAGING.md would admit
  an unlocked install for a build image that ships no image, with the internal closure
  installed from `.dist` first:
  1. `buyer_domain_wheels.py` derives the closure under repository dependencies;
  2. it is installed with `--no-index --no-deps`;
  3. only third-party packages are then resolved from PyPI.

  `check-uv-setup` widens to `*.Dockerfile` and states the amendment. This keeps D18 as
  written, but leaves third-party versions unlocked in a binary customers download.
- **(c) Keep this commit's install, and amend the rule to admit it as it is.** Not
  recommended, because of the `Requires-Dist` hazard above.

**A smaller question for the same design round.**
- The binary's name and output are spelled outside the declaration:
  - `BINARY_NAME = "market"` in `buyer_domain_wheels.py`;
  - `--name market` and `/market` in the Dockerfile;
  - `dest=$(DIST_DIR)/bin` in `build-market-binary`.
- The single-enumeration rule does not cover a build target, so nothing catches these
  drifting from `binaries[]`. Reading them from the declaration is cheap, if design
  wants it.

**What this commit holds (no task checked).**
- 9.1–9.4 implemented as their notes above say, with the evidence recorded there.
- Fixes from the fresh-context check, made after the pre-commit run:
  - per-image ignore files exclude `.dist/bin`;
  - the smoke test counts entry points, not wheels;
  - `build-market-binary` stops on a failing derivation instead of passing an empty
    argument;
  - `constraints` reports a missing `pyproject.toml`;
  - the CLI-wheel refusal and the missing-project case have tests;
  - the wheel-metadata case fails on a missing wheel rather than skipping it;
  - `arkhai-vms-buyer`'s description;
  - overstated evidence labels in the notes.

  After these fixes, the scripts' affected tests were rerun and pass. Neither the
  binary build nor the pre-commit run was repeated.

**Not done.** `check-uv-setup` is not widened to `*.Dockerfile`, since the chosen option
decides what it then refuses. The section's closing pre-commit run and a second
fresh-context check belong to the session that finishes it.

**How design settled it.** Design took option (a), and D18 was amended; the owner waived
another design review. The section was replanned: 9.1, 9.2 and 9.5 above.

Design corrected two of these notes:
- **A lock with the CLI and all three domains does exist.** `e2e-tests/uv.lock` resolves
  all four from `.dist`. D18 rejects building the binary from it, because a test project
  would then own what customers download.
- **Widening `check-uv-setup` to `*.Dockerfile` would not have refused this commit's
  install.** Its Dockerfile rule recognised only `uv sync` and `uv pip install
  --find-links`, and this commit's pins come through a build argument. 9.2 closes both
  gaps.

A virtual project is not a package to the architecture check, so the binary's project
needs no row in `ARCHITECTURE.toml`.

### Section 9 notes (2026-11-13)

**How the binary's build works, where the task is silent.**
- **What is derived.** The domains are not the only thing derived. The buyer CLI is the
  declared distribution whose project defines `market` as a console script, and its
  entry point is that script's value. Neither is named in the Dockerfile or the
  Makefile.
- **Hidden imports.** PyInstaller passes `--hidden-import` for each module a domain's
  entry point names, as well as `--copy-metadata` for the CLI and each domain.
  Discovery imports each domain by the name in its entry point, which PyInstaller's
  import analysis cannot see. That they are needed is reasoning from how discovery
  works; no build without them was made.
- **The two-phase install.** PyPI also serves the internal distributions, some at the
  versions `.dist` holds, and the binary must bundle `.dist`'s bytes.
  1. The first `pip install` resolves third-party packages from PyPI, holding every
     declared distribution at its declared version (`constraints`).
  2. The second reinstalls each declared distribution the first installed from `.dist`
     alone, with `--no-index --no-deps --force-reinstall`, whichever source the
     resolver chose.

  Third-party versions are not locked. No project's lock covers the CLI with all three
  domains, and D18 makes the binary's identity its SHA-256, not its repeatability.
- **The smoke test.** It runs `market plugins` twice, in the venv and frozen, and
  requires:
  - the same stdout from both;
  - one line per registered `market.buyer_domains` entry point, as the venv's metadata
    counts them, since one wheel may register several;
  - no "skipping buyer domain" on either stderr.

  Discovery only warns and skips a domain that fails to load, and the API-credit domain
  prints pydantic `UserWarning`s on stderr, so the outputs cannot be compared with
  stderr included. The first build failed on exactly that.
- **Output.** The binary is exported with `docker build --output type=local` from a
  final `scratch` stage. That needs BuildKit, which Docker uses by default and Podman
  supports. The root `.dockerignore` excludes `.dist/bin`, and so do the three
  per-image ignore files that admit `.dist/` whole: the VM storefront's and the two lane
  doubles'. No image build therefore receives the last binary, or has its cache
  invalidated by it.
- **No `dist` prerequisite.** Like the image targets, `build-market-binary` builds no
  wheels. `build` runs `dist` first, and 11.2's load builds `.dist` once.

**How the digest was obtained.** The session could not query a registry: `docker image
inspect`, `docker pull` and web fetches are not in this step's rules. The first build
ran on the unpinned tag, and BuildKit's log recorded the digest it resolved,
`sha256:281d39ff…0b7f`. That digest was pinned, and the second build ran from it.
Bumping Python means pinning a new digest; the build's own check refuses a stale one.

**Outside the plan.**
- `scripts/check_python_version.py` read only `Dockerfile*`, so the plan's file name,
  `market-binary.Dockerfile`, would have escaped the check 9.2 says applies. It now
  also reads `*.Dockerfile`, with a test case.
- `push-cli` uploaded `domains/vms/buyer/dist/market`, which no build writes once
  `build-buyer` is retired. It now uploads `.dist/bin/market`, spelled literally, so
  the single-enumeration rule still refuses it until 10.8 makes it read the
  declaration. Its refusal is unchanged: "publish target push-cli names binary market".
- `domains/Makefile`'s `dist-buyer` help no longer calls the VM buyer the `market` CLI.

**For closeout.**
- **13.9.** `docs/buyer-quickstart.md` still gives `make build-buyer`.
- **13.3 or 13.9.** `docs/development/BUILD_AND_PACKAGING.md` should say:
  - `check-python-version` reads `*.Dockerfile`;
  - the binary's build image is pinned by digest, and a Python bump re-pins it.
- **Defect, not this change's.** The API-credit domain prints pydantic `UserWarning`s
  ("Field name "schema" … shadows an attribute in parent") whenever `market` starts,
  frozen or not. It is not this change's. It could be recorded as unowned in the
  index at closeout (13.6).

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
  - Done (2026-11-13). The six Makefiles use `--short=9`. The check is a fourth rule of
    `scripts/check_release_components.py`, `revision` (`--rule revision`). It refuses
    any `git rev-parse` in a Makefile that abbreviates with anything but `--short=9`,
    across continuation lines too, and reads no declaration.
    - Unit, `test_check_release_components.py`: a bare `--short`, `--short=7` and
      `--short=12` each refused; one across a continuation refused; `--short=9`, a full
      revision and a comment pass; the rule run alone; every rule run when none is
      named; the command passing on this tree with `--rule revision`.
    - `make check-release-components` passes on the tree with all four rules.
- [x] 10.2 Every declared image's and development image's build writes
  `arkhai:<local>-<rev9>` when `IMAGE_SUFFIX` is empty. `build-bare-metal-storefront`
  gains its tag (D8).
  - Extend `scripts/tests/test_image_publication_contract.py` from provisioning to every
    declared image and development image, read from the declaration.
  - Verify: the extended test passes.
  - Done (2026-11-13). `build-bare-metal-storefront` tags its image with the revision
    when `IMAGE_SUFFIX` is empty, as `build-frp-grant-admission` does.
    `test_image_publication_contract.py` is rewritten. It follows `make build-dev`
    through `make -n`, entering each subproject Makefile that a recipe enters with
    `cd <dir> && make <target>`, which `make -n` prints rather than runs. It reads the
    images from the declaration. Unit, a static check of the Makefiles' recipes
    through `make -n`, as `test_change_build_and_helm_targets.py` is. It passes:
    - each of the five release images and two development images has a `docker build`
      writing `arkhai:<local>`, and a `docker tag arkhai:<local> arkhai:<local>-<rev9>`;
    - every image `push-images` and `push-dev-images` push from, as the script runs
      them with the arguments their recipes pass and `run` stubbed, is a tag a build
      writes. Which images they push is `test_publish_artifacts.py`'s (10.3).

    `test_change_build_and_helm_targets.py` (unit, through `make -n`): the bare-metal
    storefront joins the frps image's case, tagged with its commit unless suffixed,
    and its `_commit()` reads `--short=9`.
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
  - Done (2026-11-13). `scripts/publish_artifacts.py` reads the declaration and has
    the commands `check`, `images [--development]`, `chart` and `binaries`. Each push
    target is one line naming no component. Gone:
    - `push-wheels`, and `scripts/push-distributions.py`, its only caller;
    - `clobber-wheels`, and the script's `wheel` command and `publish_wheel`, whose
      only caller it was;
    - `PYTHON_REGISTRY` and the three client-version variables.

    `push-runtime-artifacts` is `push-images push-charts push-cli`.
  - Integration, `test_publish_artifacts.py`, with every subprocess stubbed at the
    script's `run` seam. Read through `make -n`, each push target's command line, run
    by the script, shows:
    - `push-images` pushes exactly the declared images, each tagged from
      `arkhai:<local>-<rev9>` as `arkhai:<name>-<rev9>` and `arkhai:<name>`, and
      `provisioning` from `compute-provisioning`;
    - `push-dev-images` does the same for the declared development images.

    Called directly rather than through a target: a failed tag stops one image's
    remaining tags and pushes (`push_image`); a declaration the reader refuses, and a
    chart with no version, are reported with nothing run (`main` over a synthetic
    tree); and an empty destination is refused (the script's `check` command, run as
    a process).
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
  - Done (2026-11-13). `build-constraints.txt` pins `hatchling==1.33.0`, the version
    every wheel in `.dist` named. The root Makefile exports it as
    `UV_BUILD_CONSTRAINT` by its absolute path, since the dist recipes `cd` into a
    project before `uv build`. Each of the 41 subproject Makefiles that runs `uv build`
    exports it the same way, beside its `UV_PYTHON` line.
    `scripts/check_build_requirements.py` is `make check-build-requirements`, run by
    `check-packaging` after `check-python-version`. It refuses:
    - a declaration line that is not `<name>==<version>`, and a name pinned twice;
    - a `[build-system]` requirement the declaration does not pin, by normalised name;
    - a Makefile running `uv build` without the export, by a path resolving to the
      declaration.
  - Unit, `test_check_build_requirements.py`: an unpinned backend, an unpinned plugin,
    normalised names, an unconstrained `uv build`, a path that does not reach the
    declaration, a Makefile running no `uv build`, three inexact pins, a name pinned
    twice, a missing declaration, and the tree passing. `make check-build-requirements`
    passes on the tree.
  - After `make dist-clean dist`, a new case in `test_release_wheelhouse.py` read every
    declared wheel's `WHEEL` and found `Generator: hatchling 1.33.0` in each.
  - That uv applies the export was shown once. With the pin moved to 1.27.0, `make
    dist-identity` rebuilt `arkhai_kit_identity` under hatchling 1.27.0: the case named
    every other wheel and not that one. The pin was restored, the wheel rebuilt, and
    the case passed.
- [x] 10.5 Remove `appVersion` from `helm/Chart.yaml` and the nine subcharts' `Chart.yaml`
  (D9).
  - Remove the `app.kubernetes.io/version` block from the umbrella's helpers
    (`helm/templates/_helpers.tpl`, and its copy `helm/_helpers.tpl`) and from the seven
    subcharts that carry one.
  - Bump each changed chart's version per RELEASING.md's versioning policy, and update
    the umbrella's ten dependency entries to match.
  - Verify: a search finds no `appVersion` or `.Chart.AppVersion` under `helm/`.
  - Done (2026-11-13). `appVersion` is gone from all ten `Chart.yaml`, and the
    `app.kubernetes.io/version` block from both copies of the umbrella's helpers and
    the seven subcharts. Each chart takes a patch bump, the label being in no selector
    and nothing consuming it: the umbrella, the storefront and the bare-metal
    storefront 0.4.0 → 0.4.1, and the seven others 0.1.0 → 0.1.1. The umbrella's ten
    entries follow them. A search under `helm/` finds no `appVersion` or
    `.Chart.AppVersion`.
- [x] 10.6 Chart tests (D9), run by `helm/scripts/test-render.sh`:
  - `helm/tests/test_subchart_pins.py` holds each umbrella dependency entry's `version`
    equal to its subchart's `Chart.yaml` version, naming a mismatch;
  - a render assertion that the chart's default values name no semver-shaped image tag,
    no revision-suffixed tag and no digest.
  - Verify: `make -C helm test-render` passes; a deliberately mismatched pin fails the
    pin test, checked once and reverted.
  - Done (2026-11-13). Both are standard-library tests that `test-render.sh` runs with
    the other `helm/tests/test_*.py`.
    - `helm/tests/test_subchart_pins.py` names any entry whose version differs from
      its subchart's `Chart.yaml`, and has a synthetic mismatch case. Moving the
      umbrella's `dev-env` entry to 0.1.0 failed it with `dependency dev-env pins
      subchart dev-env at 0.1.0; charts/dev-env/Chart.yaml is version 0.1.1`.
      Reverted, it passed.
    - `helm/tests/test_default_images.py` renders the umbrella with its default values
      and refuses an image with a digest, a semver-shaped tag or a revision-suffixed
      tag. A subchart renders only inside the umbrella, since it reads the umbrella's
      globals (rendered alone, `dev-env` fails on `.Values.global.rpc`). The lane
      doubles are off by default, so a second case reads every chart's `values.yaml`
      for the tags and digests it sets. A third case renders a revision tag, a semver
      tag and a digest through `--set`, and each is found.
  - `make -C helm test-render` passed under Helm v4.3.0, and again inside `make
    test-deployment-packaging` (10.10).
- [x] 10.7 `push-charts` packages the declared chart (`chart.path`) and pushes the package
  `make dist-helm` writes for it. The package is found from the declaration and the
  chart's `Chart.yaml`, never named in the recipe (D6, D7). It stays a developer push;
  no release step names it (D3).
  - Verify: an integration test with `helm` stubbed at the push's own wrapper shows the
    pushed file is the declared chart's `<name>-<version>.tgz`. The single-enumeration
    rule no longer refuses `push-charts`.
  - Done (2026-11-13). `push-charts` keeps `dist-helm` as its prerequisite and runs
    `publish_artifacts.py chart`, which names the package from the declared chart's
    `Chart.yaml`. The recipe's `rm` of the package is gone: it removed whatever a glob
    matched, and the push now names one file. Integration, `test_publish_artifacts.py`
    (through `make -n`, `helm` stubbed at the script's `run`): the one command is
    `helm push <repo>/.dist/arkhai-node-operator-<version>.tgz <HELM_REGISTRY>`. The
    single-enumeration rule passes the target.
- [x] 10.8 `push-cli` uploads the declared binary (`binaries[]`'s `path`, `.dist/bin/market`
  since 9.3) as package `market`, version `<rev9>`. The path is never named in the recipe
  (D6, D7). It stays a developer push; 11.2's load uploads the binary itself.
  - Verify: an integration test with `gcloud` stubbed at the upload's own wrapper shows
    the uploaded file is the declared binary's path, under the nine-character revision.
    The single-enumeration rule no longer refuses `push-cli`.
  - Done (2026-11-13). `push-cli` runs `publish_artifacts.py binaries --suffix
    $(GIT_SUFFIX)`. Each declared binary goes to `<prefix>-cli` as the generic package
    of its name. Integration, `test_publish_artifacts.py` (through `make -n`, `gcloud`
    stubbed at the script's `run`): the one upload is `.dist/bin/market` as package
    `market`, version the revision the recipe passes, which is nine characters. The
    single-enumeration rule passes the target.
- [x] 10.9 Add the single-enumeration rule (7.5) to `make check-packaging` (D7). From
  here on, it also covers the targets sections 11 and 12 add.
  - Verify: `make check-release-components` runs both rules and passes on the tree;
    `make check-packaging` passes.
  - Done (2026-11-13). `check-packaging` runs `check-release-components` (every rule:
    enumeration, credentials, market binary and revision) in place of
    `check-workflow-credentials` and `check-market-binary`, and adds
    `check-build-requirements` (10.4). Section 7's notes left open whether
    `check-workflow-credentials` stays. Both focused targets stay, each running one
    rule alone, and a Makefile comment says so; 13.9's "Checks" rows should name them.
    `make check-release-components` passes on the tree, and `make check-packaging`
    passed in the pre-commit run (10.10).
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
  - Done (2026-11-13). Results:
    - `make test-deployment-packaging` passed: `make test-release-tooling`, 2967 tests,
      none failing, then `make -C helm test-render` with both new chart tests. The
      worktree then also held section 11's untracked scripts and tests, which account
      for 17 of those tests (section 11's notes).
    - Local build evidence, an image build rather than one of TESTING.md's levels:
      `make build-dev`, which runs `make build`, succeeded. The step's rules allow
      `make build-*` and not a bare `make build`. It tagged every declared image and
      development image `-f05894761`, the nine-character revision: `registry`,
      `storefront`, `compute-provisioning`, `bare-metal-storefront`,
      `frp-grant-admission`, `dev-env` and `e2e-tests`. The binary's smoke test listed
      `api_credits.v1`, `bare_metal.v1` and `compute.v1`. That build ran with section
      11's Dockerfiles and Makefiles in the worktree too (section 11's notes).
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`: its
      functional hooks passed. They include the relock, which changed no lock, `make
      check-packaging`, now running `check-build-requirements` and
      `check-release-components`, and every suite. Like the two runs above, it ran
      with section 11's unstaged Dockerfiles and untracked scripts in the worktree,
      and with section 11's one test reading its Make target held back.
    - After the fresh-context check's fixes, the touched script and chart tests were
      rerun and passed (107 tests); the full runs above were not repeated.
    - Its closing `pre-commit` hook passed every check but the documentation
      citations. That check reports 18 citations in the change's own documents, of the
      two kinds section 7's notes describe:
      - files section 12 creates: `scripts/release_images.py` and its test;
      - files the change deleted or renamed. This section adds
        `scripts/push-distributions.py`, which the proposal and 3.2's completed text
        name.
    - `make check-comment-hygiene` passed inside that hook.
  - End-to-end: no scenario exercises the release components, and none was added. The
    pipeline's three lanes build every image through the changed targets, so a lane
    passing shows the builds and the revision tags still work. The Helm validation's
    render and upgrade of the chart without `appVersion` is validation's to record.
  - Owed by validation: confirmed as written above. `tests.yml` is a workflow
    `scripts/ci_evidence.py` lists, and its `test · test-deployment-packaging` job runs
    `make test-deployment-packaging`, whose `make -C helm test-render` runs both new
    chart tests.

### Section 10 notes (2026-11-13)

**How the image contract test reads the builds.** `make -n` runs a `$(MAKE)` line
rather than printing it. The wheelhouse build's recursive makes therefore print their
own `cd <dir> && make` lines, relative to directories the walk cannot see. The walk
follows only a `cd` naming a Makefile's directory relative to the Makefile being
read; the other lines build wheels, not images. `make -o dist` does not stop a
`$(MAKE) dist` recipe line, so the wheelhouse build cannot be skipped that way.

**Choices for review.**
- `publish_artifacts.py` derives the generic repositories (`<prefix>-cli`, and
  section 11's `<prefix>-candidates`) from the prefix. The Docker and Helm registries
  stay derived in the Makefile and passed in whole, as before.
- The chart test reads every chart's `values.yaml` as well as rendering the umbrella.
  A subchart cannot render alone, and the lane doubles render nothing by default.
- The chart bumps are patches: the removed label is in no selector, and nothing reads
  it.
- `build-constraints.txt` refuses an inexact pin, including `hatchling == 1.33.0`
  written with spaces.

**From the fresh-context check.** Fixed:
- the revision rule's docstring justified itself by the lanes' release-image suffix,
  which section 12 adds; it now gives the push targets and the bill of materials;
- the image contract test took any `docker tag` target as the revision tag; it now
  requires `docker tag arkhai:<local> arkhai:<local>-<rev9>`;
- its push case repeated `test_publish_artifacts.py`; it now holds only what the
  pushes read to what the builds write;
- `test_default_images.py`'s docstring described one kind of test of its three;
- refusal branches with no test now have one: a project that is not TOML, a build
  requirement naming no package, a chart with no version;
- the 10.2, 10.3 and 10.10 notes overstated or left out what their tests ran.

Declined: sharing `_environment()` and `_revision()` between the two test modules that
copy them. Each module states what it reads from Make and git, and a shared helper
would hide that for two short functions.

**Outside the plan.**
- `scripts/push-distributions.py` is deleted, since `push-wheels` was its only caller.
  The check's uploader pattern no longer names it.
- `test_change_build_and_helm_targets.py` took the bare-metal storefront's new tag,
  and reads the commit with `--short=9`.

**For closeout (13.9).**
- `BUILD_AND_PACKAGING.md`, "Checks": the `check-release-components` row names its
  four rules and the two focused targets; the `check-build-requirements` row names
  `build-constraints.txt` and the `UV_BUILD_CONSTRAINT` export in every Makefile that
  runs `uv build`.
- `TESTING.md`, "Chart Render Tests": nothing names the new chart tests
  (`test_subchart_pins.py`, `test_default_images.py`). They run with the umbrella's
  other tests, and the section may want a line for them.
- `RELEASING.md` describes no push target. `docs/development/VALIDATION_RUNBOOK.md`
  still runs `make push-runtime-artifacts`, which no longer pushes wheels.

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
  - Done (2026-11-13), with the inspection unrun. `scripts/wheelhouse_digest.py`
    prints the digest: `release_bom.files_digest` over the declared wheels in `.dist`.
    It refuses a missing declared wheel, naming `make dist`, rather than digest a
    partial set. Each of the five images' builds runs it first and passes
    `WHEELHOUSE_DIGEST`. Each Dockerfile declares the argument before copying `.dist/`
    in its builder stage, so the install's cache keys on it, and records it as the
    label in its final stage, before the cross-stage copies. The two `cksum`
    fingerprints, their Makefile variables and their labels are gone.
    - Unit, `test_wheelhouse_digest.py`: the digest is the dirhash of the declared
      wheels alone, ignoring an undeclared wheel and another version; a changed wheel
      changes it; a missing wheel is refused, naming it and `make dist`; the command
      prints it.
    - Unit, `test_image_publication_contract.py`, through `make -n` as 10.2's cases:
      every declared image whose Dockerfile copies `.dist/` computes the digest
      before its `docker build`, passes it, and labels its final stage with it, and
      the other two (`frp-grant-admission`, `dev-env`) carry no such label. The images
      built from the wheelhouse are exactly the five the design names.
    - Local build evidence, an image build rather than one of TESTING.md's levels:
      `make build-dev` (10.10) and `make build-candidate` (11.3) each ran every one of
      the five builds' `digest=$(python3 …/wheelhouse_digest.py) &&` before its
      `docker build`, and each build succeeded. A failing digest would have stopped
      the build, so each got a digest; the logs do not show its value.
    - Not run: `docker image inspect`, which no rule of this step allows. Validation
      or the owner can confirm the label on the built images.
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
  - Done (2026-11-13). `scripts/load_candidate.py` runs every process through one
    `run` seam:
    1. `make dist`, `make check-release-versions`, then the wheelhouse digest;
    2. `docker image rm` of each declared image's local revision tag, refusing a
       removal that fails for any reason but an absent tag, then `make
       build-candidate`, a new root target building the binary, the chart's package
       (`dist-helm`) and every release and development image from `.dist`, and no
       wheels. Then each declared image's revision tag is inspected, and the chart's
       package and each binary are looked for. With the earlier tags removed, a tag
       found was written by this load;
    3. a refusal, uploading nothing, when the wheelhouse's digest moved, an image's
       label differs from it (an empty label included), a declared image was not
       built, or the chart's package or a binary is missing;
    4. deletes of the revision's `wheelhouse` and `chart` versions in
       `<prefix>-candidates` and of each binary's in `<prefix>-cli`, a `NOT_FOUND`
       being already deleted and any other failure a refusal;
    5. uploads of the declared wheels, the chart's package and each binary, then the
       pushes of the images and development images through 10.3's functions.

    `make load-candidate` passes the destination, `$(DOCKER_REGISTRY)` and
    `$(GIT_SUFFIX)`. An image without the label counts as built from no wheelhouse,
    which 11.1's test backs: every declared image built from the wheelhouse carries
    it. `make` is run with `IMAGE_SUFFIX=` empty, since a suffixed build writes no
    revision tag.
  - Integration, `test_load_candidate.py`: `make`, `docker` and `gcloud` stubbed at the
    script's `run` (`helm` is reached only inside the stubbed `make`), over a synthetic
    tree whose declaration, projects and wheelhouse are real files. It shows:
    - the step order: `make dist` and the version check, every revision tag removed,
      `make build-candidate`, every inspection before the first delete, every delete
      before the first upload, and every upload before the first push;
    - a revision tag removed before the build, so that an image the build did not
      write is refused rather than passed as an earlier build's, and a removal
      refused for another reason stopping the load before the build;
    - the store receiving exactly the declared wheels, not an undeclared one in
      `.dist`, one chart package and one binary, under the revision;
    - every image and development image pushed under both tags;
    - no command carrying `--skip-existing`;
    - no delete, upload or push when a wheel changes during the build, when an image's
      label differs or is empty, when a declared image was not built, and when the
      chart's package and the binary are missing, each refusal named;
    - a version check failure stopping the load before any build;
    - a reload deleting versions that exist, and a delete refused for another reason
      uploading nothing;
    - an upload failing after the deletes stopping the load;
    - `make -n load-candidate` passing the destination and the nine-character
      revision.

    The stub stands in for `gcloud`: its `NOT_FOUND` answer to a delete is the
    test's own text, and it models no store. The spec delta's reload scenarios are
    therefore shown as the commands the load runs, not as a store's contents. That
    `gcloud artifacts versions delete` answers `NOT_FOUND` for a missing version is
    not shown here; the first real load shows it.
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
  - Done (2026-11-13). Results:
    - Local build evidence: `make build-candidate` succeeded at section 10's commit
      with this section's changes in the worktree. It froze `core_buyer.cli:main` as
      `.dist/bin/market`, packaged `arkhai-node-operator-0.4.1.tgz`, and tagged the
      seven declared images `-92d47be09`, the four image builds and the test image's
      each computing the digest first. 11.1's label inspection is unrun (11.1).
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`: its
      functional hooks passed, among them the relock, which changed no lock, `make
      check-packaging` with `check-release-components` passing over `load-candidate`,
      and every suite. `make test-release-tooling` passed 2979 tests there.
    - Its closing `pre-commit` hook failed only on the documentation citations: the
      same 18 that section 10's run reports (10.10).
    - After the fresh-context check's fixes, `make test-release-tooling` passed 2981
      tests, among them `test_load_candidate.py` (16) and
      `test_image_publication_contract.py` (17). `make check-comment-hygiene` and
      `make check-release-components` passed. The pre-commit run and the build were
      not repeated, and the fresh-context check was not run again: the fixes answer
      its findings and touch only the load script, its tests, the contract test, the
      seller quickstart and these notes.
    - No real load was made: the candidate store is provisioned outside this
      repository, and this step's rules allow no registry write.
  - End-to-end: confirmed that no scenario runs the load, and none was added. The
    pipeline's three lanes build the registry, storefront, provisioning, bare-metal
    storefront and test images through the changed Makefiles and Dockerfiles, so a lane
    passing shows the digest's build argument breaks no build.
  - Owed by validation: none beyond section 7's. The new tests run in `tests.yml`'s
    `test · test-deployment-packaging` job, which section 7 already owes.

### Section 11 notes (2026-11-13)

**How the two sections were committed.** Sections 10 and 11 were implemented in one
working tree before section 10 was committed. Section 11's hunks were taken out of the
files both sections change, section 10 was checked and committed, and the hunks were
restored. Section 10's checks therefore ran with section 11's Dockerfiles and new files
in the worktree (10.10). The guarded push refuses a worktree that is not clean, so
section 10's commit was pushed with this one.

**Choices for review.**
- **An image without the label counts as built from no wheelhouse.** The load cannot
  tell which images install from `.dist`: only the Makefiles know which Dockerfile
  builds each image. 11.1's test holds every declared image whose Dockerfile copies
  `.dist/` to the label, deriving that from the Makefiles through `make -n`. The
  fresh-context check proposed that the load read the Dockerfiles itself. That needs an
  image-to-Dockerfile map in the load, a second copy of what the Makefiles say, so it
  was declined.
- **`build-candidate` names its build targets**, as `build`, `build-dev` and the lane
  targets do. The declaration says what a release comprises, and the Makefile how to
  build it (D6), so a newly declared image needs its build target added here. The load
  refuses until it is: the earlier revision tag is removed, so a declared image the
  target does not build is missing.
- **The load runs `make`**, so its own `check-release-versions` and builds are the same
  targets an operator runs, and the tests stub them at one seam.
- **The wheelhouse digest refuses a partial wheelhouse.** Every image built from
  `.dist` runs it, so `build-seller` now builds the release's whole wheel set
  (`dist-release-set`) rather than a hand-picked subset, which lacked
  `arkhai-core-registry` and `arkhai-compute-provisioning-client`.

**From the fresh-context check.** Fixed:
- an earlier build's revision tag at the same revision passed as this load's; the load
  now removes each declared image's revision tag before building;
- the test of the images built from the wheelhouse was named for the design; it now
  states its invariant;
- the Dockerfile test now holds the order the cache key depends on: the builder
  stage's argument before `COPY .dist/`, and the final stage's label before its
  cross-stage copies;
- `docs/seller-quickstart.md` described `build-seller`'s old wheel set;
- the D3 promotion row now names `BUILD_AND_PACKAGING.md`, "Images";
- the 11.1–11.3 notes overstated their evidence, and 11.3 recorded none.

Declined:
- the load reading Dockerfiles to refuse an unlabelled image (above);
- re-digesting the wheels after uploading them: they are read from `.dist` seconds after
  the check, and a guard for a wheel rebuilt in that window is speculative;
- calling the `make -n` tests integration: section 10 classes the same tests as unit.

**Outside the plan.**
- `build-seller` builds `dist-release-set` (above), and `docs/seller-quickstart.md`
  says so.

**For closeout (13.9).**
- `BUILD_AND_PACKAGING.md`, "Images": every image built from `.dist` takes
  `WHEELHOUSE_DIGEST` from `scripts/wheelhouse_digest.py` before its `docker build`,
  declares it before copying `.dist/`, and records `org.arkhai.wheelhouse-digest` in
  its final stage before the cross-stage copies. The section's Dockerfile example
  lacks the argument. 13.9 does not name this; the D3 row now does.
- `RELEASING.md`: `make load-candidate` removes the declared images' local revision
  tags before it builds, and refuses when one cannot be removed, for example while a
  container runs it.

**From the triage of the round at `033dd0250`** (2026-11-14; implementation review 52
F1). `build-candidate` keeps naming its build targets (D6), and nothing held it to the
declaration: a declared image it did not build was found only by an operator's load,
after building everything else. `test_image_publication_contract.py` now follows `make
build-candidate` through `make -n` as it follows `build-dev`. Every declared image and
development image's revision tag must be written there, and every command of each
declared binary's own `target` and of `dist-helm` must run there. The delta's "A
component is added" scenario now says the declaration is edited beside the component's
own build, and that the packaging tests fail until the candidate build builds it. D6 says
so too. The checks are recorded in section 12's last note.

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
  - Done (2026-11-13). The registry, storefront and provisioning lines of the three
    domain stacks, and `compose.apicredits-lane.yml`'s compute registry, read
    `arkhai:<local>${IMAGE_SUFFIX:-}`. The bare-metal storefront's default is
    `${BARE_METAL_STOREFRONT_IMAGE:-arkhai:bare-metal-storefront${IMAGE_SUFFIX:-}}`, and
    Compose resolves the nested default. Each domain stack's header says why, and
    `compose.apicredits-lane.yml` says it beside its line. The API-credit images,
    dev-env, the test image and the lane doubles keep their names.
    - Integration with a real external process, `test_release_images.py`: each lane's
      Compose files, taken from the `--compose` argument its target passes to the check,
      are rendered with `docker compose config --images`, unset and with
      `IMAGE_SUFFIX=-0123456ab`. Unset, the lane runs at least one release image, by its
      bare tag. Set, exactly the images that were release images' bare tags gain the
      suffix, none stays bare, and every other image is unchanged. No render from before
      the change is compared: "as before" rests on the bare tags being the ones the
      lines held. The renders skip without Docker Compose, except under
      `COMPOSE_REQUIRED=1`, which `tests.yml`'s packaging job now sets beside
      `HELM_REQUIRED`, so a skip fails there. They ran here.
    - `test_committed_stack_values.py`, which renders the four stacks and selects the
      registries by `arkhai:registry`, passes. Its render now drops `IMAGE_SUFFIX` from
      the environment, as it drops `PROVISIONING_MODE`, and fails rather than skips
      under `COMPOSE_REQUIRED=1`.
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
  - Done (2026-11-13). `scripts/release_images.py` runs `docker` through one `run` seam
    and reads the declared release images through `release_components`:
    - `pull --registry= --suffix=` pulls `<registry>/arkhai:<name><suffix>` and tags it
      `arkhai:<local><suffix>`, for each declared release image.
    - `check --suffix= --compose=` renders the lane's Compose files with `docker compose
      config --images`, from the repository root with `IMAGE_SUFFIX` set to the suffix.
      It names every declared release image they run that `docker image inspect` does
      not find, and reports any other inspection failure as itself, such as an
      unreachable daemon. It also refuses one they run bare (`arkhai:<local>` with the suffix
      set), which would run whatever holds the bare tag; that goes beyond the task's
      wording ("Section 12 notes").
    - `record --lane= --suffix= --compose=` reads the lane's running containers (`docker
      compose ps --quiet`, `docker container inspect`), keeps those running
      `arkhai:<local><suffix>`, and reads each image's repo digests (`docker image
      inspect`). It counts only a repo digest from a registry: one in the local `arkhai`
      repository names none (12.3's finding). It refuses an image with no such digest
      or with two different ones, a release image the lane's Compose files run that no
      running container runs, and a lane running no release image of the candidate. It
      writes the record and prints it.
    - Each refuses an empty suffix, and `pull` an empty registry, before running
      anything.

    `make -C e2e-tests pull-release-images` runs `pull` with `DOCKER_REGISTRY` and
    `IMAGE_SUFFIX`. A suffix begins with `-`, so every call passes `--suffix=<value>`:
    argparse reads `--suffix -0123456ab` as a missing value.
    - Integration, `scripts/tests/test_release_images.py`, `docker` stubbed at the
      script's `run`, over a synthetic declaration of three release images, as 11.2's
      load tests are:
      - `pull`'s commands, in order, `provisioning` tagged `compute-provisioning`, and
        a failed pull stopping and named;
      - an empty suffix refused by each command, and an empty registry by `pull`, with
        nothing run;
      - `check`: every release image present passes, rendered from the root with the
        suffix; an image the lane does not run, and a non-release image, are not looked
        for; each missing image named; another inspection failure named as itself; a
        bare release image refused;
      - `record`: the shape, written and printed; two containers of one image read
        once; one manifest under two registries is one digest; the local repository's
        digest beside a registry's ignored; no registry name in the record; no repo
        digest, only the local repository's, and two different ones each refused, with
        nothing written; a release image the Compose files run with no running
        container refused; a lane running no candidate image refused.
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
  - Done (2026-11-13), with the registry round trip unrun.
    - **The lanes.** Each lane target checks `RELEASE_IMAGES` is `1` or unset. With it
      set, the lane runs the check first, before it tears down or builds anything, then
      `build-e2e-<lane>`, `up --wait`, then the record, before the payments check and
      the scenarios. Without it, both expand to nothing. `e2e-tests/Makefile` exports
      `IMAGE_SUFFIX`, which the Compose files read.
    - **The builds.** With `RELEASE_IMAGES` set, the root `build-e2e-*` targets drop
      their release-image builds (`e2e_release_builds`) and pass `IMAGE_SUFFIX=` empty
      to every image build they run (`E2E_IMAGE_SUFFIX`). The suffix names the
      candidate's images, and the Compose files run what the lane builds by its bare
      tag. Like any unsuffixed build, dev-env's and the test image's also write their
      revision tags. The build targets are still named in the lane targets, as `build`,
      `build-dev` and `build-candidate` name theirs.
    - Unit, through `make -n` as 10.2's cases, in `test_release_images.py`, for each
      lane:
      - with `RELEASE_IMAGES=1 IMAGE_SUFFIX=-0123456ab`, no `docker build` or `docker
        tag` writes a release image's tag, bare, suffixed or revision-tagged; the test
        image and dev-env are built bare, and no tag carries the suffix; the order is
        check, down, the first build, up, record, the scenarios; the check and the
        record pass the suffix and exactly the Compose files the lane brings up;
      - without the switch, the lane builds release images and runs neither command;
      - `RELEASE_IMAGES=yes` refused.

      Also `pull-release-images`' command line.
    - Integration with real Compose, in the same file, for each lane: in release-image
      mode, every `arkhai:` image the lane's Compose files run that is not a declared
      release image's suffixed tag is one the lane writes. A build target left in
      `e2e_release_builds` after its image left the declaration would fail it, whether
      or not its Compose line keeps the suffix.
    - The `make -n` walk reads the root build as the lane's `$(MAKE)` line runs it in
      place, with the suffix MAKEFLAGS passes, tracking directories through `-w`, and
      follows each `cd <dir> && make` line from the directory make was in. It reads
      every `-t` of a `docker build`, and every `docker tag`.
    - **The local run.** A missing image:
      `make -C e2e-tests test-e2e-bare-metal RELEASE_IMAGES=1 IMAGE_SUFFIX=-000000000`
      failed at its first command, naming `arkhai:registry-000000000`,
      `arkhai:compute-provisioning-000000000` and
      `arkhai:bare-metal-storefront-000000000`, before `down` ran. An empty suffix:
      `make -C e2e-tests test-e2e-vm RELEASE_IMAGES=1` failed at the check, naming
      `IMAGE_SUFFIX`.
    - **The lane on candidate-shaped images, first run.** `make -C e2e-tests
      test-e2e-bare-metal RELEASE_IMAGES=1 IMAGE_SUFFIX=-92d47be09` passed, 98
      scenarios, against the `-92d47be09` images that section 11's `make
      build-candidate` wrote and no step pushed. Its check passed. Its build ran four
      `docker build`s: dev-env, the test image and the two lane doubles, each to its
      bare tag (dev-env and the test image also took their revision tags). Its record,
      printed and written to `.snapshot/e2e-release-images-bare-metal.json`, named
      `registry`, `provisioning` and `bare-metal-storefront`, each with one `sha256:`
      digest. That record should not have been written: see the finding below.
    - **A finding, fixed: on this Docker, a locally built image has a repo digest.**
      This Docker keeps images in containerd: its builds export an image index
      ("exporting manifest list" in the build log), and each built image carries a repo
      digest in the local `arkhai` repository, though no registry served it. D17's "no
      repo digest" refusal assumed the classic image store, where only a push or a pull
      sets one. The first run showed it; the first fresh-context check proposed the
      fix. `record` now counts only a repo digest from a registry, any repository but
      the local `arkhai`, and the record still carries no registry name. That a pull
      records `<registry>/arkhai@<digest>`, on either store, is expected and was not
      observed: no pull ran.
    - **Second run, after the fix.** With `release_images.py` as committed but for the
      wording of an inspection failure (a later fix), the same command built the same
      four images, then the record refused all three images, each "has no repo digest
      from a registry, so it was not pulled", and the lane failed before its
      scenarios. That shows each built image's only repo digests are in the local
      repository. No run shows the final code recording images it accepts. Both runs'
      stacks were taken down with `make -C e2e-tests e2e-bare-metal-down`.
    - **The registry round trip**, unrun by the implementing step, whose rules allow
      neither `docker push` nor `docker pull`, was run at the owner's request for the
      round's triage (implementation review 52 F3). It ran at `033dd0250` in a fresh
      worktree, on Docker 29.8.0 with the containerd image store and Compose 5.5.1,
      against a disposable `registry:2` on `localhost:5055`:
      1. `make dist`, then the five release images' build targets with `IMAGE_SUFFIX=`
         empty, wrote `arkhai:<local>-033dd0250` for each.
      2. `publish_artifacts.py images --registry localhost:5055 --suffix 033dd0250`,
         the code `make push-images` runs, pushed each. Each `docker push` digest
         equalled the registry's `Docker-Content-Digest` for the tag.
      3. A push alone gives the local image the registry's repo digest on this store,
         so every tag of the five images was removed and each image confirmed absent
         first. `make -C e2e-tests pull-release-images DOCKER_REGISTRY=localhost:5055
         IMAGE_SUFFIX=-033dd0250` then downloaded each and tagged it
         `arkhai:<local>-033dd0250`, its image ID the pushed manifest digest and its
         repo digests `arkhai@<digest>` and `localhost:5055/arkhai@<digest>`: the
         registry's survives the retag.
      4. `make -C e2e-tests test-e2e-bare-metal RELEASE_IMAGES=1
         IMAGE_SUFFIX=-033dd0250` passed its check, built only dev-env, the test image
         and the two lane doubles (the five release images' IDs unchanged), and passed
         98 scenarios. Its record named `registry`, `provisioning` and
         `bare-metal-storefront`, each with the pushed manifest digest:
         `sha256:d3fc37bf…eae7`, `sha256:3b85cff0…1e98` and `sha256:51257c27…d828`.

      With `arkhai:registry-033dd0250` removed, the same lane failed at its first
      command, naming it, before building or starting anything. Not covered: the VM
      and API-credit lanes in this mode, and a hosted registry. The run also showed a
      push gives an image a registry's repo digest on this store, so `record`'s
      refusal shows the recorded value is a registry's manifest digest, not that the
      image was pulled (§12 Q1, in the round triage's note below).
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
  - Done (2026-11-13). Results:
    - Unit and integration: `make test-release-tooling` passed, 3005 tests, among them
      `test_release_images.py`'s 24, whose three Compose renders ran rather than
      skipped. After both fresh-context checks' fixes, `test_release_images.py` passed
      32 tests, its six Compose cases running, and `make test-release-tooling` passed
      3013 tests inside the last pre-commit run below.
    - `make check-release-components` passed, with the enumeration rule reading the
      changed lane targets and `pull-release-images`.
    - Local lane run: 12.3's, its registry round trip run for the round's triage.
    - `scripts/change-workflow run pre-commit publish-wheels-through-a-gate` ran three
      times: before the fresh-context checks and after each one's fixes. Each time its
      functional hooks passed.
      They include the relock, which changed no lock, `make check-packaging` with
      `check-release-components` (whose credential rule read the changed `tests.yml`),
      and every suite. Each time its closing `pre-commit` hook passed every check but
      the documentation citations. That check now reports 16 citations, all of the
      second kind section 7's notes describe: files the change deleted or renamed.
      Section 12's own two files resolve the last of the first kind.
  - End-to-end: confirmed. No marker in `e2e-tests/` was added. The pipeline's three
    lanes run in build mode, where the Compose files resolve to the bare tags, as the
    renders above show, so they must pass unchanged. The release-image mode is
    exercised only by 12.3's local run and the deployment's release validation.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging`. With
    `COMPOSE_REQUIRED=1`, which this section adds to that job, the Compose render cases
    of `test_release_images.py` and `test_committed_stack_values.py` run rather than
    skip and pass. The job passing shows it, since a skip fails there.

### Section 12 notes (2026-11-13)

**Choices for review.**
- **`check` refuses a release image run bare.** With the suffix set, a Compose line that
  still reads `arkhai:<local>` would run whatever image holds the bare tag. The lane's
  check would not have looked for it, and its record would have left it out. D17 asks
  only that missing images be named. One rendering with the suffix set finds both.
- **`record` counts only a repo digest from a registry** (12.3's finding). D17 says
  "from their repo digests" and expects an image not pulled to have none, which holds
  only on the classic image store. Excluding the local `arkhai` repository restores
  that on the containerd store too, with no registry name in the record. A candidate
  pulled from a registry named in Docker's familiar form, such as Docker Hub's
  `<org>/arkhai`, still counts, since only the bare local repository is excluded.
- **`record` refuses a release image the lane's Compose files run that no running
  container runs**, and a lane running no release image of the candidate. D17 says
  each lane records the release images it runs; either gap would leave the record
  short without failing.
- **The check runs before `down` and the build.** The release images are pulled, not
  built, so they can be checked first, and a missing one fails the lane in seconds.
- **The root `build-e2e-*` targets clear the suffix themselves** in release-image mode,
  rather than relying on the lane target to pass `IMAGE_SUFFIX=`. `make
  build-e2e-bare-metal RELEASE_IMAGES=1 IMAGE_SUFFIX=-…` run directly therefore builds
  what the lane runs.
- **Which builds a lane drops is named in the root Makefile** (`e2e_release_builds`),
  not derived from the declaration, since only the Makefile knows which target builds
  which image (section 11's notes). A newly declared image left in a lane's build
  list fails the `make -n` test; a dropped build whose image has left the declaration
  fails the Compose test.
- **`BARE_METAL_STOREFRONT_IMAGE`**, set in the environment, replaces the bare-metal
  storefront's image. Set to the bare `arkhai:bare-metal-storefront`, the check
  refuses it as run bare; set to the candidate's tag, it is checked and recorded; set
  to any other image, neither command sees a release image there. That last is an
  operator's explicit choice of image, so neither refuses it.
- **A lane run with `IMAGE_SUFFIX` and no `RELEASE_IMAGES`** builds every image
  suffixed, and its Compose files now run the release images suffixed and the rest
  bare. Before this section they ran everything bare, so the combination was
  inconsistent before and after; no lane or workflow uses it, and nothing refuses it.

**From the fresh-context check.** Fixed:
- the Compose renders skipped with no gate; `tests.yml`'s packaging job now sets
  `COMPOSE_REQUIRED=1`, and both render tests fail rather than skip under it;
- the stubbed-`run` tests were labelled unit; they drive `main` against the process
  boundary, as 11.2's integration tests do, and are now labelled integration;
- the root Makefile's `IMAGE_SUFFIX` comment said Compose and the lanes always use the
  bare tags;
- the `build-e2e-*` comment, and 12.3's notes, said what the lane builds is tagged
  bare; dev-env and the test image also take their revision tags, and the `make -n`
  test now reads `docker tag` lines too;
- the record counted a local repository's digest (above), and left out a release
  image with no running container (above);
- no test caught a dropped build whose image left the declaration (above);
- the `RELEASE_IMAGES` refusal was tested on one lane; it is tested on each;
- a vacuous assertion in the Compose test;
- the API-credit compose comment, and an unmarked placeholder registry in the tests;
- notes overstating their evidence: "the five release images", "all bare", "nothing
  carries a suffix", and what the Compose test compares.

Declined:
- **Make variables for the build lists derived from the declaration.** An
  image-to-target map would be a second copy of what the Makefiles say; the two tests
  above hold the lists instead.
- **Refusing a suffix not beginning with `-`.** Such a suffix names tags no build or
  pull writes, so the check already fails, naming each missing image.
- **The `make -n` tests labelled integration.** Sections 10 and 11 class the same
  tests as unit, and this section follows them; TESTING.md does not name them.
- **Recording the containerd finding in `design.md`.** This step does not amend the
  design; the question is raised below for the round.

**From the second fresh-context check.** Fixed:
- the `build-e2e-*` comment said every unsuffixed build writes a revision tag; only
  the dev chain's and the test image's do;
- the root Makefile's `IMAGE_SUFFIX` comment now says the lanes' Compose files name
  release images with `IMAGE_SUFFIX` whenever it is in their environment;
- the `make -n` walk's docstring said `$(MAKE)` lines are printed, not run; the walk
  now reads them as run in place, tracks directories through `-w`, and no longer walks
  the root build a second time without the inherited suffix;
- the walk read only the first `-t` of a `docker build`;
- the Compose test of a lane's own images missed an image that left the declaration
  with its Compose line still suffixed;
- `check` reported any failed inspection as a missing image;
- a test docstring called the two-registry shape the bare-metal lane's;
- notes overstating their evidence: a pull's repo digest (unobserved), which run used
  which code, the storefront override, and 12.1's headers.

Declined:
- **A refusal of `IMAGE_SUFFIX` without `RELEASE_IMAGES`** (above).
- **Relabelling the `make -n` tests**, as after the first check.

**Questions for the round.**
- **D17 and the delta's wording on repo digests.** The delta's requirement says
  "failing an image without exactly one repo digest", and D17 "no repo digest, or two
  different ones". Read literally on the containerd store, they accept a locally built
  image, which has one, and could refuse a pulled image whose local tag adds a second
  reference in the local repository. `record` reads "repo digest" as one a registry
  served. Triage can amend D17 and the delta to say so, or rule otherwise.
- **The behaviours beyond D17's text**: `check` refusing a release image run bare, and
  `record` refusing a release image with no running container. If accepted, D17 and the
  delta's requirement could name them.
- **A permanent scenario this section makes stale.** `openspec/specs/deployment-state/
  spec.md`, "A stack's configuration lives in committed files", scenario "A lane stack
  is brought up", says a lane target "names only the lane's Compose files and the run's
  provisioning mode". A lane target now also takes the release-image mode and its
  suffix. The delta does not modify that requirement, so the archive would leave it
  stale; a MODIFIED requirement in the delta would correct it. `docs/development/
  TESTING.md`'s matching sentence ("A lane target names only its Compose files, its
  project, and the run's provisioning mode") is for 13.9.
- **Test levels.** TESTING.md names no level for a dry run of committed Makefiles
  through a real `make`. Sections 10–12 call those tests unit; the Compose renders,
  which need a binary a runner may lack, are gated as the third flavour of
  integration test. TESTING.md could say which.

**Outside the plan.**
- `test_committed_stack_values.py`'s render drops `IMAGE_SUFFIX` from the environment,
  since its registry selection compares the bare tag, and fails under
  `COMPOSE_REQUIRED=1` rather than skipping.
- `tests.yml`'s packaging job sets `COMPOSE_REQUIRED`, as section 8 added
  `HELM_REQUIRED`.

**For closeout (13.9).**
- `docs/development/DEPLOYMENT_AND_CONFIG.md` says "Compose, the pipeline lanes, and
  your own deployments keep bare tags". A lane run with `RELEASE_IMAGES=1` does not.
  13.9 does not name this document.
- `docs/development/TESTING.md`: "A lane target names only its Compose files, its
  project, and the run's provisioning mode" (above). `COMPOSE_REQUIRED` is now
  described beside `HELM_REQUIRED` in "Static Configuration Tests" (the round triage's
  note below).
- The record shows each release image's manifest digest under a registry's name, which
  proves neither a pull nor that the registry holds it; the deployment's comparison with
  the pushed manifests is what shows they are the candidate's. RELEASING.md should say
  so.
- `docs/development/TESTING.md`, "Locally verifiable and external-topology scenarios":
  the release-image mode, the order (check, build, up, record), and the record's shape.
- `RELEASING.md`: `make -C e2e-tests pull-release-images DOCKER_REGISTRY=…
  IMAGE_SUFFIX=-<rev9>`, then each lane with `RELEASE_IMAGES=1` and the same suffix. A
  suffix is passed as `--suffix=<value>` inside the targets; an operator passes Make
  variables and never meets that.

### Round triage fixes (2026-11-14)

The triage of the round at `033dd0250` (implementation review 52, validation 53, the
owner's notes 54) accepted the following fixes, made against `033dd0250`. Those of
sections 8 and 11 are described in their notes.
- **52 F3: the registry round trip** ran at the owner's request, and 12.3 records it.
- **§12 Q1: what `record`'s digest rule proves.** The round trip showed that on the
  containerd store, tagging an image for a registry, as a push does, gives it that
  registry's repo digest. `record`'s refusal therefore no longer says an image "was not
  pulled": it has "no repo digest from a registry: its manifest digest is unknown".
  The module docstring says a registry's repo digest is the image's own manifest digest
  under a registry's name, proving neither a pull nor that the registry holds it, and
  that the deployment's comparison with the pushed manifests ties the record to the
  candidate. D17 and the delta say "from a registry", the local `arkhai` repository not
  counted.
- **§12 Q2: the refusals beyond D17's text** are now in D17 and the delta, with three
  scenarios: a release image named without the suffix; one with no running container;
  one with only a local repo digest.
- **§12 Q3: the stale permanent scenario.** The delta modifies "A stack's configuration
  lives in committed files". A Makefile may also choose a release candidate's image
  suffix, and "A lane stack is brought up" names it. TESTING.md's matching sentence
  stays with 13.9.
- **§12 Q4: test levels.** TESTING.md gains "Static Configuration Tests": a chart render,
  a Compose render or a `make -n` dry run, asserting on what committed configuration
  would do without doing it. These sit beside the four levels, run where unit tests run,
  and are gated by `HELM_REQUIRED` or `COMPOSE_REQUIRED` where the tool may be missing.
  "Chart Render Tests" points to it. Sections 10–12's `make -n` tests are of this
  kind; their test code carries no level label to change.
- **54 O1** (`UV_BUILD_CONSTRAINT` exported with no visible use): no change, by the
  owner's word.

**Checks of the fixes.**
- `make test-release-tooling` passed 3027 tests with none skipped. Among them are the new
  real-Helm cases in `test_release_bom.py`, run with the pinned Helm v4.3.0.
  - `test_the_deployment_chart_packaged_twice_gives_one_content_digest`, which packages
    this checkout's `helm/`, passed. That checkout holds an ignored `Chart.lock`, nine
    `charts/*.tgz` and `tests/__pycache__/`, so the `.helmignore` kept them out and the
    guard, run through real `git`, passed.
  - The first run failed one case: the tracked-files copy lacked the new `.helmignore`
    until it was staged.
- `make -C helm test-render` passed with the `.helmignore` in place.
- The fresh-context check of the diff against `033dd0250` raised two fixes and seven
  points to consider. Fixed:
  - the digest wording claimed a registry's manifest digest where a tag alone gives
    one;
  - this note was cited before it existed;
  - "tracked files alone" overstated the guard, which refuses ignored files; an
    untracked file Git does not ignore is an edit D5 tolerates, and D14 says so;
  - "every remote" is every remote-tracking branch as of the last fetch;
  - TESTING.md now places the category beside the four levels;
  - two line-wrapping slips.

  Declined:
  - the binary and `dist-helm` case comparing commands is brittle if those targets ever
    enter a subproject Makefile, but it is not vacuous, and it would fail loudly;
  - `helm/Makefile`'s `init` comment is accurate.
- `scripts/change-workflow run pre-commit publish-wheels-through-a-gate`, after those
  fixes:
  - `after-functional-change` passed, exit 0;
  - `pre-commit-functional` passed, exit 0, with `make check-packaging` and every suite;
  - `pre-commit` failed, exit 2, only on the documentation citations: the same 16
    citations of files the change deleted or renamed that 12.4 records. The index, tasks,
    skills and `openspec validate --strict` checks passed.

### Pre-closeout triage edits (2026-11-14)

The triage of pre-closeout review 70 at `a9560056a` (with validation 69, which passed)
made documentation edits only:
- **70 F1:** the version check compares only the release tags the checkout holds. The
  delta's requirement now says so and requires its result to name every tag it compared,
  which `test_check_release_versions.py` already asserts. D14 states the precondition and
  why the check stays offline. 13.9's RELEASING.md bullet gains the preflight.
- **70 F2:** D3 no longer says the check compares only with the previous release.

`scripts/change-workflow run pre-commit publish-wheels-through-a-gate` after the edits:
the index, tasks and skills checks and `openspec validate --strict` passed; `pre-commit`
failed, exit 2, only on the same 16 citations of deleted files that 12.4 records.

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
  - `scripts/market_binary.py`;
  - `scripts/check_uv_setup.py`;
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
  - Record the question 1.1e kept in section 1 (`arkhai-vms-provisioning-iac` is not
    built by `make dist`) as unowned work in the campaign's section.
  - Run `make check-change-index`.
- [ ] 13.7 **Packaging.** Run `make check-packaging`, now including
  `check-release-components`, `check-market-binary` and `check-build-requirements`, and
  resolve every failure.
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
| D3 Every component of a release candidate is stored under its revision by one load | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization"; `docs/development/RELEASING.md`; `docs/development/BUILD_AND_PACKAGING.md`, "Images" (the `WHEELHOUSE_DIGEST` argument and `org.arkhai.wheelhouse-digest` label of every image built from `.dist`) | Pending |
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
| D18 The release's `market` binary is PyPI's CLI | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization"; `docs/development/BUILD_AND_PACKAGING.md`, "Images" and "Checks"; `docs/buyer-quickstart.md`, "1. Install" | Pending |
| D19 The npm package is not a release component until it can be loaded | `openspec/specs/deployment-state/spec.md` (the declaration requirement); `docs/development/RELEASING.md` | Pending |
| D20 The orphaned release-verification requirement is removed | `openspec/specs/deployment-state/spec.md` (removed by the archive) | Pending (13.11) |
| D21 RELEASING.md keeps the anchors other documents cite | `docs/development/RELEASING.md` | Pending |
| D22 The change keeps its name | No permanent destination — the change's own directory name | — |
| Roadmap currency | `docs/development/ROADMAP.md`: expected no change | Pending (13.5) |
| Campaign index currency | `openspec/changes/README.md`: this row, the campaign, `configure-pypi-trusted-publishing`'s row, 1.1e's unowned item | Pending (13.6) |
