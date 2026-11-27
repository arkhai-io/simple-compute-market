# Search RFQs in the database

## Why

`add-buyer-compute-rfqs` filters RFQs as the registry filters listings: status in SQL, the
configured filters in Python over every open record. On a public registry anyone can search
without signing, so every search pays for every open RFQ, and a flood of RFQs slows search for
every reader. RFQs can launch without this, at the volumes an admitted registry sees, but not
grow without it.

RFQs name regions by ISO 3166-1 and UN M49 codes, matched hierarchically. Listings name their
region as free text, so an RFQ and the supply that could meet it are matched only where the two
happen to agree.

## What Changes

- **RFQ search filters in the database**, with the indexes it needs, so a search's cost does
  not grow with the number of open RFQs that do not match it.
- **Listings name regions by the same codes as RFQs**, so the two match, unless
  `add-buyer-compute-rfqs` already moved them.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: database-side RFQ filtering; listing regions as codes.
- `buyer-compute-rfqs`: search semantics unchanged, cost bounded.

## Dependencies and Related Changes

- Depends on `add-buyer-compute-rfqs`.
- `index-registry-filters` holds the deferred, measured design for indexing listing filters on
  PostgreSQL. Whether this change shares or precedes that design is its first open question.

## Permanent documentation impact

- [ ] The repository's architecture document
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: database-side RFQ filtering to `registry-discovery` and `buyer-compute-rfqs`.
- D2: shared region codes to `registry-discovery`.
