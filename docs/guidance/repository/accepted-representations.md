---
tags: [repository, persistence]
---

# Accepted representations

What this repository's services accept of a stored representation, and what a
cutover counts as live.

Persisted protocol documents, retained records, and schema changes follow [`persistence.md`](../engineering/persistence.md). Here, unsupported mandate forms remain unsupported rather than being inferred from a compatible encoding, and zero nonterminal contracts does not establish that a reader is unused: retained terminal evidence and supported buyer recovery may still require it. In a workload-lifecycle cutover the live records are the active workloads, and the external identity each carries is its known provider-operation identity ([`persistence.md`, "Atomic cutovers of live records"](../engineering/persistence.md#atomic-cutovers-of-live-records)).
