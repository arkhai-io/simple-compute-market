## ADDED Requirements

### Requirement: Buyer introduction commands have one implementation

Starting a revealed introduction from an accepted run, re-reading it, and
re-delivering it to the buyer's own sinks MUST have one implementation in the core
buyer role, mounted by every domain buyer whose listings can settle by introduction.
A domain buyer MUST supply only its run-recovery hook — how a recorded run is
reloaded under that domain's configuration and registry trust — and the identity of
the mechanism it mounts the commands for, and MUST NOT carry a copy of the start,
read, deleted-outcome, or delivery handling.

The core buyer role MUST NOT depend on a settlement mechanism package or branch on a
concrete mechanism identifier to provide these commands; the mounting domain supplies
the mechanism identity.

Negotiating an introduction option opens a negotiation in the domain's own terms, so
each domain buyer whose listings can settle by introduction MUST expose a command
that negotiates exactly one advertised rateless introduction option and records the
accepted run in the shared run log, from which the core commands recover it.

#### Scenario: A domain buyer mounts the introduction commands

- **WHEN** a domain buyer whose listings can settle by introduction is installed
- **THEN** its command surface offers negotiating an introduction option, starting
  the introduction, and re-reading it with optional re-delivery
- **AND** the start, read, and re-delivery behaviour is the core implementation

#### Scenario: The storefront deleted the introduction's payloads

- **WHEN** a buyer starts or re-reads an introduction whose payloads the storefront
  deleted, through any domain buyer
- **THEN** the command reports the deleted outcome and exits successfully
- **AND** nothing is delivered

#### Scenario: Core stays mechanism-free

- **WHEN** the core buyer role's imports are checked
- **THEN** it imports no settlement mechanism package to provide the introduction
  commands
