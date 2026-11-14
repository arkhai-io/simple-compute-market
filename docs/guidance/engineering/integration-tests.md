---
tags: [engineering, testing]
---

# Integration tests

Rules for application integration tests, which drive a service's real application
in process ([Test levels](test-levels.md), "Integration tests").

## No raw calls: the typed client is the contract

Integration tests call a service's canonical typed client methods directly against
the in-process application, not raw HTTP. Route strings, request body shapes, and
response parsing are owned by the client; happy-path tests do not construct requests
by hand. If an API renames a field or changes a route, the typed client raises its
own client error and the test fails at once — a test that builds its own request
will not catch that, which is exactly the kind of interservice mismatch that unit
tests against a doubled boundary cannot catch either. This is the most important rule
for the level where real bugs are most often found in review: an integration test
that bypasses the typed client to make assertions easier has quietly stopped testing
the client contract at all.

Two narrow exceptions are permitted:

1. **Rejection-path tests** — testing the server's validation of inputs the typed
   client deliberately refuses to construct, such as asserting a 422 on a malformed
   body the client's own request model would reject before it reached the HTTP
   layer. These prove the server's validation boundary, not the client's; they
   assert only on status codes, never on response body field names, and are
   commented as rejection-path tests.
2. **Service-internal state setup** — inserting database rows directly to establish
   a precondition no API can express. This is not an HTTP call at all but ordinary
   test setup, preferred only when the state genuinely is not reachable through an
   API; where it is, the test creates it through the API, so the tests stay honest
   about what the API contract supports.

Any other raw HTTP call in an integration test is a gap: either add a method to the
canonical client, or restructure the test. A comment such as "not yet a client
method" marks deferred debt, not a permanent exemption.

## Sync and async client parity

When a client package exposes both asynchronous and synchronous variants, the owning
service's unit suite includes a small contract test comparing public method names and
signatures across both, and a new client method is added to both at once. The guard
belongs with the service's tests, not the client package's, because the service owns
the contract-validation boundary; it does not substitute for integration tests that
exercise the methods through the real routes.
