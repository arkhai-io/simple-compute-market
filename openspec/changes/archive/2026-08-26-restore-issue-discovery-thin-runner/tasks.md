> **Archived 2026-08-26 — not implemented.** No task below was started.
>
> The list is retained as the record of what this change intended to build and
> in what order. Read it as evidence of scope, never as work to resume: its
> successor sequences differently, and a task here that looks unfinished is
> finished in the sense that matters — it will not be done.

---

# Tasks

One commit. The configuration repair and the validation that would have caught
it belong together — landing the repair alone leaves the next drift undetectable
by the same mechanism.

Sequenced after nothing. `remove-relative-uv-sources` task 2.5 carries the
wider `reinit` inventory and excludes `kit/policy` to avoid colliding with 1.2
here; neither change blocks the other.

Baseline: `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`. Re-pin
before starting and re-pin if the session spans a day; the entry-point audit in
`design.md` is a statement about a tree.

## 1. Repair the phase configuration

- [ ] 1.1 In `tools/issue-discovery/config/phases/local.yaml`, repoint the
  `buyer_tests` phase's three commands from `buyer` to `domains/vms/buyer`. That
  package defines `reinit`, `test`, and `smoke-test`, so all three commands
  survive unchanged.
- [ ] 1.2 Repoint `policy_tests` from `policy` to `kit/policy`, and add a
  `reinit` target to `kit/policy/Makefile` following the pattern in
  `kit/config/Makefile` and `kit/fulfillment/Makefile`. `reinit` maintains the
  project's `.venv` dependencies and is owed to the package's own developers
  independently of the harness; the phase command stays.
- [ ] 1.3 Remove the `shared_service_tests` phase. Its `service` workdir does
  not exist and the successor is not determinable from the configuration —
  `kit/config`, `kit/fulfillment`, and `core/storefront` are all candidates. See
  `design.md`, "Open questions". Removal is not the answer to that question; it
  keeps the configuration loadable while the question is open, and restoring the
  phase is a small deliberate act once someone answers it. Do not repoint it at
  the nearest plausible directory: a phase that tests nothing identifiable
  produces candidate issues attributed to a package not under test.
- [ ] 1.4 Check `targeted_repros.yaml` and `clean_ubuntu_bootstrap.yaml` for the
  same class of drift. The audit in `design.md` covered `local.yaml` only.

## 2. Make drift detectable

- [ ] 2.1 In `tools/issue-discovery/src/issue_discovery/config.py`, extend phase
  configuration loading so that every command's declared `workdir` exists
  relative to the repository root, every `make <target>` command resolves by
  running `make -n <target>` in that directory, and every other command's
  executable resolves on `PATH`. `make -n` executes no recipe but resolves
  includes, variables, pattern rules, and the prerequisite chain — a target that
  exists but depends on a missing one is caught. Report every failure in one
  pass rather than the first; a configuration three directories stale should say
  so once.
- [ ] 2.2 Fail loading, not the phase. A stale configuration is a defect in the
  harness and must not reach the collector-and-candidate path, which would
  attribute it to the product.
- [ ] 2.3 Add `tools/issue-discovery/tests/test_phase_entrypoints.py` covering:
  every shipped phase file passes; a missing `workdir` fails and names it; an
  undefined `make` target fails and names both target and directory; a target
  whose prerequisite is undefined fails, which parsing would not have caught; a
  non-`make` command with no executable on `PATH` fails; all failures are
  reported together. Use a fixture Makefile rather than the repository's own, so
  the test does not fail when an unrelated target is renamed.
- [ ] 2.4 Document the known limit where the check lives: `make -n` does not
  expand recursive make inside a recipe, so a target whose recipe is
  `cd <dir> && make <target>` has its nested entry point unvalidated. State it
  rather than letting a reader infer coverage the check does not provide.
- [ ] 2.5 Confirm `tools/issue-discovery/schemas/phases.schema.json` needs no
  change — this is a resolution rule against the tree, not a shape rule — or
  amend it and say why in the task note.

## 3. Add the invocation entry points

- [ ] 3.1 Add `issue-discovery` to the root `Makefile`, delegating to
  `./scripts/issue-discovery` and passing arguments through. Register it in
  `.PHONY`.
- [ ] 3.2 Add `issue-discovery-test`, running the locked suite in the tool's own
  `uv` environment: `cd tools/issue-discovery && uv --no-config run pytest -q`.
  Register it in `.PHONY`.
- [ ] 3.3 Do not add either target to the aggregate `test` target or to the
  Tests workflow. `docs/development/TESTING.md` records why the suite is
  excluded — the bootstrap tests inspect the host — and this change does not
  revisit that decision.

## 4. Correct the permanent documentation

- [ ] 4.1 Rewrite `docs/development/TESTING.md`'s harness section to describe
  the tool that exists. Keep: the harness is not a fifth level and is not in the
  jurisdiction table; product behaviour belongs at the level that owns it; the
  harness earns a test only when the behaviour under test is the harness's own.
- [ ] 4.2 Remove the capacity-specific claims — scenario admissibility,
  reservation and fulfillment correlation, expected-scarcity evaluation — and
  both unresolvable citations: the `test-compatibility` requirement "Agent-driven
  VM capacity contracts are finite and non-executing", and the
  `ISSUE_DISCOVERY.md` "Privacy and validation responsibility" section. Neither
  target exists on this branch.
- [ ] 4.3 Remove the claim that the harness performs no provisioning action. The
  tool starts a compose stack in mock provisioning mode and registers a mock
  host. State what it does execute and under which profile.
- [ ] 4.4 Cite the two requirements this change adds, and verify both citations
  resolve on the branch before marking the task done.
- [ ] 4.5 Check `docs/development/ISSUE_DISCOVERY.md` describes the repaired
  invocation, including the new Make targets.

## 5. Closeout

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
  match. Read the touched files directly for the fuzzier violations the target
  cannot catch — references to the review or migration that introduced code.
- [ ] 5.2 **Import placement.** Migrate local imports added by this change to
  module level where safe, checking each for a genuine circular import or a
  documented lazy-load reason first. Verify against the real suite.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted
  decisions against `openspec/README.md`'s placement rules. Confirm every path
  cited by the rewritten `TESTING.md` section exists on the branch — the defect
  this change corrects was an unresolvable citation in a permanent document, and
  re-introducing one here would be the same error.
- [ ] 5.4 **Narrative compression.** Shorten completed-task notes to final
  behaviour, validation evidence, unresolved work, and promotion destinations.
  The `service` workdir question belongs in `design.md`'s "Open questions", not
  in a task note.
- [ ] 5.5 **Roadmap currency.** `docs/development/ROADMAP.md` owes nothing: the
  harness is a tool, not a market capability, and holds no goal or gap row.
  Recorded as a deliberate disposition rather than omitted.
- [ ] 5.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

`Applied` rows are already in the named document. `At archival` rows are spec
deltas that `openspec archive` synchronizes into `openspec/specs/`.

| Accepted decision | Permanent location | State |
|---|---|---|
| The harness is outside the four-level jurisdiction table; product behaviour belongs at the level that owns it; the harness earns a test only when the behaviour is its own | `docs/development/TESTING.md` | Pending |
| What the harness actually executes, and under which provisioning profile | `docs/development/TESTING.md` | Pending |
| Invocation is through named Make targets; the locked suite stays outside the aggregate test target | `docs/development/ISSUE_DISCOVERY.md` | Pending |
| `Issue-discovery harness jurisdiction` and `Harness phase configuration resolves against the current tree` | `openspec/specs/test-compatibility/spec.md` | At archival |
