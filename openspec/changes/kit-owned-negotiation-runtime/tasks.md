# Implementation Tasks

## 1. Compare before moving

- [x] 1.1 Re-verified: VM had 1,324 lines, API credits had 652, and bare metal had no runtime.
- [x] 1.2 Recorded the control-flow and domain-edge drift in `design.md`.
- [x] 1.3 Kept protocol guards/state transitions in kit and moved codecs, price
      references, resource/quota/key validation, agreement terms, artifacts,
      persistence, and holds behind domain hooks.

## 2. Extract onto the seam

- [x] 2.1 Extracted the mechanism into `kit/negotiation-runtime`.
- [x] 2.2 The kit imports only identity and policy foundation contracts; concrete
      storefront/domain/configuration behavior is injected.
- [x] 2.3 Recorded each drift disposition and its rationale in `design.md`.

## 3. Compose every domain

- [x] 3.1 Composed every existing VM and API-credit production caller onto the kit
      runtime and exposed the same resolver/hook contract to the bare-metal
      composition track, which had no caller in this checkout.
- [x] 3.2 Deleted the VM, API-credit, and interim core lifecycle modules rather than
      retaining aliases or compatibility imports.
- [x] 3.3 Supplied schema-opaque opening/continuation resolvers and domain hook
      interfaces for bare metal to consume without importing another domain.

## 4. Packaging follow-through

- [x] 4.1 Added kit/root build, CI/PyPI matrix, storefront dependency/reinit, Docker
      wheel-refresh, and distribution-package coverage.
- [x] 4.2 Regenerated the kit lock and updated both storefront locks for the new wheel.

## 5. Validation

- [ ] 5.1 Run the kit, VM, API-credit, bare-metal, and conformance suites. Disclose
      any suite not run.
- [x] 5.2 Removed every VM/API-credit/core lifecycle implementation and legacy import.
- [ ] 5.3 Validate behavior against the recorded drift matrix, per concern, not against
      a general impression that the suites pass.
- [ ] 5.4 Run `openspec validate --all --strict`.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`; read the kit
      modules' docstrings directly for references to the domain they were moved from.
- [x] 6.2 Kit imports are foundation-only; domain imports remain in composition adapters.
- [x] 6.3 Promoted the ownership and recovery requirements to
      `openspec/specs/market-composition/spec.md`.
- [x] 6.4 Compressed closeout notes to the final mechanism/hook split, drift
      disposition, and package surfaces.
- [x] 6.5 Updated Goal 4's current state and removed the completed negotiation-copy gap.
- [x] 6.6 Completed the design-promotion record and permanent architecture/testing docs.
- [ ] 6.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

- [ ] 6.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=kit-owned-negotiation-runtime` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 6.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Kit-owned synchronous negotiation runtime | `openspec/specs/market-composition/spec.md` |
| Where the existing implementations diverged and which behavior was chosen | This change's `design.md` |
