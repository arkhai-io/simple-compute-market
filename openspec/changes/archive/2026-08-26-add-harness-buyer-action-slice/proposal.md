> **Archived 2026-08-26 — superseded, not implemented.**
>
> **Superseded by:** `define-participant-contracts-and-action-boundary`, in the testing-harness repository.
>
> **Why.** The harness moved to a repository of its own. The word *slice* was undefined here and appeared once; it is not carried forward.
>
> **What carried forward.** The action-ownership boundary, independent observation, and frozen requests carry forward close to verbatim. The boundary is now expressed per effect rather than per role, because the same effect class is a fixture before a scenario starts and under test after it, for the same participant.
>
> **Where the reasoning lives.** `design.md`'s account of how the abandoned branch crossed this boundary — a wrapper emitting a buyer request from the controller side, with tests passing throughout — is why the successor enforces by capability rather than by review. It is cited, not restated.
>
> Design rationale is referenced rather than duplicated: successors cite this
> change by name and do not restate it, so the two cannot drift under two
> vocabularies.

---

## Why

`add-harness-scenario-contract` declares what a scenario is. Nothing performs
one, and nothing establishes who is allowed to perform which part of one.

That boundary is the harness's central claim. A buyer action performed by the
controller measures the controller. A buyer action performed by an actor that
owns its own request, released by a barrier the controller holds, measures the
product under the demand the scenario declared. The two produce identically
shaped results and only one of them is evidence.

This change adds the buyer action slice: an adapter bound to the product's
documented buyer entry points, an action-ownership boundary the controller
cannot cross, frozen requests, independent observation, and a structured
diagnosis handoff into the existing issue engine. It exercises documented buyer
*preparation* against local and mock product facilities. It does not run a
declared scenario.

Two things make the boundary worth enforcing mechanically rather than by
convention.

**The archival branch crossed it and stayed coherent.** That branch carries
`wrappers/emit-buyer-request.sh`, `wrappers/publish-listing.sh`, and
`wrappers/start-seller-service.sh` — controller-side action emission. Its tests
passed. Its task list was internally consistent. Nothing in it announced that
the thing being measured had changed from the product to the driver.

**The documented buyer path is a real artifact with real steps.**
`docs/buyer-quickstart.md` takes a reader through install, configure, browse,
buy, resume, and tear down, using `uv tool install arkhai-core-buyer`,
`market listing list`, `market buy`, `market logs show`, and
`market escrow reclaim`. Those are the product-owned targets an adapter binds
to. Binding to anything else — an internal client, a test fixture, a direct HTTP
call — would test a path no buyer uses, and would quietly stop testing whether
the documentation works.

## What Changes

- A buyer adapter bound to the product's documented buyer entry points, invoked
  the way the quickstart invokes them.
- An **action-ownership boundary**: the buyer actor performs every documented
  buyer action; the controller coordinates only — authority checks, barrier
  release, deadlines, retry prohibition, cancellation, observation, cleanup
  trigger. A controller-side path that performs a buyer action fails closed.
- **Frozen requests.** A buyer's request is fixed before the barrier releases and
  cannot change afterwards. Contention between buyers whose requests differ
  proves nothing about contention.
- **Independent observation.** Observation is captured by an observer that is not
  the actor being observed, so an actor's own account of what it did is never
  the sole record of it.
- **Diagnosis handoff.** A structured investigation and root-cause record from an
  actor feeds the existing issue engine's candidate path, in the same shape the
  phase pipeline already produces.
- **Fail-closed adapters.** Selecting any live market, wallet, cloud, host,
  provisioning, VM, GPU, or authenticated repository-hosting adapter fails before
  a subprocess starts or a socket opens — by configuration, not by an
  instruction the actor is asked to respect.
- Concurrency and failure paths are exercised with fake processes.

Not in scope: running a declared scenario, any contention outcome, any capacity
claim, the private supervision entrypoint, and any real-model invocation beyond
what the decision below settles.

## Impact

- Affected specs: `test-compatibility`
- Affected code: `tools/issue-discovery/src/issue_discovery/`,
  `tools/issue-discovery/config/`, `tools/issue-discovery/schemas/`,
  `tools/issue-discovery/tests/`
- Depends on `add-harness-scenario-contract` for the declaration this slice
  eventually performs, and on `restore-issue-discovery-thin-runner` for the
  issue engine the diagnosis handoff feeds.
- **Preparation is exercised; scenarios are not.** The distinction is load
  bearing. The adapter runs the documented buyer preparation steps against local
  and mock facilities to prove the binding is real. It does not release a
  barrier, does not evaluate an outcome against a declared expectation, and does
  not produce a scenario result. Anything that would require those belongs to a
  later change.
- **Whether a real model runs is decided here, and the plan's default is wrong
  for one of the two reasons.** See the decision in `design.md`; the milestone
  currently frames real-model invocation as warranted only by a changed
  boundary, which does not cover proving that documentation is executable.
- Behaviour change to record: none in the product. This change adds harness
  capability and alters no product behaviour.
- Product observation, not fixed here: `market buy` currently cannot load the VM
  buyer domain until `compose-domain-wheels-and-policies` closes. The adapter
  binds to the documented target regardless; exercising it end to end waits on
  that change.

## Permanent documentation impact

- [ ] `docs/development/TESTING.md` — the action-ownership boundary and what a
  controller-performed action would invalidate
- [ ] Existing subsystem specification — `test-compatibility`
- [ ] `docs/development/ISSUE_DISCOVERY.md` — the diagnosis handoff into the
  existing candidate path
- [ ] `docs/development/ARCHITECTURE.md` — none owed
- [ ] New subsystem specification — none owed
- [ ] `docs/development/ROADMAP.md` — none owed; the harness holds no goal row

### Knowledge to promote

See the design-promotion record in `tasks.md`.
