## ADDED Requirements

### Requirement: An exact selection of a time-priced option settled from the Agreement is accepted only at its total

When a seller accepts an exact settlement selection of an option whose mechanism builds no
obligation and settles from the Agreement alone, the Agreement's amount is the whole payment.
Where the selected option has one `amount` rate that scales by time, identified by its field and
not by its position among the option's rates, the seller MUST accept the selection only at that
rate over the requested duration, truncated to whole base units: the same total the seller's
reference amount names. A selection carrying another amount, a total that truncates to zero, and
an option advertising more than one `amount` rate MUST be refused before any negotiation thread,
Agreement, or settlement data is kept. A selection carrying no amount MUST be accepted at that
total. Options without a time-scaled `amount` rate, and mechanisms that build an obligation, are
unaffected.

#### Scenario: A buyer proposes half the total

- **WHEN** a buyer selects an option charging 1000000 base units an hour for 1800 seconds and
  proposes 250000
- **THEN** the seller refuses the selection and keeps no thread, Agreement, or settlement data

#### Scenario: A buyer proposes no amount

- **WHEN** a buyer selects the same option for 1801 seconds and proposes no amount
- **THEN** the seller accepts at 500277 base units, and the Agreement and its settlement data
  carry that amount

#### Scenario: The duration is priced at zero

- **WHEN** a buyer selects an option charging 1 base unit an hour for 60 seconds
- **THEN** the seller refuses the selection, whatever amount it carries, and keeps nothing
