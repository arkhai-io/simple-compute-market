## Context

`StorefrontDomainRuntime` currently supplies six normalization callables, while buyer entry points, storefront publication sources, negotiation policies, settlement codecs, fulfillment functions, and result decoding are assembled separately. VM, bare metal, and API credits already provide enough distinct examples to identify the stable boundary. Core must remain schema-opaque and must not import any of those implementations.

The shared storefront-client wire still has a flat legacy provision-terms form with compute vocabulary. Defining the contract without removing that path would leave two competing domain interfaces.

## Goals / Non-Goals

**Goals:**

- Publish one typed, versioned market-domain contract owned by core.
- Compose buyer and storefront roles from explicit domain capabilities.
- Fit all three current domains and run the same conformance suite against each.
- Keep optional capabilities absent rather than represented by no-op methods.
- Cut over provision terms to one domain envelope and remove the legacy form.

**Non-Goals:**

- Standardize domain payload schemas or policies.
- Require compute provisioning, capacity, or one settlement mechanism.
- Host several storefront domains in one process.
- Apply repository-wide strict typing.

## Decisions

### Extend the existing runtime instead of adding a parallel abstraction

Evolve the existing core-owned runtime into a small immutable contract composed of focused capability protocols. Preserve one domain identity/version at the root and group hooks by role. A second `DomainPlugin` abstraction would create ambiguous ownership and migration order.

### Separate deterministic semantics from role adapters

The root contract references:

- deterministic codecs for listing, message, agreed terms, materialization, receipt, and result;
- buyer hooks for commands, terms construction, policy selection, and result decoding;
- storefront hooks for publication, negotiation policy, settlement verification/plan construction, and fulfillment;
- an explicit set or mapping of optional capabilities.

Core owns protocol shapes and orchestration. Domains own implementations and payload models. Role packages may import both; domain concept packages do not import role composition roots.

### Identify domains and contract versions independently

Use a stable domain/schema identifier for payload meaning and a separate contract-version field for the plugin API. Startup rejects duplicate domain IDs, unsupported contract versions, and declared capabilities whose required hooks are missing. Payload evolution remains domain-owned.

### Use explicit optional capabilities

Compute provisioning, capacity interpretation, domain services, and mechanism-specific behavior are advertised capabilities. Absence is valid. API credits therefore does not gain fake compute methods, and generic core does not branch on concrete domain names.

### Use one versioned provision-terms envelope

The shared negotiation wire carries `{kind, version, payload}`-equivalent domain data and generic settlement selection. VM, bare metal, and API credits validate their payloads at their adapters. Flat compute parameters and legacy coercions are removed after every in-repository producer and consumer migrates.

### Verify with contract tests and import-boundary tests

A reusable conformance suite exercises identity/version rejection, codec delegation and errors, optional capability discovery, buyer/storefront assembly, and provision-envelope round trips. It runs against the three shipped domains plus a minimal fake domain to prove core extensibility without editing core.

### Clean cutover and rollback

Migrate core consumers, domain implementations, entry points, and client/server wire together. Rollback is the previous package/image set and wire version; mixed old/new in-repository versions are not supported for this non-additive cutover. No aliases or legacy envelope parsers remain afterward.

## Risks / Trade-offs

- **The contract may become a service locator.** Mitigation: expose focused immutable capabilities; keep orchestration services and infrastructure clients outside the domain object.
- **Three existing domains may still share accidental repository conventions.** Mitigation: include a minimal fake external-style domain in conformance tests and avoid source-path requirements.
- **A coordinated wire bump reduces rollout flexibility.** Accepted because all in-repository callers are controlled and retaining both shapes would prolong ambiguity.
- **Optional capabilities can become stringly typed.** Mitigation: capability identifiers map to typed protocols and startup validation, not arbitrary feature flags.
