## Why

An end-to-end scenario may wait only on an effect its own request caused or for
an instant the Agreement fixes, and a behaviour defined by time elapsing is
driven by moving the deciding service's perceived clock
(`docs/development/TESTING.md`, "The discipline every scenario follows"). Only
the lane doubles have such a clock (`tools/lane-double-controls`). The storefront
reads wall time, so no storefront step may follow a double's clock advance: a
stop the double records at an advanced instant is in the storefront's future,
and the storefront would truncate and wait on wall time.

A per-period deal that runs out of funds ends at an instant the payments service
derives from funding, not one the Agreement fixes. Proving that ending in a lane
needs the storefront's clock moved together with the doubles'. The live
storefront container cannot be monkeypatched, so the override has to be a
configurable option of the storefront itself.

This change is one of Goal 8's MVP changes (see `offer-per-period-vm-terms`'s
design for the set). It takes the storefront's share of the roadmap's unowned
"lane-wide perceived clock" gap; the site's and buyer's shares stay unowned
unless its design finds a lane row that needs them.

## What Changes

- **A configurable storefront clock.** The VM storefront's composition takes a
  clock source from configuration: wall time by default, or a perceived clock —
  wall time plus an offset — when explicitly enabled.
- **An admin route, mounted only when enabled.** When the perceived clock is
  enabled, the storefront serves routes to advance it and reset it to wall time.
  When it is not, the routes do not exist.
- **Refused in production.** A production composition refuses to start with the
  perceived clock enabled, and a storefront running with it says so at startup
  and on its operator surfaces.
- **One lane fixture for every movable clock.** The lane advances the storefront's
  clock and both doubles' clocks together, and resets all of them whatever a
  module's outcome, extending today's `lane_double_clock` fixture.
- **The rule restated.** `TESTING.md`'s discipline names the storefront as a
  service whose perceived clock a control moves, and states what a storefront
  step after an advance may rely on.

## Capabilities

### Modified Capabilities

- `market-composition`: the storefront's clock source, its configuration, and its refusal in production.
- `vm-storefront-fulfillment`: the clock control routes on the VM storefront's operator API when enabled.
- `test-compatibility`: one lane clock fixture across the storefront and both doubles.

### New Capabilities

None.

## Non-Goals

- A perceived clock in the site, the buyer, or the registry, unless the design finds an MVP lane row that cannot run without one.
- Composing the clock in the bare-metal storefront; `converge-ongoing-compute-leases` adds it (its task 4.1a), so this change keeps the mechanism composable by both storefronts.
- Writing the funds-exhausted scenario itself, which is `serve-running-rate-deals-on-vm`'s.
- Any clock behaviour in a production deployment other than wall time.

## Impact

- Configuration: one new storefront setting, defaulting to wall time.
- Operator API: routes present only when the setting enables them.
- Packaging: production code must not depend on a test-only distribution; where the perceived clock lives is a design decision.
- No wire or database change.

## Dependencies and Related Changes

- No dependency. Runs in parallel with `offer-per-period-vm-terms` and `derive-rate-parts-in-the-payments-kit`.
- `serve-running-rate-deals-on-vm`'s funds-exhausted row depends on it; that change's other rows do not.
- Takes part of Goal 8's unowned "lane-wide perceived clock" row in `docs/development/ROADMAP.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `market-composition`, `vm-storefront-fulfillment`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `market-composition`'s spec — the clock source, its default and its production refusal; `docs/development/DEPLOYMENT_AND_CONFIG.md` — the setting.
- D2: `test-compatibility`'s spec and `docs/development/TESTING.md` — the storefront as a service with a perceived clock, and the joint fixture.
- D3: `market-composition/architecture.md` — the clock mechanism as composable by every storefront.
