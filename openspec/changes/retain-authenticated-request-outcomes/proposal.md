## Why

`openspec/specs/marketplace-identity/spec.md` requires that an authenticated
authority, on an exact retry of a request it has already seen, *"returns or
resumes the recorded operation outcome without executing a conflicting
mutation."*

`SiteAuthMiddleware` implements half of that. It reserves
`(principal, request_id)` before dispatch and rejects changed reuse with a
409, but its replay store keeps no outcomes, so it has nothing to return on an
exact retry. Conformance is therefore delegated to handlers, and most of them
satisfy it: a credits consume deduplicates on an idempotency key carried
inside the signed body, a revoke is idempotent by construction, an issuance is
unique per fulfillment id. Each resolves an exact retry to the recorded
outcome in the handler, which is where the outcome actually lives.

`repair-storefront-alkahest-configuration` made that delegation explicit
rather than assumed: `SiteRouteContract.exact_retry_safe` declares per route
whether an exact retry may be re-executed, and the middleware refuses one on a
route that says it may not. `credits_key_adjust` is the first such route --
it applies a relative delta and records no idempotency key, so re-executing
would apply the adjustment twice.

That closed the safety half: no conflicting mutation runs. It did not close
the requirement. A refusal is not the recorded outcome, so a caller that lost
its response still cannot learn what happened, which is the situation the
requirement exists to resolve.

## What changes

- A replay store that retains the outcome of an authenticated request and
  returns it on exact reuse, so an exact retry resolves rather than being
  refused. Changed reuse remains the 409 case.
- A durable provider for services that must honour the requirement across an
  authority restart. The default store is process-local, which cannot satisfy
  a contract about resuming an outcome the caller never received: a restart
  between the mutation and the retry loses exactly the record the caller needs.
  API credits is the first service in that position.
- `credits_key_adjust` gains an idempotency key, as consume has, so its exact
  retry resolves in the handler like its siblings rather than being refused at
  the boundary. That needs a column on `credit_grants`, which is why it is here
  and not in the change that declared the route unsafe.
- Retire `exact_retry_safe=False` as routes stop needing it. The field should
  end up documenting nothing, and a route still carrying it after this change
  is a route whose outcome is not retained.

## Design questions this owes

None of these is settled, and picking one shapes the rest:

- **What is a recorded outcome.** Status and body is the obvious answer and is
  wrong for a streaming response. It may be that only routes returning a
  complete JSON body are eligible, and that eligibility is declared the way
  `exact_retry_safe` is now.
- **Where retention happens.** The middleware can buffer a response body,
  which it already does to sign it, so the mechanism exists. Whether the
  *store* should hold bodies, or hold a reference the handler writes, is a
  question about who owns the record.
- **How long an outcome is kept, and what happens after.** An expired outcome
  makes an exact retry indistinguishable from a first attempt, which is the
  current behaviour and the thing being fixed. Expiry needs an answer that is
  not "fall back to re-executing".

## What this change does not cover

The `(principal, request_id)` reservation, changed-reuse rejection, and skew
enforcement, all of which already conform.
