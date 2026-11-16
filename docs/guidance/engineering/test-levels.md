---
tags: [engineering, testing]
---

# Test levels

Tests belong at the lowest level that can prove the behaviour: unit, integration,
smoke, and system. Each level defends the narrowest observable contract appropriate
to it, and no level relies on system tests alone for behaviour it could prove itself.
Each has a defined jurisdiction, stated below with what it covers and what it does
not, and the table at the end divides the concerns between them.

## Unit tests

**What they cover:** a class or function in isolation. A unit test instantiates one
class, passes test doubles for its injected dependencies, and asserts on the return
value or side effects of a specific method ([Test seams](test-seams.md)).

**What they do not cover:** orchestration. If a function's sole purpose is to call
other functions in sequence, that function has no meaningful unit tests — the
correctness of the sequence is an integration-test concern. The final abstraction
before an external boundary (a database write, a subprocess invocation, an HTTP
call) is similarly not meaningful to unit test in isolation; its behaviour is proven
by integration tests against the real boundary or a well-defined double of it.

## Integration tests

**What they cover:** request-to-response paths with the full application stack
running — the real application, a real database, its dependency container wired —
and a controlled double only at the external boundary. Orchestration, background job
processing, retry behaviour, and error propagation are proven here, not in unit
tests.

**What they do not cover:** every edge case of data transformation, which belongs in
unit tests. An integration test needs one representative case per behaviour of the
external double, not exhaustive parametrization.

**The external boundary:** any I/O that crosses a process boundary — a subprocess
invocation, a call to a service the codebase does not own, a blockchain RPC call. A
test doubles it at the point the codebase's own code wraps that boundary, not deeper.

Integration takes three forms, each named by what it runs:

- **Application integration** drives the running application in process, through
  its typed client ([Integration tests](integration-tests.md)).
- **Library integration** drives a library's public API against the real storage it
  owns — a real embedded database, say — with collaborators it does not own
  injected, and no application. A library has no application, so this is what
  integration means for it. Such tests prove durable behaviour a unit test with
  doubled collaborators cannot: transaction boundaries, locking, and
  independent-session concurrency. They do not replace the application integration
  tests of a service composing the library, which remain the tests of that
  service's wire contract. A service's migration test with no application — its
  migration chain against real storage — is library integration too. A
  library test that exercises a real database but sits among the unit tests moves to
  the integration tests when it is next touched.
- **External-process integration** runs real external processes the test starts,
  such as a proxy and its client. It is skipped in the default suite where their
  binaries are absent, and run in a gate that fails on a skip.

## Smoke tests

**What they cover:** stateless, idempotent verification that a deployed stack is
wired correctly — services can reach each other, authentication is enforced, health
endpoints respond, expected routes exist.

**What they do not cover:** service semantics. By the time a smoke test runs,
semantics have already been proven by integration tests. A smoke test verifies that
a health endpoint answers 200 and that a protected endpoint answers 401 without
valid credentials; it does not submit a real job and poll for completion. A smoke
check that writes state belongs in an integration test instead.

## System tests

**What they cover:** cross-service contracts — scenarios that need two or more
services to interact over the network to produce a meaningful result
([System tests](system-tests.md)).

**What they do not cover:** anything already covered by the three levels above.
These tests are expensive to run and brittle to maintain; they are minimal in count
and cover only the cross-service contract, not any one service's internal logic.

## Coverage between the levels

Duplicating coverage across levels creates maintenance burden without a
corresponding safety benefit: a change should need its assertions updated in one
place.

| Concern | Unit | Integration | Smoke | System |
|---|---|---|---|---|
| Data transformation / parsing logic | ✅ exhaustive | one happy path | ❌ | ❌ |
| Request/response model validation rules | ✅ exhaustive | ❌ | ❌ | ❌ |
| Orchestration / job lifecycle | ❌ | ✅ exhaustive | ❌ | ❌ |
| Retry / backoff arithmetic | ✅ | one case | ❌ | ❌ |
| Auth middleware enforcement | ❌ | ✅ | one case | ❌ |
| Client ↔ API contract | ❌ | ✅ | ❌ | ❌ |
| Service-to-service wiring | ❌ | ❌ | ✅ | ❌ |
| Cross-service business flow | ❌ | ❌ | ❌ | ✅ |

## Aggregate test targets

A build target that aggregates several projects' tests runs every included project's
default tests. A project's own target stays useful for focused work, but the
aggregate's contract is complete coverage, not a curated subset.
