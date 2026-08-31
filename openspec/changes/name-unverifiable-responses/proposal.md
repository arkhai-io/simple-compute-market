## Why

A client that refuses a response it cannot authenticate says only that the
response was "malformed or legacy". That sentence is produced by constructing
the authentication record out of response headers and failing, which happens for
every response that carries no such headers — including an ordinary `404`, a
`403`, or a gateway error page. The refusal is correct; the account of it is
not, because it names the shape the client wanted rather than the answer it got.

The VM hosted lane stops there right now. Buyer status polling against the
storefront refuses `GET /api/v1/settlements/{ref}`, and from the refusal alone
there is no way to tell an unsigned response from a route that answered `404`
from an authority that rejected the caller. That is the same blindness the
hosted diagnostic work has been removing one layer at a time, in the one
remaining layer between the buyer and a working lane.

The lane also runs against a private registry it never authenticates to. The
harness configures `registry-b` to require read and write API keys, generates
those keys, and hands neither to the storefront nor to the buyer, so every
publication to that registry answers `401` and every discovery through it is
unavailable. Seller principal resolution reads from the registry, so this is
either the cause of the refusal above or sitting immediately behind it.

## What Changes

- A client that refuses a response for failing authentication reports what it
  refused: the HTTP status, and whether the response carried authentication at
  all. Never the body, which is what the redaction exists for.
- The harness supplies the private registry's bearer authorization to the
  storefront and to the buyer, from the keys it already generates for it.
- The lane is run again, and the refusal it then names is diagnosed — fixed here
  if it is a marketplace defect, recorded for `add-bare-metal-hosted-settlement`
  if it belongs to the hosted matrix.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: the requirement governing how storefront clients
  verify signed authority responses gains the obligation that a fail-closed
  refusal identifies what was refused.

## Impact

- `core/buyer` — the authenticated-response reader shared by every buyer call.
- `scripts/assemble-hosted-credentials.py` and `e2e-tests` — the registry
  authorization a development run assembles for itself.
- No wire, listing, negotiation, obligation, or configuration schema changes.
  Refusal remains refusal: nothing this change does makes an unverifiable
  response acceptable.
