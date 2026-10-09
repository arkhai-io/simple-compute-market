## Why

Two more concerns are duplicated per storefront beneath the shell.

Authentication: the VM storefront carries a full scheme-neutral v2 middleware set —
seller authentication for listing mutations, administrator identity, buyer
body-bound authentication, and service-peer authentication with signed responses
(1,631 lines across four modules) — over core's `identity_authority` and `auth`.
API credits and bare metal each carry a 146- and 149-line `response_auth` and reach
the rest through core directly, so the three storefronts authenticate the same routes
by three arrangements.

Persistence: core's domain-neutral SQLite client and migrations (4,824 and 2,062
lines) own listings, negotiations, escrows, claims, and publications, yet each
storefront keeps its own client and migrations beside them (VM 1,845 lines, bare
metal 1,723, API credits 252). Part of each is domain tables; part reimplements
access to core-owned market state, and the boundary between the two is not stated.

## What Changes

- Move the v2 authentication middleware set — seller, administrator, buyer,
  service-peer, and signed responses — into core or kit as one set the shell applies,
  with the domain contributing nothing but the principals its configuration names.
- State the persistence boundary: core owns market state; a domain's client holds
  only tables the domain's contract introduces. Reduce each storefront's client and
  migrations to that, moving any core-state access it reimplements into core.
- Compose all three domains and remove every domain-local copy in this change.
- Record, per concern, where the copies diverged and which behavior was chosen.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: request authentication and market-state persistence are
  core- or kit-owned; a domain's persistence is its own tables only.

## Non-Goals

- Do not change any authentication scheme, principal model, or wire signature; the
  same requests authenticate the same way.
- Do not migrate persisted data; the boundary is stated and code moves, tables stay.
- Do not extract the shell or the lifecycles — sibling changes.

## Impact

- Code: VM `middleware/{seller_auth,admin_identity,service_peer_auth,buyer_auth}.py`,
  API-credit and bare-metal `response_auth.py`; every storefront's `utils/sqlite_client.py`
  and `utils/migrations.py`; core's `auth.py` and `sqlite_client.py`.
- Tests: middleware and persistence suites collapse into core or kit suites plus
  per-domain table coverage.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — authority boundaries and package layers.
- [x] Existing subsystem specification — `openspec/specs/market-composition/spec.md`.
- [ ] New subsystem specification

### Knowledge to promote

- Request authentication is one core- or kit-owned middleware set; a domain's
  persistence is its own tables only — `openspec/specs/market-composition/spec.md`.

## Dependencies and Related Changes

- Depends on `kit-owned-storefront-shell`, which applies the middleware set and
  mounts the routes it protects.
- Independent of `kit-owned-listing-and-fulfillment-lifecycles`; either order.
