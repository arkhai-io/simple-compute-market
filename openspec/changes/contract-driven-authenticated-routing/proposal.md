## Why

`redesign-authenticated-requests` moves every authority onto one admission core in
two forms (its design's D3): a middleware form for the authorities that route by a
contract table — the provisioning service and the site kit — and a request-dependency
form for those that authenticate inside each route — the registry, the storefront
controllers and deal-servicing. Its design review 16, finding F2, showed that the
dependency form cannot see what no route runs: a path or method no route serves is
answered by the router before any dependency, so it cannot be signed, and a core
reached only through the routes that call it cannot refuse to start over a route that
forgot to. That change closes both gaps with an application-level fallback and a route
inventory checked at startup.

The owner judged the cleaner long-term solution to be one form: every authenticated
route on every authority served by a router driven by its route contract, so the
admission core sees every route, routes and authenticates in one place, and needs
neither the fallback nor the inventory. It rewrites the routing of seven arrangements,
which is too large for `redesign-authenticated-requests`, so it is this change.

## What Changes

To be settled by its design:

- Every authenticated route on the registry, the three storefronts and deal-servicing
  is declared in a route contract table and served through the admission core's
  contract-driven form, as the provisioning service and the site kit already are.
- The request-dependency form, the unmatched-request fallback and the route inventory
  that `redesign-authenticated-requests` adds are retired once no authority uses them.

## Capabilities

### Modified Capabilities

- `marketplace-identity`, `registry-discovery`, `storefront-publication` — as its
  design finds.

### New Capabilities

None expected.

## Non-Goals

- The version 3 profile, the replay component and the admission core's behaviour,
  which `redesign-authenticated-requests` owns.
- The storefront role middleware set, its administrator route contracts and how the
  shell applies them, which `kit-owned-storefront-auth-and-persistence` keeps; this
  change's design settles how it meets that change's route contracts.

## Dependencies and Related Changes

- Follows `redesign-authenticated-requests`, whose admission core and contract-driven
  form it extends to every authority.
- Related to `kit-owned-storefront-auth-and-persistence` and `kit-owned-storefront-shell`,
  which own the storefront's route contracts and how the shell applies them.

## Impact

The registry's and the storefronts' route modules, deal-servicing's routes, and
`kit/authenticated-requests`.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — as its design finds
- [x] Existing subsystem specification — as its design finds
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be named by its design.
