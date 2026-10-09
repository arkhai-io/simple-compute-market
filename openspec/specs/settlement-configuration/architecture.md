# Settlement Configuration Architecture

The [normative contract](spec.md) defines the configuration, readiness, migration, publication, and selection invariants shared by settlement mechanisms. This document explains why one typed hierarchy composes distinct mechanisms without merging their authorities or runtimes.

## One hierarchy, peer mechanisms

Marketplace roles use one `[Settlement]` root. Its `priority` list contains canonical mechanism IDs and its typed peer subsections contain only mechanism-owned policy and public client inputs:

```toml
[Settlement]
priority = ["arkhai.payments.v1", "alkahest.v1"]

[Settlement.arkhai_payments]
enabled = true

[Settlement.alkahest]
enabled = false
```

Configuration keys are stable operator vocabulary: `arkhai_payments` maps to `arkhai.payments.v1`, and `alkahest` maps to `alkahest.v1`. Canonical IDs remain the wire and runtime vocabulary. A quoted table keyed directly by the canonical ID would make dotted-path editing and environment overlays awkward; a generic list of dictionaries would discard typed validation.

Identity, wallet, and chains remain siblings of settlement. Identity authenticates marketplace roles. Wallet and chain resources support explicitly selected EVM effects. Neither is mechanism policy, and a non-EVM payment role must not need placeholder EVM resources.

New defaults select nothing. An operator must explicitly enable and order mechanisms, while migration preserves the previously effective selection. This avoids silently publishing a financial option merely because its package is installed.

## Registration and ownership

Each installed mechanism explicitly registers its canonical ID, config key and schema, applicable roles, preflight, client factory, listing-option builder, buyer compatibility hook, typed public clause projections, and optional operator commands. Mechanism-qualified clause fields stay under the config-key namespace and declare their roles, operators, and value types. Shared configuration code owns grammar integration, ordering, exact option correlation, and common status; it does not interpret chain, arbiter, condition, provider, or financial-authority fields.

A composition root injects only the resources a registration declares. Alkahest may receive wallet and chain clients. Arkhai payments resolves owner-scoped WorkOS credentials and trusted receipt policy through `market_arkhai_payments.settlement_config`. The buyer's payer account is domain input, independent of marketplace identity and service policy: `[vms].payer_account` or `[apicredits].payer_account`. Seller clients use the accepted option's payee account. API-credit seller clients are request-scoped and close after polling, attachment, and any reversal; there is no startup-global payment account. Omitting a registration removes that mechanism from status, publication, and selection rather than installing a placeholder.

Registration shares configuration, readiness, option construction, and selection,
not execution or a universal lifecycle. Fresh publication and buyer compatibility
intersect registrations with the corresponding supported role table. Registration
alone grants no execution support. Accepted work retains its Agreement-selected
entry independently of current priority or enablement; unavailable accepted support
refuses before effects rather than falling through to escrow.

Arkhai payments leaves conditional-escrow client and obligation hooks unset;
domain composition consumes the exact Agreement and signed receipt. Alkahest and
contact exchange use the shared obligation runtime. A compatible kit may opt
into a stage convention, whose kit home is chosen only when implemented. There
is no required convention protocol or speculative adapter dependency, including
for contact, seller-first or fused stages.

## Readiness, publication, and selection

Preflight normalizes mechanism-owned checks into a public-safe result: canonical ID, configured, enabled, ready, blocker codes and messages, capabilities, and contract/schema versions. Mechanism detail is allowlisted. Status is observational: it does not publish, create transient browser actions, submit transactions, or mutate provider or settlement state.

The storefront evaluates every enabled registration, then combines ready registrations with validated publication clauses. Only a clause owned by an enabled, ready mechanism with a supported seller entry can produce an option. Options follow configured mechanism priority and source clause order. One unready mechanism is suppressed and remains visible through sanitized status; a ready peer with a valid clause remains usable. An enabled mechanism without a clause does not inherit another mechanism's price or publish an implicit option. Arkhai payment clauses include the payee account and asset explicitly. The shared payment builder scales hourly prices from decimal major units by asset precision and accepts generic integer base-unit prices per unit without scaling. Domain adapters own unit vocabulary: API credits accepts `credit`, `token`, or `request`.

Priority is pre-acceptance policy only. The buyer first filters advertised options by installed/enabled compatibility and authoritative resource constraints. Explicit repeatable settlement clauses then act as ordered alternatives; every predicate in a clause must match one option. Configured priority ranks survivors only when no explicit clause supplies order. Accepted Terms pin one exact option. Later enablement, readiness, ordering, or clause changes cannot switch or reinterpret an accepted or in-flight obligation.

## Role-appropriate operator surfaces

The storefront owns seller settlement administration under one command tree:

```text
market-storefront settlement status
market-storefront settlement alkahest check
market settlement status
market settlement alkahest escrow show
```

Mechanism subcommands remain asymmetric. Arkhai payments has no marketplace payer setup, instrument, or Stripe onboarding surface. Buyer templates expose selection inputs and omit seller account, onboarding, authority-administration, publication, and provider fields.

## Precedence and secret boundaries

Resolution order is explicit CLI override, environment or Secret overlay, role/user configuration files — for a storefront, `storefront.toml` then a chart-rendered `storefront.json` — then committed defaults. Lists replace lower-layer lists in full. Typed metadata drives role templates, dotted-path validation, environment schema fragments, the VM storefront chart's generated values-schema definition, and reference output so these surfaces drift together. That definition refuses secret-marked and role-inapplicable fields and closes typed sections; it carries no defaults, because a chart passes the configuration through and the storefront owns them.

Public principals, payment receipt trust pins, fee/dispute policy, account references, assets, condition profiles, chain names, and deployed addresses may be ordinary configuration. Private identity, wallet, or request credentials cross only approved Secret or environment boundaries. Payment-provider, administrator, webhook, ledger database, and service-migration configuration belongs to the payments service and is rejected by marketplace schemas.

## Configuration migration and recovery

Settlement configuration migration is explicit, previewable, conflict-rejecting, validated, backed up with restrictive permissions, and atomically replaced. Storefront publication migration separately converts legacy scalar pricing and CSV `accepted_escrows` input into complete typed clauses. A source that would require one ambiguous price to construct multiple mechanism options is rejected for manual resolution. Both migrations preserve unrelated TOML or CSV bytes where possible, require an explicit backup before writing, and are no-ops when repeated. Runtime accepts only the typed hierarchy and publication inputs. Legacy Stripe settings are rejected with removal diagnostics, not mapped to a payment account, credential, mandate, or transaction.

Deployment stages migration tooling before the rejecting runtime, previews and backs up every role file, publication config, and inventory, quiesces publication and config automation, migrates all surfaces, validates them, and then activates the clean-cutover release. Before activation, rollback restores matching configuration, inventories, and artifacts together. After new publication or settlement effects begin, recovery rolls forward.

Run logs may retain the public configuration schema version and mechanism-set fingerprint, but exact accepted Agreement bytes, settlement data, and domain/obligation progress remain authoritative. Recovery uses the accepted canonical mechanism and stable operation identities even when that mechanism is disabled for new deals.


## Related contracts

- [Settlement servicing](../settlement-servicing/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Market composition](../market-composition/spec.md)
- [Deployment and state](../deployment-state/spec.md)
