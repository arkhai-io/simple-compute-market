# Implementation Tasks

## 1. Generalize the e2e fixtures

- [x] 1.1 Re-verify that no e2e file references bare metal or API credits, and inventory
      the VM assumptions in shared fixtures and helpers.
- [x] 1.2 Generalize fixtures and helpers away from VM-specific listing shape,
      provisioning, and teardown assumptions.
- [x] 1.3 Keep scenarios thin. Copying the VM scenarios and editing them per domain
      reproduces, one layer up, exactly the duplication this goal removes.

## 2. Recompose API credits

Implementation dependency: tasks 2.1-2.2 wait for the final committed interfaces
from `kit-storefront-composition-seam`, `kit-owned-negotiation-runtime`, and
`kit-owned-capacity-and-publication`. This change will consume those modules and
remove the API-credit copies; it will not recreate an absent extraction locally.


- [ ] 2.1 Remove every remaining local implementation of a concern the kit extractions
      own, so the domain is configuration and codecs over kit.
- [ ] 2.2 Confirm no extracted concern retains an API-credits copy. The domain already
      completes deals with its own implementations, so a passing scenario is not evidence
      of recomposition.
- [x] 2.3 Add the API-credits end-to-end deal path.
- [x] 2.4 Sequenced first deliberately: there is a working implementation to compare
      against, so a failure here is a recomposition defect rather than an unknown.

## 3. Bare-metal deployable stack

- [ ] 3.1 Add the stack definition, following the topology conventions
      `domains/vms/compose.yml` and `domains/apicredits/compose.yml` already use.
- [ ] 3.2 Write it so the deployment shape can change — standalone service or a second
      contract inside a shared storefront process — without rewriting the scenarios.
- [ ] 3.3 Update `docs/bare-metal-seller-quickstart.md` with standing the stack up.

## 4. Bare-metal deal path

The static task 4.1 scenario consumes only the accepted `market bare-metal`
public command contract. Its live execution remains blocked on the installed
buyer contribution, sibling storefront's authenticated result/access/teardown
endpoints, selected-site authority, credentials, and real access target.


- [x] 4.1 Add the end-to-end scenario: discovery, negotiation, settlement, delivery,
      teardown.
- [ ] 4.2 Treat defects this surfaces in bare metal's own behavior as bare-metal
      findings, recorded against its owning change rather than absorbed here.
- [x] 4.3 Decide and record whether bare-metal teardown semantics differ from VM's, since
      whole-machine release is not VM destruction.

## 5. Validation

External gate: tasks 5.1-5.2 require running API-credit and bare-metal seller
stacks, role-scoped credentials, the selected site/provisioning authority, and a
real whole-host access target. Static scenario/configuration work is not live-deal
evidence. Task 5.3 is intentionally unrun in this delegated lane.


- [ ] 5.1 Run both new end-to-end paths against a live service stack. This repository has
      previously recorded e2e work validated only statically because no stack was
      available; treat a live run as an explicit gate, not a formality.
- [ ] 5.2 Confirm the goal's completion test: each domain runs a full deal through a
      composed storefront with no domain-local copy of an extracted concern.
- [ ] 5.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`.
- [ ] 6.2 **Import placement.** Review imports this change adds or touches.
- [ ] 6.3 **Documentation compliance.** Confirm the per-domain deal path landed in
      `test-compatibility`, the stack requirement in `deployment-state`, and that
      `TESTING.md` states what an end-to-end deal path proves.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior and
      validation evidence, including whether the live run happened.
- [ ] 6.5 **Roadmap currency.** Update Goal 4's current-state description in
      `docs/development/ROADMAP.md`. If every gap is closed, remove the goal — its
      durable result belongs in the specs and `ARCHITECTURE.md`.
- [ ] 6.6 **Promotion.** Complete the design-promotion record below.
- [ ] 6.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| An end-to-end deal path is proven per domain, exercising shared fixtures rather than copied scenarios | `openspec/specs/test-compatibility/spec.md` — "Per-domain end-to-end deal path" |
| Every domain intended for deployment has a stack definition | `openspec/specs/deployment-state/spec.md` — "Deployable stack per market domain" |
| What an end-to-end deal path proves | `docs/development/TESTING.md` |
| Why API credits is recomposed rather than merely made to pass, and why fixtures generalize instead of scenarios copying | This change's `design.md` |
