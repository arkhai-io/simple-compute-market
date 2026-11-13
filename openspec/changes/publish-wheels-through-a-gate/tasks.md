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

- [ ] 9.1 Rename `scripts/buyer_domain_wheels.py` to `scripts/market_binary.py`, and add
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
- [ ] 9.2 Build the binary from a locked virtual project, and make `check-uv-setup`
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
- [ ] 9.3 Point the declaration's `market` entry at `build-market-binary` and
  `.dist/bin/market`. `build` builds it in place of `build-buyer`.
  - Retire `build-buyer`, the PyInstaller recipe in `domains/vms/buyer/Makefile`, and
    `domains/vms/buyer/src/arkhai_vms_buyer/main.py`, whose only user is that recipe.
  - Update any target, test or comment that names them; the search includes
    `scripts/tests/test_init_targets.py` and the e2e-tests comments.
  - Verify: a search outside `openspec/` and `docs/` finds no `build-buyer` and no
    `arkhai_vms_buyer/main.py`. `make test-release-tooling` passes. `docs/` is rewritten
    at closeout (13.9).
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
- [ ] 9.4 Remove `pyinstaller` from `arkhai-vms-buyer`'s runtime dependencies, and bump
  it a minor version (0.11.0 → 0.12.0) per RELEASING.md's versioning policy. Move any
  exact pin on it with the bump, and refresh every lock that installs it with
  `make lock`.
  - Verify:
    - `make check-version-bumps` passes;
    - `make check-packaging` passes, with locks current;
    - `make test-domains` passes for the VM buyer;
    - the built wheel's metadata requires no PyInstaller.
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
- [ ] 9.5 Section verification.
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
- [ ] 10.7 `push-charts` packages the declared chart (`chart.path`) and pushes the package
  `make dist-helm` writes for it. The package is found from the declaration and the
  chart's `Chart.yaml`, never named in the recipe (D6, D7). It stays a developer push;
  no release step names it (D3).
  - Verify: an integration test with `helm` stubbed at the push's own wrapper shows the
    pushed file is the declared chart's `<name>-<version>.tgz`. The single-enumeration
    rule no longer refuses `push-charts`.
- [ ] 10.8 `push-cli` uploads the declared binary (`binaries[]`'s `path`, `.dist/bin/market`
  since 9.3) as package `market`, version `<rev9>`. The path is never named in the recipe
  (D6, D7). It stays a developer push; 11.2's load uploads the binary itself.
  - Verify: an integration test with `gcloud` stubbed at the upload's own wrapper shows
    the uploaded file is the declared binary's path, under the nine-character revision.
    The single-enumeration rule no longer refuses `push-cli`.
- [ ] 10.9 Add the single-enumeration rule (7.5) to `make check-packaging` (D7). From
  here on, it also covers the targets sections 11 and 12 add.
  - Verify: `make check-release-components` runs both rules and passes on the tree;
    `make check-packaging` passes.
- [ ] 10.10 Section verification.
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
    - `make check-release-versions` and its offline scope (D14);
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
| D18 The release's `market` binary is PyPI's CLI | `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization"; `docs/development/BUILD_AND_PACKAGING.md`, "Images" and "Checks"; `docs/buyer-quickstart.md`, "1. Install" | Pending |
| D19 The npm package is not a release component until it can be loaded | `openspec/specs/deployment-state/spec.md` (the declaration requirement); `docs/development/RELEASING.md` | Pending |
| D20 The orphaned release-verification requirement is removed | `openspec/specs/deployment-state/spec.md` (removed by the archive) | Pending (13.11) |
| D21 RELEASING.md keeps the anchors other documents cite | `docs/development/RELEASING.md` | Pending |
| D22 The change keeps its name | No permanent destination — the change's own directory name | — |
| Roadmap currency | `docs/development/ROADMAP.md`: expected no change | Pending (13.5) |
| Campaign index currency | `openspec/changes/README.md`: this row, the campaign, `configure-pypi-trusted-publishing`'s row, 1.1e's unowned item | Pending (13.6) |
