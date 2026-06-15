# Middleware conformance fixtures

`session.json` is the shared behavioral contract for the API-tokens
gating middleware. Python ships first and gates the e2e sample service;
TypeScript and Rust follow, and each must reproduce this recorded
session exactly. Keeping the trace in data (not in each language's test
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

1. Stand up a mock tokens service that records `verify`/`consume` calls
   per key and replays the scripted responses (HTTP-level mock — e.g.
   `httpx.MockTransport` in Python, `nock` in TS, `wiremock`/a tiny
   in-process server in Rust). Driving the real HTTP client, not a stub,
   is the point: it validates request shape and response parsing too.
2. Build the gate from `config`.
3. For each step: snapshot the call counters, call the gate with the
   step's `Authorization`, then assert the decision and the per-step
   call deltas.

The Python reference harness is
`domains/apitokens/middleware/python/tests/conformance_runner.py`.
