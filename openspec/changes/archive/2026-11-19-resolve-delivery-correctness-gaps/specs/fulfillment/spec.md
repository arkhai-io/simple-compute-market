## ADDED Requirements

### Requirement: An equivalent acceptance that waited on another returns the first

Fulfillment acceptance MUST judge the aggregate as the row lock it takes shows it, not as an earlier read in the same transaction held it. An equivalent `begin_fulfillment` for a reservation that waited on that lock while another acceptance of the same reservation committed MUST return that acceptance's fulfillment, with its `fulfillment_id`, and MUST NOT accept, prepare, or persist the fulfillment a second time.

#### Scenario: A retry waited on the first acceptance's commit

- **GIVEN** an acceptance that read a reservation's aggregate before another acceptance of it committed
- **WHEN** it then takes the aggregate's row lock and accepts an equivalent request
- **THEN** it returns the committed acceptance's `fulfillment_id`, and the aggregate keeps that identity and its prepared operation
