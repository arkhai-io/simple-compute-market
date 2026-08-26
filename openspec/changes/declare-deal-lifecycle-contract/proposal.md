# Declare the deal lifecycle contract

## Why

The end-to-end suite drives a complete deal across every service, and its
structure exists only as numbered comments. Nothing names the stages a deal
passes through, so nothing can reference one: not a test, not a failure report,
not another repository.

Every service has a lifecycle of its own — lease, escrow, settlement,
fulfillment, listing, job — and each is a single entity's state machine. The
inter-service flow those lifecycles compose has no name at all, which is why the
suite carries its shape in prose.

Naming it pays here first. A test that references a stage says where it failed
without a reader counting comment headers, and a second domain gets a structure
to conform to rather than a file to imitate.

## What Changes

- Declares `DealLifecycle`: the inter-service flow constituting one complete unit
  of market activity — discovery, negotiation, settlement, provisioning,
  delivery, teardown. The existing per-entity lifecycles become its constituents.
- Declares `DealStage` identities as a published, importable artifact rather than
  a convention.
- Restructures `e2e-tests/` to reference stages. The existing numbered
  choreography step is retained as a `TestPhase` **within** a stage: several
  phases carry no deal content at all — arming a gate, dry-running a publication,
  advancing a pipeline — and collapsing the two would misattribute them.
- Records the boundary this contract does **not** cross: it declares which stages
  exist, not what should be true at one. An expectation authored from this
  contract by the thing being tested would be the product grading itself.

## Permanent documentation impact

- [x] Existing subsystem specification — `test-compatibility`
- [x] `docs/development/TESTING.md`

### Knowledge to promote

The deal lifecycle and its stages, the stage-versus-phase distinction, and the
rule that this contract carries structure and not expectations.

## Impact

- Affected specs: `test-compatibility`
- Affected code: `e2e-tests/`, `docs/development/TESTING.md`
- Consumed by an external suite that imports the contract rather than
  reimplementing it
