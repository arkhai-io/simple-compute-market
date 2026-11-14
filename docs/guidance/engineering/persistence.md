---
tags: [engineering, persistence]
---

# Persistence

How stored representations are kept readable, how a schema changes, and how a
cutover of live records is made safely. How a migration runs at a deployment is
[Migrations](migrations.md).

## Accepted representations and application views

A persisted protocol document may be projected into a validated application view
without making that view the protocol evidence. The owner retains the canonical
bytes and verifies their outer identity and any nested result identity before
exposing typed fields. Publication, storage, and resolution preserve that original
document; clients match the requested digest before converting it. This keeps
defaults, omissions, explicit nulls, timestamp spelling, and other wire details
stable even when the application view evolves.

## A retained record stays readable

Compatibility applies while a retained record may still be read. A writer change
either preserves that representation or keeps a compatible reader through the
retention period. Deletion and tombstoning remain the owning component's explicit
lifecycle, and a form the reader never supported stays unsupported rather than being
inferred from a compatible encoding. No open record using a form does not establish
that its reader is unused: retained terminal evidence and recovery a client still
supports may require it. The rule calls for no inventory of every stored artifact,
nor for automatic measurement of when a reader retires.

## Schema changes

Schema changes are additive by default. A non-additive change uses expand and
contract across releases, unless an explicit contract lets the database be discarded
and rebuilt. Operational seeding driven by configuration belongs in runtime
initialization; a migration seeds only the deterministic system rows a new schema
constraint requires.

## Atomic cutovers of live records

A schema cutover that transfers ownership of live records between persistence models
treats each record and the external identities it carries — a provider's operation
id, say — as authoritative: it validates the complete candidate population and writes
the new records atomically before retiring the old table, and any unsafe ambiguity
rolls back the entire conversion.
