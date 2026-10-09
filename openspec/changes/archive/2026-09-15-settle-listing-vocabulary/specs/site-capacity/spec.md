## ADDED Requirements

### Requirement: The capacity claim names the offering mode

A capacity claim MUST carry the requested offering mode under the key
`offering_mode`, and that key MUST be required. It is the same value a Resource
Pool declares as deliverable and advertisable, the same value the durable listing
binding records, and the same value the published listing carries; no surface may
name it `executor_kind`, `offering_type`, or `virtualization_type`.

The claim's site-inventory discriminator remains a separate field and a separate
axis. Naming the offering mode consistently MUST NOT merge the two.

`executor` MUST NOT be used as vocabulary for the offering mode, for the machine, or
for the delivery handler. The machine is a host, the handler is a provider, and the
mode is an offering mode.

#### Scenario: A claim omits the offering mode

- **WHEN** a capacity claim carries no `offering_mode`
- **THEN** the request is refused, as it is today for the retired key

#### Scenario: A claim names the offering mode under a retired key

- **WHEN** a capacity claim carries the requested mode under `executor_kind`
- **THEN** the claim is treated as carrying no offering mode and is refused

#### Scenario: Pool delivery authorization reads the claim's offering mode

- **WHEN** admission checks whether a pool may deliver a claim's requested mode
- **THEN** it compares the claim's `offering_mode` against the pool's declared deliverable modes
