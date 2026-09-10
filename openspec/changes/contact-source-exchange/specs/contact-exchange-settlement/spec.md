## ADDED Requirements

### Requirement: Reviewed whole text uses the existing immutable exchange

Seller text configuration MUST use the explicit private `contact_payload: {text: <whole blurb>}` profile without runtime generation or automatic enrollment. Historical opaque maps MUST remain readable without conversion. New finalization MUST preserve the exact reviewed buyer text, seller snapshot and authoritative accepted package in one immutable exchange and atomically create exactly two awaiting-completion intents under the existing v2 fences.

#### Scenario: Pre-consent drift refuses capture

- **WHEN** buyer text/route, seller text/route or the accepted context differs from a review
- **THEN** finalization refuses capture under the existing review and provenance checks
- **AND** no exchange or recipient intent is created

#### Scenario: Forged context cannot replace accepted facts

- **WHEN** a request supplies replacement context or persisted accepted context fails its obligation digest check
- **THEN** the authenticated route rejects the request without revealing contacts or creating jobs

#### Scenario: Historical records are not enrolled

- **WHEN** an old immutable introduction or no-outbound agreement is read or recovered after configuration changes
- **THEN** its stored payload, package and identity remain unchanged
- **AND** no stronger provenance or new delivery intent is inferred

#### Scenario: Lost finalization acknowledgement recovers the same capture

- **WHEN** the server commits finalization but its HTTP response is lost
- **THEN** authenticated owner status and an exact retry after restart recover the same immutable exchange and exactly two intents

#### Scenario: Cancellation fences delayed review or finalization

- **WHEN** cancellation commits before a delayed review or finalization transaction
- **THEN** the delayed request creates no exchange or recipient intents
- **AND** cancellation after committed finalization reports committed rather than cancelled

#### Scenario: Current configuration cannot replace accepted terms

- **WHEN** current public terms/channel or SMTP credentials rotate while reviewed contact, routes and accepted package remain unchanged
- **THEN** finalization retains the accepted package without expanding the review fingerprint
- **AND** missing required profile or policy remains unavailable rather than silently selecting another configuration
