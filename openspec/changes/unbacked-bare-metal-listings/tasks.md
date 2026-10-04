# Tasks — unbacked bare-metal listings

Blocked on `bare-metal-listing-shapes` and `compose-contact-exchange-across-compute`
Sections 1–3b; `bare-metal-publication-reads-pool-declarations` is complete. Design
phase; not yet planned.

## 1. Design

- [x] 1.1 Decide each open question in `design.md` and record the decision there.
      Decided: site-and-resource identity with optional host fields; candidates from
      the capacity declaration; a publication change over the kit negotiation
      composition.
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
