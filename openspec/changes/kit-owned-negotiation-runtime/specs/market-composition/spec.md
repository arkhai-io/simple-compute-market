## ADDED Requirements

### Requirement: Kit-owned synchronous negotiation runtime

The synchronous negotiation protocol runtime — round persistence, terminal-state handling, accept chokepoints, and the guards around them — MUST live in the kit layer and be composed by a market domain. A domain MUST supply
its contract, its configuration, and its domain-specific semantics, and MUST NOT
reimplement the mechanism. Every domain implementing it MUST be composed onto the kit
implementation, and a domain that lacked it MUST gain it by composition.

#### Scenario: A domain runs a negotiation round

- **WHEN** a market domain processes a negotiation round
- **THEN** the protocol runtime is the kit implementation, with the domain supplying
  codecs, policy, and configuration

#### Scenario: A protocol-level guard is added

- **WHEN** a guard or capability is added to the negotiation runtime
- **THEN** every composing domain obtains it, rather than one domain gaining it and the
  others silently lacking it

#### Scenario: A domain has no negotiation runtime

- **WHEN** a domain without its own negotiation implementation is composed
- **THEN** it can complete a negotiation through the kit runtime
