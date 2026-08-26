# Define where a generated regression lands and who owns it

## Why

`docs/development/TESTING.md` places agent-driven testing outside the four test
levels deliberately. A regression generated from one of those runs lands
*inside* them, and the document does not currently say which level receives it
or who maintains it afterwards.

Left unanswered, the default answer is whoever last touched it, which is how a
test with no owner and no stated provenance accumulates in a suite.

Two properties make the answer non-obvious. A generated regression is hermetic by
construction, so it cannot exercise concurrency against a real barrier or a real
provisioner — and it will be read as though it can, because it is fast and it is
green. And a recording is not a specification: nothing in a capture distinguishes
correct behaviour from a defect that happened to be present.

## What Changes

- Names the test level that receives a generated regression, and the ownership
  that transfers with it.
- Requires a generated regression to record its provenance in a form a reader
  encounters before the assertions: what produced it, against which revision, and
  what it does not demonstrate.
- States that a generated regression carries deterministic-reference strength
  regardless of what produced it, and that a passing suite of them is never
  concurrency or capacity evidence.
- Requires fail-before / pass-after evidence against the exact revision that
  failed, so a recording that froze a defect is rejected at the boundary.

This change accepts regressions. It generates none.

## Permanent documentation impact

- [x] Existing subsystem specification — `test-compatibility`
- [x] `docs/development/TESTING.md`

## Impact

- Affected specs: `test-compatibility`
- Affected code: `e2e-tests/`, `docs/development/TESTING.md`
- Depends on `declare-deal-lifecycle-contract` — which level receives a
  regression is easier to answer once the stages a regression can target are named
- Rescoped from `add-deterministic-regression-contract`; generation semantics
  moved to the testing-harness repository
