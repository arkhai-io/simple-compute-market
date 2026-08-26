> **Archived 2026-08-26 — not implemented.** No task below was started.
>
> The list is retained as the record of what this change intended to build and
> in what order. Read it as evidence of scope, never as work to resume: its
> successor sequences differently, and a task here that looks unfinished is
> finished in the sense that matters — it will not be done.

---

# Tasks

Two commits, reviewed and merged as one change. Commit 1 must be independently
green: the projection produces deterministic results from fixture corpora with
the issue engine untouched. Commit 2 extends the engine, which is the only part
that can mutate anything outside the working tree.

Baseline: `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`. Re-pin
before starting.

Sequenced after `add-harness-scenario-contract` and
`restore-issue-discovery-thin-runner`.

Fixtures only. Nothing here runs a scenario or produces an event corpus from a
running system. If a task appears to need one, the plan premise is wrong —
pause for design review.

## Commit 1 — Deterministic projection

### 1. Event corpus and result shape

- [ ] 1.1 Define the recorded event shape and the projected result shape as
  schemas under `tools/issue-discovery/schemas/`. The result names its scenario,
  its series, its evidence class, its measurements, and its unattributed
  observations.
- [ ] 1.2 Commit fixture corpora covering: a clean single-buyer run, a
  contention run with expected refusals, a run with a collector gap, a run that
  left residue, and a run where an actor missed its release.
- [ ] 1.3 Make the projection a pure function of the corpus. No ambient clock,
  no ordering by wall-clock timestamp where causal ordering is available, no
  identifier that varies between projections of one corpus.
- [ ] 1.4 Add a test that projecting one corpus twice produces byte-identical
  results, and that projecting a corpus whose events are shuffled produces the
  same result where causal ordering determines it.

### 2. Measurement vocabulary

- [ ] 2.1 Derive offered demand from the actors' frozen requests and their
  release, not from responses.
- [ ] 2.2 Derive served capacity from product-owned outcomes only. Do not
  re-derive it from harness observations of those outcomes.
- [ ] 2.3 Derive load-generator limit from harness-side constraints: an actor
  that failed to start, missed its release, or was still preparing at release.
- [ ] 2.4 Report a quantity that cannot be attributed to exactly one of the
  three as unattributed, carrying the events that made it ambiguous. Do not
  compute any of the three as the residual of the others.
- [ ] 2.5 Add a test using the actor-missed-release corpus asserting the
  shortfall lands in load-generator limit and not in served capacity.

### 3. Missingness and evidence class

- [ ] 3.1 Record an underivable metric as absent with a reason. Never default to
  zero, and never omit the field — a consumer must be able to distinguish "not
  measured" from "not applicable".
- [ ] 3.2 Add a test using the collector-gap corpus asserting residue is absent
  with a reason rather than zero.
- [ ] 3.3 Attach an evidence class to every result. Refuse to attach a claim the
  class does not admit, rather than attaching it with a qualifier.
- [ ] 3.4 Add a test that a mock-sourced corpus cannot produce a result carrying
  a live, capacity, or production claim.

### 4. Series identity and repetition

- [ ] 4.1 Distinguish warmup repetitions from measured ones in the result.
- [ ] 4.2 Make series identity immutable once established: a later run extends a
  series and cannot redefine it. Include the product revision in the identity,
  so a revision change starts a new series — see `design.md`, "Open questions".
- [ ] 4.3 Add a test that a corpus claiming an existing series identity with
  different defining attributes is refused.

## Commit 2 — Issue engine integration

### 5. Suppression and cleanup gating

- [ ] 5.1 Suppress a refusal that matched its declared signature at projection
  time, so it never becomes a candidate. Do not generate and filter — a
  candidate in the run artifacts is a defect to the next reader of those
  artifacts.
- [ ] 5.2 Count suppressed expected refusals in the result. A scenario that
  declared three and produced none has a finding, visible only if the count is
  reported.
- [ ] 5.3 Gate filing readiness on cleanup: a finding whose run left residue is
  not `ready_to_file`.
- [ ] 5.4 Make cleanup failure its own finding class, not a note on the finding
  the run was investigating. The two get fixed and closed separately.

### 6. Update, reopen, recurrence

- [ ] 6.1 Extend `IssueRepository` to act on the `state` the duplicate search
  already retrieves: recurrence against an open issue records recurrence;
  against a closed issue, reopens.
- [ ] 6.2 Do not file a second issue for a known fingerprint under any state.
- [ ] 6.3 Keep both paths behind the existing `ready_to_file` and redaction
  gates. Reuse `_body_is_redacted`; do not add a second redaction path.
- [ ] 6.4 Record the recurrence against the product revision observed, so a
  recurrence after a claimed fix is distinguishable from one before it.

### 7. Draft-fix proposals, guarded

- [ ] 7.1 Materialize a proposed fix as an artifact in the working tree.
- [ ] 7.2 Fall back to a candidate packet where even a working-tree write is not
  permitted.
- [ ] 7.3 Add no code path that creates a comment, a branch, a pull request, or
  a merge.
- [ ] 7.4 Add a test asserting the engine's reachable surface contains no such
  path. Assert on the surface, not on behaviour under a flag: a promise not to
  mutate is the control that failed before.

### 8. Documentation

- [ ] 8.1 Record evidence classes in `docs/development/TESTING.md`, including
  what a mock or fixture result may not be said to prove.
- [ ] 8.2 Record update, reopen, suppression, and the cleanup gate in
  `docs/development/ISSUE_DISCOVERY.md`, alongside the existing create path.
- [ ] 8.3 State the three measurements and why they are never derived from one
  another. This is the claim most likely to be misread downstream.
- [ ] 8.4 Verify every path cited by both documents resolves on the branch.

### 9. Closeout

- [ ] 9.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
  match; read touched files for what the target cannot catch.
- [ ] 9.2 **Import placement.** Migrate local imports added here to module level
  where safe, verifying each against the real suite.
- [ ] 9.3 **Documentation compliance.** Re-check accepted decisions against
  `openspec/README.md`'s placement rules, and confirm every citation resolves.
- [ ] 9.4 **Narrative compression.** Reduce task notes to final behaviour,
  validation evidence, unresolved work, and promotion destinations. The
  three-quantity reasoning belongs in `design.md`.
- [ ] 9.5 **Roadmap currency.** `docs/development/ROADMAP.md` owes nothing: the
  harness is not a market capability. Recorded as a deliberate disposition.
- [ ] 9.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Offered demand, served capacity, and load-generator limit are distinct and never derived from one another | `docs/development/TESTING.md` | Pending |
| An evidence class bounds what a result may be said to prove; a mock or fixture result is never live or capacity evidence | `docs/development/TESTING.md` | Pending |
| Filing readiness is gated on cleanup, and cleanup failure is its own finding class | `docs/development/ISSUE_DISCOVERY.md` | Pending |
| Recurrence updates or reopens the existing issue; the engine creates no comment, branch, or pull request | `docs/development/ISSUE_DISCOVERY.md` | Pending |
| `Campaign projection is deterministic`, `Measurements are attributed, not derived`, `Underivable metrics are absent with a reason`, `Evidence class bounds the claim`, and `The existing issue engine is the only issue lifecycle` | `openspec/specs/test-compatibility/spec.md` | At archival |
