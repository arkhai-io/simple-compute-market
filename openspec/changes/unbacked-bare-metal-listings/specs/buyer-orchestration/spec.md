## ADDED Requirements

### Requirement: A buyer funds only what it derives

A buyer MUST fund an Alkahest escrow only from terms it derives itself, through its
domain's mechanism hooks, from its accepted proposal or selection and the release
condition the selected listing advertised, and MUST NOT fund terms a seller supplied.
The buyer MUST require the seller's accept reply to carry a settlement plan, and its
derivation to equal the plan's obligation before funding, on every path that funds an
escrow, through the plan check its domain supplies; a reply carrying none MUST be refused
before funding, naming `seller_plan_missing`. A buyer MUST record the selected listing's
advertised release conditions in its run-log at acceptance, and a resumed run MUST derive
the escrow from its recorded accepted proposal and those recorded conditions, at the
recorded Agreement's exact amount, and hold it to the recorded seller plan. A resumed run
whose run-log predates the recorded conditions and records no escrow MUST NOT fund one: it
MUST end naming that the run was accepted before release conditions were recorded.

#### Scenario: A seller's plan names another recipient

- **WHEN** a seller's accept reply carries a plan whose release condition pays a recipient
  other than the one its listing advertised
- **THEN** the buyer creates no escrow and ends the run naming the mismatch

#### Scenario: An API-credit buyer proposes an escrow

- **WHEN** an API-credit buyer's escrow proposal is accepted
- **THEN** the buyer derives the escrow, checks it against the seller's plan, and funds
  its own derivation

#### Scenario: A seller's accept reply carries no plan

- **WHEN** a seller accepts an Alkahest escrow and its reply carries no settlement plan
- **THEN** the buyer creates no escrow and ends the run naming `seller_plan_missing`

#### Scenario: A run is resumed with only an accepted proposal

- **WHEN** a buyer resumes a run whose run-log holds the accepted proposal, the Agreement,
  the seller's plan, and the listing's recorded release conditions, but no escrow
- **THEN** it derives the escrow from the accepted proposal and the recorded conditions at
  the Agreement's exact amount, requires it to equal the seller's plan, and creates it,
  rather than refusing

#### Scenario: A run-log predates recorded release conditions

- **WHEN** a buyer resumes a run whose run-log holds an accepted proposal and seller terms
  but no recorded release conditions and no escrow
- **THEN** it creates no escrow and ends the run naming that it was accepted before
  release conditions were recorded

### Requirement: Two domains may not register one root command

The core buyer application MUST refuse at startup when two installed domain plugins
register the same root-level command name, naming both domains and the command, rather
than letting the later registration replace or shadow the earlier one.

#### Scenario: Two plugins register `settlement`

- **WHEN** the buyer CLI starts with two installed domain plugins that each register a
  root-level `settlement` command group
- **THEN** it refuses to start, naming the command and both domains

#### Scenario: Bare metal's settlement commands are namespaced

- **WHEN** the buyer CLI starts with the VM and bare-metal plugins installed
- **THEN** it starts, VM's settlement commands are at the root, and bare metal's are
  under `market bare-metal settlement`
