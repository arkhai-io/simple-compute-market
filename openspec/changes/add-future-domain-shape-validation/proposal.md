## Why

The harness is being built against one domain. If supporting a second requires
editing its core, then every new market the product opens costs a harness
project, and the harness becomes a thing the product waits on.

The property worth proving is narrow and testable: **adding a domain requires an
adapter, an oracle, redaction and cleanup rules, and focused tests — and no edit
to the generic runtime.** That property is only credible if something exercises
it, and it decays silently the moment a concrete-domain branch appears in the
core.

This change proves it two ways. An arbitrarily-named fake adapter that the core
has never heard of round-trips an opaque payload without a core edit. Disabled
fixtures for the product's other real domains validate and dry-plan without
executing anything.

Two things shape the design.

**The product already has three domains, and two of them have no harness
adapter.** `domains/vms`, `domains/bare_metal`, and `domains/apicredits` each
declare a `MarketDomainContract` with a `DomainIdentity` and a set of
`DomainCapability` values. The VM contract declares `PUBLICATION`; the
capability vocabulary also has `BUYER`, `STOREFRONT`, `SETTLEMENT`,
`FULFILLMENT`, `COMPUTE_PROVISIONING`, and `NEGOTIATION`. Fixtures for bare
metal and API credits therefore use real product identities rather than invented
ones, which makes the compatibility claim about the product rather than about a
mock.

**Fixtures for domains the product does not have are a different and riskier
thing.** Inference and optional-provider shapes have no product referent. A
fixture for one is a shape with nothing to be right or wrong about, and
elaborating it is how speculative scope grew on the abandoned branch — 25 schemas
and a profile registry for a harness that had never run. Those fixtures are
admitted here for exactly one purpose: proving the seam accepts a namespace the
core has never seen. They may not encode a design for a domain that does not
exist.

## What Changes

- **A generic seam proof.** One arbitrarily-named fake adapter, carrying an
  opaque namespaced payload through the runtime and back, with no core edit and
  no concrete-domain branch anywhere in the generic path.
- **Version and capability failure validation.** An adapter declaring an
  unsupported contract version, or a capability the runtime does not know, fails
  clearly and names what it declared.
- **Disabled fixtures for the product's other domains**, using the real
  `DomainIdentity` and declared capabilities of `bare_metal` and `apicredits`.
  They validate and dry-plan. They have no adapter, and attempting to execute
  one produces no effect at all.
- **A bounded non-executable fixture** for a domain the product does not have,
  admitted only to prove the seam accepts an unknown namespace, and constrained
  by schema from carrying domain design.
- **A feature-onboarding proof.** The intake workflow run against an arbitrary
  fixture, plus a simulated deprecated product target, demonstrating that
  support is narrow and that an incompatible product change fails clearly rather
  than degrading.
- **Import and identity purity tests.** The generic runtime imports no concrete
  domain, and a domain identity does not leak into a generic code path.

Not in scope: an adapter for bare metal or API credits, any execution of any
future-domain fixture, any credential, network, process, or cleanup executor for
them, and any plugin discovery or registration mechanism.

## Impact

- Affected specs: `test-compatibility`
- Affected code: `tools/issue-discovery/src/issue_discovery/`,
  `tools/issue-discovery/schemas/`, `tools/issue-discovery/config/`,
  `tools/issue-discovery/tests/`
- Depends on `add-harness-buyer-action-slice` — the seam is proved generic by
  contrast with a working concrete adapter, and there is nothing to contrast
  with until one exists.
- **This is a testing seam, not a plugin platform.** No discovery, no registry,
  no lifecycle hooks, no third-party contract. An adapter is a module the
  configuration names. The distinction matters because a plugin platform is a
  product with its own compatibility obligations, and nobody has asked for one.
- **Zero-effect is asserted on effects, not on exceptions.** Attempting to
  execute a disabled fixture must leave no process, no file, no connection, and
  no state change. A test asserting only that an error was raised would pass
  against an implementation that acted and then complained.
- Behaviour change to record: none in the product.
- Risk accepted and bounded: fixtures for non-existent domains are the smallest
  speculative surface in this programme, and they are capped by schema rather
  than by intent — see `design.md`.

## Permanent documentation impact

- [ ] `docs/development/TESTING.md` — what adding a domain to the harness costs,
  and what the generic runtime may not contain
- [ ] Existing subsystem specification — `test-compatibility`
- [ ] `docs/development/ISSUE_DISCOVERY.md` — the feature-onboarding workflow
- [ ] `docs/development/ARCHITECTURE.md` — none owed; the harness is a tool and
  introduces no dependency-layer rule
- [ ] New subsystem specification — none owed
- [ ] `docs/development/ROADMAP.md` — none owed; the harness holds no goal row

### Knowledge to promote

See the design-promotion record in `tasks.md`.
