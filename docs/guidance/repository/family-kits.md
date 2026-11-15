---
tags: [repository, architecture, dependencies]
---

# Family kits

What a family kit is here, when a capability belongs in one, and what it may depend
on: the scope rule of [`package-layers.md`](package-layers.md#scope) applied to a
market family. The compute family's kits are
[`ARCHITECTURE.md`, "Family kits"](../../development/ARCHITECTURE.md#family-kits).

A family kit owns reusable mechanism, authority, and optionally persistence for concepts whose scope is one market family rather than every market or one concrete domain. It is the operational counterpart to a family vocabulary package. Unqualified "kit" in this repository's documents means a repository-wide kit capability, whose abstractions are family-neutral; a family kit is not one, because it speaks its family's vocabulary.

A capability belongs in a family kit when it belongs intrinsically to the family: several sibling domains use it, or it is the family's single cross-domain authority. Code that merely looks similar across domains does not qualify. A family kit stays meaningful independently of any one domain, and a new sibling domain consumes it by contributing values, codecs, hooks, or registrations, never by adding domain-specific branches to it. It carries no concrete domain's listing schema, policy, result meaning, domain-specific infrastructure choices, or composition wiring, so it belongs to no sibling domain.

A family kit is a specialization with the family alone in its scope, so the scope rule says what it may depend on: its family's vocabulary package, repository-wide kits, core, and lower-level family-kit distributions of the same family — never a concrete domain, another family, a role implementation, or a deployed service. It may own durable state, workers, and authority lifecycles for its family. Dependencies among a family's kit distributions must be acyclic: an optional implementation distribution may depend on the family's base mechanisms and authorities, and those base distributions must not depend back on an optional implementation.

Domains define the values, codecs, hooks, and registrations a family kit consumes; composition roots select and assemble those contributions, provide configuration and external resources, and wire runtime instances. A family kit never discovers or imports its domains. A family may split its kit into more than one distribution where dependency weight or an optional implementation technology would otherwise force unrelated consumers to install dependencies they do not use; such optional implementation distributions are not a further layer.

Family vocabulary packages are specialization libraries: they define a family's shared names, schemas, identifiers, and value semantics, own no authority or persistence, and never depend on a family kit.

## Placement tests

Applied in order:

- **Outside the family.** A capability meaningful and family-neutral for every market belongs in a repository-wide kit. Behaviour invariant across marketplace roles may instead belong in core.
- **Contribution or change.** If adding a sibling domain would mean registering a new contribution, the capability belongs in the family kit; if it would mean changing the capability's internal domain semantics, it belongs in the domain.
- **Third domain.** A family kit passes only if a third domain of its family could use it without the kit learning that domain's schema or branching on its identity.
- **Wiring.** Instance wiring, process lifecycle, route mounting, and aggregation of contributions belong in the composition root.

Another market family needing apparently similar behaviour is a signal to evaluate extraction into a repository-wide kit, not an automatic promotion. Promotion is right only when the capability's vocabulary and authority semantics can be made family-neutral without depending on either family's identity or domain meaning; otherwise two family kits are correct.

## Sibling domains behave alike

Sibling domains of one family behave alike unless a reason specific to one of them is stated where the difference lives. A difference with no stated reason is a defect to reconcile, and the reconciled behaviour moves to shared code at the narrowest scope that holds it: a family kit or vocabulary package where it speaks the family's vocabulary, a repository-wide kit where it does not. The VM and bare-metal storefronts' per-clause option derivation (`ClausePublication` in `kit/settlement-runtime`) and their settlement-clause resolver (`listing_terms` in `kit/resource-pools-contracts`) are both repository-wide for that reason: neither names a compute concept, since the step takes whether its options are compute as a flag and the resolver takes the family key as data. Code that looks similar but carries a genuinely different domain meaning stays in its domains.
