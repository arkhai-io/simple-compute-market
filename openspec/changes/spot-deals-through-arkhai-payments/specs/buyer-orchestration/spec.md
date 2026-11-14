## ADDED Requirements

### Requirement: Payment approval applies the run's terms policy
Both compute buyers MUST pass the run's terms policy, with its per-term waivers, to payment approval. Approval of a rate mandate MUST refuse each term a default buyer refuses that the run did not waive, naming it, and MUST NOT refuse a term the run waived. With no policy supplied, approval MUST refuse every term a default buyer refuses. Approval MUST NOT rank the dispute authority again: selection ranked it against the listing's registry, and the exact mandate check binds it to the accepted option.

#### Scenario: A run waives a charged term end
- **GIVEN** an accepted rate option whose term end charges its started period and whose payee stop returns
- **WHEN** a buyer whose run waived the charged term end approves its mandate
- **THEN** approval admits it

#### Scenario: A run waives a different term
- **GIVEN** an accepted rate option whose payee stop and term end both charge their started period
- **WHEN** a buyer whose run waived only the charged term end approves its mandate
- **THEN** approval refuses it, naming the charged payee stop
