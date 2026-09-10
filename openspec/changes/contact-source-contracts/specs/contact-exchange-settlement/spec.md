## ADDED Requirements

### Requirement: Whole contact text is a strict profile of the private map

A text client SHALL submit exactly `{"text": <whole blurb>}` as its private contact payload. The blurb SHALL preserve 1–512 Unicode scalar values including whitespace and escaping, contain at least one non-whitespace scalar, and reject oversize or lone-surrogate input without truncation. Older opaque maps SHALL retain their meanings. Review/finalization and signed identity envelopes SHALL remain version 2.

#### Scenario: A reviewed Unicode blurb is changed

- **WHEN** a buyer changes any scalar or its own route after review
- **THEN** finalization refuses the prior binding without capturing contacts

### Requirement: Explicit context eligibility freezes authoritative declaration facts

Only new options with `context_contract: "accepted-listing.v1"` SHALL require typed accepted listing context. The storefront SHALL capture that context from immutable publication intent and listing binding at acceptance, validate the exact selected option, and bind its canonical digest into the obligation. Protected reads SHALL validate the persisted package against the accepted obligation, never reconstruct from a registry or current seller configuration.

#### Scenario: Provenance is absent or inconsistent

- **WHEN** an eligible option lacks matching immutable declaration/option provenance
- **THEN** acceptance fails before committing a plan or capturing contact data

#### Scenario: The authoritative listing projection cannot be decoded or validated

- **WHEN** an eligible option's stored listing projection contains malformed JSON or invalid domain structure
- **THEN** acceptance raises `NegotiationRequestError` with exactly `invalid_contact_provenance`, without input values or negotiation/obligation persistence

#### Scenario: The projection database is unavailable

- **WHEN** projection loading fails with a database operational error
- **THEN** the database failure remains distinct from invalid provenance and no negotiation or obligation is persisted

#### Scenario: Historical acceptance is read

- **WHEN** an older option or accepted plan has no context eligibility
- **THEN** its terms, IDs, digests, legacy read behavior and no-outbound semantics remain unchanged

### Requirement: Declaration identifiers are not physical authority

A bare-metal contact declaration SHALL use a declaration identifier with no machine or physical-host identifier and no site, pool or Physical Resource authority. It SHALL retain `vms.compute` discovery, `bare_metal.v1` negotiation and non-access terms. Site-backed listings SHALL retain required machine and physical-host identifiers.

#### Scenario: A declaration claims a physical backing

- **WHEN** a declaration supplies a machine, physical-host, site, pool or Physical Resource identity
- **THEN** admission refuses it rather than treating a placeholder as authority
