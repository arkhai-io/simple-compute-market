## ADDED Requirements

### Requirement: Documented user actions are actor-owned
Every action a product's published documentation instructs a user to perform
MUST be performed by the actor playing that user, through the entry points the
documentation names. The controller MUST coordinate only — authority checks,
release, deadlines, retry prohibition, cancellation, observation, and cleanup
trigger — and MUST have no code path that performs a documented user action. A
result produced by a controller-performed user action MUST NOT be treated as
evidence about the product.

#### Scenario: The controller is inspected for user-action capability
- **WHEN** the controller's reachable surface is examined
- **THEN** it exposes no path that performs a documented user action, including
  for setup or convenience

#### Scenario: An adapter binds to an entry point the documentation does not name
- **WHEN** an adapter reaches the product through an internal client, a test
  fixture, or a direct call to an endpoint the documentation does not instruct a
  user to call
- **THEN** the binding is rejected, because a result from it cannot support a
  claim about the documented path

#### Scenario: Setup requires pre-seeded user state
- **WHEN** a scenario needs user state established before release
- **THEN** it is established by an actor action or by product-owned preparation,
  and not by a controller path added for the purpose

### Requirement: Requests are frozen before concurrent release
Each actor's request in a concurrent scenario MUST be fixed before release and
MUST NOT change afterwards. The frozen request MUST be carried in the recorded
result. A result whose actors' requests differ in the dimension under contention
MUST NOT be reported as a contention outcome.

#### Scenario: An actor would compose its request at release
- **WHEN** an actor attempts to construct or alter its request after release
- **THEN** the attempt fails, naming the actor and the field

#### Scenario: A reviewer checks that actors were contending
- **WHEN** a recorded concurrent result is reviewed
- **THEN** each actor's frozen request is present in the record, so contention
  can be confirmed rather than assumed

### Requirement: Observation is independent of the observed
An actor's account of its own behavior MUST NOT be the sole record of that
behavior. Observation MUST be captured by a component that is not the actor
observed. Where the two records disagree, both MUST be retained and the
disagreement MUST be reportable.

#### Scenario: An actor reports an action it did not perform
- **WHEN** an actor's account names an action the independent observation does
  not show
- **THEN** both records are retained and the disagreement is reported, rather
  than either being taken as authoritative

#### Scenario: Only the actor's account exists
- **WHEN** a result carries an actor's account and no independent observation
- **THEN** the result is inadmissible as evidence about what the actor did

### Requirement: Live adapters fail closed by configuration
Selecting an adapter that could produce a live market, wallet, cloud, host,
provisioning, VM, GPU, or authenticated repository-hosting effect MUST fail on
the resolved configuration, before any process is started or connection opened.
The refusal MUST NOT depend on a runtime branch, an instruction to an actor, or
a check at the point of use.

#### Scenario: A live adapter is selected
- **WHEN** a configuration resolves to an adapter capable of a live external
  effect
- **THEN** selection fails before any subprocess is started or socket opened,
  and the refusal names the adapter and the effect class

#### Scenario: An actor is instructed not to use a live path
- **WHEN** the only thing preventing a live effect is an instruction the actor
  is asked to respect
- **THEN** the configuration is inadmissible, because instruction is not a
  control
