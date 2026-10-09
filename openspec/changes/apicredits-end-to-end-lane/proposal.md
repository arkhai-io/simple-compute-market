## Why

API credits is a deployable market domain, but nothing proves its storefront works as
assembled:

- **No end-to-end lane of its own.** Its one scenario,
  `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_deal_buyer_cli.py`,
  runs inside the VM lane: the VM compose stack includes `domains/apicredits/compose.yml`.
  A VM-lane failure therefore hides API-credit evidence and the reverse, and the
  scenario never holds or steps the API-credit storefront's loops, which no
  pipeline run exercises at all.
- **No production-application test.** Every API-credit storefront test builds a
  minimal application, or stubs the lifespan's start and stop hooks. Its startup —
  credits-service preflight, demo-listing seeding, capacity polling against
  configured site authorities, and the three timer loops — has no test that runs it.
  `kit-owned-storefront-loop-lifecycle` found this when its API-credit lifecycle-route
  test could be no more than a component test.

The domain is unreleased, so nothing deployed depends on either gap yet. Both have to
close before it is.

## What Changes

- Hold and step the API-credit storefront's loops through the canonical client while
  the API-credit deal scenario runs in its own lane. The lane itself — its own pipeline
  job, compose stack, development identities, and lane environment, with the scenario
  moved out of the VM lane — moved to `bare-metal-mock-provisioned-deal` on 2026-10-01,
  which gives each lane its own build and topology.
- Give the API-credit storefront production-application integration tests: the real
  application through its lifespan, a real database, and the canonical typed client,
  with the credits service and capacity authority supplied as the tests need.
- Reclassify or replace the existing API-credit storefront tests that call themselves
  integration tests without running the production application.

## Capabilities

### Modified Capabilities

- `test-compatibility`: the API-credit lane holds and steps its storefront's loops, and
  the storefront has production-application integration tests.

### New Capabilities

None.

## Non-Goals

- Do not change API-credit market behaviour, settlement, or the credits service.
- Do not change the VM or bare-metal lanes; separating the API-credit lane from the VM
  lane is `bare-metal-mock-provisioned-deal`'s.
- Do not add protected Stripe, signed producer release, or live resolver evidence;
  `add-api-credits-hosted-settlement` owns that.

## Impact

- The API-credit deal scenario in `e2e-tests`.
- `domains/apicredits/storefront/tests`, and whatever startup seams the integration
  tests need.
- `docs/development/TESTING.md`.

## Dependencies and Related Changes

- **Follows `bare-metal-mock-provisioned-deal`**, which creates the API-credit lane
  this change's loop holding runs in. Production-application integration tests do not
  depend on it.
- **Follows `kit-owned-storefront-loop-lifecycle`**, which gave the API-credit
  storefront lifecycle controls and recorded the missing production-application
  coverage.
- Coordinate with `add-api-credits-hosted-settlement`, whose protected evidence is
  separate from this lane.

## Permanent documentation impact

- [x] Existing subsystem specification — `openspec/specs/test-compatibility/spec.md`.
- [x] `docs/development/TESTING.md` — the lanes and the API-credit loop row.
- [ ] `docs/development/ARCHITECTURE.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The API-credit lane holds and steps its storefront's loops —
  `openspec/specs/test-compatibility/spec.md`.
- The API-credit storefront's integration tests run the production application —
  `openspec/specs/test-compatibility/spec.md`, `docs/development/TESTING.md`.
