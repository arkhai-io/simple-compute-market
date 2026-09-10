## ADDED Requirements

### Requirement: General declarations publish only by explicit opt-in

The bare-metal storefront SHALL expose `publish-declarations --offers PATH` and startup opt-in `BARE_METAL_STOREFRONT_CONTACT_DECLARATIONS_PATH` for the existing strict schema-3 declaration carrier. Both startup file paths together SHALL fail before publication. Without either path startup SHALL publish no file. Historical v1/v2 loaders, commands, identities and physical publication checks SHALL remain unchanged.

#### Scenario: Operator declares third-party machine facts

- **WHEN** six valid public TEST declarations select an eligible configured contact profile
- **THEN** publication accepts the batch without site, pool, machine or physical-host registration
- **AND** discovery remains `vms.compute` and local negotiation remains `bare_metal.v1`

### Requirement: General declaration preflight covers the entire file

The publisher SHALL read at most 1048577 bytes and use the strict one-MiB domain parser. It SHALL validate every entry, exact context-eligible rateless contact option, configured policy/profile, absence of configured private contact/route/SMTP literals, signed registry schema and existing listing-ID conflicts before listing-intent persistence or registry POSTs. Initialization and authenticated schema reads are outside the no-publication gate. Public profile terms SHALL contain `CONTACT-ONLY: machine facts are operator declarations; ownership and availability are unverified; no payment or physical commitment.` The listing description SHALL emit the same notice. Missing contact configuration SHALL fail without inventing a contact or route.

#### Scenario: Invalid final declaration

- **WHEN** the final entry fails parsing, profile, privacy, schema or immutable existing-ID validation
- **THEN** no listing intent or registry POST occurs for any entry
- **AND** diagnostics do not echo supplied values

### Requirement: General publication preserves immutable provenance

New declarations SHALL persist the strict schema-3 intent and unbacked declaration source through existing domain admission. All new intended listings SHALL be durable before the first registry POST. Each invocation SHALL use the existing at-most-three-attempt signed upsert loop for every intended listing. Changed intent or inactive local identity SHALL refuse; omitted IDs SHALL not be withdrawn. No accepted plan or historical intent SHALL be backfilled or reinterpreted.

#### Scenario: Acknowledgement is lost after a partial publication

- **WHEN** a signed registry upsert commits but its response is lost
- **THEN** the invocation reports uncertain remote outcome and bounded confirmed count
- **AND** retry after restart reuses exact listing and option identities without duplicate listings
