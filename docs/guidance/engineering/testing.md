---
tags: [engineering, testing]
---

# Testing

How a test is placed and what it must show. The levels themselves, and what each
may prove, are [Test levels](test-levels.md).

## Where a test goes

- Put a test at the lowest level that can meaningfully prove the behaviour
  ([Test levels](test-levels.md)).
- Prefer observable seams, injected dependencies, and deterministic test controls
  over sleeps or brute-force patching ([Test seams](test-seams.md),
  [Deterministic tests](test-determinism.md)).
- A difficult-to-test failure is evidence to consider a testability refactor, not
  permission to bypass the boundary.

## Diagnosing a failure

When a failure cannot be reproduced locally, report useful diagnostic steps, and
identify any design decision needed before changing behaviour.

## Registration and traffic are different proofs

A test that a connection, proxy, or route was admitted also carries traffic through
it. A peer can report a registration it cannot serve — a tunnel listed as running
whose remote port reaches nothing, an address delivered that routes elsewhere — and
only bytes sent end to end show the admission did what it claims. A reverse proxy's
admission test, for example, sends bytes from the proxy's public port to a listener
behind its client, and a proxy that outlives a reload carries traffic on a held
connection and on a new one.

## Work is not complete because its own tests pass

A unit of work is not complete because the tests written with it pass. The tier that
runs the whole system end to end catches what no in-process test reports: a wire
contract whose two sides disagree, a service that starts cleanly and cannot do its
work, a configuration gap no unit test can see ([Test levels](test-levels.md),
"System tests").
