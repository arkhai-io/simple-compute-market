## ADDED Requirements

### Requirement: Negotiation recovery is deterministic

Recovery of a persisted thread MUST use its recorded buyer and seller principals and MUST authorize a continuation only for the recorded buyer or a replacement principal bound by a completed rotation.

#### Scenario: A nonterminal thread is recovered

- **WHEN** the seller restarts with a nonterminal negotiation persisted and the thread's recorded buyer resumes it
- **THEN** the seller continues the same thread and canonical history without replaying prior policy decisions or changing accepted party ownership

## REMOVED Requirements

### Requirement: Negotiation identity migration and recovery are deterministic

**Reason**: Its migration clause governs the conversion of address-shaped negotiation parties, message authors, and accepted Terms to canonical principals, which is part of every storefront's v0.3.0 floor: each database a storefront's migration command adopts has already run it, and the command refuses any older database as unsupported, so the conversion is deleted with core storefront's pre-floor chain. Its recovery clause is kept unchanged as "Negotiation recovery is deterministic", with a scenario stating recovery itself, since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a storefront database from before the marketplace v0.3.0 release starts the storefront from a fresh database; recovery's rule is unchanged under the new requirement's name.
