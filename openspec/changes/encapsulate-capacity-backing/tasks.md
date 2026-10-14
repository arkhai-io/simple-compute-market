# Tasks — encapsulate capacity backing

Design phase; not yet planned. Prerequisite of `unbacked-bare-metal-listings`.

## 1. Design

- [x] 1.1 **Decision gate.** Inventory every production switch on capacity backing —
      label comparisons, binding-class tests, hard-coded backed assumptions, and
      mechanism fulfilment declarations — across core, kit, provisioning, and every
      domain, classified by what each decides. Record it in `design.md`. Decided with
      the maintainer: nine behaviours become delegate operations; comparing bound and
      source backing is a divergence, not an operation; API credits moves onto the
      delegate in this change; the storefront's copy of the vocabulary validates
      through the delegate while its database check stays ("What the delegate
      decides", "API credits moves onto the delegate in this change", "The
      storefront's copy of the vocabulary goes; its database check stays").
- [x] 1.2 **Decision gate.** Derive the delegate's operations from the inventory, so
      that no caller compares the label or tests the binding class, and name the
      delegate. Record it in `design.md`. Decided with the maintainer:
      `CapacityBacking` in `kit/resource-pools-contracts`, one class with `BACKED` and
      `UNBACKED` instances, whose operations take the caller's work as callables
      ("The delegate's operations").
- [ ] 1.3 **Decision gate.** Decide the unified behaviour for each divergence between
      VM, bare metal, and API credits, and where bare metal's refusal of unbacked
      pools is expressed while this change keeps it. Record each as its own decision.
- [x] 1.4 **Decision gate.** Decide how the `CapacityBinding` and `UnbackedBinding`
      classes relate to the delegate, and record it. Decided with the maintainer: one
      `PublicationBinding` class carrying the delegate replaces both; a refused
      admission answers 409 ("One binding class carries the delegate").
- [ ] 1.5 **Decision gate.** Decide how the site's resource publication views receive
      the pool's delegate, and record it.
- [ ] 1.6 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations, and
      reconcile the plan with the bordering changes `proposal.md` names.

## 2. Closeout

- [ ] 2.1 The closeout task defined in
      `openspec/README.md#plan-closeout-requirements`, written out in full when this
      change is planned.
