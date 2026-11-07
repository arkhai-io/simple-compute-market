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

Per `openspec/README.md#plan-closeout-requirements`. This change's implementation predates the closeout task becoming a planning requirement, so each part is recorded with the evidence that discharges it rather than assumed.

- [x] 4.1 **Comment hygiene.** `make check-comment-hygiene` passes. Direct-read the four
      files this change touches outside `openspec/` — `make/hosted-release.mk`,
      `scripts/check-hosted-client-pin.py`, and the two `scripts/tests/` modules — for the
      provenance narration the target cannot catch: none present. Comments state the
      current contract (one pin is the statement of record) rather than what preceded it.
- [x] 4.2 **Import placement.** Every import this change adds is module level: `argparse`,
      `re`, `sys`, `pathlib` in the new pin checker, and `importlib.util`, `pathlib`,
      `pytest` in its test. The one function-local import in a file this change touched
      (`scripts/tests/test_hosted_compose_contract.py`, `importlib.util` inside the
      ready-gate test) predates this change and stays: relocating it is a general-purpose
      cleanup this section's diff does not own.
- [x] 4.3 **Documentation compliance.** This change carries no delta specs; it changes how
      the repository binds an external release, not observable market behavior, so no
      subsystem contract owns it. Its durable statement is
      `docs/development/TESTING.md#raising-the-hosted-contract`, which describes the current
      procedure in present tense and names the one file that states the version. Rejected
      alternatives stay in `design.md`.
- [x] 4.4 **Narrative compression.** Completed-task notes already carry final behavior and
      the file each outcome landed in, with rationale held in `design.md`. Re-read at
      closeout; nothing to move or delete.
- [x] 4.5 **Roadmap currency.** No impact. `docs/development/ROADMAP.md` carries goals in
      terms of market capability; how this repository pins and verifies an external release
      is release mechanics behind Goal 6's mechanism rather than a goal-level gap, and no
      goal's current-state paragraph or gap mapping changes. Disposition recorded rather
      than the step skipped.
- [x] 4.6 **Campaign index currency.** The index gained a row for this change on 2026-09-04
      under the "Hosted fiat settlement" campaign, which had been absent from it entirely.
      On archival that row is removed, which is the disposition a completed change owes the
      index.
- [x] 4.7 **Promotion.** Design-promotion record added to `design.md`. No production source
      references `openspec/changes/bind-one-hosted-release-coordinate` — verified across
      Python, Make, TOML, and YAML outside `openspec/`.
