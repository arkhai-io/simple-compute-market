# Tasks

Two commits. Commit 1 defines the representation and its evidence rules; commit
2 places it in the test hierarchy and documents the crossing. The jurisdiction
question is easier to review separately from the format.

Baseline: `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`. Re-pin
before starting.

Sequenced after `add-harness-findings-projection` for the evidence-class
vocabulary, and after `refactor-e2e-fulfillment-lifecycle` for a target layer
asserting on fulfillment identity — a regression generated against the current
assertions would encode the identity confusion that change removes.

**This change generates nothing.** It defines what a generated regression must
be. If a task appears to need a generator, the plan premise is wrong — pause for
design review.

## Commit 1 — Representation and evidence

### 1. Representation

- [ ] 1.1 Define a regression as normalized actions and expected outcomes,
  separate from the adapter that executes them.
- [ ] 1.2 Exclude from the representation: model prose, hidden reasoning,
  incidental command ordering, timestamps, temporary identifiers, and anything
  else the protected behaviour does not depend on. Each is a reason the
  regression will later fail for something unrelated to what it protects.
- [ ] 1.3 Make hermetic execution the default adapter, and permit a reviewed
  configuration to use a controlled integration environment where fidelity
  justifies it. The point is that a regression can be re-run under a different
  adapter when there is reason to doubt it.
- [ ] 1.4 Carry whatever identity semantic reuse will need — scenario, action,
  and finding — even though the reuse rule itself is not defined here. A
  representation designed without it cannot acquire it later without rewriting
  every regression.

### 2. Evidence

- [ ] 2.1 Require fail-before/pass-after or mutation sensitivity for a
  regression protecting a corrected defect. This is what separates a captured
  fix from a captured defect; without it a regression asserts the system does
  what it did, which is true of a bug.
- [ ] 2.2 Permit another focused demonstration where neither is practical, and
  require the substitution to be recorded. An unrecorded substitution is
  indistinguishable from an unexamined one.
- [ ] 2.3 Define the evidence class a regression carries: which layer authored
  it, and what it therefore cannot prove.
- [ ] 2.4 Make a regression's evidence class refuse a concurrency or capacity
  claim outright, rather than qualifying one. A generated regression is hermetic
  by construction and cannot exercise either.
- [ ] 2.5 Assign a distinct, lower evidence class to a regression generated from
  a run that passed. It has no failure to demonstrate against, and its class
  should record that it was never observed failing.

### 3. Sanitization

- [ ] 3.1 Require a regression derived from agent evidence to pass the same
  allowlist projection as any other artifact crossing from the private side.
  Not a lighter one because it is a fixture.
- [ ] 3.2 Add a test with a private identifier embedded in a recorded action's
  payload, asserting the containing field is withheld. A fixture is where a
  private identifier survives unnoticed: committed once, read rarely, and it
  looks like data.

## Commit 2 — Jurisdiction

### 4. Placement

- [ ] 4.1 Place a generated regression at the level owning the behaviour it
  protects. Do not create a separate level or a quarantined directory: a
  directory of generated tests becomes one nobody reads, whose failures are
  assumed stale.
- [ ] 4.1a Do not prescribe who maintains it thereafter. Placement is decided;
  maintenance is an open question with three live options, and settling it in a
  task would close it without anyone choosing.
- [ ] 4.2 Record the consequence rather than eliding it — someone maintains a
  test they did not write, from a trace they cannot read, protecting behaviour
  found by a tool they do not run. See `design.md`, "Who owns a generated
  regression after it lands?".

### 5. Documentation

- [ ] 5.1 Extend `docs/development/TESTING.md`'s harness section with the
  crossing: a generated regression is the one artifact moving from the harness's
  jurisdiction into the four-level hierarchy, which level receives it, and who
  owns it.
- [ ] 5.2 State plainly that a green regression suite is not concurrency or
  capacity evidence. The document is read when someone is thinking about
  strategy; the wrong inference is drawn when someone is looking at a green
  suite, which is why the evidence class is in the artifact as well.
- [ ] 5.3 Verify every path cited resolves on the branch.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve
  every match; read touched files for what it cannot catch.
- [ ] 6.2 **Import placement.** Migrate local imports added here to module level
  where safe, verifying against the real suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
  `openspec/README.md`'s placement rules; confirm every citation resolves.
- [ ] 6.4 **Narrative compression.** Reduce task notes to final behaviour,
  validation evidence, and unresolved work. The recording-versus-specification
  argument belongs in `design.md`.
- [ ] 6.5 **Roadmap currency.** `docs/development/ROADMAP.md` owes nothing: the
  harness is not a market capability. Recorded as a deliberate disposition.
- [ ] 6.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| A generated regression is placed at the level owning the behaviour it protects, and placement does not settle maintenance | `docs/development/TESTING.md` | Pending |
| A green regression suite is not concurrency or capacity evidence | `docs/development/TESTING.md` | Pending |
| `A regression declares what it cannot prove`, `A regression is separated from its execution adapter`, `A defect regression demonstrates failure without its fix`, and `A regression derived from agent evidence is sanitized before it is committed` | `openspec/specs/test-compatibility/spec.md` | At archival |
