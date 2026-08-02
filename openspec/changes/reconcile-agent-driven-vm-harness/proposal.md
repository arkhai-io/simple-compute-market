## Why

The public issue-discovery tool predates the current reservation and durable
fulfillment lifecycle. An earlier side branch added agent-driven capacity
scenarios while the POOLS refactor was in progress, so that work cannot be
merged or restored mechanically: current `dev` is the product authority, and
the harness must describe the contracts that exist there now.

The intended change is deliberately narrow. It prepares the existing
issue-discovery harness to represent a finite set of VM tests with one physical
whole GPU, substantive buyer and seller agents, deterministic findings, and
mocked issue/fix planning. It does not execute those tests or introduce a new
testing platform.

## What Changes

- Add one portable VM/G1 capacity-scenario contract that represents Q0,
  controller-driven Reference B1, and agent-driven Q1-Q8 with explicit
  orchestrator, buyer, seller, host, listing, request, and GPU counts.
- Distinguish substantive role ownership from controller-driven reference
  emission, including common-release-barrier contention and serialized reuse.
- Correlate results using current `capacity_reservation_id`, `fulfillment_id`,
  fulfillment status/result, and fulfillment-driven teardown vocabulary.
- Treat only the expected HTTP 409 `offer_unfulfillable` /
  `no_matching_inventory` tuple as scenario scarcity; preserve all other
  failures for classification.
- Produce sanitized, stable findings and deterministic create, update, reopen,
  suppress, and guarded draft-fix candidate plans without invoking GitHub.
- Require cleanup eligibility before publication planning, while retaining a
  cleanup failure as its own finding.
- Expose deterministic machine-readable validation, evaluation, cancellation,
  cleanup, and dry-run results suitable for local use now and a later
  on-demand runner.
- Correct only stale issue-discovery repository paths and prerequisite test
  expectations needed by current `dev`.

## Affected Capability

- Modified: `test-compatibility`

No production marketplace capability is modified.

## Compatibility and Breaks

This is an additive harness contract on current `dev`. Historical capacity
fixtures are not wire compatibility promises. VM/G1 fixtures are rebuilt to
the new schema; G2 fixtures remain absent. Existing non-capacity
issue-discovery phases continue to use their current interfaces except for
repository-path and prerequisite corrections.

No database, service API, package publication, deployment, or product behavior
changes. No dependency or lockfile change is required.

## Non-Goals

- Running Q0, Reference B1, or Q1-Q8.
- Proving real market, wallet, cloud, private-control-plane, KVM, Ansible, VM, or GPU
  behavior.
- Changing product or E2E implementation code to accommodate the harness.
- Supporting non-VM deal types or more than one physical GPU.
- Restoring the historical G2, qualification-profile, generalized role/action,
  finding-v2, or transactional publication work.
- Adding Tekton, a cloud runner, scheduling, or a default-branch workflow.
- Making authenticated GitHub mutations or creating a real issue, branch, or
  pull request.
- Opening or merging the eventual harness pull request.

## Permanent Documentation Impact

- [ ] `openspec/specs/test-compatibility/spec.md`
- [ ] `openspec/specs/test-compatibility/architecture.md`
- [ ] `docs/development/ISSUE_DISCOVERY.md`
- [ ] `tools/issue-discovery/README.md`
- [ ] No repository-wide `docs/development/ARCHITECTURE.md` change

### Knowledge to Promote

- The finite VM/G1 scenario and substantive-agent contract belongs in the
  permanent testing and compatibility specification.
- The public/private ownership split, evidence layering, cleanup gate, and
  future-runner seam belong in the permanent testing architecture.
- Current commands, result claims, and the preparation-only safety boundary
  belong in issue-discovery operator documentation.

## Acceptance Boundary

The change is ready for review when the public harness can validate every
finite row, evaluate current lifecycle receipts, plan the complete finding and
guarded fix-candidate sequence under mocks, reject live adapters, pass its
locked test suite, and remain confined to the approved issue-discovery and
OpenSpec paths. Passing these checks is not live or capacity qualification.
