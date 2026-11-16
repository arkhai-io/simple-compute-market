---
tags: [repository, testing]
---

# Contract conformance

How this repository's independent implementations of one protocol are held to it.

## Cross-language contract conformance

This repository's independent implementations of one protocol are held to
[`conformance-tests.md`](../engineering/conformance-tests.md).

**Current example:** the api family's bearer gate — the Python
`arkhai-api-gate` (reference implementation) and the API-credits
TypeScript and Rust middlewares — all replay
`kit/api/gate-ports/conformance/session.json` — one recorded
session of requests against the gate, with each step asserting the
allow/deny decision, the deny body's machine-readable error code,
whether a `purchase` pointer is present, and call counts against the
stateful collaborators the step is meant to exercise (cache-hit
skipping, zero-calls-on-known-exhaustion). See
`kit/api/gate-ports/conformance/README.md` for what each step
field asserts, and the runners at
`kit/api/gate/tests/conformance_runner.py`,
`kit/api/gate-ports/typescript/test/conformanceRunner.ts`,
and `kit/api/gate-ports/rust/tests/conformance.rs`.
