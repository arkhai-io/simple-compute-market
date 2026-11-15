## MODIFIED Requirements

### Requirement: Compute buyers end delivery through the canonical lifecycle client

The VM and bare-metal buyer end commands MUST end a deal through the buyer half's `end`, with the accepted buyer's profile signer and storefront trust, and its once-only end MUST use the lifecycle client's `end_delivery(negotiation_id)`. The canonical verb is `end` in both domains — `market end` and `market bare-metal end` — registered from the buyer half's shared command, not a domain-only transport, so both take the same options and print the same result: the end's progress, the storefront's delivery read and whether capacity is released. `market bare-metal teardown` MUST remain a deprecated alias of `market bare-metal end` for one release: it prints a notice naming `end`, ends the deal as `end` does, and keeps the output its callers parse — the end's progress alone, exiting 0.

#### Scenario: A bare-metal buyer tears down

- **WHEN** the buyer runs `market bare-metal end` for its committed deal
- **THEN** it uses the same authenticated lifecycle client method as the VM end verb and keeps the signed response

#### Scenario: A buyer runs the deprecated teardown

- **WHEN** the buyer runs `market bare-metal teardown` for its committed deal
- **THEN** a notice names `market bare-metal end`, the deal ends exactly as `end` ends it, and the command prints the end's progress alone

#### Scenario: A buyer leaves a reserved deal

- **WHEN** a buyer ends delivery on a `once`-only hosted deal or a current Alkahest deal without a lifecycle payment adapter
- **THEN** it sends `end_delivery` without trying an unsupported payment stop or claiming a refund

#### Scenario: The storefront is down

- **WHEN** a buyer's rate-part stop is accepted but the storefront cannot receive the hint
- **THEN** the command reports the accepted stop and unacknowledged hint separately and does not claim the resource was torn down

#### Scenario: The buyer obtains a site report

- **WHEN** the buyer's lifecycle read returns a site-signed `lease_ended` report
- **THEN** the buyer stores its exact bytes and proof even if it has no independently trusted site identity to verify it, without treating it as a payment authority record

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
