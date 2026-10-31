## ADDED Requirements

### Requirement: A bare-metal purchase pays the selected option's total for its duration

The bare-metal `buy` command MUST quote the selected payment option's one time-scaled `amount`
rate, identified by its field, over the requested duration, truncated to whole base units, and
MUST negotiate that quote as the deal's absolute bounds, scaled by no further unit count. A quote
that truncates to zero, and an option charging on any field other than `amount`, MUST be refused
before any request to the seller. Before the mandate is approved, and again inside the negotiation
before an accepted round is kept, the buyer MUST refuse an accepted Agreement whose amount differs
from the quote or whose duration differs from the one requested, and MUST end the run as exited
with that reason, so no approval follows and the run is not left open.

#### Scenario: Half an hour is bought

- **WHEN** a buyer buys 1800 seconds of an option charging 1000000 base units an hour
- **THEN** the buyer negotiates 500000 as both its opening and its ceiling, with a unit count of one

#### Scenario: The seller's Agreement pays another amount

- **WHEN** the accepted Agreement for that purchase names 250000, or another duration
- **THEN** the buyer refuses it, no mandate is approved, and the run ends as exited

#### Scenario: The option charges another field

- **WHEN** a payment option carries a rate on a field other than `amount`, beside its amount
  rate or alone
- **THEN** the command refuses before any negotiation request

#### Scenario: The quote is zero

- **WHEN** a buyer buys 60 seconds of an option charging 1 base unit an hour
- **THEN** the command refuses before any negotiation request
