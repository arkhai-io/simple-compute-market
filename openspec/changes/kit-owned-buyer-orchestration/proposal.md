## Why

The buyer role, `core/buyer` (`arkhai-core-buyer`), is a composition: it ships
the `market` executable and discovers buyer-domain plugins. Most of it is not
composition, though. Its run orchestration, signed negotiation client, run log,
deal recovery, buyer and registry configuration resolution, settlement policy,
policy surface, and CLI helpers are reusable machinery every domain's buyer
builds on.

A domain's buyer plugin is itself a composition, so it may depend on the role.
A library may not: a package depends only on its own layer or a lower one
(`docs/development/ARCHITECTURE.md`, "Repository layers"). The api family's
buyer-side libraries, `arkhai-api-buying`, `arkhai-api-buying-alkahest`, and
`arkhai-api-buying-arkhai-payments`, are libraries over that machinery, so each
depends upward on the buyer composition. `compose-api-family-kit` records the
three edges as `layer` exception rows in `docs/development/ARCHITECTURE.toml`
owned by this change, as the selling side's edge into the core storefront is
owned by `kit-owned-storefront-auth-and-persistence`.

## What Changes

- Move the buyer role's reusable orchestration below the composition boundary
  into a repository-wide kit: what a buyer-side library builds on, which today
  is the package root's exports and `orchestration`, `orchestrator`,
  `negotiation_client`, `run_log`,
  `deal_helpers`, `buyer_config`, `registry_config`, `settlement`,
  `policy_surface`, and the command helpers in `cli`. The role keeps the `market`
  executable, plugin discovery, and command assembly.
- Migrate `arkhai-api-buying`, `arkhai-api-buying-alkahest`, and
  `arkhai-api-buying-arkhai-payments` onto the kit, so none depends on
  `arkhai-core-buyer`.
- Migrate every other importer of the moved modules in the same change, leaving
  no copy or re-export behind: the VM, bare-metal, and API-credit buyers, the
  storefront test suites that drive buyer commands, and `e2e-tests`.
- Delete the three `layer` exception rows this change owns.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: the buyer role is a composition over a buyer
  orchestration kit; buyer-side libraries depend on the kit, never on the role.

## Non-Goals

- No change to buyer behaviour, command surfaces, run-log contents, or wire
  shapes; the modules move and their callers follow.
- No path change for `core/buyer` itself; where role packages live is
  `align-package-paths-with-layers`'s.
- No change to how buyers call storefront routes; that is
  `buyers-use-the-storefront-client`'s.
- No change to escrow-shaped buyer orchestration; that is
  `move-escrow-into-alkahest`'s.

## Impact

- Code: `core/buyer/src/core_buyer/`, a new kit project under `kit/`, every
  importer named above, and their dependency declarations and locks.
- Architecture: the three `arkhai-api-buying*` exception rows in
  `docs/development/ARCHITECTURE.toml` are deleted.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the kit areas and the buyer role's layer.
- [x] Existing subsystem specification — `openspec/specs/market-composition/spec.md`.
- [ ] New subsystem specification

### Knowledge to promote

- Buyer orchestration is a kit the buyer role composes; buyer-side libraries
  depend on the kit — `docs/development/ARCHITECTURE.md`,
  `openspec/specs/market-composition/spec.md`.

## Dependencies and Related Changes

- Depends on `compose-api-family-kit`, which creates the three libraries it
  migrates and the exception rows it deletes.
- Coordinates with `align-package-paths-with-layers` (the role's path),
  `buyers-use-the-storefront-client` (the storefront call helpers in
  `core_buyer`), and `move-escrow-into-alkahest` (the escrow-shaped
  orchestration), each of which edits modules this change moves.
