## ADDED Requirements

### Requirement: The protocol ends at the mechanism's commitment act

The negotiation protocol MUST consist of discovery, negotiation, and the selected mechanism's commitment act. Every later exchange MUST be post-commitment lifecycle, governed by the `deal-lifecycle` capability and visible to arbitration only through evidence. Core MUST keep the agreement and commitment carriers schema-opaque.

#### Scenario: A buyer commits and never reports it

- **WHEN** a buyer approves a hosted mandate and sends nothing to the seller
- **THEN** the deal is committed but unstarted, and the buyer has broken no protocol step

### Requirement: Each option names its adjudication regime

A clause MUST be decided by the regime its option names. A buyer MUST refuse an option whose regime is not in the closed vocabulary its client ships. A regime MUST be chosen by choosing among options; a buyer MUST NOT edit seller-owned option parameters.

#### Scenario: A seller offers two regimes

- **WHEN** a listing carries two otherwise equal options whose clauses name different regimes
- **THEN** the buyer chooses its regime by selecting one option, and each has its own option ID
