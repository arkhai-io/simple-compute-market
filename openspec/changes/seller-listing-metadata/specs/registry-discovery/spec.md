## MODIFIED Requirements

### Requirement: Schema-driven listing validation
A registry MUST validate publish candidates and compile discovery filters from its configured filter-spec rather than hardcoding a concrete market schema into route signatures. A publisher MAY state three optional seller-authored detail fields beside the listing envelope: `title` (plain text, at most 200 characters), `description` (plain text, at most 4000 characters), and `metadata` (at most 50 keys; each key 1–40 characters of `[A-Za-z0-9_.-]`; each value a string of at most 500 characters, a finite number, or a boolean). The served `listing_shape` MUST declare all three, and the publish boundary MUST refuse a listing whose stated values violate these limits, naming the field. An explicit null MUST be treated as an unstated field.

#### Scenario: Publisher submits a listing
- **WHEN** a signed listing candidate is published
- **THEN** the registry validates it against the filter-spec listing shape before storing it

#### Scenario: A listing carries seller details
- **WHEN** a publisher submits a listing whose body states `title`, `description`, or `metadata` within these limits
- **THEN** the registry stores those values with the listing and returns them unchanged on `GET /listings` and `GET /listings/{id}`, under the publisher's listing signature

#### Scenario: A listing violates a detail limit
- **WHEN** a publisher submits a listing whose `title`, `description`, or `metadata` exceeds a limit above, or whose `metadata` value is null, an array, or an object
- **THEN** the publish is refused with an error naming the field, and no listing row is written

#### Scenario: A listing without seller details
- **WHEN** a publisher submits a listing stating none of the three fields
- **THEN** it publishes, stores, and reads exactly as before the fields existed

## ADDED Requirements

### Requirement: Seller details are discoverable through the filter spec

The registry MUST store a listing's seller-authored details in envelope columns of their own, so a filter declaration addresses them like any other listing field.

#### Scenario: A metadata key is declared as a filter

- **WHEN** a registry's filter spec declares a filter whose `path` is `$.metadata["<key>"]`
- **THEN** `GET /listings` filters listings on that metadata key's value, and a listing that states no value for the key behaves as the filter's `on_missing` rule says
