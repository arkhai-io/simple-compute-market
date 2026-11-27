# Design: search-rfqs-in-the-database

## Context

The registry narrows listings by status and publisher in SQL and evaluates the filter
specification's JSONPath filters in Python. `index-registry-filters` keeps the
specification's `indexed` declaration inert until a measured PostgreSQL workload justifies
indexes. `add-buyer-compute-rfqs` validates and filters RFQs with the same specification (its
D4), and lets anyone search open RFQs where supply discovery is public (its D3).

The review of pull request #401 on 2026-11-27 found that a search's cost grows with every open
RFQ, and the owner settled that RFQs launch without database-side filtering and gain it in this
change.

## Decisions

### D1 — RFQ search filters in the database

A search narrows open RFQs by its filters in the database, so its cost follows what matches,
not what is open.

### D2 — Listings and RFQs share region codes

Listings name regions by the codes RFQs use, matched by the same hierarchy, unless
`add-buyer-compute-rfqs` has already moved them (its Q3).

## Open Questions

### Q1 — Relation to `index-registry-filters`

Whether RFQ filtering shares that change's PostgreSQL indexing design, precedes it, or is
specific to RFQs; and whether it needs that change's measured activation condition.

### Q2 — SQLite and PostgreSQL

How database-side filtering behaves on each, while registries run on both.

### Q3 — Listing region migration

How listings published with free-text regions move to codes, and what a seller's
configuration states.

## Verification

Integration tests prove filter results equal to the Python evaluation on both databases, and
that a search's work does not grow with non-matching open RFQs.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 | `openspec/specs/registry-discovery/spec.md`; the `buyer-compute-rfqs` capability's specification |
| D2 | `openspec/specs/registry-discovery/spec.md`; the compute family's listing configuration documentation |
| Goal 9 | `docs/development/ROADMAP.md`, Goal 9 |
