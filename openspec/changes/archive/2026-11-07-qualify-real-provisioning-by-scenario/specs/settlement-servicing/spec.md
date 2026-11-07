## ADDED Requirements

### Requirement: The settle wait resolves a settlement by its reference or its negotiation

An administrator's settle wait MUST resolve the reference it is given to a settlement
the same way in every storefront that binds it, whatever the settlement's mechanism: by
the settlement evidence whose settlement reference it is, and otherwise by the
settlement evidence of the negotiation it names. The settlement runtime kit MUST own
that resolution and the wait's terminal states, `ready` and `failed`; a storefront MUST
supply only its lookups of settlement evidence by settlement reference and by
negotiation, and its delivery status for a resolved settlement. A reference that
resolves to no settlement MUST be treated as a poll that found nothing terminal.

#### Scenario: A payments deal is waited on by its negotiation

- **WHEN** an administrator waits on an `arkhai.payments.v1` deal's negotiation in any
  storefront, and the deal's delivery becomes ready
- **THEN** the wait reports ready

#### Scenario: A payments deal is waited on by its transaction

- **WHEN** an administrator waits on an `arkhai.payments.v1` deal by its transaction,
  the settlement reference its evidence records
- **THEN** the wait resolves the same settlement and reports the deal's delivery status

#### Scenario: An Alkahest deal is waited on by its escrow

- **WHEN** an administrator waits on an Alkahest deal by its escrow
- **THEN** the wait resolves the settlement whose evidence records that escrow, as it
  did before

#### Scenario: The reference names no settlement

- **WHEN** an administrator waits on a reference that names no settlement evidence and
  no negotiation with any
- **THEN** the wait polls until its deadline and reports `ready: false`
