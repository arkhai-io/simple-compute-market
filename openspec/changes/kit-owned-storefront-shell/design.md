# Design

Design phase; not planned.

## Context

- Core owns the shell's foundation: `core_storefront.app_composition`
  (`StorefrontAppConfig`), `domain_registry` (the frozen mode/domain/version
  registry), `domain_plugins` (`StorefrontDomainContribution` discovered through
  `market.storefront_contributions`), `app_lifecycle`, and `app_startup`. Every
  storefront starts through `StorefrontAppConfig`.
- Each storefront nonetheless mounts its own controllers: the VM storefront's six
  (`listings`, `negotiate`, `negotiations`, `settle`, `system`, `admin`), API
  credits' six, and bare metal's `api.py`. They decode the same core models, call the
  same kit runtimes, and differ in the domain hooks they pass.
- Executable assembly differs in shape more than substance: VM's `server.py` (497),
  `startup.py` (409), `container.py` (108); API credits' `server.py` (364),
  `startup.py` (298), `container.py` (103); bare metal's `server.py` (139) and
  `runtime.py` (541).
- The provisioning service composes `vm_adapter_bundle` and `bare_metal_adapter_bundle`
  into one process through `compose_adapter_bundles`; a bundle contributes handlers,
  not a server.
- The timer-loop lifecycle is extracted ahead of this change by
  `kit-owned-storefront-loop-lifecycle`: one kit controller per storefront process,
  composed by all three storefronts, with a framework-free lifecycle route service
  each binds. What remains here is moving that registration into the kit composition
  root.

## Questions to settle before planning

- **Where a domain's extra routes go.** Contributions have routes the shared set does
  not (VM admin resource routes, bare-metal introduction routes, API-credit issuance
  evidence). The contribution declares them and the shell mounts them; the question is
  whether the shell also owns their authentication dependencies or the contribution
  does.
- **Whether the shell owns the operator CLI.** `market-storefront config/escrow/
  settlement/logs/publish` are VM-only in form and mechanism-shaped in content;
  API credits has a 196-line CLI, bare metal a publication CLI. Likely a kit CLI with
  contribution-registered groups, on the buyer executable's pattern; decide here or
  defer to a sibling.
- **Where each route's typed client lives.** A documented need from
  `bare-metal-listing-shapes`. `TESTING.md` requires a service's routes to be
  exercised through its typed client, never hand-built requests. Two route families
  have typed clients only inside buyer packages:
  - the bare-metal fulfillment routes, whose client is `BareMetalFulfillmentTransport`
    in `arkhai-bare-metal-buyer`;
  - the introduction routes, whose client calls live in `core_buyer`.
  A third route has no typed client at all: reading an introduction as the seller,
  since the buyer's `IntroductionTransport` always signs as the buyer. The
  storefront that serves them can reach them in tests only by taking a buyer
  package as a test dependency, which is the interim that change adopted, and
  hand-builds the seller read as marked debt. The
  recommended direction is that each route this shell mounts, shared or a
  contribution's extra route, has its typed client in the package that owns the
  route: introductions beside `kit/contact-exchange`'s route service, bare-metal
  fulfillment in the bare-metal domain package. Buyers then import those clients
  rather than owning them. This belongs here rather than earlier because the shell
  decides where those routes live; moving the clients first would move them twice.
  Planning retires the interim test dependency.
- **Deal controls arrive as kit route services.** `bare-metal-mock-provisioned-deal`
  moves the stage-event read, evaluate-negotiate, force-accept, settle verify,
  evaluate-settle (with a per-domain fulfillment-preview hook), settle wait, admin
  reserve, and the capacity-released callback into the kits that own their mechanisms,
  as framework-free route services every storefront binds, with wire paths and client
  methods unchanged. Decided there on 2026-10-01 rather than waiting for this change.
  The shell mounts those services; it does not extract them again, and its drift
  inventory skips them.
- **Settlement divergences already resolved.** From `bare-metal-listing-shapes`:
  - a settlement request restates no negotiated term, in every domain;
  - Alkahest-path fulfillment starts when settlement is verified, which
    `bare-metal-mock-provisioned-deal` implements for bare metal.
  The shared settle route adopts both, so neither is a drift to decide.
- **Loop registration.** Whether a domain keeps registering its loops with the kit
  loop controller, or the kit runtimes register their own loops and the domain
  supplies only timings.

## Decisions

None yet.
