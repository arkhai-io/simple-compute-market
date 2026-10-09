# Middleware conformance fixtures

`session.json` is the shared behavioral contract for the API-credits
gating middleware. All three implementations reproduce this recorded
session exactly: Python (`../python`, the reference, which also gates
the e2e sample service), TypeScript (`../typescript`), and Rust
(`../rust`). Keeping the trace in data (not in each language's test
code) is what makes "identical behavior across three languages" a
checkable claim rather than a hope.

## What a step asserts

Each step feeds one request's `Authorization` header to the gate and
checks:

- `expect.allowed` / `expect.status` — the gate's decision (allow → the
  request reaches the app; otherwise the deny status).
- `expect.error` — the machine-readable code in the deny body
  (`missing_api_key`, `invalid_api_key`, `key_revoked`,
  `insufficient_credits`). Clients dispatch on this, not the status.
- `expect.purchase` — whether the deny body carries the `purchase`
  pointer (present on exhaustion/revocation so a client can re-enter the
  buy loop; absent on missing/invalid-key denials, which are not a
  credit problem).
- `verify_calls` / `consume_calls` — how many calls to the tokens
  service this single step triggered. These pin the two stateful
  behaviors: a repeated key skips `verify` (the short-TTL cache), and a
  key already known-exhausted denies with **zero** consume calls.

## The scripted service

`service.verify[key_id]` and `service.consume[key_id]` are ordered
response lists; a harness replays them in order and repeats the last
entry once exhausted. `verify` responses are always HTTP 200 (the real
service returns validity in the body); `consume` responses carry their
own `status` (200 on success, 402 on `insufficient_credits`). The gate
runs with `flush_interval_seconds = 0`, so every charge is a
synchronous consume and the call trace is deterministic.

## Implementing a harness

1. Stand up a mock credits service that records `verify`/`consume` calls
   per key and replays the scripted responses, and drive the **real**
   HTTP client against it (not a stub) so request shape and response
   parsing are validated too. The three reference harnesses do this with
   `httpx.MockTransport` (Python) and a real in-process HTTP server
   (`node:http` in TypeScript, `axum` in Rust).
2. Build the gate from `config`.
3. For each step: snapshot the call counters, call the gate with the
   step's `Authorization`, then assert the decision and the per-step
   call deltas.

The reference harnesses (identical structure in each language):

- Python — `python/tests/conformance_runner.py`
- TypeScript — `typescript/test/conformanceRunner.ts`
- Rust — `rust/tests/conformance.rs` (+ `rust/tests/common/mod.rs`)

## Scope: this fixture does not cover service authentication

`session.json` pins the gate's *inbound* contract — the end user's
`Authorization` header, the allow/deny decision, the deny body, and the
verify/consume call counts. It says nothing about how a middleware
authenticates itself to the credits service on the way out.

That matters, because the two are no longer the same across
implementations. The credits service authenticates every non-health route
against a signed marketplace identity v2 envelope and signs every
response, including refusals. It accepts signed requests **or** the legacy
`X-Admin-Key` shared secret, never both, chosen by its own configuration.

- **Python** signs (`apicredits_middleware.signing`), gated behind the
  `signed` extra. It works against either service configuration.
- **TypeScript** and **Rust** send the shared secret only. They work
  against a service that has not enabled signed authentication, and are
  refused by one that has — including the compose topology in this
  repository, where it is enabled.

So all three still reproduce this fixture exactly, and are still
behaviourally identical in everything it asserts. They are not
interchangeable deployments.

Closing that gap needs a validation path for the TypeScript and Rust
clients before signing support, because neither has an end-to-end scenario:
signing code for them could pass its own language's unit tests, satisfy
this fixture, and still be refused by a real service — which is precisely
the failure this fixture cannot see.
