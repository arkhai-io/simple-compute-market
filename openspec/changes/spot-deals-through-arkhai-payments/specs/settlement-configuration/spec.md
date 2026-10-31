## ADDED Requirements

### Requirement: Hosted rate parameters are explicit and unit-safe
SCM MUST admit period and reserve_ahead_seconds together or neither and require positive fixed-unit values. Rate options MUST have a finite maximum term. Materialization MUST reject fractional Agreement starts. Optional setup_amount MUST be a disclosed positive minor-unit amount in the selected asset; omission MUST mean no setup part. Approval expiry and dispute holds MUST remain separate.

#### Scenario: Only one rate parameter is set
- **WHEN** an option supplies period without reserve_ahead_seconds or the converse
- **THEN** publication and mandate derivation refuse it with the missing parameter named

#### Scenario: Calendar units cannot define a billing period
- **WHEN** an option declares a calendar month or year period
- **THEN** the kit refuses it rather than approximating it in seconds

#### Scenario: A rate Agreement has a fractional start
- **WHEN** rate materialization receives a fractional-second start_utc under an integer-second payment contract
- **THEN** it refuses rather than round upward past the accepted capacity window or rewrite signed Agreement bytes
- **AND** once-only fractional timestamp handling is unchanged

#### Scenario: Rate end treatment is explicit
- **WHEN** a rate option is published or accepted
- **THEN** only early_termination.settles_through supplies term-end treatment through the deal-lifecycle codec and is checked against vendored end capabilities
- **AND** an unknown value or unexpressible treatment refuses instead of defaulting from current configuration

#### Scenario: A seller opts out of setup
- **WHEN** a complete rate option omits setup_amount
- **THEN** derivation emits no setup part
- **AND** neither compute domain requires a minimum spend

### Requirement: Rate materialization requires a servicing contract declaration
SCM MUST refuse rate mandate materialization without a composition's rate-servicing declaration validated under the recurring-servicing declaration contract. This gate MUST also apply to accepted-but-unmaterialized work. Removing publication enablement MUST NOT abandon already materialized deals.

#### Scenario: An accepted option outlives its declaration
- **GIVEN** a previously accepted rate option and no current servicing declaration
- **WHEN** settlement attempts to materialize its mandate
- **THEN** materialization refuses before approval or delivery

#### Scenario: The declaration validator refuses a target
- **GIVEN** a proposed declaration rejected by the neutral lane/target/mode validator
- **WHEN** the materialization door is called
- **THEN** it refuses before deriving or approving a rate mandate

#### Scenario: A lane-only proposed declaration names the wrong identity
- **GIVEN** a proposed declaration whose fixture payments identity differs from configured SERVICE_IDENTITY or whose mode is not test mode
- **WHEN** the materialization door layers its payments-specific identity/mode check on neutral validation
- **THEN** it refuses before mandate derivation or approval
- **AND** production cannot admit the lane-only proposed declaration

#### Scenario: Publication is disabled after materialization
- **WHEN** a previously materialized rate deal is recovered with new publication disabled
- **THEN** its existing servicing continues under accepted terms
