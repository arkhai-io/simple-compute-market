# Design

Design phase; not planned.

## Context

- Core owns `identity_authority` (857 lines), `auth` (371), and `identity_lifecycle`;
  the market-composition contract already requires independent request
  authentication and injected signers.
- The VM middleware set is the complete one; the other two storefronts compose a
  subset directly from core. The likely outcome is that the VM set, minus anything
  VM-specific, becomes the shared set.
- API credits' `require_admin_principal` signs over the route name and request path,
  not the explicit operation and resource `storefront_client` signs for
  administrator calls (`admin_advance_negotiation`, `admin_pause_listing`,
  `admin_resume_listing`), so the canonical client cannot call those three routes.
  Found while moving the deal controls into kit route services; the shared set has
  to carry each route's signed contract with the route.
- Core's `sqlite_client` is domain-neutral by its own docstring; each storefront's
  client says it holds what core does not. Which is true per table has not been
  inventoried.

## Questions to settle before planning

- **Core or kit for the middleware set.** Core already owns authentication
  primitives; kit owns composition. The set is composition over core primitives,
  which argues for `kit/storefront`.
- **The persistence inventory.** Per storefront table: core-owned market state, a
  domain table, or a reimplementation of core access. The change is sized by that
  inventory, not by line counts.

## Decisions

None yet.
