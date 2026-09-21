## ADDED Requirements

### Requirement: A host has one identity name

A host's identity MUST be named `host_id` on every surface that names it: the host
registry, a capacity declaration's host link, reservation execution references,
fulfillment metadata, job parameters, lease APIs, playbook variables, and published
listings. No surface MAY name that identity `name`, `vm_host`, `machine_id`, or any
other domain-prefixed spelling. The stable identity of a physical machine across
hosts is a distinct concept and MUST keep its own name.

#### Scenario: A VM reservation binds to a host

- **WHEN** a VM reservation is admitted against a declaration delivered through a host
- **THEN** its execution reference names that host as `host_id`

#### Scenario: A bare-metal listing is published

- **WHEN** a bare-metal listing is published for a declaration delivered through a host
- **THEN** the listing names that host as `host_id` under the listing kind that
  carries it, and names the physical machine separately as `physical_host_id`

#### Scenario: Two hosts share one physical machine

- **WHEN** one physical machine is registered as a VM host and as a bare-metal node
- **THEN** each has its own `host_id`, and both declarations carry the same
  `physical_host_id` so cross-mode accounting sees one machine

### Requirement: Existing host identities migrate without loss

A compute provisioner MUST migrate every persisted host identity to `host_id` in one
transaction before serving requests. A declaration whose host spellings disagree, or
whose cross-mode accounting fields disagree between locations, MUST abort the
migration with nothing written, naming the row.

#### Scenario: A declaration carries both legacy spellings with one value

- **WHEN** a declaration's `vm_host` and its publication `machine_id` name the same host
- **THEN** the migration records that host as the declaration's `host_id` and removes
  both legacy spellings

#### Scenario: A declaration carries conflicting spellings

- **WHEN** a declaration's `vm_host` and its publication `machine_id` name different hosts
- **THEN** the migration aborts, names the declaration, and leaves the database unchanged

### Requirement: A bare-metal storefront refuses state written under a retired listing kind

A bare-metal storefront MUST refuse to start against a database whose persisted state
was written under a listing kind it no longer decodes, and the refusal MUST name the
operator procedure that resolves it. It MUST NOT start and then fail when a retired
record is first decoded.

#### Scenario: The storefront starts against a pre-rename database

- **WHEN** a bare-metal storefront starts against a database written under
  `bare_metal.v1`
- **THEN** startup fails before serving requests, naming the reset procedure, and no
  record is decoded or rewritten

#### Scenario: The storefront starts against a fresh database

- **WHEN** a bare-metal storefront starts against an empty database
- **THEN** it creates its schema under the current listing kind and serves requests
