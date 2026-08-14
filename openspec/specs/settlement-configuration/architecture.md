# Settlement Configuration Architecture

The [normative contract](spec.md) defines the configuration, readiness, migration, publication, and selection invariants shared by settlement mechanisms. This document explains why one typed hierarchy composes distinct mechanisms without merging their authorities or runtimes.

## One hierarchy, peer mechanisms

Marketplace roles use one `[Settlement]` root. Its `priority` list contains canonical mechanism IDs and its typed peer subsections contain only mechanism-owned policy and public client inputs:

```toml
[Settlement]
priority = ["fiat.stripe.v1", "alkahest.v1"]

[Settlement.stripe]
enabled = true

[Settlement.alkahest]
enabled = false
```

Configuration keys are stable operator vocabulary: `stripe` maps to `fiat.stripe.v1`, and `alkahest` maps to `alkahest.v1`. Canonical IDs remain the wire and runtime vocabulary. A quoted table keyed directly by the canonical ID would make dotted-path editing and environment overlays awkward; a generic list of dictionaries would discard typed validation.

Identity, wallet, and chains remain siblings of settlement. Identity authenticates marketplace roles. Wallet and chain resources support explicitly selected EVM effects. Neither is mechanism policy, and a hosted non-EVM role must not need placeholder EVM resources.

New defaults select nothing. An operator must explicitly enable and order mechanisms, while migration preserves the previously effective selection. This avoids silently publishing a financial option merely because its package is installed.

## Registration and ownership

Each installed mechanism explicitly registers its canonical ID, config key and schema, applicable roles, preflight, client factory, listing-option builder, buyer compatibility hook, typed public clause projections, and optional operator commands. Mechanism-qualified clause fields stay under the config-key namespace and declare their roles, operators, and value types. Shared configuration code owns grammar integration, ordering, exact option correlation, and common status; it does not interpret chain, arbiter, condition, provider, or financial-authority fields.

A composition root injects only the resources a registration declares. Alkahest may receive wallet and chain clients. Hosted Stripe receives the marketplace signer and manifest-pinned hosted client. Omitting a registration removes that mechanism from status, publication, and selection rather than installing a placeholder.

Registration extends the existing settlement mechanism registry. It does not create another lifecycle: every configured client enters the same mechanism-neutral settlement runtime, obligation journal, retry policy, and aggregate status authority.

## Readiness, publication, and selection

Preflight normalizes mechanism-owned checks into a public-safe result: canonical ID, configured, enabled, ready, blocker codes and messages, capabilities, and contract/schema versions. Mechanism detail is allowlisted. Status is observational: it does not publish, create transient browser actions, submit transactions, or mutate provider or settlement state.

The storefront evaluates every enabled registration, then combines ready registrations with validated publication clauses. Only a clause owned by an enabled, ready mechanism can produce an option. Options follow configured mechanism priority and source clause order. One unready mechanism is suppressed and remains visible through sanitized status; a ready peer with a valid clause remains usable. An enabled mechanism without a clause does not inherit another mechanism's price or publish an implicit option.

Priority is pre-acceptance policy only. The buyer first filters advertised options by installed/enabled compatibility and authoritative resource constraints. Explicit repeatable settlement clauses then act as ordered alternatives; every predicate in a clause must match one option. Configured priority ranks survivors only when no explicit clause supplies order. Accepted Terms pin one exact option. Later enablement, readiness, ordering, or clause changes cannot switch or reinterpret an accepted or in-flight obligation.

## Role-appropriate operator surfaces

The storefront owns seller settlement administration under one command tree:

```text
market-storefront settlement status
market-storefront settlement stripe onboard
market-storefront settlement stripe status
market-storefront settlement alkahest check
market settlement status
market settlement alkahest escrow show
```

Mechanism subcommands remain asymmetric where the mechanisms differ. Stripe onboarding can return a transient Account Link; Alkahest has no invented equivalent. The hosted client supplies workflow primitives, but marketplace command ownership remains with the storefront. Buyer templates expose selection inputs and omit seller account, onboarding, authority-administration, publication, and provider fields.

## Precedence and secret boundaries

Resolution order is explicit CLI override, environment or Secret overlay, role/user TOML, then committed defaults. Lists replace lower-layer lists in full. Typed metadata drives role templates, dotted-path validation, environment and Helm schema fragments, and reference output so these surfaces drift together.

Public principals, trust pins, manifest and capability pins, account references, currencies, condition profiles, chain names, and deployed addresses may be ordinary configuration. Private identity, wallet, or request credentials cross only approved Secret or environment boundaries. Hosted provider, administrator, webhook, database, and service-migration configuration belongs to the hosted authority and is rejected by marketplace schemas.

## Clean cutover and recovery

Settlement configuration migration is explicit, previewable, conflict-rejecting, validated, backed up with restrictive permissions, and atomically replaced. Storefront publication migration separately converts legacy scalar pricing and CSV `accepted_escrows` input into complete typed clauses. A source that would require one ambiguous price to construct multiple mechanism options is rejected for manual resolution. Both migrations preserve unrelated TOML or CSV bytes where possible, require an explicit backup before writing, and are no-ops when repeated. Runtime accepts only the new hierarchy and typed publication inputs; old and new names never participate in hidden precedence.

Deployment stages migration tooling before the rejecting runtime, previews and backs up every role file, publication config, and inventory, quiesces publication and config automation, migrates all surfaces, validates them, and then activates the clean-cutover release. Before activation, rollback restores matching configuration, inventories, and artifacts together. After new publication or settlement effects begin, recovery rolls forward.

Run logs may retain the public configuration schema version and mechanism-set fingerprint, but durable plans and operation journals remain authoritative. Recovery uses the accepted canonical mechanism and stable operation identities even when that mechanism is disabled for new deals.

## Related contracts

- [Settlement servicing](../settlement-servicing/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Market composition](../market-composition/spec.md)
- [Deployment and state](../deployment-state/spec.md)
