## ADDED Requirements

### Requirement: The storefront keeps each registry's last successful publication

A storefront MUST keep, for each listing and each registry it publishes to, the
listing payload of its most recent successful publication there, recorded only when
an attempt succeeds. A failed publication attempt MUST NOT clear or replace it. A
seller prices and pins a negotiation from that payload, which is what a buyer read at
the registry, not from its own stored listing record.

#### Scenario: A failed republication keeps the last successful payload

- **WHEN** a storefront republishes a listing and the registry refuses or cannot be
  reached
- **THEN** the storefront still holds the payload of its last successful publication
  to that registry

#### Scenario: A listing with no successful publication

- **WHEN** a shape-priced listing has no successful publication recorded, as after an
  upgrade from a release that did not record one
- **THEN** the seller takes no new negotiation on it until a publication succeeds
