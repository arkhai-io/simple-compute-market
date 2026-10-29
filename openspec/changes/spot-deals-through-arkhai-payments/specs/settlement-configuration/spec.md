## ADDED Requirements

### Requirement: Hosted rate parameters are explicit and unit-safe
SCM MUST admit period and reserve_ahead_seconds together or neither, require positive fixed-unit period and reservation lead, and enforce reserve_ahead_seconds at least exposure_seconds. Optional setup_amount MUST be a disclosed positive minor-unit amount in the selected asset; omission MUST mean no setup part. Approval expiry and dispute holds MUST remain separate.

#### Scenario: Only one rate parameter is set
- **WHEN** an option supplies period without reserve_ahead_seconds or the converse
- **THEN** publication and mandate derivation refuse it with the missing parameter named

#### Scenario: Calendar units cannot define a billing period
- **WHEN** an option declares a calendar month or year period
- **THEN** the kit refuses it rather than approximating it in seconds

#### Scenario: A seller opts out of setup
- **WHEN** a complete rate option omits setup_amount
- **THEN** derivation emits no setup part
- **AND** neither compute domain requires a minimum spend

### Requirement: Rate materialization requires a servicing contract declaration
SCM MUST refuse rate mandate materialization without a composition's rate-servicing declaration. A proposed declaration MUST be accepted only under the explicit lane profile bound to its in-lane double and test mode; SCM MUST refuse it for other endpoints or livemode evidence. Published production activation MUST wait for the deployed hosted contract revision.

#### Scenario: An accepted option outlives its declaration
- **GIVEN** a previously accepted rate option and no current servicing declaration
- **WHEN** settlement attempts to materialize its mandate
- **THEN** materialization refuses before approval or delivery

#### Scenario: Proposed configuration points outside the lane
- **WHEN** a proposed declaration is used outside the lane profile or with a target other than its double
- **THEN** startup refuses that configuration

#### Scenario: Proposed evidence claims live mode
- **WHEN** a proposed-contract run receives livemode true
- **THEN** the evidence is refused even if another setting would accept live mode
