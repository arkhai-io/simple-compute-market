## MODIFIED Requirements

### Requirement: Common settlement fields include the lifecycle projections

The settlement DSL MUST reserve common fields for option identity and mechanism-neutral values (mechanism, option ID, asset) and for the lifecycle codec's projections: `adjudication.dispute.interface`, `adjudication.dispute.account`, `early_termination.payer`, `early_termination.payee`, `early_termination.payee.notice_seconds`, `early_termination.premature_stop_penalty` and `delivery_deadline_seconds`. A registration MAY add typed fields only under its configuration-key namespace. An entitlement an option does not state MUST project false, including on an option that carries no lifecycle terms; a notice or delivery deadline it does not state MUST project as missing, never as zero.

#### Scenario: A clause filters on a lifecycle term and a mechanism field

- **WHEN** a buyer compiles a clause on `adjudication.dispute.account` and `alkahest.chain`
- **THEN** the first is evaluated as a common lifecycle projection for every mechanism's options, and the second only through the Alkahest registration's typed projection

#### Scenario: An option states no payee notice

- **WHEN** a clause contains `early_termination.payee.notice_seconds<=300` and an option grants the payee no entitlement
- **THEN** the option does not match, because its payee notice is missing rather than zero

#### Scenario: An option carries no lifecycle terms

- **WHEN** a clause contains `early_termination.payer=false early_termination.payee=false` and an option carries no lifecycle terms
- **THEN** the option matches

## ADDED Requirements

### Requirement: A compute class expands to entitlement predicates

A compute class shorthand MUST expand to predicates on `early_termination.payer` and `early_termination.payee` alone: reserved to both false, on-demand to the payer true and the payee false, spot to both true, committed spot to the payer false and the payee true. The expansion MUST be conjoined with every explicit settlement clause and MUST NOT form an alternative of its own; with no explicit clause it MUST be the one clause. It MUST NOT name a mechanism's field or a billing value. Explanation MUST show the expansion as the predicates it evaluated.

#### Scenario: A class beside two explicit clauses

- **WHEN** a buyer asks for spot with two explicit settlement clauses
- **THEN** each alternative also requires the payer and the payee entitlement
- **AND** no option survives by satisfying an explicit clause alone

#### Scenario: A class with no explicit clause

- **WHEN** a buyer asks for on-demand and names no settlement clause
- **THEN** selection evaluates one clause requiring the payer entitlement and no payee entitlement

#### Scenario: Spot does not match a committed term

- **WHEN** a buyer asks for spot and an option entitles the payee and not the payer
- **THEN** the option does not match, and it matches when the buyer asks for committed spot

#### Scenario: One class across mechanisms

- **WHEN** a buyer asks for reserved and a listing advertises an Arkhai payments option and an Alkahest option, neither stating an entitlement
- **THEN** both options satisfy the class
