## Why

`ARCHITECTURE.md`'s "Route contracts and their HTTP binding" splits a capability's HTTP
surface into a typed client, route contracts, wire models, an HTTP binding, and a
framework-free route service, and says `kit/site` "predates the pattern and ships its own
FastAPI router". Split from `resolve-compute-family-findings` by its design (decision D1,
2026-10-27), because it creates a package and changes a repository-wide kit's contract
shape, and nothing else there depends on it.

- `kit/site/src/market_site/router.py`'s `make_capacity_router` serves fifteen routes whose
  handlers call `CapacityLedgerService` and `SiteProjectionService` directly and raise
  `HTTPException`; there is no route service. Two composition roots mount it: the compute
  provisioning service and the API-credits service.
- The site's route contracts are declared twice, `kit/site/src/market_site/auth.py`
  (`SiteRouteContract`, `CAPACITY_ROUTE_CONTRACTS`, `CAPACITY_DEFINITION_ROUTE_CONTRACTS`)
  and `kit/site-client` (`CapacityRouteContract`, with its own copies of the
  capacity-definition models), held together by `kit/site/tests/unit/test_auth_route_parity.py`.

## What Changes

Proposed; design not started. The design decides:

- whether a `kit/site-contracts` package holds the route contracts and wire models once,
  with `kit/site` and `kit/site-client` built on it and the parity test retired. It fits
  the contracts kind allowlist (`docs/development/ARCHITECTURE.toml`); the
  capacity-definition models must first leave a module that also carries YAML,
  SQLAlchemy, and ledger code; and a new published package needs its publish-workflow
  entry;
- whether `kit/site` gains a framework-free route service, and whether the router factory
  stays as the one binding both composition roots mount, as a capability contributed to a
  service it does not compose supplies its router as a factory, or each root binds it;
- what `ARCHITECTURE.md`'s route-contract section then says of `kit/site`.

## Capabilities

### Modified Capabilities

Expected: `site-capacity`. `.openspec.yaml` sets `skip_specs` until design adds deltas.

### New Capabilities

None expected.

## Non-Goals

- The site middleware's answer to an unroutable request, and the site client's report of
  an unauthenticated answer: `resolve-compute-family-findings`.
- The request envelope: `redesign-authenticated-replay-state`.

## Dependencies and Related Changes

- Opened by `resolve-compute-family-findings`.
- Coordinates with `kit-owned-storefront-auth-and-persistence` and
  `align-package-paths-with-layers`, which touch neighbouring packages.

## Impact

`kit/site`, `kit/site-client`, a possible `kit/site-contracts`, the compute provisioning
service's and the API-credits service's composition, the publish workflow, and
`docs/development/ARCHITECTURE.md`.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `site-capacity`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
