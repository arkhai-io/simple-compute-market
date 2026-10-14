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

Listed in an earlier order; closeout works the parts in `openspec/README.md`'s order.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them, including the kit modules' docstrings for references to the
      domain they were moved from. Do not edit code here: anything to rewrite returns
      the change to implementation.
- [x] 6.2 Kit imports are foundation-only; domain imports remain in composition adapters.
- [x] 6.3 Promoted the ownership and recovery requirements to
      `openspec/specs/market-composition/spec.md`.
      Archival uses `--skip-specs`: this task synchronized the specification by hand.
- [x] 6.4 Compressed closeout notes to the final mechanism/hook split, drift
      disposition, and package surfaces.
- [x] 6.5 Updated Goal 4's current state and removed the completed negotiation-copy gap.
- [x] 6.6 Completed the design-promotion record and permanent architecture/testing docs.
- [ ] 6.7 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 6.8 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=kit-owned-negotiation-runtime` and resolve every
      match, then `openspec validate kit-owned-negotiation-runtime --strict`.
- [ ] 6.9 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 6.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 6.11 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe.
- [ ] 6.12 **Archival.** Last, once every other part is checked: `openspec archive
      kit-owned-negotiation-runtime -y --skip-specs` moves the change under
      `openspec/changes/archive/` without re-applying the deltas 6.3 synchronized by
      hand; point the index row at the archived directory, and run
      `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Kit-owned synchronous negotiation runtime | `openspec/specs/market-composition/spec.md` |
| Where the existing implementations diverged and which behavior was chosen | This change's `design.md` |
