## 1. One place names the bound release

- [x] 1.1 Add `make/hosted-release.mk` deriving `HOSTED_RELEASE_TRUST` and every
      value that follows from it, composing all paths from `HOSTED_REPO_ROOT`.

      It states no version of its own. `scripts/select-hosted-client-channel.py`
      already owns the relationship between the pinned version and what
      `manifests/` signs, and its docstring says why a third statement must not
      exist. The first draft here added one, `HOSTED_RELEASE_BOUND_VERSION`, and
      was replaced.
- [x] 1.2 Replace the duplicated blocks in `Makefile`,
      `domains/vms/storefront/Makefile`, and `kit/hosted-settlement/Makefile`
      with `HOSTED_REPO_ROOT` plus an include.
- [x] 1.3 Evidence: each Makefile resolves the same trust path, wheel path, and
      release file list as before the change, proven by printing them from all
      three directories and diffing against the values recorded first.

      Identical on the release channel, with two additive differences: the two
      sub-Makefiles now also define `HOSTED_RELEASE_SCHEMA` and
      `HOSTED_RELEASE_FILES`, which they previously left empty and do not use.
      `scripts/tests` passes, 114 tests.

## 2. The client pin has a single source

- [x] 2.1 Use the version `kit/hosted-settlement/pyproject.toml` states, which
      the channel selector already reads, rather than declaring another.
- [x] 2.2 Add `scripts/check-hosted-client-pin.py`, failing with the file and the
      found value when a follower disagrees, and rewriting them under `--fix`.
- [x] 2.3 Run it as an ordinary tree-consistency test under `scripts/tests`, with
      `make check-hosted-client-pin` and `make fix-hosted-client-pin` for hand use.
- [x] 2.4 Evidence: the check passes as the tree stands; mutating one pin fails
      it and names that file; `--fix` restores it. Four unit tests cover the
      agreeing tree, a named laggard, `--fix`, and a file stating no version.

## 3. The bump is one edit

- [x] 3.1 Record in `docs/development/TESTING.md` how to raise the contract:
      which variable moves when a release is published, which moves when this
      source starts consuming a new capability, and that they differ while a
      capability is built locally.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`. This change's implementation predates the closeout task becoming a planning requirement. The parts are recorded here so each carries an explicit disposition rather than an assumed one; confirm and tick each rather than treating the change as closed.

- [ ] 4.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the
      comments and docstrings this change touches for the fuzzier provenance-narration rule
      the target cannot catch mechanically.
- [ ] 4.2 **Import placement.** Review every import this change adds or touches and move it
      to module level where safe; retain a local import only against an observed circular
      import or a documented lazy-load reason, verified against the real suite.
- [ ] 4.3 **Documentation compliance.** Re-check this change's accepted decisions against
      `openspec/README.md`'s placement rules. It carries no delta specs, so confirm every
      material decision has a permanent destination or an explicit temporary, superseded, or
      rejected classification.
- [ ] 4.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and permanent-documentation
      destinations, moving durable rationale into `design.md` first.
- [ ] 4.5 **Roadmap currency.** This change belongs to no campaign, so it most likely owes
      `docs/development/ROADMAP.md` nothing. Confirm that and record the disposition
      explicitly rather than omitting the step.
- [ ] 4.6 **Campaign index currency.** This change has no row in
      `openspec/changes/README.md`; add one under the campaign that owns it with its status
      and acceptance boundary, or record here why it stands outside every campaign.
- [ ] 4.7 **Promotion.** Add a design-promotion record, mapping every accepted decision to
      its exact permanent heading, and verify no production source references
      `openspec/changes/bind-one-hosted-release-coordinate`.
