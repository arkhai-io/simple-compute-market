## Context

Three storefronts sign responses, and all three sign them the same way: an
authentication step deposits its result on the request, and a wrapper further
out reads that deposit and signs whatever the route produced. The VM
storefront deposits `AuthenticatedPrincipal` at
`request.state.marketplace_authenticated`; the bare metal storefront deposits
`_ResponseAuthContext` at `request.state.marketplace_response_auth`; the
API-credits storefront follows the VM shape.

That design makes a refusal during authentication unsignable: there is no
deposit, so the wrapper returns the response bare. Both wrappers say so
explicitly — `if context is None: return response`. Neither is a bug in
isolation; together they mean the caller cannot read the one answer that tells
it what to fix.

The administrator path in the VM storefront already diverged from this shape.
`_authenticated_error_response` signs from the *contract* — the operation and
resource the route derived — plus the request identity from the headers,
independent of whether trust succeeded. That is the model to generalize.

Established by reproduction, not assumed: a buyer status poll is refused
`403` and the answer carries no `X-Market-*` response headers, so
`AuthenticatedResponse.model_validate` fails on the absent timestamp before
any verification runs. That is precisely what the real lane reported as
`HTTP 403 carried no response authentication`.

## Goals / Non-Goals

**Goals:**

- A caller that pins the storefront principal can read every refusal the
  storefront gives it on an authenticated route.
- The route's contract, not the authentication result, is what a refusal is
  bound to — so a refusal raised before trust is signable.
- Wire-level coverage for the hosted settlement routes, since controller-level
  tests structurally cannot observe response signing.

**Non-Goals:**

- Changing what is refused. This change makes refusals readable; it does not
  loosen, tighten, or reclassify any authentication decision.
- Changing the refusal wording. `_verification_error` already maps each code to
  a sentence; those sentences become readable, and are not rewritten here.
- Signing responses on unauthenticated routes. A public route has no caller
  identity to bind and gains nothing.
- Diagnosing the underlying `403` on the hosted settlement lane. That is what
  this change makes possible, not what it does.

## Decisions

**D1 — Bind refusals to the route contract, not to the authentication result.**
Every path that signs already computes an operation and resource *before*
authenticating: `_buyer_response_contract` for buyer routes,
`ListingMutation` for seller mutations, `AdminRouteContract` for admin routes.
Those are derived from the request line, not from the caller's claims, so they
are available whether or not the caller is trusted. The request identity comes
from the `X-Market-Request-ID` header, which the caller chose and will compare
against — a caller that sent no request identity cannot be lied to about one.

Alternative considered and rejected: deposit a partial authentication result
before verifying, so the existing wrapper finds something. That makes an
unverified principal indistinguishable from a verified one at every later
reader, which is a far worse failure than an unreadable refusal.

**D2 — An unbindable refusal stays unsigned.** If there is no request identity
or no recognized contract, there is nothing to bind. Signing a response over
an invented request identity would produce an answer that verifies against
nothing the caller sent, which is worse than an unsigned one: the caller would
have to reject it anyway, having spent trust to find out. The administrator
path already makes exactly this call and returns bare in that case.

**D3 — Sign refusals that escape the route, too, not only those raised during
authentication.** The VM buyer path already signs post-authentication
responses, including error status codes, because `_verify` deposits before the
route can fail. But a refusal raised inside `_verify` itself — the cached
principal mismatch, or any `AuthError` — escapes as an `HTTPException` that
FastAPI renders after the deposit would have happened. Handling both means the
wrapper signs on the way out regardless of where the status came from, using
the deposit when it exists and the contract when it does not.

**D4 — Do not record a replay outcome for a refusal that never authenticated.**
The replay journal exists so an exact retry resolves to the recorded outcome
of a dispatched operation. A request refused during authentication reserved
nothing and dispatched nothing, so there is no outcome to record, and writing
one would make the next honest attempt with the same request identity resolve
to a refusal it never earned. Signing and recording are separate concerns and
this change touches only the first.

**D5 — Test at the wire, through the mounted application.** The defect is
invisible to a controller-level test by construction: calling
`SettlementsController.status(...)` directly never runs the middleware that
signs. New coverage signs requests exactly as `core_buyer` signs them and
verifies responses exactly as `core_buyer` verifies them, so a passing test
means a real buyer completes the exchange. The existing controller tests stay
— they cover authorization inputs precisely, which the wire tests do not.

## Risks / Trade-offs

- **A signed refusal is a signed statement about an untrusted caller's
  request.** It binds the operation and resource the caller named and the
  status, and its body is the existing refusal sentence. It confirms the
  storefront's expectation of the route, which the caller already knows from
  having called it, and discloses nothing about other callers or state.
- **A refusal now costs one signature.** Signing is local Ed25519 with no
  chain or network dependency, and a refused request has already paid for
  proof verification. An unauthenticated flood is refused before this point
  by the contract lookup, which recognizes nothing and returns bare.
- **Three implementations, one requirement.** The API-credits and bare metal
  storefronts have their own wrappers, and a fourth storefront would have to
  remember. Consolidating the wrappers is the real fix and is out of scope
  here; the spec requirement, not the shared code, is what binds the next one.
