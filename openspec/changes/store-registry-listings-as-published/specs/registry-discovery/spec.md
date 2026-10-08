## ADDED Requirements

### Requirement: Accepted listing content is retained

A registry MUST NOT acknowledge a publication while discarding listing content its served
filter-spec listing shape admits. Every listing field a registry accepts at publish MUST be stored
and returned by its listing reads; a field it will not store MUST be refused at publish with an
error naming the field.

#### Scenario: A publisher sends a top-level field the schema does not name

- **WHEN** a publisher publishes a listing carrying a top-level field outside the registry's stored
  carriers
- **THEN** the registry either stores the field and returns it on every read of that listing, or
  refuses the publication naming the field, and never acknowledges the publication while discarding
  the field

#### Scenario: A listing is republished

- **WHEN** a publisher republishes an existing listing
- **THEN** every field of the republished listing that the registry acknowledged is what its reads
  return
