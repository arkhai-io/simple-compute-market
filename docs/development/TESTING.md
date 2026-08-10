# Testing Strategy

This document defines the testing conventions for this repository. It
exists to give every contributor — human or AI — a consistent mental
model of what each test level is responsible for, what it is explicitly
not responsible for, and how the levels relate to each other. Put a new
test at the lowest level that can meaningfully prove the behavior in
question; see `AGENTS.md`'s "Tests and diagnostics" for the underlying
rule this document elaborates.

Read this alongside `docs/development/ARCHITECTURE.md` (system shape)
and `openspec/README.md` (documentation placement). This document
describes current testing practice, the same way `ARCHITECTURE.md`
describes current system architecture — it is not a changelog of how
testing conventions were introduced, and it should be corrected in place
when practice changes rather than accumulate historical commentary.

## Four-Level Hierarchy

### 1. Unit Tests

**What they cover:** A class or function in isolation. A unit test
instantiates one class, passes mocked collaborators for its injected
dependencies, and asserts on the return value or side effects of a
specific method.

**What they do not cover:** Orchestration. If a function's sole purpose
is to call other functions in sequence, that function does not have
meaningful unit tests — the correctness of the sequence is an
integration-test concern. The final abstraction before an external
boundary (a database write, a subprocess invocation, an HTTP call) is
similarly not meaningful to unit test in isolation; its behavior is
validated by integration tests against the real boundary or a
well-defined mock of it.

**Mocking convention:** Use `unittest.mock.MagicMock`/`AsyncMock` for
injected collaborators, passed in via the constructor. Do not patch
module-level imports — the dependency-injection composition pattern
used throughout this repository makes constructor injection the natural
seam; patching around it defeats the purpose of the seam and produces
tests that break when internal call structure changes even though
behavior didn't.

### 2. Integration Tests

**What they cover:** End-to-end request → response paths with the full
application stack running (the real app, a real database, the DI
container wired) and a controlled mock only at the external I/O
boundary. Orchestration logic, background job processing, retry
behavior, and error propagation are validated here, not in unit tests.

**What they do not cover:** Every edge case of data transformation
logic — that belongs in unit tests. An integration test needs one
representative case per external-mock behavior, not exhaustive
parametrization.

**External boundary definition:** Any I/O that crosses a process
boundary — a subprocess invocation, a call to a service this codebase
doesn't own, a blockchain RPC call. Mock at the point this codebase's
own code wraps that boundary, not deeper.

**Test setup pattern:** Use `httpx.AsyncClient` with `ASGITransport`
against the real application instance, injected via the service's
canonical typed-client constructor (`FooClient(transport=...)`).
Override DI container providers for the specific collaborator being
mocked before the test and restore them after.

**Typed client contract verification — the "no raw calls" rule:**
Integration tests call a service's canonical typed client methods
directly against the in-process app, not raw HTTP. Route strings,
request body shapes, and response parsing are owned by the client;
happy-path tests should not construct requests by hand. If an API
renames a field or changes a route, the typed client should raise its
own client error and the test should fail immediately — a test that
builds its own request dict will not catch that, which is exactly the
kind of interservice mismatch that mocked-boundary unit tests cannot
catch either. This is the single most important rule for the layer
where real bugs are most often found in review: an integration test
that bypasses the typed client to make assertions easier has quietly
stopped testing the client contract at all.

Two narrow exceptions are permitted:

1. **Rejection-path tests** — testing server-side validation of inputs
   the typed client deliberately refuses to construct (asserting a 422
   on a malformed body the client's own request model would reject
   before it ever reached the HTTP layer). These verify the *server's*
   validation boundary, not the client's, and must only assert on
   status codes, never on response body field names, and must be
   clearly commented as rejection-path tests.
2. **Service-internal state setup** — inserting DB rows directly to
   establish precondition state that cannot be expressed through any
   HTTP API endpoint. This is not an HTTP call at all; it is standard
   test-setup, and should be preferred only when the state genuinely
   isn't reachable through an API — prefer creating precondition state
   through the HTTP API where feasible, so integration tests stay
   honest about what the API contract actually supports.

Any other use of a raw HTTP call in an integration test is a gap: either
add a method to the canonical client, or restructure the test. A comment
like "not yet a client method" is a deferred-debt marker, not a
permanent exemption.

**Sync/async client parity:** When a client package exposes both async
and sync variants, the owning service's unit suite should include a
small contract test comparing public method names and signatures across
both. A new client method must be added to both in the same change. This
guardrail belongs with the service's tests, not the client package,
because the service owns the contract-validation boundary — it does not
substitute for integration tests that exercise the methods through real
controller routes.

**Async test discipline — no sleeps:** Tests exercising a background
job-processing loop must never use `asyncio.sleep` or a bare timeout
race to wait for a side effect — this produces intermittent failures.
Use an explicit test seam instead: an injectable callback invoked at the
point the test needs to synchronize on (for example,
`AsyncJobQueue.__init__`'s `on_job_started: Optional[Callable[[str], None]]`,
`None` in production and zero-cost there), set an `asyncio.Event` from
the callback, and `await asyncio.wait_for(event.wait(), timeout=...)`
before proceeding. If no such seam exists yet where a test needs one,
adding it is the correct fix, not a sleep.

### 3. Smoke Tests (Deployment Validation)

**What they cover:** Stateless, idempotent verification that a deployed
stack is wired correctly — services can reach each other, authentication
is enforced, health endpoints respond, expected routes exist.

**What they do not cover:** Service semantics. By the time a smoke test
runs, semantics have already been validated by integration tests. A
smoke test verifies that a health endpoint returns 200 and that a
protected endpoint returns 401 without valid credentials — it does not
submit a real job and poll for completion.

**Current location:** `e2e-tests/tests/smoke/`, run as Helm test hooks
in Kubernetes (`helm/templates/tests/`, per-chart `templates/tests/`
directories).

### 4. System Integration Tests (End-to-End)

**What they cover:** Cross-service contracts — scenarios that require
two or more services to interact over the network to produce a
meaningful result.

**What they do not cover:** Anything already covered by the three levels
above. These tests are expensive to run and brittle to maintain; they
should be minimal in count and cover only the cross-service contract,
not any one service's internal logic.

**Current location:** `e2e-tests/tests/e2e/`.

<!-- Confirmed current and real (openspec/specs/test-compatibility/spec.md's
"Dependency-aware e2e stages" and "Exact e2e state dependencies"
requirements): downstream e2e stages declare which prior stage's state
they consume via `require_state`, using one exact producer/consumer
field name per staged value, and skip with the missing field name
rather than failing on an unrelated symptom -- see
`e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py` and
`e2e-tests/tests/e2e/roles/README.md`. The specific scenario structure
beyond that skeleton (which stages exist today, the dry-run/advance
pattern's current shape, specific test file layout) still needs
confirming before being restated here in detail. -->

The e2e test pod cannot import service internals — it uses typed
clients, explicit test controllers, and stage/event APIs over HTTP, the
same "no raw calls" discipline integration tests follow. Design new
observability seams for e2e-visible behavior accordingly.

## Agent-Driven Capacity Harness

The four levels above all run inside this repository against this
repository's code. The agent-driven capacity harness in
`tools/issue-discovery` is not a fifth level and does not belong in the
jurisdiction table: it describes runs performed *outside* the repository
by an external orchestrator, and validates their recorded results after
the fact.

Its jurisdiction is contract validation and finding production — whether
a declared capacity scenario is admissible, whether a supplied result
correlates through the current reservation and fulfillment lifecycle,
whether an outcome counts as expected scarcity, and what sanitized
finding and issue plan follow. It performs no market, wallet, cloud,
host, provisioning, VM, or GPU action, and makes no authenticated GitHub
call. The permanent contract lives in
`openspec/specs/test-compatibility/spec.md`'s "Agent-driven VM capacity
contracts are finite and non-executing" requirement.

**Where to put a new test.** The rule at the top of this document still
applies — the lowest level that can meaningfully prove the behavior. A
scenario about the product's own reservation, scheduling, or scarcity
behavior belongs at the level that owns it, usually integration or
system integration, not in this harness. The harness earns a test only
when the behavior under test is the harness's own: schema admissibility,
result evaluation, fingerprint stability, privacy refusal, or planning
determinism.

**How it is validated.** By its own locked suite, which is excluded from
the default Tests workflow because its bootstrap tests inspect the host
system. Run it explicitly:

```bash
cd tools/issue-discovery
uv --no-config run pytest -q
```

The suite is verified on CPython 3.12 and 3.14, and its result codes do
not vary across that range. See
`docs/development/ISSUE_DISCOVERY.md`'s "Privacy and validation
responsibility" for the input bounds this depends on.

## Coverage Contract Between Levels

Each level has a defined jurisdiction. Duplicating coverage across
levels creates maintenance burden without a corresponding safety
benefit — a change should only need its assertions updated in one
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

## Contract Fixtures

A **contract fixture** is a pair of functions — `build_*()` and
`validate_*()` — that define the canonical shape of a message at a
package boundary. They are shared between the producer's tests (which
call `validate_*` to assert real code emits the agreed shape) and the
consumer's tests (which call `build_*` to produce mock inputs of exactly
that shape). When the boundary changes, both sides break at once,
instead of the consumer silently mocking a shape the producer no longer
emits.

**When to add one:** A boundary earns a contract fixture when *both*
its producer and consumer have unit or integration tests. A
consumer-only mock with no corresponding producer test should stay as a
local inline value — a contract fixture without producer-side
enforcement just documents an agreement nothing actually checks.

**`build_*()`** constructs a minimal but complete canonical instance,
using keyword arguments with sensible defaults so a test can override
only the fields it cares about. Non-deterministic fields (timestamps,
generated IDs) get fixed sentinel values in `build_*` and range/type
assertions in `validate_*` — never equality checks, which produce
brittle failures when an incidental field shifts.

**`validate_*()`** asserts structural and semantic constraints on a
value produced by real code: field presence, type, and any invariant
the consumer depends on. It does not check incidental fields the
consumer ignores.

**Where they live — import direction always flows producer → consumer:**

- **Same-package boundary** (producer and consumer share a package):
  `tests/fixtures/<module>.py` within that package, importable as
  `tests.fixtures.<module>` by any test in the package. Example:
  `domains/vms/storefront/tests/fixtures/publish.py`.
- **Cross-package boundary** (the consumer is a separate, higher-level
  package): `src/<package_name>/fixtures/<module>.py` inside the
  producer's own source package. Because the producer is already
  installed as a wheel in consumer packages, this needs no path
  configuration — the import mirrors the client import it sits next to.
  Example: `core/storefront-client/src/storefront_client/fixtures/escrow.py`,
  imported as `from storefront_client.fixtures.escrow import build_claim_response`
  alongside `from storefront_client import SyncStorefrontClient`.

If the producer has no unit tests yet, create the `fixtures/` subpackage
anyway with dormant `validate_*` functions — they document the contract
and give a future producer test an immediate hook. Mark a dormant
validator's module docstring with which test file is expected to call
it once the producer gains coverage.

## Test File Layout

A service's tests split into `unit/` and `integration/` subdirectories
under its own `tests/` root, matching the four-level hierarchy above.
System-level tests live in the separate `e2e-tests` package, itself
split into `unit/` (its own helper logic), `smoke/`, and `e2e/`.

## Boundary-Change Validation

Moving or renaming a contract at a package boundary needs more than
relocated unit tests. Validate:

- package build and wheel contents;
- typing markers and static type checks where the contract moved;
- allowed dependency direction, including `TYPE_CHECKING` imports (see
  `AGENTS.md`'s "Package and dependency discipline");
- old import removal, or an explicit, deliberate compatibility path;
- every changed consumer's unit and integration suites, not just the
  producer's;
- composition startup and duplicate-registration checks;
- deterministic, idempotent retry behavior;
- observable lifecycle events verified without arbitrary sleeps (see
  "Async test discipline" above).

## Cross-Language Contract Conformance

Where the same protocol has independent implementations in more than one
language, each implementation MUST reproduce one shared, data-driven
conformance trace rather than each maintaining its own hand-written
assertions of the same behavior. Keeping the trace in data, not in each
language's test code, is what makes "identical behavior across
languages" a checkable claim rather than an assumption.

**Current example:** the API-credits gating middleware's Python
(reference implementation), TypeScript, and Rust ports all replay
`domains/apicredits/middleware/conformance/session.json` — one recorded
session of requests against the gate, with each step asserting the
allow/deny decision, the deny body's machine-readable error code,
whether a `purchase` pointer is present, and call counts against the
stateful collaborators the step is meant to exercise (cache-hit
skipping, zero-calls-on-known-exhaustion). See
`domains/apicredits/middleware/conformance/README.md` for what each step
field asserts, and the runners at
`domains/apicredits/middleware/python/tests/conformance_runner.py`,
`domains/apicredits/middleware/typescript/test/conformanceRunner.ts`,
and `domains/apicredits/middleware/rust/tests/conformance.rs`.

## Offline Review Validation

Review validation packages a scoped wheelhouse rather than copying a
virtual environment or sharing a package cache, so an offline reviewer
can run each affected project's real `make test` target with network
and Python downloads disabled. The scope resolver accepts an explicit
project list or a review manifest, and otherwise maps a Git diff to
repository-owned project roots and applies impact-expansion rules from
there. Each project keeps its own locked third-party requirements rather
than being forced into one synthetic shared environment. A project's own
`Makefile` must keep its interpreter selection configurable so the
review environment can use the wheelhouse's declared Python version.

**Current implementation:** `make review-wheelhouse` (scope preview via
`make review-wheelhouse-scope`, controlled by `REVIEW_PROJECTS`,
`REVIEW_SCOPE_FILE`, or `BASE_REF`), which rebuilds wheels, refreshes
scoped lockfiles (`scripts/refresh-review-locks.py`), and bundles the
result via `scripts/package-review-wheelhouse.sh`.
