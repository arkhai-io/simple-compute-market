## Why

The end-to-end pipeline runs each market domain in a lane of its own — VM, bare
metal, and API credits — as separate jobs on separate runners. On one host the
three stacks cannot run side by side, so `make -C e2e-tests test-e2e` runs them in
turn, taking each stack down before the next comes up:

- **One chain container name.** `compose.dev.yml` names the dev chain's container
  `anvil`, and every stack includes it, so a second stack's chain refuses to start
  while another's exists.
- **Fixed host ports.** Every stack publishes the chain on 8545. The VM stack
  publishes 8001, 8002, 8025, 8080–8083, and 6379; the bare-metal stack 8000, 8080,
  and 8081; the API-credit stack 8090, 8092, 8093, and 8095. The VM and bare-metal
  stacks collide on 8080 and 8081 as well as 8545.

The lanes' scenarios run from a container on each stack's own compose network and
reach services by name, never through a host port. The collisions therefore cost a
local run its wall-clock time without protecting anything the lanes test.
`bare-metal-mock-provisioned-deal` recorded the constraint when it gave each domain
its own lane, and opened this change at the maintainer's request.

## What Changes

- Let the three lane stacks run concurrently on one host: no fixed container name
  shared across stacks, and no host port that two lane stacks both publish.
- `make -C e2e-tests test-e2e` runs the lanes concurrently once nothing collides,
  keeping each lane's failure output its own.
- State: **proposed; design not started.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None expected; this is compose and build tooling, so `.openspec.yaml` sets
`skip_specs`. Design confirms whether `test-compatibility`'s lane requirement
changes, and adds a delta and clears `skip_specs` if it does.

## Non-Goals

- Do not change what any lane composes or runs, or the pipeline's one job per lane.
- Do not change the full local stack's ports, which local tooling and the
  validation runbook address directly.

## Open questions

- Whether the lanes drop host ports altogether (scenarios use only the compose
  network) or publish them under per-lane bases, and what local debugging then
  reaches each service through.
- Whether the chain's fixed container name has a reader that needs it, or a
  project-scoped service name suffices everywhere.
- How a concurrent `test-e2e` keeps each lane's output and exit status separate.

## Dependencies and Related Changes

- Follows `bare-metal-mock-provisioned-deal`, which gave each domain its own lane
  and recorded this constraint (its design, "Section 10 design: each lane builds and
  composes its own stack", decision 2).

## Impact

`compose.dev.yml`, the domain compose files' `ports`, the lane overlays, and
`e2e-tests/Makefile`'s `test-e2e`. No runtime behaviour changes.
