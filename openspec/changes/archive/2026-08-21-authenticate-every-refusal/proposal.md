## Why

A buyer polling `GET /api/v1/settlements/{ref}` against the real Stripe test
account is refused with `HTTP 403 carried no response authentication`. The
buyer cannot say what was refused, because the refusal is unsigned and a
client that pins the storefront's principal is right to discard it. The
purchase stops, and the cause — which of role, principal, route, body digest,
timestamp, or signature disagreed — is unreadable from the outside.

The refusal is unsigned by construction, not by accident. Every storefront
signs its answer from state that authentication itself deposits: the VM
storefront reads `request.state.marketplace_authenticated`, the bare metal
storefront reads `request.state.marketplace_response_auth`. A request refused
*during* authentication never deposits that state, so the signing wrapper has
nothing to sign with and passes the refusal through bare. The result is that
the answers a caller most needs to read — the ones that say it got something
wrong — are exactly the answers it must discard.

The administrator path already solved this: `_authenticated_error_response`
signs a refusal over the contract the request named, before trust succeeds.
Nothing carried that fix to the buyer and seller paths.

## What Changes

- A refusal on an authenticated route is itself authenticated, over the
  operation and resource the route derived from the request, the request
  identity the caller sent, the status, and the canonical refusal body. This
  covers refusals raised during authentication, not only after it.
- The VM storefront's buyer and listing-mutation paths, the bare metal
  storefront's response wrapper, and the API-credits storefront gain the
  treatment the administrator path already has.
- A refusal that cannot be bound to a caller — no request identity, or no
  route contract — stays unsigned, because there is nothing to bind it to and
  inventing an identity would be worse than the silence.
- Wire-level coverage: the hosted settlement routes are exercised through the
  mounted application with signed requests and verified responses, which is
  where this defect was invisible. Controller-level tests cannot see it.

## Capabilities

### Modified Capabilities

- `marketplace-identity`: response authentication currently binds authenticated
  *mutation* responses. Extend it to every answer on an authenticated route,
  refusals included, and state the one case that stays unsigned.

## Impact

- `domains/vms/storefront/src/market_storefront/middleware/seller_auth.py`
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/response_auth.py`
- `domains/apicredits/storefront/src/apicredits_storefront/middleware/`
- New wire-level integration coverage for the hosted settlement routes.
- No client change: `core_buyer` and `storefront_client` already verify
  refusals and already report the status and whether the answer was
  authenticated at all. This change gives them something to verify.
