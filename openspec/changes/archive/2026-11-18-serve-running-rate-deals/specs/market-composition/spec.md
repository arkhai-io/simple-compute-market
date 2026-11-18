## ADDED Requirements

### Requirement: Both compute storefronts run one loop layout

The VM and bare-metal storefronts MUST each register, through the kit loop controller, the same four loops under the same names, each running one job: `deal-servicing`, the kit's servicing cycle; `delivery-recovery`, the re-drive of unfinished deliveries; `payment-reconciliation`, the advance of accepted payment deals their buyer has not settled; and `settlement-servicing`, the settlement worker alone. Each loop's interval MUST be configured by its own key, a new key defaulting to the interval its job ran at before, and a key a release accepted MUST keep its meaning.

#### Scenario: An operator steps servicing without re-driving delivery

- **WHEN** an operator holds every loop of either compute storefront and steps `deal-servicing` once
- **THEN** one servicing cycle runs and no delivery is re-driven

#### Scenario: The layout is the same in both storefronts

- **WHEN** the VM and bare-metal storefronts start
- **THEN** each reports the loops `deal-servicing`, `delivery-recovery`, `payment-reconciliation` and `settlement-servicing`

### Requirement: A storefront reports deals its configuration cannot service

A compute storefront whose configuration composes no adapter for an open deal's mechanism MUST start, MUST show each such deal repair required in its seller list naming the missing configuration, and MUST report those deals at startup in its log and its readiness report. Withdrawing a treatment from the rate servicing declaration MUST withdraw new offers and acceptances only; deals already materialized MUST keep being serviced.

#### Scenario: The payments section is removed while deals are open

- **GIVEN** a storefront holding open payment deals, once-only and rate
- **WHEN** it restarts with its payments section's servicing fields removed
- **THEN** it starts, lists each of those deals repair required naming the missing section, and reports them at startup

#### Scenario: A treatment is withdrawn

- **GIVEN** a running rate deal accepted under a declaration listing `returned`
- **WHEN** the storefront restarts with `returned` removed from its declaration
- **THEN** no new option naming `returned` publishes, and the running deal is still serviced to its end

### Requirement: Each compute composition builds its payments seller stage

The VM and bare-metal settlement compositions MUST each build their payments seller stage themselves, over the rate servicing declaration their publication and acceptance read, whenever their payments section has its servicing fields; no composition root or test helper builds a second stage.

#### Scenario: The VM composition is built without a stage supplied

- **WHEN** the VM settlement composition is constructed from a configuration whose payments section has its servicing fields
- **THEN** it builds its payments seller stage over its declaration, as the bare-metal composition does
