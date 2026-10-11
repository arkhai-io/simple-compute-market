# Design — API-credit end-to-end lane

## Context

- The pipeline runs three lanes, VM, bare metal, and API credits, each its own job
  building and composing only its own stack (`make -C e2e-tests test-e2e-<lane>`). The
  API-credit lane runs the credits registry, service, storefront, and sample app, a
  compute-schema registry of its own (`compose.apicredits-lane.yml`), and the dev
  chain, with values from `make e2e-apicredits-dev-env`; its scenarios are
  `e2e_credits_deal` and `e2e_credits_payment_deal`, and its lane settings fail
  rather than skip when absent. Neither holds nor steps the API-credit storefront's
  loops; only VM's and bare metal's scenarios use the lifecycle pause.
- Every lane stack runs a local `anvil` under a fixed container name and publishes
  fixed host ports, so locally the lanes run one after the other; in CI each is a job
  on its own runner.
- The API-credit storefront's startup polls the credits service's health, optionally
  seeds a demo listing from a `[seed]` block, and builds a capacity runtime that
  requires at least one configured site authority. With
  `credits.fail_on_unreachable = false` startup continues without the credits
  service after `credits.preflight_timeout`, at least one second.
- No API-credit storefront test runs the production application through its
  lifespan.

## Decisions

### The lane is its own job, not part of the VM lane

Decided with the maintainer. Evidence for each domain stays attributable to that
domain, and a failure in one lane does not mask the other. Building the lane moved to
`bare-metal-mock-provisioned-deal` on 2026-10-01, where each lane builds and composes
its own stack; this change holds and steps the API-credit loops once that lane
exists.

### The storefront's integration tests run the production application

Decided with the maintainer. Tests named integration build the application the
storefront serves, run its lifespan, use a real database, and drive it with the
canonical typed client, as `docs/development/TESTING.md` defines integration.

## Open questions

- **What supplies the credits service and capacity authority to integration tests.**
  A real credits-service application in process, a test double at the HTTP boundary,
  or a configuration seam, for each.
- **What happens to the existing component tests.** Which become integration tests
  and which stay component tests under an accurate name.
- **Which loop transitions the scenario holds and steps.**
