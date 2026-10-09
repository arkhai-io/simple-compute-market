## ADDED Requirements

### Requirement: Bare-metal negotiation preserves demand and authority ownership

A bare-metal opening MUST carry a versioned `bare_metal.v1` provision envelope whose
closed payload contains a positive lease duration, one requested access method, and its
validated buyer-owned input; for SSH the only buyer-owned access input is a public key.
The authority-authenticated listing and seller policy MUST supply the listing, site,
Resource Pool, Physical Resource, physical host, executor machine, seller, availability,
rate, settlement alternatives, condition, and deadline. Canonical agreed terms MUST bind
those seller-authoritative facts to the original demand without accepting buyer
duplicates as authority. A resumed bare-metal negotiation MUST use the recorded thread,
parties, listing, original envelope, history, settlement selection, and accepted terms,
and MUST NOT reconstruct demand from current defaults, profile, or a changed listing.

#### Scenario: Seller accepts a valid SSH demand

- **WHEN** a buyer proposes a duration within the selected listing bounds, requests listed SSH access, supplies a valid public key, and selects an advertised settlement alternative
- **THEN** both parties derive identical bare-metal terms containing the original duration and access demand and the trusted listing's immutable resource and commercial bindings

#### Scenario: Demand contains an access reference

- **WHEN** a buyer submits an `access_ref`, password, private key, provisioning endpoint, or seller-owned resource or routing field in its domain payload
- **THEN** the opening is rejected before negotiation policy or persistent thread creation

#### Scenario: Terms do not match the chosen listing

- **WHEN** returned terms name a different machine, Physical Resource, listing, seller, access method, settlement option, or deadline from the trusted inputs
- **THEN** the buyer rejects the terminal response and does not materialize settlement

#### Scenario: Listing changes during interruption

- **WHEN** an interrupted run resumes after the registry listing changes or closes
- **THEN** the buyer continues or inspects the recorded seller thread under its original trusted inputs and does not silently adopt the changed listing
