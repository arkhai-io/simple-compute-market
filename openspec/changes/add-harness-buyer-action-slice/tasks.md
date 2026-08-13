# Tasks

One commit. The boundary and the thing it constrains are the same review: an
adapter landing without the boundary is an adapter a later change has to be
trusted to constrain.

Baseline: `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`. Re-pin
before starting.

Sequenced after `add-harness-scenario-contract` and
`restore-issue-discovery-thin-runner`.

Nothing here runs a declared scenario, releases a barrier, or evaluates an
outcome against a declared expectation. Preparation is exercised; scenarios are
not. If a task appears to need the barrier or the evaluator, the plan premise is
wrong — pause for design review.

## 1. Buyer adapter bound to documented targets

- [ ] 1.1 Bind the adapter to the entry points `docs/buyer-quickstart.md`
  instructs a reader to run: `uv tool install arkhai-core-buyer --with
  arkhai-vms-buyer`, `market --version`, `market listing list`,
  `market listing show`, `market buy`, `market logs show`,
  `market escrow reclaim`. Invoke the installed CLI the way the quickstart does.
- [ ] 1.2 Do not bind to an internal buyer client, a test fixture, or a direct
  HTTP call to a negotiation endpoint. An adapter on a path no buyer uses runs
  green while the documented path is broken, which is the defect class this
  harness exists to catch.
- [ ] 1.3 Pin the quickstart revision the adapter was bound against and carry it
  in the adapter's own record, so a later reader can tell whether the
  documentation moved underneath it.
- [ ] 1.4 Record that `market buy` cannot load the VM buyer domain until
  `compose-domain-wheels-and-policies` closes. Bind to the documented target
  regardless; exercising it end to end waits on that change.

## 2. Action ownership

- [ ] 2.1 Place every documented buyer action in the buyer adapter. Give the
  controller no code path that performs one — not behind a flag, not for
  convenience, not for setup.
- [ ] 2.2 Restrict the controller to coordination: authority checks, barrier
  release, deadlines, retry prohibition, cancellation, observation, and cleanup
  trigger.
- [ ] 2.3 Add a test asserting the controller module performs no buyer action —
  by import surface, not by inspecting strings. A controller that can reach the
  adapter's action functions is a controller that will.
- [ ] 2.4 Where scenario setup wants pre-seeded buyer state, express it as an
  actor action or as product-owned preparation. Do not add a controller path for
  it. The inconvenience is the boundary working.

## 3. Frozen requests

- [ ] 3.1 Fix each buyer's request before release and make it immutable
  afterwards. An actor that would compose its request at release time has
  changed the experiment.
- [ ] 3.2 Carry the frozen request in the result record, so a reviewer can
  confirm the buyers were contending rather than take it on trust.
- [ ] 3.3 Add a test that a mutation attempt after freezing fails, and names the
  buyer and the field.

## 4. Independent observation and diagnosis handoff

- [ ] 4.1 Capture observation with an observer that is not the actor observed.
  Keep the actor's own account as a separate record.
- [ ] 4.2 Retain both where they disagree, and make the disagreement itself
  reportable rather than resolving it silently in favour of either.
- [ ] 4.3 Feed a structured investigation and root-cause record into the
  existing issue engine's candidate path, in the shape the phase pipeline
  already produces. Do not add a second candidate format.
- [ ] 4.4 A passing run produces receipts and no diagnosis narrative. See
  `design.md`, "What is a diagnosis of a passing run?".

## 5. Fail-closed adapters

- [ ] 5.1 Fail adapter selection for any live market, wallet, cloud, host,
  provisioning, VM, GPU, or authenticated repository-hosting target before a
  subprocess starts or a socket opens. Check the resolved configuration, not a
  runtime branch.
- [ ] 5.2 Add tests that each live selection fails, and that the failure occurs
  before any process or connection — assert on the absence of the effect, not
  only on the raised error.
- [ ] 5.3 Exercise concurrency and failure paths with fake processes.

## 6. The real-model decision

- [ ] 6.1 Request the widened real-model rule recorded in `design.md`: a
  real-model component may be necessary either because a changed boundary cannot
  be exercised faithfully by fakes, or because the claim is about documentation
  executability, which fakes cannot support by construction.
- [ ] 6.2 Until the widening is accepted, implement the fake-process paths and
  the diagnosis handoff, and record the documentation-executability claim as
  unproven. Do not substitute a fake result for it.
- [ ] 6.3 If accepted, define the smallest sufficient component — one actor
  following the published buyer quickstart with no repository context, against a
  local stack — and state whether it runs here or is deferred.
- [ ] 6.4 If the decision is still open when this change is otherwise ready,
  record it through the operator's pending-decision channel and proceed. Do not
  stall the change on it and do not assume an answer.

## 7. Documentation

- [ ] 7.1 Record the action-ownership boundary in
  `docs/development/TESTING.md` — what the controller may do, what it may not,
  and what a controller-performed buyer action would invalidate about a result.
- [ ] 7.2 Record the diagnosis handoff in `docs/development/ISSUE_DISCOVERY.md`
  as an additional producer for the existing candidate path.
- [ ] 7.3 Verify every path cited by both documents resolves on the branch.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
  match; read touched files for what the target cannot catch.
- [ ] 8.2 **Import placement.** Migrate local imports added here to module level
  where safe, verifying each against the real suite.
- [ ] 8.3 **Documentation compliance.** Re-check accepted decisions against
  `openspec/README.md`'s placement rules, and confirm every citation resolves.
- [ ] 8.4 **Narrative compression.** Reduce task notes to final behaviour,
  validation evidence, unresolved work, and promotion destinations. The archival
  branch analysis and the real-model reasoning belong in `design.md`.
- [ ] 8.5 **Roadmap currency.** `docs/development/ROADMAP.md` owes nothing: the
  harness is not a market capability. Recorded as a deliberate disposition. The
  private harness roadmap's Goal 1 current state does change, and is updated
  there.
- [ ] 8.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| The controller coordinates and performs no documented user action; a controller-performed action invalidates the result as evidence about the product | `docs/development/TESTING.md` | Pending |
| A buyer's request is frozen before release and carried in the result | `docs/development/TESTING.md` | Pending |
| Agent diagnosis feeds the existing candidate path rather than a second format | `docs/development/ISSUE_DISCOVERY.md` | Pending |
| `Documented user actions are actor-owned`, `Requests are frozen before concurrent release`, `Observation is independent of the observed`, and `Live adapters fail closed by configuration` | `openspec/specs/test-compatibility/spec.md` | At archival |
