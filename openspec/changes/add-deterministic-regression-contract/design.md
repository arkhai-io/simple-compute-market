# Design

## Grounding

`docs/development/TESTING.md` defines four levels and places the harness outside
them, in a section that states its jurisdiction is contract validation and
finding production rather than a fifth level. The document's central rule is
that a test goes at the lowest level that can meaningfully prove the behaviour.

A generated regression is the first artifact to cross that boundary in the other
direction: produced by the harness, landing inside the hierarchy. The document
has no rule for it because nothing has crossed before.

## Decisions

### A regression declares what it cannot prove, in the artifact

The evidence class travels with the regression rather than sitting in
documentation about regressions.

The failure it prevents is specific and likely. A regression suite is fast and
green, and it protects behaviour originally found under concurrency against a
real provisioner. Six months later someone reports that concurrency is covered,
because the tests that cover it pass. The artifact is the only place that
statement can be contradicted at the moment it is made.

Rejected: a statement in `TESTING.md` alone. Correct and insufficient — the
document is read when someone is thinking about testing strategy, and the wrong
inference is drawn when someone is looking at a green suite.

### A recording is not a specification, and the evidence requirement is what separates them

A regression protecting a corrected defect carries fail-before/pass-after or
mutation sensitivity. Both establish the same thing: that the test fails when
the behaviour it protects is absent.

Without it, a generated regression asserts that the system does what it did,
which is true of a bug. The evidence requirement is the only mechanism that
distinguishes a captured fix from a captured defect, and it needs someone to
independently know which one it was — which is why a spec-derived deterministic
suite has to exist underneath. A regression suite is not a substitute for one.

Where neither method is practical, another focused demonstration may be accepted
and the substitution is recorded. An unrecorded substitution is indistinguishable
from an unexamined one.

### Representation is separate from execution

A regression declares normalized actions and expected outcomes. How they run is
an adapter. Hermetic is the default; a reviewed configuration may use a
controlled integration environment where fidelity justifies it.

The reason is not portability. It is that a regression which embeds its
execution cannot be re-run under a different adapter, so the question "does this
still hold against a real system" has no cheap answer. Keeping them separate
means a regression that normally runs hermetically can be run once against
something realer when there is reason to doubt it.

Rejected: recording exact command sequences. They capture incidental ordering,
temporary identifiers, and timing, none of which the behaviour depends on, and
all of which will make the regression fail for reasons unrelated to what it
protects.

### A regression is placed at the level that owns the behaviour it protects

Not a separate level, not a quarantined directory of generated tests.

A generated regression that lives apart from the tests protecting the same
behaviour is a second place to look and a second thing to keep current, and in
practice it becomes a directory nobody reads whose failures are assumed stale.

**This decides placement and not maintenance.** Which level a regression lands
in is settled here. Who repairs it when it fails for an unrelated reason is a
different question with real alternatives, and it stays open — see below. The
two are easy to conflate because "owned" reads naturally for both, and
conflating them would settle an architectural question on the strength of a
word.

The consequence of the placement decision is what makes the maintenance question
pressing: a generated regression sits among tests written by people who did not
write it, from a trace they cannot read, protecting behaviour found by a tool
they do not run.

### Sanitization is the same boundary as any other crossing

A regression derived from agent evidence passes through the allowlist projection
that governs every artifact leaving the private side. Not a lighter one because
it is a test fixture.

A fixture is exactly where a private identifier survives unnoticed: it is
committed once, read rarely, and looks like data.

### A regression from a passing run is kept, at a lower evidence class

The clear case is a corrected defect: fail-before, pass-after. A newly covered
journey that passed has no failure to demonstrate against, so the evidence
requirement has nothing to bite on.

**Decided:** yes, but at a lower evidence class that records it was never
observed failing. Worth revisiting once there is one, because the alternative —
only generating from defects — is simpler and may lose little.

## Open questions

### Who owns a generated regression after it lands?

It sits in the product's suite. It was generated from a harness trace the
product team cannot read. It protects behaviour discovered by a tool they do not
run. When it fails for an unrelated reason — a refactor, a renamed field — they
must decide whether it is still protecting anything.

Options: the harness owns it and regenerates it on demand, which requires the
harness to be runnable by whoever hit the failure. The product owns it outright,
which means accepting a test whose provenance is opaque. Or a generated
regression carries enough context to be maintained without its generator, which
is the most work and the only one that does not depend on someone's
availability.

Not resolved. It should be, before the first regression is generated rather than
when the first one breaks.

### What does semantic equivalence mean for reuse?

The generation side needs to know whether a new regression duplicates an
existing one. That requires identity over scenario, action, and finding, and it
is not obvious whether two regressions protecting the same finding through
different journeys are one or two.

Deliberately left to the private generation change, which is design phase for
this reason among others. Recorded here because the public representation has to
carry whatever identity the answer needs, and a representation designed without
it may not.
