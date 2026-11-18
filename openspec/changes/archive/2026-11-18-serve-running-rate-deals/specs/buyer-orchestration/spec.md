## MODIFIED Requirements

### Requirement: The buyer refuses seller ends that keep the started period

The buyer's acceptance policy MUST by default refuse an option whose payee entitlement or term end has a `settles_through` other than `last_boundary`, naming the term, and MUST let the buyer waive each refusal through its own per-term waiver, `--allow-charged-preemption` for the payee entitlement and `--allow-charged-term-end` for the term end, as "Each default refusal has its own waiver" gives them.

#### Scenario: A spot option charges the started period on a seller stop

- **WHEN** a buyer with the default policy is offered a spot option whose payee entitlement settles through `started_period`
- **THEN** the buyer refuses the option, naming the payee entitlement's `settles_through`

#### Scenario: A buyer accepts charged seller stops

- **WHEN** a buyer passes `--allow-charged-preemption`
- **THEN** the same option is acceptable, and a charged term end is still refused by name

## ADDED Requirements

### Requirement: The buyer is shown the penalty's collectible bound and why a funding stop is final

Both compute buyers' pre-approval disclosure of an on-demand option MUST state that its premature-stop penalty is collectible only from the seller's earnings still held, which under the option's holds is what the deal has earned so far and nothing in its first period without a setup charge. When a deal's rate part stops with cause `terms` before the Agreement's end, the buyer's delivery and read output and the watchdog's exit MUST say that the deal stopped because its balance could not reserve the next period, that a top-up cannot revive it, and that a new deal is needed, classifying the stop with the compute-family classifier the storefronts use.

#### Scenario: An on-demand option is disclosed

- **WHEN** a default buyer is shown an on-demand option with a premature-stop penalty before approval
- **THEN** the disclosure states the penalty is collectible only from the seller's earnings still held, nothing in the first period without a setup charge

#### Scenario: A deal stops for lack of funds

- **WHEN** a buyer reads a deal whose rate part stopped with cause `terms` one period before the Agreement's end
- **THEN** the read says the balance could not reserve the next period, a top-up cannot revive the deal, and a new deal is needed
- **AND** a deal stopped at the Agreement's end is shown as having reached its term, without that message
