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
- **A mechanism-named seam on the neutral lifespan.** *Gates the executable-assembly
  step.* `core_storefront.app_lifecycle.StorefrontLifecycleCallbacks` has a
  `build_alkahest_clients` field, and every storefront root fills it by reading its
  own `[Settlement].alkahest` section and wallet configuration and calling
  `market_storefront_kit.build_alkahest_clients`
  (`vms/storefront/server.py`, `apicredits/storefront/server.py`,
  `bare_metal/storefront/runtime.py`). That factory, `kit/storefront/alkahest_clients.py`,
  is why `kit/storefront` declares `arkhai-kit-alkahest` and `alkahest-py`, which the
  kit-areas text forbids and `ARCHITECTURE.md` records as a divergence: a kit that is
  not the Alkahest kit holds Alkahest in its scope. Arkhai payments and contact
  exchange have no such slot; they are composed through `MechanismRegistration` and
  each storefront's `settlement_composition.py`. Suggested resolution:
  `move-escrow-into-alkahest` gives each registration "a typed resource model,
  replacing the untyped `resources` bag", and that model is the slot. The lifespan
  builds each enabled registration's resources in configured mechanism order and
  the container holds them under the mechanism ID; `alkahest_clients.py` moves to
  `market_alkahest.clients` and the Alkahest registration's resource model is its
  chain-client map. `kit/storefront` then drops both dependencies, the three
  duplicated prologues collapse into one Alkahest-owned function, and the kit-areas
  sentence becomes true as written. Decide whether the lifespan step lands here or
  in `move-escrow-into-alkahest`, which owns the registration's shape; this change
  must not design a second resource mechanism. If the edge is kept, the kit-areas
  item for `kit/storefront` is amended to say "foundation capabilities and mechanism
  kits" so the document and the code agree.
- **The VM storefront is the compute-family shell, living under one domain.**
  *Gates the executable-assembly step.* The VM storefront's package is
  `market_storefront`, the only domain package with a market-neutral name, and
  that name is accurate: `ARCHITECTURE.md` describes the storefront role as one
  compute-family shell that discovers installed `market.storefront_contributions`,
  and the VM storefront's `pyproject.toml` declares `arkhai-bare-metal` and
  `arkhai-bare-metal-storefront` — with no import of either — so that the image
  the shared chart deploys installs the bare-metal contribution. Those
  declarations are not stale; they are how a host installs a plugin. But a
  package under `domains/vms/` composing a sibling domain is the scope rule's own
  example of a violation, and `enforce-package-layers` carries the row under this
  change. The resolution is this change's central question stated in placement
  terms: when every domain storefront becomes a contribution plus an entry point,
  the shell is a composition that belongs either with the compute family
  (`domains/compute/storefront`, if it stays a compute shell) or with the
  repository-wide roles (if API credits composes it too), and the VM contribution
  that remains under `domains/vms/` is named `arkhai_vms_storefront` like its
  siblings and declares no sibling domain. Decide which home before planning
  executable assembly; `align-package-paths-with-layers` moves it there.
  The two rows are a scope finding on `arkhai-vms-storefront` → `arkhai-bare-metal`
  and → `arkhai-bare-metal-storefront`; the first also has a declarations row
  giving its runtime reason, which goes with it. While they stand,
  `domains/vms/storefront/tests/unit/test_architecture_imports.py`'s
  `test_vm_storefront_imports_no_bare_metal_composition` stays, because the row
  that excuses the declaration would also excuse an import. Retire that test in the
  same commit that deletes the rows.

## Decisions

None yet.
