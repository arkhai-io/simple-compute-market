## Why

An end-to-end scenario may wait only on an effect its own request caused or for
an instant the Agreement fixes, and a behaviour defined by time elapsing is
driven by moving the deciding service's perceived clock
([`deal-scenarios.md`, "The discipline every scenario follows"](../../../docs/guidance/repository/deal-scenarios.md#the-discipline-every-scenario-follows)).
Only the lane doubles have such a clock (`tools/lane-double-controls`). Both
compute storefronts read wall time, so no storefront step may follow a double's
clock advance: a stop the double records at an advanced instant is in the
storefront's future, and the storefront would truncate and wait on wall time.

A per-period deal that runs out of funds ends at an instant the payments service
derives from funding, not one the Agreement fixes. Proving that ending in a lane
needs the storefront's clock moved together with the doubles'. The live
storefront containers cannot be monkeypatched, so the override has to be a
configurable option of each storefront itself.

This change is one of Goal 8's three MVP changes: it runs beside
`serve-running-rate-deals`, whose funds-exhausted rows in both lanes need it, and
`switch-on-hosted-per-period-vm` follows them. It takes the storefronts' share of
the roadmap's unowned "perceived clock" gap; the site's and the buyer's shares
stay unowned unless its design finds a lane row that needs them.

## What Changes

- **A configurable storefront clock in both compute storefronts.** Each
  storefront's composition takes a clock source from configuration: wall time by
  default, or a perceived clock — wall time plus an offset — when explicitly
  enabled.
- **An admin route, mounted only when enabled.** When the perceived clock is
  enabled, the storefront serves routes to advance it and reset it to wall time.
  When it is not, the routes do not exist.
- **Refused in production.** A production composition refuses to start with the
  perceived clock enabled, and a storefront running with it says so at startup
  and on its operator surfaces.
- **One lane fixture for every movable clock.** Each lane advances its
  storefront's clock and both doubles' clocks together, and resets all of them
  whatever a module's outcome, extending today's `lane_double_clock` fixture.
- **The rule restated.** The scenario discipline in
  `docs/guidance/repository/deal-scenarios.md`, and its description in
  `docs/development/TESTING.md`, name the storefronts as services whose perceived
  clock a control moves, and state what a storefront step after an advance may
  rely on.

## Capabilities

### Modified Capabilities

- `market-composition`: the storefront's clock source, its configuration, and its refusal in production, in both compute compositions.
- `vm-storefront-fulfillment`: the clock control routes on the VM storefront's operator API when enabled.
- `test-compatibility`: one lane clock fixture across each storefront and both doubles.

The bare-metal storefront's operator routes have no specification of their own; the design session names where its clock routes are specified.

### New Capabilities

None.

## Non-Goals

- A perceived clock in the site, the buyer, or the registry, unless the design finds an MVP lane row that cannot run without one.
- Writing the funds-exhausted scenarios themselves, which are `serve-running-rate-deals`'.
- Any clock behaviour in a production deployment other than wall time.

## Impact

- Configuration: one new setting in each compute storefront, defaulting to wall time.
- Operator API: routes present only when the setting enables them.
- Packaging: production code must not depend on a test-only distribution; where the perceived clock lives is a design decision.
- No wire or database change.

## Dependencies and Related Changes

- No dependency. Runs in parallel with `serve-running-rate-deals`, whose funds-exhausted rows depend on it; its other rows do not.
- Takes `converge-ongoing-compute-leases`' task 4.1a, the bare-metal storefront clock, since `serve-running-rate-deals` now qualifies both lanes.
- Takes the storefronts' part of Goal 8's unowned perceived-clock row in `docs/development/ROADMAP.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `market-composition`, `vm-storefront-fulfillment`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `market-composition`'s spec — the clock source, its default and its production refusal; `docs/development/DEPLOYMENT_AND_CONFIG.md` — the setting.
- D2: `test-compatibility`'s spec, `docs/guidance/repository/deal-scenarios.md` and `docs/development/TESTING.md` — the storefronts as services with a perceived clock, and the joint fixture.
- D3: `market-composition/architecture.md` — one clock mechanism composed by both storefronts.
