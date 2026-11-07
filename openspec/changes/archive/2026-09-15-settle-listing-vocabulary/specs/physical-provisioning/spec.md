## MODIFIED Requirements

### Requirement: Validated executor registration

Service composition MUST reject duplicate executor registrations, duplicate fulfillment-provider identities, and incomplete adapter bundles before accepting traffic. An executor adapter MUST be selected by the `offering_mode` it serves together with its action; no surface may name that selector `executor_kind`, `offering_type`, or `virtualization_type`. Executor and provider registries MUST remain separate authority dimensions: registering or resolving a provider does not claim, infer, or override an executor's offering mode. Provider fulfillment and executor dispatch remain separate paths unless composition explicitly joins them through a supported lifecycle.

`executor` names this action-dispatch abstraction and nothing else when it is the head noun. It MUST NOT stand in for the offering mode, the machine, or the delivery handler: the mode is an offering mode, the machine is a host, and the handler is a provider. The abstraction keeps the name because it validates parameters, submits work, and validates results and credentials; only its selector moves.

`executor_`-prefixed compounds naming the abstraction's own targets, references, or actions MUST retain the name, because `executor` carries its action-dispatch sense in them rather than standing in for another concept. `executor_ref` is the executor's reference, `executor_target` is the target of an executor action, and an executor action envelope carries an executor action; none of these is the mode, the machine, or the handler as a head noun. This requirement's prohibition therefore applies to the head noun and MUST NOT be read as a prohibition on the prefix.

#### Scenario: An executor-prefixed compound names the abstraction's own target

- **WHEN** a durable reservation or lease records the target or reference an executor action acts on
- **THEN** those fields retain their `executor_`-prefixed names
- **AND** the offering-mode selector on the same record does not, because its head noun is the mode

#### Scenario: Two adapters claim one executor kind

- **WHEN** composition registers duplicate ownership for one `offering_mode` and action pair
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Two adapters claim one provider identity

- **WHEN** composition registers duplicate ownership for a fulfillment-provider identity
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Provider and executor registrations coexist

- **WHEN** service composition registers executor adapters and fulfillment providers
- **THEN** each registration remains in its own namespace and provider availability does not select or replace an executor adapter

### Requirement: VM release delegates to durable fulfillment teardown

For VM reservations, lease release SHALL initiate teardown through a narrow fulfillment-teardown port. The VM release adapter SHALL use the durable `fulfillment_id` as the release tracking identifier and SHALL NOT submit or poll a provider job directly. Release-status lookup SHALL be selected by the reservation's `offering_mode`, the same value the capacity claim carries and the Resource Pool declares; VM lookup SHALL read fulfillment aggregate state while bare-metal lookup MAY read its executor job service.

#### Scenario: Unexpected teardown submission failure remains diagnosable

- **WHEN** composition, persistence, or an unexpected implementation failure prevents VM teardown submission
- **THEN** the failure SHALL propagate to lease lifecycle handling and be recorded as `release_submit_error` rather than being converted to an absent job identifier

#### Scenario: Release status is selected by the offering mode

- **WHEN** lease lifecycle resolves a release-status lookup for a reservation
- **THEN** the lookup is selected by the reservation's recorded `offering_mode`
- **AND** a reservation carrying the retired selector key is treated as carrying no offering mode rather than defaulting to one
