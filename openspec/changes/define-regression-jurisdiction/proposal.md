# Define where a generated regression lands and who owns it

## Why

`docs/development/TESTING.md` places agent-driven testing outside the four test
levels deliberately. A regression authored from one of those runs lands
*inside* them, and the document does not currently say which level receives it
or who maintains it afterwards.

Left unanswered, the default answer is whoever last touched it, which is how a
test with no owner and no stated provenance accumulates in a suite.

Two properties make the answer non-obvious. A regression derived from a recorded
run is hermetic by construction, so it cannot exercise concurrency against a real barrier or a real
provisioner — and it will be read as though it can, because it is fast and it is
green. And a recording is not a specification: nothing in a capture distinguishes
correct behaviour from a defect that happened to be present.

## What Changes

- Defines the **handoff** this repository accepts from an external suite: a
  concise defect description, permitted reproduction evidence, and proposed
  acceptance criteria for a regression. No test code arrives. This repository
  authors the fix and the test through its own change and conventions, and no
  named triage owner is required initially.
- Names the test level that receives a regression authored from such a handoff,
  and the ownership that attaches to it.
- Requires the authored regression to record its provenance in a form a reader
  encounters before the assertions: what it was derived from, against which
  revision, and what it does not demonstrate.
- States that a regression derived from a recorded run carries
  deterministic-reference strength regardless of what produced the recording, and
  that a passing suite of them is never concurrency or capacity evidence.
- Requires fail-before / pass-after evidence against the exact revision that
  failed, so a recording that froze a defect is rejected at the boundary.

This change accepts handoffs and authors regressions. It generates none, and it
does not accept generated test code.

## Permanent documentation impact

- [x] Existing subsystem specification — `test-compatibility`
- [x] `docs/development/TESTING.md`

## Impact

- Affected specs: `test-compatibility`
- Affected code: `e2e-tests/`, `docs/development/TESTING.md`
- Depends on `declare-deal-lifecycle-contract` — which level receives a
  regression is easier to answer once the stages a regression can target are named
- Rescoped from `add-deterministic-regression-contract`; how a finding becomes a
  handoff is the external suite's concern and not stated here
