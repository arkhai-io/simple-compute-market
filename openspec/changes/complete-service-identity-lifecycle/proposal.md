## Why

`service-identity-signing` was archived on 2026-10-27 as delivered, its requirements
already in the permanent specifications, and what its tasks left undone moved to
`redesign-authenticated-requests`. That change's design (its decisions D1 and D19)
kept the request contract and replay state and moved the identity-lifecycle and
trust-configuration remainder here, so the replay fix does not wait on
`sign-multi-language-credits-middleware`.

What is undone today:

- **The API-credits shared-secret fallback.** The service mounts either
  `SiteAuthMiddleware` or `AdminKeyAuthMiddleware`, never both, chosen by whether signed
  authentication is configured
  (`domains/apicredits/service/src/apicredits_service/main.py`). The Python credits
  clients send `X-Admin-Key` only when they are not configured to sign; the TypeScript
  and Rust middlewares send only the shared secret, which is why removing the fallback
  waits on `sign-multi-language-credits-middleware`.
- **API-credits trust has no durable rotation.** The service's trusted principals are
  read once, at import, from its Dynaconf configuration — the environment in every
  shipped deployment (`domains/apicredits/service/src/apicredits_service/identity.py`) —
  with no rotation record, route or reload.
- **No single site-registry interface.** Storefronts reach sites three ways: bare metal
  through `BareMetalSiteBinding` and service-peer trust, VM through its configured
  capacity sites and service-peer trust, and the API-credits storefront with both the
  URL and the expected authorities read from configuration and no service-peer trust at
  all.
- **Provisioning cannot retire or disable a principal.** Its principal authority has
  only `rotate`; overlap expiry is implicit
  (`provisioning/compute/service/src/compute_provisioning_service/services/principal_authority.py`),
  while `physical-provisioning`'s "Counterparty principals rotate with dual proof"
  requires explicit retirement and a disablement distinct from rotation.
- **The storefront's disablement has no operator route.** `disable` exists in the
  storefront's identity authority; the administrator routes reach rotation, retirement
  and status only.

## What Changes

To be settled by its design:

- Remove the API-credits `X-Admin-Key` fallback and the Python clients' shared-secret
  path once every credits middleware signs.
- Give the API-credits service's trusted principals a durable, rotatable record.
- One site-registry interface returning each site's identity, URL and principals,
  principals through service-peer trust, used by all three storefronts.
- Explicit principal retirement and disablement in the provisioning service.
- An operator route to the storefront's principal disablement.

## Capabilities

### Modified Capabilities

- `api-credits`, `physical-provisioning`, `storefront-publication`,
  `marketplace-identity` — as its design finds.

### New Capabilities

None expected.

## Non-Goals

- The request envelope, replay state and the shared admission core, which
  `redesign-authenticated-requests` owns.
- Signing in the TypeScript and Rust credits middlewares, which
  `sign-multi-language-credits-middleware` owns.

## Dependencies and Related Changes

- The fallback's removal follows `sign-multi-language-credits-middleware`, which itself
  follows `redesign-authenticated-requests`.
- Its routes authenticate through `redesign-authenticated-requests`' admission core.

## Impact

The API-credits service and its clients, each storefront's site wiring, the
provisioning service's principal authority and administrator routes, and the
storefronts' administrator identity routes.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — as its design finds
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be named by its design.
