---
tags: [repository, testing]
---

# Testing market composition

How the common storefront shell's tests divide the multi-domain composition this
capability owns between the levels
([`test-levels.md`](../../../docs/guidance/engineering/test-levels.md)).

## Multi-Domain Storefront Composition

The common shell owns a boundary matrix rather than duplicating complete domain
scenarios at every level:

- core storefront unit tests cover contribution discovery, duplicate/unknown
  rejection, exact-object registry resolution, immutable listing/thread
  bindings, lifecycle carriers, publication fan-out, and schema-opaque result
  dispatch;
- VM storefront tests cover installed contribution wiring, exact public
  `offering_mode`, configured source selection, negotiation/settlement
  adapters, selected-site capacity calls, and restart recovery;
- bare-metal domain/storefront tests own only bare-metal codecs, publication
  semantics, and the production lifecycle hook supplied by that package;
- deployment tests render one combined image/command/database, both explicit
  registrations, disabled-domain absence, and secret canary exclusion;
- the system lanes observe a VM deal and a selected-site bare-metal deal, each
  in its own lane through mock-provisioned delivery, including result,
  teardown, and restored capacity; real bare-metal access and its revocation
  are the protected lane's evidence, which no mock-provisioned deal stands in
  for.

Every cross-swap test asserts the unselected policy, repository mutation,
capacity/provider call, result decoder, and teardown spy remain untouched.
Restart fixtures route from recorded bindings even when current publication
configuration changes.
