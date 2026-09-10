## ADDED Requirements

### Requirement: General declaration input has finite strict bounds

The bare-metal domain SHALL expose a no-I/O UTF-8 bytes parser for `ContactDeclarationOffers`: integer `schema_version:3` and `offers` containing 1–256 exact `{declaration, profile}` objects. The parser SHALL reject files above 1048576 bytes, duplicate JSON keys, invalid UTF-8, nonfinite numbers, unknown fields, unsupported versions and scalar coercion with `invalid_contact_declaration_file` and no input values. Both listing and declaration IDs SHALL be unique in the document. General file listing IDs SHALL use `declared-contact-` with a nonempty identifier suffix. Profile names SHALL match `[a-z0-9][a-z0-9_.-]*` and contain at most 128 characters. Existing v1/v2 synthetic file parsing and identity SHALL remain unchanged. Parsing SHALL perform no publication, persistence, configuration resolution or physical admission.

#### Scenario: More than five declarations are supplied

- **WHEN** six public test declarations with unique IDs and valid profiles are parsed
- **THEN** the complete schema-3 document is accepted without creating physical registrations

#### Scenario: A batch exceeds a boundary

- **WHEN** the document contains zero or 257 entries, exceeds one MiB, repeats an identity or contains an invalid last entry
- **THEN** the parser refuses the entire document with a fixed diagnostic

### Requirement: Declaration admission preserves immutable option provenance

A declaration listing SHALL have no machine or physical-host identifier, exactly non-access methods, and only the typed machine/region projection. Admission SHALL require an exact version-3 publication intent containing the public declaration and 1–32 unique strict context-eligible contact options owned by the listing seller. The immutable source envelope SHALL use `bare_metal.introduction-declaration.v1` and null site, pool and Physical Resource authority. Changed intent under an immutable listing identity SHALL be refused. Site-backed listing requirements SHALL remain unchanged.

#### Scenario: Local projection differs from intent

- **WHEN** a declaration's machine facts, listing identity or selected options disagree with its publication intent
- **THEN** admission refuses before listing persistence rather than manufacturing authoritative context

#### Scenario: A Python declaration Mapping contains unsupported input

- **WHEN** a supported Mapping, including `UserDict`, contains unknown declaration fields, invalid machine facts, or a bytes or non-string declaration identifier
- **THEN** validation refuses it before coercion or field discard, and admission persists no listing or binding
- **AND** historical listings retain their existing parsing and serialization behavior
