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
- **What `core/storefront` is, before deciding what it owns.** *Gates planning.*
  The change undertakes to state that "core owns market state", but the package it
  would state it for is not a core package by `ARCHITECTURE.md`'s layers: a core
  carrier has no internal dependencies, and `core_storefront` is a 13.7k-line
  composition. `sqlite_client.py` and `sqlite_migrations.py` (7k lines) are
  persistence; `app_composition.py`, `app_lifecycle.py`, `app_startup.py`, and
  `openapi.py` are FastAPI assembly and lazily import `fastapi`; `refund.py` lazily
  imports `market_alkahest.schemas` and `token_transfer.py` lazily imports `web3`;
  none of the three is declared in its `pyproject.toml`. Two kits depend on it —
  `kit/storefront`, which the kit-areas text sanctions, and
  `kit/capacity-publication`, which imports `AggregateCapacityClient`,
  `PlacementPolicy`, `CapacityDelta`, `PublicationSource`, the publication runner,
  the registry publication helpers, and `SellerClosedListingError` through an edge
  no document sanctions — and both compute vocabulary packages import
  `core_storefront.publication_sources.PublicationSource`. A kit depending on a
  composition is the layer rule inverted, and `ARCHITECTURE.md` lists it under
  "Where the current tree diverges" with this change as owner. Suggested
  resolution: carve the shared contracts out into a new repository-wide kit,
  `kit/storefront-contracts` — the hook shapes (`publication_sources`, `capacity`,
  the `AggregateCapacityClient` and `PlacementPolicy` protocols), the domain
  registry and lifecycle contracts, and the wire models under `models/` — with
  declared dependencies of exactly `arkhai-core`, `arkhai-kit-identity`, and
  pydantic, and relocate the rest of `core/storefront`: persistence and FastAPI
  assembly to `kit/storefront` (this change's and the shell's existing intents),
  and `refund`, `token_transfer`, `escrow_identity` to `kit/alkahest`, which
  `move-escrow-into-alkahest` owns since it claims escrow as Alkahest's model. What
  remains of `core/storefront` is the storefront role's composition, and
  `align-package-paths-with-layers` moves it to the roles directory afterwards. A
  contracts-only `core/storefront` was considered and rejected: a repository-wide
  contracts package is a kit, and a kit under `core/` is the misplacement the move
  change exists to remove. Every kit → `core_storefront` edge becomes
  kit → `kit/storefront-contracts`. If the edge is sanctioned as it stands instead,
  say so, because `kit/capacity-publication`'s edge is undocumented either way.
  Either answer deletes this change's rows in `enforce-package-layers`'s exceptions
  table.
- **Sequencing against the shell.** The index orders the shell before this change,
  but the shell and `kit-owned-listing-and-fulfillment-lifecycles` both add kit
  code that would import `core_storefront`; whichever lands first either imports
  the contracts package or re-creates the edge the question above removes. Decide
  whether the contracts carve-out is the first step of this change, landing before
  the shell's route set is planned, or its own small prerequisite change the other
  two depend on.

## Decisions

None yet.
