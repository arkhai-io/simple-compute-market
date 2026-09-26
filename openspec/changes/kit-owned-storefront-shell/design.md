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
- `lifecycle.py` (VM) holds the timer loops and the pause flag; `TESTING.md` requires
  every loop an end-to-end test advances to be holdable and steppable;
  `bare-metal-mock-provisioned-deal` adds bare metal's controls.

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
- **Loop registration.** Whether a domain registers loops by name with the kit
  lifecycle, or the kit runtimes register their own loops and the domain supplies
  only timings.

## Decisions

None yet.
