## MODIFIED Requirements

### Requirement: Schema-driven listing validation

A registry MUST validate publication and dry-run candidates against its configured
filter-spec listing shape and compile discovery filters from that specification,
without hardcoding a concrete market schema into route signatures. Authentication
MUST precede publication validation. A schema-invalid publication MUST be refused
before changing listing content or publisher state.

A publisher MAY state three optional seller-authored detail fields beside the
listing envelope: `title` (plain text, at most 200 characters), `description`
(plain text, at most 4000 characters), and `metadata` (at most 50 keys; each key
1–40 characters of `[A-Za-z0-9_.-]`; each value a string of at most 500
characters, a finite number, or a boolean). The served `listing_shape` MUST declare
all three with these limits, whatever filter specification the registry loads, so
that it refuses every stated value publication refuses but a non-finite number,
which JSON cannot carry. Publication and the
dry run MUST refuse a candidate whose stated values violate these limits, naming
the field. An explicit null MUST be judged as an unstated field.

#### Scenario: Publisher submits a listing

- **WHEN** a signed listing candidate is published
- **THEN** the registry validates the complete body against the filter-spec listing shape before storing it

#### Scenario: A schema-invalid publication is submitted

- **WHEN** an authenticated publication violates the configured listing shape
- **THEN** it fails with field-path errors and leaves prior listing content unchanged

#### Scenario: A listing carries seller details

- **WHEN** a publisher submits a listing whose body states `title`, `description`, or `metadata` within these limits
- **THEN** `GET /listings` and `GET /listings/{id}` return those values unchanged, as does the seller's retained publication

#### Scenario: A listing violates a detail limit

- **WHEN** a publisher submits a listing whose `title`, `description`, or `metadata` exceeds a limit above, or whose `metadata` value is null, an array, or an object
- **THEN** the publication is refused with an error naming the field and leaves prior listing content unchanged
- **AND** the dry run of the same body reports the same errors

#### Scenario: A detail is stated as null

- **WHEN** a publisher submits a listing whose `title`, `description`, or `metadata` is null
- **THEN** the listing publishes as if the field were unstated, and the retained publication keeps the null as sent

#### Scenario: A listing without seller details

- **WHEN** a publisher submits a listing stating none of the three fields
- **THEN** it publishes, stores, and reads exactly as before the fields existed

## ADDED Requirements

### Requirement: Seller details are discoverable through the filter spec

The registry MUST keep a listing's seller-authored details in the publication
document it retains, so a filter declaration addresses them like any other listing
term and a republication that stops stating them withdraws them.

#### Scenario: A metadata key is declared as a filter

- **WHEN** a registry's filter spec declares a filter whose `path` is `$.metadata["<key>"]`
- **THEN** `GET /listings` filters listings on that metadata key's value, and a listing that states no value for the key behaves as the filter's `on_missing` rule says

#### Scenario: A seller withdraws its details by republication

- **WHEN** the owner republishes a listing stating none of the details it stated before
- **THEN** reads no longer contain them, and a filter on a metadata key it stated decides the listing by its `on_missing` rule
