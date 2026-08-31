# CLI Query Language Architecture

The [normative contract](spec.md) defines two comparison-only languages. This document explains why they share syntax while retaining separate schema authorities and execution boundaries.

## One grammar, two authorities

Both languages use ordered, space-separated comparisons and the same typed scalar/list values. The grammar deliberately excludes boolean expression trees, interpolation, and executable syntax. Reuse stops at parsing and typed comparison; it does not merge field ownership.

A resource query derives its complete vocabulary from the active registry filter specification. The registry controls aliases, operators, types, missing-value behavior, canonical parameters, and the ETag that protects those semantics. Shared buyer code therefore does not gain a VM field table.

A settlement clause derives common option fields from the settlement runtime and qualified public fields from installed mechanism registrations. Registrations own projection and validation, but projections are pure functions of advertised listing data. They cannot construct clients, contact a provider or chain, or expose opaque mechanism state.

## Correlation and ordering

One resource query is a conjunction pushed to each compatible registry. One settlement clause is a conjunction over one advertised `SettlementOption`; comparisons from different array elements cannot satisfy it. Repeated settlement clauses are pre-acceptance alternatives in source order.

```text
resource query ── registry filter-spec compile + ETag ──> resource listings
                                                               │
                                                               ▼
settlement clauses ── installed/enabled compatibility ──> option survivors
                                                               │
                                                               ▼
                                      negotiation policy and exact acceptance
```

This ordering preserves distinct diagnostics. “No resource listing matched” and “resources matched but settlement was incompatible” are different outcomes. Once Terms accept an option, clause order and current mechanism priority have no recovery authority.

## Publication uses the same clause carrier

A seller publication clause carries one complete mechanism option request. Common fields identify mechanism, asset, decimal rate, and unit; mechanism input supplies only its registered public construction fields. Command clauses and config defaults are whole-list defaults, while a resource record's list replaces them in full.

Rates remain human asset quantities until the owning mechanism normalizes them exactly once. Stripe applies the currency exponent; Alkahest applies authoritative token decimals. The shared layer never rounds, guesses an asset scale, or reuses one scalar as two mechanism prices.

## Semantic pushdown and explanation

Resource compilation pushes declared semantics to the existing registry query contract and binds the filter-spec ETag. This says where a predicate is evaluated, not whether an index exists. Settlement predicates remain buyer-local until a future filter specification can represent one correlated option-element predicate atomically.

Explanation follows the same stages as execution but stops before negotiation, persistence, prerequisite resolution, or any provider/chain effect. It reports canonical inputs, semantic pushdown, local constraints, survivor counts, option identity, and stable sanitized rejection categories. It never reports physical query plans, credentials, private RPC details, action URLs, or opaque provider payloads.

## Command ownership

Normal discovery, purchase, resume, service, reclaim, and publication surfaces accept the two DSLs plus mechanism-neutral lifecycle controls such as the buyer action policy. Mechanism-specific setup, diagnostics, and raw mutation live below `settlement <mechanism>`. Namespace placement does not create another settlement runtime or allow a utility to reinterpret accepted state.

## Related contracts

- [Registry discovery](../registry-discovery/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Settlement configuration](../settlement-configuration/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
