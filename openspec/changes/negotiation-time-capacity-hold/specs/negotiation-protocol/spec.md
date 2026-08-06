## ADDED Requirements

### Requirement: Capacity is held from first commitment, not from agreement

Capacity for a negotiation MUST be held from the point a counterparty first proposes
terms differing from the offering's own, rather than from terms acceptance. Discovering
an offering, inquiring about it, and verifying its feasibility MUST NOT hold capacity or
require committed funds. A counter-offer that restates the offering's existing terms MUST
NOT place a hold.

#### Scenario: Counterparty proposes different terms

- **WHEN** a counterparty first proposes terms differing from the offering's own
- **THEN** capacity for the negotiation is held from that point, before terms are agreed

#### Scenario: Buyer inquires and verifies without proposing

- **WHEN** a buyer discovers an offering and verifies its feasibility without proposing
  different terms
- **THEN** no capacity is held and no funds are required

#### Scenario: Counter-offer restates existing terms

- **WHEN** a counter-offer proposes the offering's own terms unchanged
- **THEN** no hold is placed

#### Scenario: Second buyer negotiates the same scarce capacity

- **WHEN** one negotiation holds the last capacity matching a shape and another buyer
  proposes terms for it
- **THEN** the second cannot hold that capacity, and learns so during negotiation rather
  than at settlement

### Requirement: One reservation spans a negotiation

A negotiation MUST hold at most one capacity reservation at a time. A change to the
requested capacity shape MUST supersede the existing reservation rather than adding
another, and a repeated or retried proposal MUST NOT admit a second reservation. The
reservation MUST be released when the negotiation reaches a terminal state without
agreement, including abandonment by an absent counterparty, rather than being left to
lapse at its own bound.

#### Scenario: Requested shape changes mid-negotiation

- **WHEN** a negotiation's requested capacity shape changes after a hold exists
- **THEN** the existing reservation is superseded and the negotiation still holds exactly
  one

#### Scenario: A proposal is retried

- **WHEN** the same proposal is delivered again
- **THEN** the existing reservation is returned and no additional capacity is held

#### Scenario: Negotiation is abandoned by an absent counterparty

- **WHEN** a negotiation is marked abandoned after a counterparty stops responding
- **THEN** its reservation is released promptly rather than held until its own bound
  expires

#### Scenario: Negotiation reaches agreement

- **WHEN** a negotiation concludes successfully
- **THEN** the reservation it already holds is carried into settlement rather than a new
  one being reserved
