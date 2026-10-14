# Tasks — unbacked bare-metal listings

Depends on `encapsulate-capacity-backing` (design phase).
`bare-metal-mock-provisioned-deal`, `bare-metal-listing-shapes`,
`compose-contact-exchange-across-compute`, and
`bare-metal-publication-reads-pool-declarations` are archived. Design under review
since 2026-10-14; not yet planned.

## 1. Design

- [x] 1.1 Decide each open question in `design.md` and record the decision there.
      Decided: site-and-resource identity with optional host fields; candidates from
      the capacity declaration; a publication change over the kit negotiation
      composition.
- [x] 1.3 **Decision gate.** Resolve the 2026-10-14 design review's first findings and
      record them in `design.md`. Decided with the maintainer: the dependency on
      `bare-metal-mock-provisioned-deal` is satisfied (archived 2026-10-09); backing is
      decided by one delegate, introduced and adopted by both domains in the new
      prerequisite `encapsulate-capacity-backing`; the site emits the bare-metal view
      for unbacked supply, host or no host, built through the pool's backing
      delegate, superseding the original "candidate comes from the capacity
      declaration" decision; the `bare_metal_publication` attribute stays the opt-in
      for both backings; an unbacked resource is never judged against availability.
- [ ] 1.4 **Decision gate.** Decide each open question `design.md` lists from the
      2026-10-14 review, and record each decision there.
- [x] 1.5 **Decision gate.** Record that this change removes the refusal of unbacked
      pools `encapsulate-capacity-backing` keeps in bare-metal publication. Decided
      with the maintainer ("This change removes bare metal's temporary refusal of
      unbacked pools"); planning names the deletion as a task.
- [ ] 1.2 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations.

## 2. Closeout

- [ ] 2.1 The closeout task defined in
      `openspec/README.md#plan-closeout-requirements`, written out in full when this
      change is planned, including the system evidence that unbacked bare-metal
      discovery reaches a usable introduction, and that a buyer query bounded by
      asking rate returns backed and unbacked bare-metal listings together
      (transferred from `publish-indicative-listing-rates` 7.13).
- [ ] 2.2 **System, both domains.** Two seller sites publishing unbacked supply to
      one storefront keep distinct origin and source identity, each introduction
      reveals its own seller's contact, and seller-side delivery reaches only that
      origin's routed instances — on the VM lane and on the bare-metal lane.
      Transferred from `compose-contact-exchange-across-compute` 6.5 (originally
      `unbacked-listing-publication` 6.8). Each lane needs a topology with one
      storefront serving two seller sites, which neither has today; planning decides
      that topology, from whatever lane baseline then exists, as its own task. The
      behaviour is already proven at integration level by
      `domains/vms/storefront/tests/integration/test_introduction_origins.py` and the
      delivery kit's routing tests, so this is the live multi-service evidence.
