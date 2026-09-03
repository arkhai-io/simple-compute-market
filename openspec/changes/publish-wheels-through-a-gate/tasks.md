## Readiness

Sections 1 and 2 are implementable now and need nothing from outside this
repository. Together they stop the failure mode that motivates the change: a
merge can no longer put a permanent artifact on a public index.

Sections 3 to 6 are **blocked on a writer identity for the development
registry**, which is granted outside this repository. They are planned here so
the shape is reviewable, and must not be started before the identity exists —
a merge-to-main publication step that cannot authenticate is worse than none,
because it fails on every merge and is muted rather than fixed.

Section 5 is additionally blocked on the settlement client being publicly
resolvable. Section 6 is additionally blocked on the cross-repository inventory
format existing.

Sequencing note: section 2 removes public publication before section 3 provides
its replacement. That order is deliberate. The gap between them publishes
nothing, which is the safe state; the reverse order leaves ungated public
publication running for longer than necessary.

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

## 3. Publish to the development registry on merge

**Blocked on a writer identity for the development registry.**

- [ ] 3.1 Add a workflow invoking `push-runtime-artifacts`, authenticating by
  workload identity federation. Do not add a long-lived credential.

  **Not on merge to the default branch.** The registry push is to be triggered
  deliberately — `workflow_dispatch`, or a push filter on a nominated branch —
  rather than by merging. That keeps the property section 2 established: no
  merge publishes anything anywhere, and the difference between the registry
  and the public index becomes which gate a human passes rather than which
  branch they landed on.
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
- [ ] 3.3 Verify by inspecting the registry after one *workflow* run: every
  manifest entry present at the version its `pyproject.toml` declares. A
  by-hand push has established the set is complete and uploadable; what remains
  unverified is that the workflow's own identity can do it.

## 4. Promotion

**Blocked on section 3.**

- [ ] 4.1 Add a promotion script under `scripts/` that, for every manifest
  entry, fetches the public index's recorded `sha256` for that version from its
  JSON metadata. No download — the digest is in the metadata, so checking all
  entries costs one request each.
- [ ] 4.2 Classify each entry: absent from the index, present with identical
  bytes, present with differing bytes.
- [ ] 4.3 **Check every entry before uploading any.** On any differing-bytes
  entry, fail the whole promotion and upload nothing. A per-entry skip would put
  distributions on a public index whose versions describe code from different
  builds, and a public index is write-once, so that state is permanent.
- [ ] 4.4 Upload absent entries by copying bytes retrieved from the development
  registry. Do not rebuild, and do not change any version.
- [ ] 4.5 Decide and record the position on sdists. At least one current
  distribution has both a wheel and an sdist published; the script must state
  whether sdists are promoted, verified, or ignored, and this is an open
  question in `design.md` rather than a settled one.
- [ ] 4.6 Add a Make target invoking the script. Human-invoked only — no
  schedule, no webhook, no trigger.
- [ ] 4.7 Add focused tests under `scripts/tests/` for the three classification
  outcomes and for the all-or-nothing refusal, with the index metadata stubbed.
  The refusal is the behaviour worth testing: it is the one that only fires when
  something has already gone wrong.
- [ ] 4.8 Document the removal condition in code where the target lives: this
  repository publishes directly because no promotion pipeline consumes its
  artifacts. State the condition, not a removal plan — a condition is checkable
  and becomes false on its own, and a migration narrative is what `AGENTS.md`
  excludes from production code.

## 5. Repair the published graph

**Blocked on sections 3 and 4, and on the settlement client being publicly
resolvable.**

- [ ] 5.1 Bump `arkhai-kit-hosted-settlement`. Its 0.1.4 on PyPI declares a
  dependency PyPI does not carry, so it is uninstallable for every external
  consumer and cannot be corrected in place.
- [ ] 5.2 Promote the new version and verify installation into a clean
  environment from the public index alone, with no `.dist` and no checkout.
- [ ] 5.3 Reconcile with `configure-pypi-trusted-publishing`, which claims
  overlapping acceptance on the distribution inventory and on proving
  PyPI-only installation. Decide which change owns which half before either is
  archived; do not let both claim it.

## 6. Inventory substitution

**Blocked on the cross-repository inventory format.**

- [ ] 6.1 Replace the manifest from section 1 with the release inventory as the
  single enumeration. Mechanical if section 1 held to one declaration.
- [ ] 6.2 Record which distribution versions a promoted product version
  comprises. Nothing in a wheel's filename says which product version it belongs
  to, so the inventory is the only place that binding exists.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene`. Then read the
  promotion script and the manifest directly: the target catches change IDs and
  task numbers mechanically and does not catch a comment narrating that this
  mechanism is temporary, which is the violation this change is most likely to
  introduce.
- [ ] 7.2 **Import placement.** Check imports added by the promotion script and
  its tests for a real reason to stay local before moving them; verify each move
  against the suite rather than a syntax check.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
  `openspec/README.md`'s placement rules. Confirm every cited `openspec/`,
  `docs/`, and `scripts/` path resolves on this branch.
- [ ] 7.4 **Narrative compression.** Reduce completed-task notes to final
  behaviour, validation evidence, and unresolved work. The rejected
  alternatives and the reasoning for all-or-nothing refusal stay in `design.md`.
- [ ] 7.5 **Roadmap currency.** Update the Package and release readiness
  campaign summary in `openspec/changes/README.md`. `docs/development/ROADMAP.md`
  owes nothing: this is a lesser goal and changes no market capability.
  Recorded as a deliberate disposition.
- [ ] 7.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Public publication is a deliberate promotion of artifacts already in the development registry, never a merge side effect | `docs/development/RELEASING.md` | Pending |
| Promotion copies bytes and never rebuilds; a distribution's version cannot change at the gate | `openspec/specs/deployment-state/spec.md` | Pending |
| A version present on the public index with differing bytes fails the whole promotion before anything is uploaded | `docs/development/RELEASING.md` | Pending |
| One enumeration of published distributions, read by every publication path | `openspec/specs/deployment-state/spec.md` | Pending |
| A product version is distinct from a distribution version; images retag, wheels and archives copy at their built version | `openspec/specs/deployment-state/spec.md` | Pending |
| The interim publication mechanism is described by its condition, and deleted rather than adapted when a promotion pipeline consumes these artifacts | `docs/development/RELEASING.md` | Pending |
