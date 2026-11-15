---
tags: [engineering, testing]
---

# Test seams

Where a test reaches into the code it tests. A seam is a point the code's own
structure already offers — an injected collaborator, a factory, a control — so that a
test replaces or drives exactly what it means to, and keeps working while the code's
internal structure changes and its behaviour does not.

## Injected collaborators

Collaborators are injected, passed in through the constructor, and a unit test passes
its doubles the same way. A test never patches a module-level import around that
seam: with constructor injection as the natural seam, patching around it defeats the
seam's purpose and produces tests that break when the internal call structure
changes even though the behaviour did not.

## Composition boundaries

When a component receives a versioned contract, its unit tests inject a distinct
compatible object and assert object identity at each constructor boundary, rather
than patching the default resolver. Fail-closed cases belong at the composition root,
and assert that the persistence, network, and worker collaborators were never
constructed. The integration tests remain responsible for public behaviour and
persisted-state parity.

## A shared runtime is tested once

Where several consumers compose one shared runtime, the runtime's invariants are
tested once, in the runtime's own suite, against an in-memory store and injected
hooks; each consumer's tests then prove only its adapters, through the runtime
itself. A consumer test that re-implements the runtime's lifecycle locally tests the
duplication rather than the production composition. A message-protocol engine shared
by several services, for example, proves its ordering and recovery once, and each
service proves only how it decodes its terms and persists its effects.

## Pause the loop, then advance it explicitly

The discipline of [Deterministic tests](test-determinism.md) applies to a service's
own background loops, where the seam is a control rather than a callback. Each loop
offers a pause, and an explicit single step that works while the loop is paused, so a
test drives each transition instead of waiting for a timer. The production half of
that rule — that a manual cycle invokes the same handler as the timer — is
[Operator lifecycle controls](implementation.md#operator-lifecycle-controls).

Traps a new loop is worth checking for:

- **A loop with no pause is not paused.** A loop running on its own timer, with no
  gate, beside a test that believes everything is stopped claims the same rows the
  test is advancing. "Everything is a double, so nothing can take wall time" is true
  of the work and false of the coordination.
- **A "run one cycle" control is not necessarily a step.** A loop that claims a row
  before polling its provider and keeps that claim on a pending answer, to space its
  next poll, reaches nothing on a further cycle inside the claim, so any number of
  such cycles is still zero advances. A step for tests releases the caller's own
  claims first. If a test needs several steps to make one transition, suspect the
  step rather than adding a sleep.
- **A loop that sleeps its interval is held late.** A loop gated at the top of each
  cycle but waiting with a plain sleep reaches its gate only when the sleep ends, so
  a pause landing in a long interval outlasts the pause's bounded wait. A timer loop
  waits through something that returns on a pause request.
