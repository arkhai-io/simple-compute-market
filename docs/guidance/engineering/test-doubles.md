---
tags: [engineering, testing]
---

# Test doubles

A test double stands in for a service, a provider, or a driver the code under test
calls. What it may answer, and what a test against it proves, follow from what it
stands in for.

## A double mirrors its producer

A double of a service mirrors its producer's API — routes, authentication,
admission, read authorization, idempotency, and error codes — unless there is a
compelling reason to deviate, and states any deviation. A double that answers
differently from its producer proves only that a client agrees with the double.
Where a double wraps the producer's own engine, it serves what that engine serves,
and narrows its claims rather than its behaviour.

A double takes its producer's decisions — a dispute authority's rulings, a provider
job's outcome — as answers a scenario programs, and never re-implements the
producer's decision logic: a rules engine held to the producer's traces drifts
whenever the producer revises its rules, and a test against a double proves the
client's handling of a decision, not the decision's arithmetic, which stays the
producer's to qualify.

## A double answers as its producer would

A double's default output is what the real producer emits for the request: a
provisioning double returns the output the shipped job would print for that job's
own parameters, in the same format, so the real reader runs on it and the linkage
between an output and its request is exercised as in a real run. A test that needs
an output the producer would not emit for its request states it explicitly, and
keeps to the level of the code that reads it.

## Controls are deterministic steps

A double's test controls — rules a scenario installs, faults it injects, a clock it
moves — are each a deterministic step: nothing delays, races, or runs in the
background. A fault never applies to a control route or to the double's health
check, so a test's cleanup can always remove the rule that caused it.

## Shared stages never depend on a double

Where one scenario runs against a double in one environment and against the real
driver in another, a stage shared by both never touches a control only the double
has. Holding a job at a double's gate, releasing it, or confirming the double is in
use is a stage of its own, declared only where the double runs; a stage that would
both advance the scenario and touch such a control is split at the control, so its
other part stays shared. A control answered by a real driver with a no-op would
report a hold that never happened, and a shared assertion would hold under one driver
and be vacuous under the other.
