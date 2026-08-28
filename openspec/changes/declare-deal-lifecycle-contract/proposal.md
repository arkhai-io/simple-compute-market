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
- Declares which refusal reasons are stable protocol constants and which are
  interpolated at their raise site. A `409 offer_unfulfillable` carries a `reason`
  drawn from several sites; some are literals and some interpolate incidental
  content — a mismatched attribute list, a listing status — into the message. A
  consumer cannot tell the two apart from the wire, so equality matching against
  an interpolated reason passes or fails on detail the contract never meant to
  promise. Publishing the distinction is what makes a refusal referenceable at
  all, in the same way naming a stage is.
- Records that one reason carries no information: a policy rejecting without a
  reason emits a bare fallback string. It is declared unmatchable rather than
  published as a constant, so nothing asserts against it while appearing to.
- Records the boundary this contract does **not** cross: it declares which stages
  exist and which reasons are constants, not what should be true at one. An
  expectation authored from this contract by the thing being tested would be the
  product grading itself.

## Permanent documentation impact

- [x] Existing subsystem specification — `test-compatibility`
- [x] `docs/development/TESTING.md`

### Knowledge to promote

The deal lifecycle and its stages, the stage-versus-phase distinction, the
stability classification of refusal reasons, and the rule that this contract
carries structure and not expectations.

## Impact

- Affected specs: `test-compatibility`
- Affected code: `e2e-tests/`, `docs/development/TESTING.md`
- Consumed by an external suite that imports the contract rather than
  reimplementing it
- **Scope grew during design.** The refusal-reason classification was added
  because a published stage vocabulary that cannot say which refusal reasons are
  constants leaves every consumer matching on strings that were never promised to
  be stable. Classifying them is the same kind of work as naming a stage and
  belongs with it rather than in a second artifact.
