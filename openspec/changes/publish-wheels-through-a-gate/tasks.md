## Readiness

Redesigned 2026-11-12. The interim gate (a merge publishing to the development registry
and a promotion script here) is replaced by the release described in `design.md`: CI
publishes nothing, a candidate is a `main` commit loaded by the publish targets, the
deployment validates, promotes and publishes, and the release is recorded last on its
release branch. Sections 1–2 are kept as implemented. Sections 3–6 belonged to the
interim design and are withdrawn, their completed tasks preserved.

**Sections 7–12 and the design promotion record predate the settled design** (D1–D22 as
amended by the triages of design reviews 11 and 26) **and are rewritten at planning.**
Do not implement from them. Planning addresses each discrepancy design review 11 F3 found:
- 8.1 adds a `public` field, which D6 removed; 12.1 and the promotion record describe
  it.
- Section 9 covers only the umbrella chart; D9 changes all nine subcharts and the
  umbrella's dependency pins.
- 10.1 compares the chart's git tree id; D14 uses the packaged-content digest, over every
  earlier record, with the bill of materials as the subject at the cut.
- No task covers the candidate store, `development_images` and `push-dev-images` in the
  load, `--short=9` in every Makefile and its check, the build-requirement pin and its
  check, the release-record reader and check, `pull-release-images`, the lanes' mode and
  record, the subchart-pin test, the workflow-credential check, or the binary build
  image.
- 8.2 and 8.6 declare and load npm; under D19 npm is not a release component until a
  development registry serves npm.
- The citations of `design.md` decisions in 4.1 (D1, D8), 6.1 (D5) and 8.3 (D4) name
  decisions renumbered by the redesign.
- Design review 26's triage adds work no task names: `make load-candidate` with the
  wheelhouse digest as every `.dist`-built image's build argument and label, replacing
  the two `cksum` fingerprints (D3, 26 F2); delete-then-upload of the `market` version
  with the `wheelhouse` and `chart` versions, and no upload mode keeping an earlier file
  (D3, 26 F5); `validate-model-release.yml` at `contents: read` without its note step,
  and the credential rule with no exception (D7, 26 F3); the declaration's absence rule
  and the record check's exact, unique component set (D6, D12, 26 F4); D14's offline
  scope, and the deployment's PyPI read in RELEASING.md's list of the deployment's steps
  (D13, D14, 26 F1).
- The sentence below was written for the interim design. A commit on this branch stops
  `publish-pypi.yml` only when the change lands on `main`, whichever section deletes it
  (design, D13).

Section 7 should land first: until it does, a merge still publishes to PyPI and npm.

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
- [x] 1.4 Update `scripts/tests/test_publish_matrix.py`. It currently parses the
  heredoc by regex and asserts the workflow states its table that way; that
  assertion is about to be false. Keep what it actually protects — that a
  distribution with a `force-include` escaping its own directory cannot be built
  as an sdist — and point it at the manifest.
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

## 2. Stop automated public publication

- [x] 2.1 Remove the publishing job from `.github/workflows/publish-pypi.yml`.
  Keep `detect-changes` if a later section needs it; delete it if not, rather
  than leaving a job whose only consumer is gone.
- [x] 2.2 Rename the workflow if it no longer publishes to PyPI. A file
  named for what it used to do is the same defect as a stale comment.
- [ ] 2.3 Record in `docs/development/RELEASING.md` that merging no longer
  publishes, and what to do instead. This is a contributor-workflow break and
  the first person it surprises should find the answer where they look.
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
- [x] 3.3 Withdrawn with 3.1.

## 4. Promotion

- [x] 4.1–4.8 Withdrawn: promotion and public publication are the deployment's
  (`design.md` D1, D8). The all-or-nothing refusal and the wheels-only answer to the
  sdist question carry forward as requirements on that publisher (D8).

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

## 7. CI publishes nothing

- [ ] 7.1 Delete `.github/workflows/publish-pypi.yml`, `publish-npm.yml`, `release.yml` and
  `release-cli.yml`. This also closes 2.7: there is no publishing workflow left to
  recover.
- [ ] 7.2 Delete `scripts/verify-marketplace-release.py` and
  `scripts/tests/test_verify_marketplace_release.py`. Nothing else reads the release
  contract.
- [ ] 7.3 Make CI build the wheelhouse and resolve every declared distribution against
  it, in `.github/workflows/tests.yml`. Repoint `scripts/tests/test_publish_matrix.py`
  and `test_image_publication_contract.py` at what remains. Delete the assertions about
  the deleted workflows; keep the ones that protect a build property, such as a
  `force-include` that escapes its directory.
- [ ] 7.4 Check that no workflow under `.github/workflows/` contains an upload step
  (`pypa/gh-action-pypi-publish`, `npm publish`, `docker push`,
  `docker/build-push-action` with push, `softprops/action-gh-release`,
  `gh release create`). Add it to the check that 1.5 introduced.

## 8. One declaration of what a release comprises

- [ ] 8.1 Rename `manifests/published-distributions.json` to
  `manifests/release-components.json`. Keep every distribution entry, and add `public`
  to each. `arkhai-apicredits-sample-app` and `lane-double-controls` are not public;
  check the rest against `docs/development/RELEASING.md`'s published-packages list.
  Update `scripts/push-distributions.py` and the tests that read the old path.
- [ ] 8.2 Declare the service images (registry, storefront, provisioning, bare-metal
  storefront, frp-grant-admission), each with its published name and the local image
  its build writes. Also declare the chart directory, the `market` binary with its
  build target, and the npm package directory.
- [ ] 8.3 Make `push-images` push the declared images through
  `scripts/publish_artifacts.py`, in place of its four literal lines. Keep the bare tag
  beside the revision tag (`design.md` D4).
- [ ] 8.4 Give `build-bare-metal-storefront` the local `-$(GIT_SUFFIX)` tag that the
  registry, storefront and provisioning builds write when `IMAGE_SUFFIX` is empty.
- [ ] 8.5 Make `push-charts` and `push-cli` take their chart directory and binary from
  the declaration. Widen the single-enumeration check (1.5) to fail on any image, chart
  or binary list in a publish target or workflow.
- [ ] 8.6 **External blocker: a development registry that serves npm.** Add `push-npm`,
  which packs the declared npm package and uploads it to that registry. Until the
  registry exists, record that the package is built and tested but not loaded.
- [ ] 8.7 Tests under `scripts/tests/` cover:
  - the declaration's shape;
  - every declared image having a build target that writes its local revision tag;
  - `push-images` (with `docker` stubbed) pushing exactly the declared set, and each
    image's bare tag.

## 9. The chart names no release

- [ ] 9.1 Remove `appVersion` from `helm/Chart.yaml`, and anything that reads it. Confirm
  `helm/values.yaml` keeps the bare tags with empty digests.
- [ ] 9.2 Add a render test in `helm/`: the chart's defaults name no semver-shaped image
  tag, no revision-suffixed tag and no digest.

## 10. Version check against the previous release

- [ ] 10.1 Add `scripts/check-release-versions.py` and `make check-release-versions`.
  - It reads `manifests/release-bom.cdx.json` from the latest `marketplace-v*` tag that
    carries one.
  - It compares that file with `.dist`'s wheels and with `helm/`'s version and git tree
    id.
  - It refuses a component whose version is unchanged but whose contents differ, and
    names each one.
  - When no earlier tag carries a bill of materials, it says so and passes.

  It reads only git and the wheelhouse; it never contacts a registry or an index.
- [ ] 10.2 Tests: an unchanged wheel passes, a changed wheel with a bumped version
  passes, a changed wheel at the same version fails, a changed chart tree at the same
  chart version fails, and no previous record passes. Use a scratch git repository
  holding a bill of materials at a tag.

## 11. Retire the curl installer

- [ ] 11.1 Delete `install.sh`, `scripts/install-remote.sh`, `scripts/build-installer.sh`,
  `scripts/tests/test_install_remote_urls.py` and
  `scripts/tests/test_install_sh_dependencies.py`.
- [ ] 11.2 Rewrite `docs/buyer-quickstart.md`'s install section. It offers PyPI
  (`uv tool install arkhai-core-buyer --with arkhai-vms-buyer`, pinned to a release's
  versions) and the release's `market` binary with its SHA-256 (linux x86_64), and
  keeps the from-the-repository path. Remove `install.sh` from `README.md`'s tree.

## 12. Documentation

- [ ] 12.1 Rewrite `docs/development/RELEASING.md` from this repository's side, replacing
  its workflow sections. It covers:
  - the five steps in `design.md`;
  - "the revision names a candidate, the semver names a release";
  - the component declaration and what `public` means;
  - the publish targets and why development tags guarantee nothing;
  - the cut: the branch, the bill-of-materials commit and the tag, made last;
  - what the bill of materials contains;
  - `make check-release-versions`;
  - that public channels are reached only by the deployment's promotion;
  - how a new PyPI project comes to be owned by the organization.

  It names no private repository, project, registry or host. This also discharges 2.3.

## 13. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 13.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`. Read the
  comments this change added for any that narrate the redesign or describe a mechanism
  as temporary. Do not edit code here: anything to rewrite returns the change to
  implementation.
- [ ] 13.2 **Import placement — confirm.** Check the imports this change added, in
  `scripts/check-release-versions.py`, the publish scripts and their tests, for any
  still local without a recorded reason.
- [ ] 13.3 **Documentation compliance.** Re-check the accepted decisions against
  `openspec/README.md`'s placement rules, and the permanent documents against the code.
  Also check that no document still describes a publishing workflow, the release
  contract or the curl installer.
- [ ] 13.4 **Narrative compression.** Compress completed-task notes to final behavior,
  material evidence, deferred work and promotion destinations. The rejected
  alternatives (merge publishes to the development registry; a tag workflow publishing
  promoted bytes; a trusted-publishing workflow for new projects) stay in `design.md`.
- [ ] 13.5 **Roadmap currency.** Expected disposition: `docs/development/ROADMAP.md` owes
  nothing, since no market capability changes. Record it.
- [ ] 13.6 **Campaign index currency.** Update this change's row and the Package and
  release readiness campaign in `openspec/changes/README.md`. Settle with
  `configure-pypi-trusted-publishing` which of the distribution-graph and PyPI-only
  installation acceptance it still owns, and record that in both rows.
- [ ] 13.7 **Packaging.** Run `make check-packaging` and resolve every failure.
- [ ] 13.8 **End-to-end pipeline.** Record the passing run the latest validation names
  and the scenarios touching this change, or an explicit blocker. Also record the first
  release cut under this procedure: its tag, and that its bill of materials was
  committed and `make check-release-versions` passed at the cut.
- [ ] 13.9 **Promotion.** Write `docs/development/RELEASING.md` and
  `docs/buyer-quickstart.md` (sections 11–12) and complete the record below.
  `openspec/specs/deployment-state/spec.md` is written by the archive.
- [ ] 13.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=publish-wheels-through-a-gate` and resolve every
  match. Then run `openspec validate publish-wheels-through-a-gate --strict`.
- [ ] 13.11 **Archival.** Last: `openspec archive publish-wheels-through-a-gate -y`, point
  the index row at the archived directory, then run `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Continuous integration publishes nothing | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md` | Pending (at archival / 12.1) |
| The revision names a candidate and the semver names a release | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md` | Pending |
| One declaration of what a release comprises, each distribution public or not | `openspec/specs/deployment-state/spec.md` | Pending (at archival) |
| The chart names no release; its version follows its own semver | `openspec/specs/deployment-state/spec.md` | Pending (at archival) |
| A release is recorded last by a tagged bill-of-materials commit on its release branch, content identities only | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md` | Pending |
| A version whose contents changed is refused against the previous release | `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md` | Pending |
| A product version is distinct from a distribution version | `openspec/specs/deployment-state/spec.md` | Pending (at archival) |
| Public channels receive promoted bytes, all or nothing, wheels only | `openspec/specs/deployment-state/spec.md` | Pending (at archival) |
| Development tags are rewritten by design and guarantee nothing; bare tags never leave development | `docs/development/RELEASING.md` | Pending |
| The buyer CLI ships from PyPI and as the promoted binary | `docs/buyer-quickstart.md` | Pending |
