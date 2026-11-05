## MODIFIED Requirements

### Requirement: Dispute timing terms are bounded

`case_hold_max_seconds` MUST be a nonnegative integer or `null`. A `dispute_window_seconds` or `case_hold_max_seconds` below the dispute authority's advertised minimum MUST be refused at publication and by the buyer. On a compute option, `dispute_window_seconds` MUST be at least `delivery_deadline_seconds` plus the authority's minimum window, so no `once` part pays out before non-delivery can be established and filed on; publication and the buyer MUST refuse an option failing this.

#### Scenario: A negative case hold is refused

- **WHEN** a seller configures `case_hold_max_seconds: -1`
- **THEN** publication refuses the option

#### Scenario: A zero case hold is below the minimum

- **WHEN** a seller configures `case_hold_max_seconds: 0` for an authority that advertises `null` as its minimum
- **THEN** publication refuses the option

#### Scenario: The dispute window ends before the delivery deadline can be filed on

- **WHEN** a compute option carries a one-hour dispute window, a three-hour delivery deadline and an authority advertising a one-day minimum window
- **THEN** publication refuses the option, naming the window that would let its setup part pay out before the seller could be found late, and a buyer offered it refuses it

#### Scenario: A supported shorter authority minimum still covers delivery timing

- **WHEN** an authority advertises a sixty-second minimum and a compute option has a
  six-hundred-second delivery deadline
- **THEN** publication and the buyer refuse a dispute window below six hundred and
  sixty seconds and accept that threshold when all other terms are valid
- **AND** the payment hold derives from the full accepted window, not only the
  authority minimum
