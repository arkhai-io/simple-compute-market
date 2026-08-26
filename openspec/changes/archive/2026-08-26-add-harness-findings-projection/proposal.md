> **Archived 2026-08-26 — superseded, not implemented.**
>
> **Superseded by:** `define-assessment-and-findings` and `define-public-projection`, in the testing-harness repository.
>
> **Why.** The harness moved to a repository of its own, and this change held two separable concerns.
>
> **What carried forward.** The update, reopen, and deduplication lifecycle and the finding-is-not-authority rule go to the first. The projection boundary goes to the second, because more than one projection exists with different allowlists and neither belongs to findings alone. The rule keeping offered demand, served capacity, and load-generator limit distinct carries forward as a measurement requirement.
>
> **Where the reasoning lives.** `design.md`'s argument that these three quantities are the most plausible false claim the harness can make is cited by both successors.
>
> Design rationale is referenced rather than duplicated: successors cite this
> change by name and do not restate it, so the two cannot drift under two
> vocabularies.

---

## Why

A harness run produces events. Nothing turns them into a result, and nothing
bounds what a result may be said to prove.

Both gaps produce the same failure in different directions. Without a
deterministic projection, two people reading the same run reach different
conclusions and neither can show the other is wrong. Without a claim boundary, a
run against mock provisioning produces a number that reads exactly like a
capacity measurement.

This change adds the projection, the measurement vocabulary that keeps three
different quantities apart, and the integration into the issue engine that
already exists. It runs no scenario and files no issue it is not already
permitted to file.

Three things shape it.

**Three quantities look identical and mean different things.** When a run
reports "twelve requests, nine served," that is consistent with the product
serving nine and refusing three, with the harness only managing to offer nine,
and with the product serving twelve while the harness observed nine. Offered
demand, served capacity, and load-generator limit are separate measurements, and
a projection that cannot tell them apart will report the harness's own
bottleneck as a product limit. That is the most plausible false claim this
harness can make and the hardest to catch afterwards.

**The issue engine already works and should not be replaced.** `issues.py`
generates candidates from failed phases, fingerprints them, writes JSONL plus
Markdown bodies, gates filing on `ready_to_file`, checks the body against
redaction rules, searches open issues for the fingerprint, and declines to file
a duplicate. What it does not do is update, reopen, suppress an expected
refusal, or gate on cleanup — and the duplicate search already fetches issue
`state` while using it only to print.

**Absence and zero are different, and the difference is load bearing.** A metric
the run could not derive is not a metric that measured zero. Reporting the first
as the second turns a gap in observation into a finding about the product.

## What Changes

- A **deterministic projection**: a recorded event corpus produces one result,
  as a pure function of the events. No wall-clock ordering, no ambient time, no
  identifiers that change between projections of the same corpus.
- A **measurement vocabulary** distinguishing offered demand, served capacity,
  and load-generator limit. A quantity that cannot be attributed to exactly one
  of the three is not reported as any of them.
- **Explicit missingness.** A metric that could not be derived is recorded
  absent with the reason it is absent, never defaulted to zero.
- **Evidence classes.** Every result carries the class of claim it can support.
  Mock, dry-run, fixture, and rehearsal results are never live, capacity, or
  production evidence, and a result whose class does not admit a claim cannot
  carry that claim.
- **Series identity and repetition handling.** Warmup repetitions are
  distinguished from measured ones; a series identity is immutable once
  established, so a later run extends a series rather than silently redefining
  it.
- **Cleanup-gated filing.** A finding whose run left residue is not
  filing-ready, and the cleanup failure is itself a finding class rather than a
  footnote on another one.
- **Expected-refusal suppression.** A declared refusal that matched its declared
  signature is an expected outcome, not a defect, and does not become a
  candidate.
- **Update and reopen** in the existing engine, using the issue state the
  duplicate search already retrieves. Recurrence is recorded against the
  existing issue rather than filed again.
- **Guarded draft-fix proposals.** A proposed fix is an artifact in the working
  tree with a candidate-packet fallback. The engine gains no path that creates a
  branch, a comment, a pull request, or a merge.

Not in scope: running a scenario, producing an event corpus from a live system,
any campaign execution, and any new issue lifecycle. The existing engine remains
the only one.

## Impact

- Affected specs: `test-compatibility`
- Affected code: `tools/issue-discovery/src/issue_discovery/issues.py`,
  `tools/issue-discovery/src/issue_discovery/`, `tools/issue-discovery/schemas/`,
  `tools/issue-discovery/tests/`
- Depends on `add-harness-scenario-contract` for the declared expectations that
  make a refusal "expected", and on `restore-issue-discovery-thin-runner` for
  the engine this extends.
- Fixtures only. The projection is exercised against recorded event corpora
  committed as fixtures; nothing in this change produces a corpus from a running
  system.
- **Absence of mutation is asserted structurally, not promised.** The engine
  gets no code path that comments, branches, opens a pull request, or merges.
  Tests assert on the reachable surface, because a promise not to mutate is the
  control the archival branch had.
- Behaviour change to record: `create` currently prints a duplicate's URL and
  returns success. With update and reopen, a recurrence against an open issue
  records recurrence, and against a closed one reopens. Both are issue-lifecycle
  mutations that did not previously occur, and both stay behind the existing
  `ready_to_file` and redaction gates.
- Product observation, not fixed here: the classifier patterns in `issues.py`
  are matched against collected evidence and produce a generic
  phase-and-command candidate when nothing matches. That conservative default is
  correct and this change preserves it.

## Permanent documentation impact

- [ ] `docs/development/TESTING.md` — evidence classes and what a mock or
  fixture result may not be said to prove
- [ ] Existing subsystem specification — `test-compatibility`
- [ ] `docs/development/ISSUE_DISCOVERY.md` — update, reopen, suppression, and
  the cleanup gate on filing readiness
- [ ] `docs/development/ARCHITECTURE.md` — none owed
- [ ] New subsystem specification — none owed
- [ ] `docs/development/ROADMAP.md` — none owed; the harness holds no goal row

### Knowledge to promote

See the design-promotion record in `tasks.md`.
