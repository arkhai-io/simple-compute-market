## MODIFIED Requirements

### Requirement: Bare-metal inventory binds an existing provider pool

The compute provisioner MUST import configured Resource Pool definitions before
seeding inventory. A bare-metal inventory host MAY name its exact pool through
`pool_id`; the seed MUST reject an unknown pool and MUST preserve that binding
on create and update. The host's explicit `bare_metal_publication` view MUST
carry that exact pool binding. The `bare_metal.ansible` provider accepts no
pool-local playbook, inventory-group, credential, or executor-target
configuration: execution uses service-owned configuration and the
scheduler-selected Physical Resource. The operator MUST register that Physical
Resource and its explicit `bare_metal_publication` view through the
authenticated capacity administration surface before the host is publishable.

#### Scenario: Fresh selected-site inventory binds to a bare-metal pool

- **WHEN** startup imports a `bare_metal.ansible` pool and then seeds a host whose inventory row names that pool
- **THEN** the durable host row retains the exact pool id and unknown pool ids fail instead of falling back to `default`

#### Scenario: Publication retains the inventory pool binding

- **GIVEN** a bare-metal inventory host is bound to a configured provider pool
- **WHEN** the compute service projects its explicit `bare_metal_publication` view
- **THEN** the view's `pool_id` is that exact inventory binding

#### Scenario: Pool-local executor configuration is supplied

- **WHEN** a `bare_metal.ansible` pool contains a non-empty `provider_config`
- **THEN** validation rejects the pool before it can authorize or dispatch fulfillment
