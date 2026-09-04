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

- [ ] 5.1 Parent integration owns the kit, VM, API-credit, bare-metal, and conformance suites.
- [x] 5.2 Removed every VM/API-credit/core lifecycle implementation and legacy import.
- [ ] 5.3 Parent integration owns behavioral validation against the recorded drift matrix.
- [ ] 5.4 Parent integration owns repository-wide strict OpenSpec validation.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 Parent integration owns `make check-comment-hygiene`.
- [x] 6.2 Kit imports are foundation-only; domain imports remain in composition adapters.
- [x] 6.3 Promoted the ownership and recovery requirements to
      `openspec/specs/market-composition/spec.md`.
- [x] 6.4 Compressed closeout notes to the final mechanism/hook split, drift
      disposition, package surfaces, and parent-owned validation.
- [x] 6.5 Updated Goal 4's current state and removed the completed negotiation-copy gap.
- [x] 6.6 Completed the design-promotion record and permanent architecture/testing docs.
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
| Kit-owned synchronous negotiation runtime | `openspec/specs/market-composition/spec.md` |
| Where the existing implementations diverged and which behavior was chosen | This change's `design.md` |
